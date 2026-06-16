import os

import requests
from dotenv import find_dotenv, load_dotenv


def main():
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
    base_url = "https://api.github.com/users/Krishpatel-161-amt/repos"
    page_number = 1

    # This add type:owner (for No fork), per page 100 and set page number to 1
    while True:
        query_params = {"type": "owner", "per_page": 100, "page": page_number}

        print(f"\n === Fetching Page {page_number} ===")

        # This grabs the repos
        r = requests.get(base_url, headers=my_header, params=query_params)

        # Conditions to check status codes (Fail Fast)
        if r.status_code == 200:
            # ---> FIX: Everything below this needed to be indented! <---
            # Parses the JSON only if the request succeeded
            data = r.json()

            # If api returns empty list
            if not data:
                print("No more repos found. Audit complete!")
                break

            print(f"The request succeeded, succesfully fetched {len(data)} repos.")

            # process the current pages of repos
            get_repo(data)

            # Increment the page number for the next loop iteration
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


# This will grab the metadata about the repos
def get_repo(repo_data):
    for repo in repo_data:
        repo_name = repo["name"]
        print(f"=== Auditing: {repo_name} ===")

        # this will grab description, language, stars, updates, forks and license
        repo_desc = repo.get("description", "No description provided")
        repo_lang = repo.get("language")
        repo_stars = repo.get("stargazers_count")
        repo_updated = repo.get("updated_at")

        # Checks description
        if repo_desc is None:
            print("     [!] AUDIT FLAG: Missing description!")
        else:
            print(f"    -Desc:{repo_desc}")

        # Checks Language
        if repo_lang is None:
            print("     [!] AUDIT FLAG: Empty repo or non-code files")
        else:
            print(f"    -Lang:{repo_lang}")

        # Checks stars:
        print(f"    -Stars:{repo_stars}")

        # Checks updates:
        print(f"    -Last updated:{repo_updated}")

        # Checks how many forks the repo has
        repo_forks_count = repo.get("forks_count", 0)
        print(f"    -Forks:{repo_forks_count}")

        # Checks if this repo is a fork of someone else's repo
        repo_is_forked = repo.get("fork", False)
        if repo_is_forked:
            print("     [!] AUDIT FLAG: This is a forked repo, not original code")

        # This checks if license exists, and if it does, grabs the "name" from inside it
        repo_license = repo.get("license")  # Step 1: grab the license object (or None)

        if repo_license is None:
            print("    -License: No License provided")
        else:
            print(
                f"    -License: {repo_license.get('name', 'No License provided')}"
            )  # Step 2: grab name from inside it


if __name__ == "__main__":
    main()
