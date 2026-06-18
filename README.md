# GitHub Profile Mini Auditor

A Python tool that audits a GitHub user's public repositories and generates a report highlighting common issues — missing descriptions, missing READMEs, missing licenses, and empty repositories.

---

## Features

- Fetches all public repositories for any GitHub username
- Handles pagination automatically for accounts with many repos
- Detects common audit flags:
  - Missing description
  - Missing README
  - Missing license
  - No primary language detected (empty or non-code repo)
  - Forked repositories
- Outputs a clean terminal summary
- Generates an HTML report
- Exports a PDF report

---

## Requirements

- Python 3.8+
- A GitHub Personal Access Token (PAT)

---

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Krishpatel-161-amt/github-profile-auditor.git
cd github-profile-auditor
```

2. Install dependencies:
```bash
pip install requests python-dotenv xhtml2pdf
```

3. Create a `.env` file in the project root:
```
GitHub_PAT=your_personal_access_token_here
```

> To generate a PAT: GitHub → Settings → Developer Settings → Personal Access Tokens → Generate new token. Public repo read access is sufficient.

---

## Usage

```bash
python github_auditor.py
```

You will be prompted to enter a GitHub username. The tool will then:

1. Fetch all public repositories for that user
2. Print a live audit log to the terminal
3. Display a clean summary of flagged repositories
4. Save `audit_report.html` to the project folder
5. Save `audit_report.pdf` to the project folder

---

## Example Output

```
=== Github profile fetched for Krishpatel-161-amt ===
Total repo count: 8

iam-access-provisioner: Missing description, No primary language found, Missing README, Missing license
disk-space-checker: Missing description, Missing license
lens_slice: Missing description, Missing license

Report saved to audit_report.html
PDF saved as audit_report.pdf
```

---

## Project Structure

```
github-profile-auditor/
├── github_auditor.py   # Main script
├── .env                # GitHub PAT (never committed)
├── .gitignore
└── README.md
```

---

## .gitignore

Make sure your `.gitignore` includes:
```
.env
__pycache__/
audit_report.html
audit_report.pdf
```

---

## Built With

- [GitHub REST API](https://docs.github.com/en/rest)
- [requests](https://pypi.org/project/requests/)
- [python-dotenv](https://pypi.org/project/python-dotenv/)
- [xhtml2pdf](https://pypi.org/project/xhtml2pdf/)
