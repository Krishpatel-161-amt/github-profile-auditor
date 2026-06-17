import base64
import os

import requests
from dotenv import find_dotenv, load_dotenv


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

        print(f"\n=== Fetching Page {page_number} ===")

        r = requests.get(base_url, headers=my_header, params=query_params)

        if r.status_code == 200:
            data = r.json()

            if not data:
                print("No more repos found. Audit complete!")
                break

            print(f"The request succeeded, successfully fetched {len(data)} repos.")

            # FIX #2: Capture return value and extend the main accumulator
            page_repos = get_repo(data, my_header, username)
            all_repos.extend(page_repos)

            page_number += 1

        elif r.status_code == 400:
            print("Bad request")
            return
        elif r.status_code == 401:
            print("Unauthorized")
            return
        elif r.status_code == 403:
            print("You hit the Rate Limit!")
            return
        elif r.status_code == 404:
            print("User or repo doesnt exist")
            return
        else:
            print(f"Unexpected error: {r.status_code}")
            return

    print(f"\n=== Audit Complete: {len(all_repos)} repos collected ===")
    # PDF generator plugs in here tomorrow:
    # generate_pdf(username, all_repos)


# This fetches the readmes
def get_readme(owner, repo_name, headers):
    readme_url = f"https://api.github.com/repos/{owner}/{repo_name}/readme"
    r_readme = requests.get(readme_url, headers=headers)

    if r_readme.status_code == 200:
        readme_data = r_readme.json()
        encoded_content = readme_data.get("content")

        if encoded_content:
            decoded_bytes = base64.b64decode(encoded_content)
            readme_text = decoded_bytes.decode("utf-8")
            return readme_text
        return None

    elif r_readme.status_code == 404:
        return None
    else:
        print(f"Unexpected error fetching README: {r_readme.status_code}")
        return None


# This will grab the metadata about the repos
def get_repo(repo_data, headers, username):
    all_repos = []  # FIX #1: Local list, fresh each call — no more global

    for repo in repo_data:
        repo_name = repo["name"]
        print(f"\n=== Auditing: {repo_name} ===")

        repo_desc = repo.get("description", "No description provided")
        repo_lang = repo.get("language")
        repo_stars = repo.get("stargazers_count")
        repo_updated = repo.get("updated_at")

        audit_flags = []

        # Checks description
        if repo_desc is None or repo_desc == "No description provided":
            print("     [!] AUDIT FLAG: Missing description!")
            audit_flags.append("Missing description")
        else:
            print(f"    -Desc: {repo_desc}")

        # Checks Language
        if repo_lang is None:
            print("     [!] AUDIT FLAG: Empty repo or non-code files")
            audit_flags.append("No primary language found")
        else:
            print(f"    -Lang: {repo_lang}")

        print(f"    -Stars: {repo_stars}")
        print(f"    -Last updated: {repo_updated}")

        repo_forks_count = repo.get("forks_count", 0)
        print(f"    -Forks: {repo_forks_count}")

        repo_is_forked = repo.get("fork", False)
        if repo_is_forked:
            print("     [!] AUDIT FLAG: This is a forked repo, not original code")
            audit_flags.append("Forked repository")

        repo_license = repo.get("license")
        final_license_name = "No License provided"

        if repo_license is None:
            print("    -License: No License provided")
        else:
            final_license_name = repo_license.get("name", "No License provided")
            print(f"    -License: {final_license_name}")

        readme_text = get_readme(username, repo_name, headers)
        if readme_text:
            print(f"    -README: Found! ({len(readme_text)} characters)")
        else:
            print("     [!] AUDIT FLAG: Missing README!")
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


if __name__ == "__main__":
    main()
