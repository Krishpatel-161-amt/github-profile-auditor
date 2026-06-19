import base64
import os

import requests
from dotenv import find_dotenv, load_dotenv
from xhtml2pdf import pisa
from rich.console import Console
from rich.table import Table

console = Console()


def main():
    # asks the username
    username = input("Enter your Github username to audit: ")

    # Find and Loads the github PAT
    dotenv_path = find_dotenv()
    load_dotenv(dotenv_path)

    # variable for token
    Github_token = os.getenv("GitHub_PAT")

    my_header = {
        "Authorization": f"Bearer {Github_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "My-Python-App",
        "X-GitHub-Api-Version": "2026-03-10",
    }

    # Pagination setup
    base_url = f"https://api.github.com/users/{username}/repos"
    page_number = 1
    all_repos = []  # FIX #1: Accumulator lives here in main(), before the loop

    while True:
        query_params = {"type": "owner", "per_page": 100, "page": page_number}

        console.print(f"\n[bold cyan]=== Fetching Page {page_number} ===[/bold cyan]")

        r = requests.get(base_url, headers=my_header, params=query_params)

        if r.status_code == 200:
            data = r.json()

            if not data:
                console.print("[bold green]No more repos found. Audit complete![/bold green]")
                break

            console.print(f"The request succeeded, successfully fetched [bold]{len(data)}[/bold] repos.")

            # FIX #2: Capture return value and extend the main accumulator
            page_repos = get_repo(data, my_header, username)
            all_repos.extend(page_repos)

            page_number += 1

        elif r.status_code == 400:
            console.print("[bold red]Bad request[/bold red]")
            return
        elif r.status_code == 401:
            console.print("[bold red]Unauthorized[/bold red]")
            return
        elif r.status_code == 403:
            console.print("[bold red]You hit the Rate Limit![/bold red]")
            return
        elif r.status_code == 404:
            console.print("[bold red]User or repo doesnt exist[/bold red]")
            return
        else:
            console.print(f"[bold red]Unexpected error: {r.status_code}[/bold red]")
            return

    console.print(f"\n[bold green]=== Audit Complete: {len(all_repos)} repos collected ===[/bold green]")
    print_summary(username, all_repos)
    generate_html_report(username, all_repos)


# This fetches the readmes
def get_readme(owner, repo_name, headers):
    readme_url = f"https://api.github.com/repos/{owner}/{repo_name}/readme"
    r_readme = requests.get(readme_url, headers=headers)

    # If only the request succeds, then parse into JSON
    if r_readme.status_code == 200:
        readme_data = r_readme.json()
        encoded_content = readme_data.get("content")

        # Decoding base64 that github sends
        if encoded_content:
            decoded_bytes = base64.b64decode(encoded_content)
            readme_text = decoded_bytes.decode("utf-8")
            return readme_text
        return None

    elif r_readme.status_code == 404:
        return None
    else:
        console.print(f"[bold red]Unexpected error fetching README: {r_readme.status_code}[/bold red]")
        return None


# This will grab the metadata about the repos
def get_repo(repo_data, headers, username):
    all_repos = []

    for repo in repo_data:
        repo_name = repo["name"]
        console.print(f"\n[bold cyan]=== Auditing: {repo_name} ===[/bold cyan]")

        repo_desc = repo.get("description", "No description provided")
        repo_lang = repo.get("language")
        repo_stars = repo.get("stargazers_count")
        repo_updated = repo.get("updated_at")

        audit_flags = []

        # Checks description
        if repo_desc is None or repo_desc == "No description provided":
            console.print("     [bold red][!] AUDIT FLAG: Missing description![/bold red]")
            audit_flags.append("Missing description")
        else:
            console.print(f"    -Desc: {repo_desc}")

        # Checks Language
        if repo_lang is None:
            console.print("     [bold red][!] AUDIT FLAG: Empty repo or non-code files[/bold red]")
            audit_flags.append("No primary language found")
        else:
            console.print(f"    -Lang: {repo_lang}")

        # Prints the star count
        console.print(f"    -Stars: {repo_stars}")

        # Prints the last date/time the repo was updated
        console.print(f"    -Last updated: {repo_updated}")

        # Checks if the repo was forked or not
        repo_forks_count = repo.get("forks_count", 0)
        console.print(f"    -Forks: {repo_forks_count}")

        repo_is_forked = repo.get("fork", False)
        if repo_is_forked:
            console.print("     [bold yellow][!] AUDIT FLAG: This is a forked repo, not original code[/bold yellow]")
            audit_flags.append("Forked repository")

        # Checks for license
        repo_license = repo.get("license")
        final_license_name = "No License provided"

        if repo_license is None:
            console.print("    -License: No License provided")
            audit_flags.append("Missing License")
        else:
            final_license_name = repo_license.get("name", "No License provided")
            console.print(f"    -License: {final_license_name}")

        # This checks if the repo has readme or not
        readme_text = get_readme(username, repo_name, headers)
        if readme_text:
            console.print(f"    -README: Found! ({len(readme_text)} characters)")
        else:
            console.print("     [bold red][!] AUDIT FLAG: Missing README![/bold red]")
            audit_flags.append("Missing README")

        repo_dict = {
            "name": repo_name,
            "description": repo_desc,
            "language": repo_lang,
            "stars": repo_stars,
            "updated_at": repo_updated,
            "forks": repo_forks_count,
            "license": final_license_name,
            "readme": readme_text,
            "audit_flags": audit_flags,
        }
        all_repos.append(repo_dict)

    return all_repos


def print_summary(username, all_repos):
    console.print(f"\n[bold magenta]=== Github profile fetched for {username} ===[/bold magenta]")
    console.print(f"total repo count: [bold]{len(all_repos)}[/bold]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Repository")
    table.add_column("Language", justify="center")
    table.add_column("Stars", justify="right")
    table.add_column("Audit Flags", style="red")

    for repo in all_repos:
        if repo["audit_flags"]:
            flags = ", ".join(repo["audit_flags"])
        else:
            flags = "[green]Clean[/green]"
            
        table.add_row(
            repo["name"], 
            str(repo["language"] or "N/A"), 
            str(repo["stars"]), 
            flags
        )

    console.print(table)


def generate_html_report(username, all_repos):

    # Build the entire HTML as one string first
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>GitHub Audit Report - {username}</title>
</head>
<body>
    <h1>GitHub Audit Report for {username}</h1>
    <p>Total repos scanned: {len(all_repos)}</p>
"""

    # This mirrors your print_summary loop exactly
    for repo in all_repos:
        if repo["audit_flags"]:
            flags = ", ".join(repo["audit_flags"])
            html_content += f"""
    <h2>{repo["name"]}</h2>
    <p><b>Issues:</b> {flags}</p>
"""

    # Close the HTML tags
    html_content += """
</body>
</html>"""

    # Write the whole string to a file
    with open("audit_report.pdf", "wb") as pdf_file:
        pisa.CreatePDF(html_content, dest=pdf_file)

    console.print("[bold blue]PDF saved as audit_report.pdf[/bold blue]")
    console.print("\n[bold blue]Report saved to audit_report.html[/bold blue]")


if __name__ == "__main__":
    main()
