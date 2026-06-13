import os

import requests
from dotenv import find_dotenv, load_dotenv


# Wrapping the code inside the main() function
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

    # This grabs my profile and parses the json
    r = requests.get(
        "https://api.github.com/users/Krishpatel-161-amt", headers=my_header
    )

    # Conditions to check status codes
    if r.status_code == 200:
        data = r.json()
        print(" The request succeeded")
        print(data["login"])
    elif r.status_code == 400:
        print("Bad request")
    elif r.status_code == 401:
        print("Unauthorized")
    elif r.status_code == 403:
        print("You hit the Rate Limit!")
    elif r.status_code == 404:
        print("User or repo doesnt exist")


if __name__ == "__main__":
    main()
