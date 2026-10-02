# Scope — GitHub Repository Audit CLI (v1)

This file records the agreed scope. Change it deliberately. New features should fit the extension points below instead of bending the architecture.

## What the tool is

An **auditor**. It checks a user's public repositories against a fixed set of rules and reports what fails. It is not a profile viewer: stats such as stars and language never affect the result.

## Tech stack

| Package | Purpose |
|---|---|
| `requests` | GitHub REST API calls (one `Session`, timeouts on every call) |
| `python-dotenv` | Load the token from `.env` |
| `argparse` (stdlib) | CLI: `python github_auditor.py <username>` |
| `rich` | Terminal table and progress output |
| `pytest` (dev only, `requirements-dev.txt`) | Tests with fake tokens and mocked HTTP |

## Authentication

- **Fine-grained PAT**, as the GitHub docs recommend. Repository access: **"Public repositories (read-only)"**. No extra permissions are needed for v1.
- The token is read from `GitHub_PAT` in `.env`, which git and Docker both ignore.
- The token must never appear in output, error messages, or logs.

## Architecture

```
fetch            audit                     render
GitHub API  →  RepoFacts  →  rules  →  Findings  →  table
```

| Layer | Does | Never does |
|---|---|---|
| **Fetch** | All network I/O. Builds one `RepoFacts` dataclass per repo, containing everything any rule needs. | Decide what's wrong |
| **Audit** | Pure functions: `RepoFacts` in, `Finding`s out. | Call the API or print |
| **Render** | Turns findings into output. | Call the API or judge repos |

If a new rule needs new data, the fetch layer collects it up front. That keeps every API call in one place and makes rules testable without a network.

## Rules

Each rule has:
- **`id`**: a short, stable name (e.g. `missing-license`), used in output, tests and future flags.
- **`severity`**: how much a failure matters.
  - `error` = should be fixed; counts toward exit code 1.
  - `warning` = nice to fix; shown but doesn't fail the run.
- **check**: pass, or fail with an exact, human-readable message saying what's missing.

### v1 rules

| id | severity | data source |
|---|---|---|
| `missing-readme` | error | one extra call per repo: `GET /repos/{owner}/{repo}/readme` (404 = missing) |
| `missing-license` | error | repo list response (`license`) |
| `missing-description` | warning | repo list response (`description`) |
| `missing-topics` | warning | repo list response (`topics`) |

## Repo selection

- Public repos only: `GET /users/{username}/repos?type=owner&per_page=100`.
- Pagination follows the `Link: rel="next"` header until it's absent.
- **Forks and archived repos are skipped.** The summary reports how many were skipped.

## Failure policy

Any failure aborts the whole run with a clean one-line message, never a stack trace. There are no retries.

| Situation | Message |
|---|---|
| 404 on user lookup | User not found |
| 401 | Token invalid or expired |
| 403 with `x-ratelimit-remaining: 0`, or 429 | Rate limit hit; show the reset time |
| 403 otherwise | Token lacks permission |
| Network error / timeout | Network failure |
| Other unexpected status | Status code shown |

Every request uses a timeout.

## Output

A findings-list table printed to **stdout**. Progress messages go to **stderr**.

```
Repository     Status   Findings
───────────────────────────────────────────────
old-scraper    ✗ 2 err  missing-readme, missing-license
               ⚠ 1 warn missing-topics
todo-app       ⚠ 1 warn missing-description
portfolio      ✓ clean

3 repos · 2 errors · 2 warnings · 1 clean · 2 skipped
```

- Worst repos are sorted first (most errors, then most warnings).
- There are no stats columns.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | No error findings (warnings allowed) |
| 1 | At least one error finding |
| 2 | The tool couldn't complete (auth, rate limit, user not found, network) |

## Out of scope for v1

- Fixing repos (creating READMEs, adding topics). The tool is read-only.
- Reports saved to files (PDF/HTML). The PDF report and `xhtml2pdf` are removed.
- Caching / ETags.
- Retries and backoff.
- Organizations, multiple users.

## Future extensions (designed for, not built)

| Feature | Plugs in at |
|---|---|
| `--include-private` (via `/user/repos`) | fetch |
| `--json` output | render (stdout is already clean) |
| `--skip-rule <id>` | audit (rules are identified by `id`) |
| Stats columns (stars, language) | render (never affects pass/fail) |
| New rules | audit, plus fetch if they need new data |
| Mark failed checks as "unknown" instead of aborting | fetch + render |
