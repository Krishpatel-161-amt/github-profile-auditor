# gh-audit Implementation Plan

> **For the engineer:** read Parts 1–3 before you touch any code. Then work through Part 4 **one task at a time, in order**. Every task follows the same loop: write the test, watch it fail, write the code, watch it pass, commit. Don't skip the "watch it fail" step. It's how you know the test actually tests something.

**Goal:** Replace the single-file MVP `github_auditor.py` with `gh-audit`, a small, tested CLI. It audits the token owner's own public GitHub repos and prints an **Info** table plus a **Hygiene** table, or JSON.

**Architecture:** There are six modules in a `src/` layout package. Network code (`client`, `fetch`) is kept apart from pure logic (`checks`, `render`). Dataclasses (`models`) carry data between them. `cli` runs the steps in order and picks the exit code.

**Tech stack:** Python ≥ 3.10, `requests`, `python-dotenv`, `rich` and `argparse` (stdlib). Dev only: `pytest` and `responses`.

**Status of the code in this plan:** every code block below was run in a prototype before it was written down. The final suite is 103 passing tests. If something doesn't pass, compare your file against the task character by character before changing anything.

---

## Table of contents

- [Part 1: Ground rules](#part-1-ground-rules)
- [Part 2: What we're building (design reference)](#part-2-what-were-building-design-reference)
- [Part 3: Background you need](#part-3-background-you-need)
- [Part 4: Tasks](#part-4-tasks)
  - Phase 0: Setup (Tasks 1–2)
  - Phase 1: Token (Tasks 3–4)
  - Phase 2: HTTP client (Tasks 5–10)
  - Phase 3: Fetch (Tasks 11–14)
  - Phase 4: Checks (Tasks 15–18)
  - Phase 5: Render (Tasks 19–23)
  - Phase 6: CLI (Tasks 24–27)
  - Phase 7: Cleanup (Tasks 28–30)
- [Appendix A: Final file tree](#appendix-a-final-file-tree)
- [Appendix B: Reference links](#appendix-b-reference-links)

---

## Part 1: Ground rules

### 1.1 Token privacy (hard rule, no exceptions)

- **Never open, read, cat, print or commit any `.env` file**, including `~/.config/gh-audit/.env` and the old `.env` in the repo root. They hold the project owner's real GitHub token.
- **Never run the tool against real GitHub yourself.** All tests use the fake token `ghp_FAKE_TOKEN_FOR_TESTS_123` and fake HTTP responses. When a task says "live check", **the project owner runs it**. Ask them.
- **Code must never put the token into any message.** All error text is written by us, never copied from an exception. Tasks 10 and 26 add tests that enforce this.

### 1.2 How to work

- **TDD loop, every task:** (1) write the test, (2) run it and see it **fail for the reason stated**, (3) write the smallest code that passes, (4) run the **whole** suite and see it pass, (5) commit.
- **Do exactly the task.** No extra flags, options, retries, caching, logging or "while I'm here" refactors. Part 2.9 lists what's deliberately out of scope. If you think something is missing, write it down and ask. Don't build it.
- **DRY, but not clever.** Shared test data lives in `tests/factories.py`. Shared error handling lives in `client.py`. Plain functions and dataclasses only, with no class hierarchies beyond the three exceptions.
- **Commit after every task** with the message given. One branch for the whole refactor: `refactor/gh-audit`.
- **Keep `master` working.** Don't merge until Task 30.

### 1.3 Commands you'll use constantly

Run them from the repo root, with the virtual environment active (Task 1 sets it up).

```bash
python -m pytest                      # whole suite
python -m pytest tests/test_checks.py # one file
python -m pytest -k stale             # tests whose name contains "stale"
python -m pytest -x                   # stop at first failure
```

---

## Part 2: What we're building (design reference)

These are decisions the project owner has already made. **Don't change them.** If one looks wrong, ask.

### 2.1 What the tool is

`gh-audit` audits **the token owner's own public repos**. It has two jobs:
- **Info:** shows facts (language, last push, open issues, size). Info never affects pass/fail.
- **Hygiene:** flags problems as **errors** ("fix this") or **warnings** ("nice to fix").

There's no username argument. GitHub tells us who owns the token.

### 2.2 Which repos

- `GET /user/repos?visibility=public&affiliation=owner&per_page=100`, following pagination.
- **Forks and archived repos are skipped and counted.** A repo that is both counts once, as a fork.

### 2.3 Checks

| Check id | Severity | Fails when |
|---|---|---|
| `missing-readme` | error | `GET /repos/{owner}/{repo}/readme` returns 404 |
| `missing-license` | error | repo's `license` is null |
| `missing-description` | error | description is null, empty or only whitespace |
| `empty-repo` | error | `size == 0` |
| `missing-topics` | warning | `topics` is an empty list |
| `stale` | warning | last push is **more than 365 days** before now (exactly 365 is not stale; no push date means not stale) |

An empty repo also has no README, so it gets **both** `missing-readme` and `empty-repo`. That's intended.

If the README request fails (timeout, network, 5xx), the README check becomes **unknown**, with the reason, and the run continues.

### 2.4 CLI

```
gh-audit              # summary line, Info table, Hygiene table
gh-audit --info       # summary line + Info only (no README calls, no checks)
gh-audit --checks     # summary line + Hygiene only
gh-audit --json       # JSON instead of tables; combines with --info / --checks
```

`--info` and `--checks` are mutually exclusive. Tables and JSON go to **stdout**. Progress and error messages go to **stderr**, so `gh-audit --json > out.json` produces valid JSON.

### 2.5 Exit codes

| Code | Meaning |
|---|---|
| 0 | No error findings (warnings are fine) |
| 1 | At least one error finding |
| 2 | Tool couldn't finish: no token, bad token, rate limit, network failure, **or any check came back unknown** (2 takes priority over 1) |

With `--info`, no checks run, so the code is 0 or 2, never 1.

### 2.6 Failure policy

| Failure | Type | What happens |
|---|---|---|
| 401 | `FatalError` | abort: "GitHub token is invalid or expired" |
| 403/429 with `x-ratelimit-remaining: 0` | `FatalError` | abort: "GitHub rate limit hit, resets at HH:MM" |
| 403 with `retry-after`, or any 429 | `FatalError` | abort: "GitHub rate limit hit, try again in Ns" |
| other 403 | `FatalError` | abort: "GitHub token lacks permission for this request" |
| timeout | `RequestError` | "timed out after 10s" |
| connection failure | `RequestError` | "could not connect to GitHub" |
| any other non-2xx | `RequestError` | "GitHub returned HTTP 502" (and so on) |
| body isn't JSON | `RequestError` | "GitHub sent a response that isn't valid JSON" |

- A `RequestError` during the **README** call is recorded as unknown, and the run continues.
- A `RequestError` during `/user` or `/user/repos` aborts the run, because there's nothing to audit without the list.
- A `FatalError` always aborts.
- Aborting means printing **one** line to stderr (`Error: <message>`) and exiting 2. **Never a stack trace.**
- No retries. Every request has a 10-second timeout.

### 2.7 Token lookup

1. Environment variable `GITHUB_TOKEN`, if set and not blank.
2. Otherwise, `GITHUB_TOKEN=...` in `~/.config/gh-audit/.env`.
3. Otherwise, print the "token not found" help (Task 3) and exit 2.

### 2.8 Output formats

**Tables** (shown with color off):

```
5 repos audited · 3 with errors · 0 unknown · 1 warnings only · 1 clean · skipped 2 forks, 1 archived
                                  Info
┌────────────────────────┬──────────┬───────────┬─────────────┬─────────┐
│ Repository             │ Language │ Last push │ Open issues │    Size │
├────────────────────────┼──────────┼───────────┼─────────────┼─────────┤
│ Audit-tool             │  Python  │  2024-05  │           0 │  0.1 MB │
│ iam-access-provisioner │    —     │  2026-09  │           0 │    0 MB │
└────────────────────────┴──────────┴───────────┴─────────────┴─────────┘
                                                  Hygiene
┌────────────────────────┬──────────────┬──────────────────────────────────────────────────────────────────┐
│ Repository             │ Status       │ Findings                                                         │
├────────────────────────┼──────────────┼──────────────────────────────────────────────────────────────────┤
│ iam-access-provisioner │ ✗ 4 errors   │ missing-readme, missing-license, missing-description, empty-repo │
│                        │ ⚠ 1 warning  │ missing-topics                                                   │
│ lens_slice             │ ✗ 1 error    │ missing-license                                                  │
│                        │ ? 1 unknown  │ missing-readme (timed out after 10s)                             │
│ github-profile-auditor │ ✓ clean      │                                                                  │
└────────────────────────┴──────────────┴──────────────────────────────────────────────────────────────────┘
```

- **The summary line is always printed first.**
- **Each repo falls into exactly one summary bucket**, checked in this order: has an error → "with errors"; else has an unknown → "unknown"; else has a warning → "warnings only"; else "clean".
- **Info table:** sorted by name (case-insensitive). Size is KB ÷ 1024, shown as "0 MB" (size 0), "<0.1 MB", or one decimal place. Last push is `YYYY-MM`. Missing values show as `—`. **Stars and forks are not shown in the table**, only in JSON.
- **Hygiene table:** worst first (most errors, then unknowns, then warnings, then name). Each repo gets one row per group (errors, warnings, unknown), or a single `✓ clean` row. Colors: errors red, warnings yellow, unknown blue, clean green. Headers are bold magenta.

**JSON:**

```json
{
  "user": "octocat",
  "summary": {
    "audited": 9, "skipped_forks": 2, "skipped_archived": 1,
    "errors": 6, "unknown": 1, "warnings": 2, "clean": 0
  },
  "repos": [
    {"name": "lens_slice", "description": null, "license": null, "topics": [],
     "language": "Python", "size": 120, "stars": 0, "forks": 0, "open_issues": 0,
     "pushed_at": "2025-08-23T15:42:00Z", "has_readme": true, "readme_error": null}
  ],
  "findings": [
    {"repo": "lens_slice", "check": "missing-license", "severity": "error",
     "status": "fail", "message": "No license"}
  ]
}
```

- `--json --info` keeps `repos`, drops `findings`, and the summary has only `audited`/`skipped_*`.
- `--json --checks` keeps `findings` and drops `repos`.

### 2.9 Out of scope (don't build)

Markdown export, a database, a configurable stale threshold, private repos, a `--stats` flag, other users and orgs, fixing repos, retries/backoff, caching/ETags, logging, config options beyond the token, and a gh-CLI extension.

### 2.10 Decisions made while writing this plan (flag them to the owner if you disagree)

1. **Watchers dropped from `Repo`.** In the repo-list response, `watchers_count` is a legacy alias for the star count, not real watchers. Real watchers (`subscribers_count`) need an extra call per repo. Watchers were never shown in a table anyway.
2. **`pushed_at` may be `None`.** GitHub can return null for a repo that was never pushed to. Show it as `—`, and it's never stale.
3. **The summary counts repos per bucket** (2.8), not individual findings. Scripts that want finding totals can count `findings`.
4. **The Info table is sorted by name.**

---

## Part 3: Background you need

### 3.1 The project today

- `github_auditor.py` is the old MVP. **It's reference only. Don't edit it**, and it's deleted in Task 30. It prompts for a username, prints as it goes, and writes a PDF. None of that survives.
- `requirements.txt` and `Dockerfile` belong to the old script and are replaced in Phase 7.
- `docs/github-api-reference.md` is a condensed GitHub API reference. Read its "Rate limits", "Pagination" and "Error handling" sections before Phase 2.

### 3.2 GitHub API facts this code relies on

- **Base URL** `https://api.github.com`. Send these headers on every request: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `User-Agent: gh-audit`.
- **`GET /user`** returns the token owner, and `login` is their username. A 401 means the token is bad. We call it first, as a cheap token check.
- **`GET /user/repos`** lists the token owner's repos. `visibility=public&affiliation=owner` restricts it to public repos they own. Don't also send `type=`, because GitHub rejects `type` combined with `visibility`/`affiliation` (422).
- **Pagination:** the response has a `Link` header such as `<https://api.github.com/user/repos?page=2&...>; rel="next"`. Keep requesting the `next` URL until there isn't one. `requests` parses this header for you: `response.links["next"]["url"]`. **The next URL already contains every query parameter**, so request it with `params=None`, or you'll send them twice.
- **`GET /repos/{owner}/{repo}/readme`** returns 200 if a README exists and **404 if it doesn't**. An empty repo also returns 404. We only care about the status, not the body.
- **Repo fields we read:** `name`, `full_name` (`owner/repo`, used to build the README URL), `fork`, `archived`, `description`, `license` (`null` or an object with `name`), `topics` (a list), `language`, `size` (**in KB**, 0 for empty repos), `stargazers_count`, `forks_count`, `open_issues_count` (**includes open pull requests**), `pushed_at` (`"2026-09-01T08:30:00Z"` or null).
- **Rate-limit headers:** `x-ratelimit-remaining` (`"0"` means you're out) and `x-ratelimit-reset` (a Unix timestamp for when it refills). Secondary limits send `retry-after` (seconds).

### 3.3 Python and packaging facts

- **`src/` layout:** the package lives in `src/gh_audit/`. It can only be imported after it's installed, which is deliberate: tests then run against the installed package, not stray files. `pip install -e ".[dev]"` installs it **editable**, so code changes apply without reinstalling.
- **`[project.scripts]`** in `pyproject.toml` (`gh-audit = "gh_audit.cli:main"`) makes pip create a `gh-audit` command that calls `main()` and uses its return value as the exit code.
- **`str | None`** type syntax needs Python ≥ 3.10.
- **Python 3.10 gotcha:** `datetime.fromisoformat("2026-09-01T08:30:00Z")` **fails on 3.10**, because the trailing `Z` is only accepted from 3.11. We replace `Z` with `+00:00` first (Task 11).
- **Default-argument gotcha:** `def f(path=CONFIG_PATH)` stores the value of `CONFIG_PATH` *once*, at import time, so a test that monkeypatches `CONFIG_PATH` has no effect. That's why `load_token` looks the default up inside the function (Task 4).
- **`raise X(...) from None`** hides the original exception's chain, so a printed error never drags along internal details, which could include request data.

### 3.4 Testing toolkit (read this if you're new to pytest)

**pytest basics**
- Any function named `test_*` in a file named `tests/test_*.py` is a test. A plain `assert` is all you need.
- `pytest.raises(SomeError, match="text")` asserts that the block raises `SomeError` with a message containing `text` (it's a regex search).
- `@pytest.mark.parametrize("x, expected", [(1, 2), (3, 4)])` runs the same test once per row. Use it when cases differ only in data.

**Built-in fixtures we use** (you get them by naming them as test parameters):
- `monkeypatch`: temporarily change things for one test, undone automatically afterwards. For example `monkeypatch.setenv("GITHUB_TOKEN", "x")`, `monkeypatch.delenv(...)`, `monkeypatch.setattr(module, "NAME", value)`.
- `tmp_path`: a fresh, empty temporary folder (`pathlib.Path`) for each test.
- `capsys`: captures what the code printed. `out, err = capsys.readouterr()` gives stdout and stderr separately.

**Our own test helpers**
- `tests/conftest.py` has an **autouse** fixture that runs before *every* test. It removes `GITHUB_TOKEN` from the environment and points the config path at an empty temp folder. **This is what guarantees no test ever sees the owner's real token.** Don't remove it.
- `tests/factories.py` has `make_repo()`, `make_raw_repo()` and `make_finding()`. Each returns a **healthy default**, and a test overrides only the field it's about: `make_repo(license=None)`. That makes each test say exactly what it's testing.

**Faking GitHub with `responses`**
- Decorate a test with `@responses.activate`. Inside it, **every** `requests` call is intercepted, and nothing reaches the internet.
- Register fake replies like this: `responses.get(url, json={...}, status=200, headers={...})`.
- To fake a network failure, pass an exception as the body: `responses.get(url, body=requests.Timeout())`.
- `responses.calls` lists every request the code made: `responses.calls[0].request.headers`, `.request.params`, `.request.url`.
- To give the same URL different replies depending on query parameters, use `match=[matchers.query_param_matcher({...})]`.
- **When a request hits a URL you didn't register, `responses` raises `ConnectionError`.** Our client turns that into "could not connect to GitHub". So if a test unexpectedly fails with "could not connect", you forgot to register a URL.

**Testing `rich` output**
- Pass the render functions a `Console(file=io.StringIO(), width=120, color_system=None)`. You get plain text with no color codes and a fixed width, so tables don't wrap differently on different machines. Then assert on substrings.

### 3.5 How to write good tests (rules for this project)

1. **One behavior per test**, and the name says it as a sentence: `test_push_exactly_365_days_ago_is_not_stale`. If you need "and" in the name, split the test, unless it's a deliberate end-to-end check.
2. **Arrange, act, assert.** Build the input, call the function once, then check the result. Keep it short.
3. **Override only what matters.** Use `make_repo(size=0)`, not a 13-field literal. If the test is about size, only size should be visible.
4. **Test the edges, not just the middle.** For stale: 366 days (stale), exactly 365 (not stale), no date (not stale). Off-by-one bugs live at the edges.
5. **Assert specific values.** `assert finding.check == "missing-license"` beats `assert findings`. Asserting "something came back" proves almost nothing.
6. **Pure code needs no mocks.** `checks` and `render` take plain objects in and return plain values. If you find yourself mocking there, stop: the design is being broken.
7. **Network code is tested only through `responses`.** Never call real GitHub, and never use `unittest.mock` to patch `requests` internals.
8. **Don't test the language or libraries.** No tests that a dataclass stores a field, or that argparse parses `--json`.
9. **See every new test fail once.** If a new test passes before you've written the code, either the behavior already exists (fine for "guard" tests, which the plan points out) or the test is broken.
10. **Tests don't depend on the clock or on each other.** "Now" is passed in (`NOW` in factories), and every test builds its own data.

---

## Part 4: Tasks

Each task lists **Files**, then numbered steps. "Run" steps show the command and the result you should expect.

---

### Phase 0: Setup

#### Task 1: Branch, `pyproject.toml`, package skeleton, `.gitignore`

**Files:**
- Create: `pyproject.toml`, `src/gh_audit/__init__.py`
- Modify: `.gitignore`

**Step 1: Branch.**
```bash
git checkout master
git pull
git checkout -b refactor/gh-audit
```

**Step 2: Create `pyproject.toml`.**
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "gh-audit"
version = "1.0.0"
description = "Audit your own public GitHub repos for missing README, license, description, topics and more."
requires-python = ">=3.10"
license = { text = "MIT" }
dependencies = [
    "requests>=2.31",
    "python-dotenv>=1.0",
    "rich>=13.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "responses>=0.25",
]

[project.scripts]
gh-audit = "gh_audit.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 3: Create `src/gh_audit/__init__.py`.**
```python
"""gh-audit: audit your own public GitHub repos for basic hygiene."""
```

**Step 4: Fix `.gitignore`.** Today it wrongly ignores `README.md` and lists some entries twice. Replace the whole file with:
```gitignore
.env
__pycache__/
.venv/
*.egg-info/
.pytest_cache/
build/
audit_report.html
audit_report.pdf
```

**Step 5: Create a virtual environment and install.** Use Python 3.10 or newer.
```bash
python -m venv .venv
# Linux/macOS:  source .venv/bin/activate
# Windows:      .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

**Step 6: Verify.**
```bash
python -c "import gh_audit; print(gh_audit.__doc__)"
python -m pytest
```
Expected: the docstring prints, and pytest reports `no tests ran` (exit code 5). That's fine for now.

**Step 7: Commit.**
```bash
git add pyproject.toml src/gh_audit/__init__.py .gitignore
git commit -m "Set up gh_audit package skeleton with pyproject.toml"
```

---

#### Task 2: Data models and test factories

There are no tests in this task (see rule 8 in 3.5): dataclasses have no behavior to test. Their first real use comes in Task 11.

**Files:**
- Create: `src/gh_audit/models.py`, `tests/factories.py`

**Step 1: Create `src/gh_audit/models.py`.**
```python
"""Data passed between the parts of gh-audit.

fetch builds Repo objects, checks turns them into Findings, and the CLI
bundles everything into an AuditResult for render.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Repo:
    name: str
    description: str | None
    license: str | None  # license name, e.g. "MIT License"
    topics: list[str]
    language: str | None
    size: int  # KB, as reported by GitHub
    stars: int
    forks: int
    open_issues: int  # GitHub counts open pull requests here too
    pushed_at: datetime | None  # None if GitHub has no push date
    has_readme: bool | None = None  # None = not checked, or the check failed
    readme_error: str | None = None  # why the README check failed


@dataclass
class Finding:
    repo: str
    check: str  # e.g. "missing-license"
    severity: str  # "error" | "warning"
    status: str  # "fail" | "unknown"
    message: str


@dataclass
class AuditResult:
    user: str
    repos: list[Repo]
    findings: list[Finding]
    skipped_forks: int
    skipped_archived: int
```

**Step 2: Create `tests/factories.py`.** These are the builders every test file uses. Each default describes a **healthy** repo, so a test only changes the field it's about.
```python
"""Builders for test data. Each returns a healthy default; override only what a test is about."""

from datetime import datetime, timezone

from gh_audit.models import Finding, Repo

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
FAKE_TOKEN = "ghp_FAKE_TOKEN_FOR_TESTS_123"


def make_repo(**overrides) -> Repo:
    fields = dict(
        name="good-repo",
        description="A tidy repo",
        license="MIT License",
        topics=["python"],
        language="Python",
        size=120,
        stars=0,
        forks=0,
        open_issues=0,
        pushed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        has_readme=True,
        readme_error=None,
    )
    fields.update(overrides)
    return Repo(**fields)


def make_finding(**overrides) -> Finding:
    fields = dict(
        repo="good-repo",
        check="missing-license",
        severity="error",
        status="fail",
        message="No license",
    )
    fields.update(overrides)
    return Finding(**fields)


def make_raw_repo(**overrides) -> dict:
    """A trimmed-down version of what GitHub's /user/repos returns for one repo."""
    raw = {
        "name": "good-repo",
        "full_name": "octocat/good-repo",
        "fork": False,
        "archived": False,
        "description": "A tidy repo",
        "license": {"key": "mit", "name": "MIT License", "spdx_id": "MIT"},
        "topics": ["python"],
        "language": "Python",
        "size": 120,
        "stargazers_count": 3,
        "forks_count": 1,
        "open_issues_count": 2,
        "pushed_at": "2026-09-01T08:30:00Z",
    }
    raw.update(overrides)
    return raw
```

> Why `from factories import ...` works in tests: there's no `tests/__init__.py`, so pytest adds `tests/` itself to `sys.path`. **Don't add a `tests/__init__.py`.**

**Step 3: Verify it imports.**
```bash
python -c "from gh_audit.models import Repo, Finding, AuditResult"
```

**Step 4: Commit.**
```bash
git add src/gh_audit/models.py tests/factories.py
git commit -m "Add Repo, Finding and AuditResult dataclasses and test factories"
```

---

### Phase 1: Token

#### Task 3: Read the token from the environment, and the test-safety fixture

**Files:**
- Create: `tests/conftest.py`, `tests/test_auth.py`, `src/gh_audit/auth.py`

**Step 1: Create `src/gh_audit/auth.py` with just the constants.** The autouse fixture in Step 2 needs `CONFIG_PATH` to exist before any test can run.
```python
"""Find the GitHub token. Never prints or logs it."""

from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "gh-audit" / ".env"

MISSING_TOKEN_MESSAGE = """\
GitHub token not found.
Set GITHUB_TOKEN, or add it to ~/.config/gh-audit/.env:
  1. Go to https://github.com/settings/personal-access-tokens/new
  2. Repository access: "Public repositories (read-only)"
  3. Add the line  GITHUB_TOKEN=your_token  to that file"""
```

**Step 2: Create `tests/conftest.py`.** This is the safety net from 3.4, and it runs before every test.
```python
import pytest

from gh_audit import auth


@pytest.fixture(autouse=True)
def no_real_token(monkeypatch, tmp_path):
    """Runs before every test: hide the developer's real token from the code under test."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(auth, "CONFIG_PATH", tmp_path / "no-such-dir" / ".env")
```

**Step 3: Write the failing tests in `tests/test_auth.py`.**
```python
from gh_audit.auth import load_token


def test_reads_token_from_environment(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    assert load_token() == "env-token"


def test_missing_everywhere_returns_none(tmp_path):
    assert load_token(tmp_path / "does-not-exist.env") is None
```

**Step 4: Run.** `python -m pytest tests/test_auth.py`
Expected: **FAIL**, `ImportError: cannot import name 'load_token'`.

**Step 5: Implement.** Add to `auth.py`: `import os` at the top, and this function at the bottom.
```python
def load_token(config_path: Path | None = None) -> str | None:
    """Return GITHUB_TOKEN from the environment, else from the config file, else None."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    return token or None
```

**Step 6: Run.** `python -m pytest`. Expected: 2 passed.

**Step 7: Commit.**
```bash
git add src/gh_audit/auth.py tests/conftest.py tests/test_auth.py
git commit -m "Load GitHub token from GITHUB_TOKEN; hide real token from all tests"
```

---

#### Task 4: Read the token from `~/.config/gh-audit/.env`

**Files:**
- Modify: `src/gh_audit/auth.py`, `tests/test_auth.py`

**Step 1: Add the failing tests to `tests/test_auth.py`.**
```python
def test_reads_token_from_config_file(tmp_path):
    config = tmp_path / ".env"
    config.write_text("GITHUB_TOKEN=file-token\n")
    assert load_token(config) == "file-token"


def test_environment_wins_over_config_file(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    config = tmp_path / ".env"
    config.write_text("GITHUB_TOKEN=file-token\n")
    assert load_token(config) == "env-token"


def test_blank_values_count_as_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    config = tmp_path / ".env"
    config.write_text("GITHUB_TOKEN=\n")
    assert load_token(config) is None


def test_config_file_without_the_variable_returns_none(tmp_path):
    config = tmp_path / ".env"
    config.write_text("OTHER_SETTING=1\n")
    assert load_token(config) is None


def test_surrounding_whitespace_is_stripped(tmp_path):
    config = tmp_path / ".env"
    config.write_text("GITHUB_TOKEN=  file-token  \n")
    assert load_token(config) == "file-token"
```

**Step 2: Run.** `python -m pytest tests/test_auth.py`
Expected: `test_reads_token_from_config_file` and `test_surrounding_whitespace_is_stripped` **FAIL** (they return `None`). The other three already pass, because they describe cases the current code handles by accident. Keep them as guards.

**Step 3: Implement.** Final `auth.py`:
```python
"""Find the GitHub token. Never prints or logs it."""

import os
from pathlib import Path

from dotenv import dotenv_values

CONFIG_PATH = Path.home() / ".config" / "gh-audit" / ".env"

MISSING_TOKEN_MESSAGE = """\
GitHub token not found.
Set GITHUB_TOKEN, or add it to ~/.config/gh-audit/.env:
  1. Go to https://github.com/settings/personal-access-tokens/new
  2. Repository access: "Public repositories (read-only)"
  3. Add the line  GITHUB_TOKEN=your_token  to that file"""


def load_token(config_path: Path | None = None) -> str | None:
    """Return GITHUB_TOKEN from the environment, else from the config file, else None."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    # Looked up at call time (not as a default argument) so tests can monkeypatch CONFIG_PATH.
    path = CONFIG_PATH if config_path is None else config_path
    if path.is_file():
        # dotenv_values reads the file without changing os.environ.
        token = (dotenv_values(path).get("GITHUB_TOKEN") or "").strip()
    return token or None
```
Why `dotenv_values` and not `load_dotenv`: `load_dotenv` writes into `os.environ` for the whole process, so state would leak between tests. `dotenv_values` just returns a dict.

**Step 4: Run.** `python -m pytest`. Expected: 7 passed.

**Step 5: Commit.**
```bash
git add src/gh_audit/auth.py tests/test_auth.py
git commit -m "Fall back to ~/.config/gh-audit/.env for the token"
```

---

### Phase 2: HTTP client

All of `client.py` is about **how** we talk to GitHub. It knows nothing about repos or READMEs. Read 2.6 and 3.2 again before starting.

#### Task 5: Exceptions, client, successful GET

**Files:**
- Create: `src/gh_audit/client.py`, `tests/test_client.py`

**Step 1: Write the failing tests in `tests/test_client.py`.**
```python
import pytest
import responses

from factories import FAKE_TOKEN
from gh_audit.client import API_URL, GitHubClient


@pytest.fixture
def client():
    return GitHubClient(FAKE_TOKEN)


# ---------- success ----------

@responses.activate
def test_get_json_returns_parsed_body(client):
    responses.get(f"{API_URL}/user", json={"login": "octocat"})
    assert client.get_json("/user") == {"login": "octocat"}


@responses.activate
def test_sends_auth_and_api_version_headers(client):
    responses.get(f"{API_URL}/user", json={})
    client.get_json("/user")
    headers = responses.calls[0].request.headers
    assert headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


@responses.activate
def test_every_request_has_a_timeout(client, monkeypatch):
    seen = {}
    original_get = client.session.get

    def spy_get(url, **kwargs):
        seen.update(kwargs)
        return original_get(url, **kwargs)

    monkeypatch.setattr(client.session, "get", spy_get)
    responses.get(f"{API_URL}/user", json={})
    client.get_json("/user")
    assert seen["timeout"] == 10
```
The timeout test uses a small "spy": it wraps `session.get`, records the keyword arguments, then calls the real thing. `responses` doesn't record timeouts, so this is the simplest way to prove one is passed.

**Step 2: Run.** `python -m pytest tests/test_client.py`
Expected: **FAIL**, `ModuleNotFoundError: No module named 'gh_audit.client'`.

**Step 3: Implement `src/gh_audit/client.py`.** The three exception classes go in now. Later tasks raise them.
```python
"""The only code that talks HTTP. Turns every failure into a GitHubError."""

import requests

API_URL = "https://api.github.com"
TIMEOUT_SECONDS = 10


class GitHubError(Exception):
    """Base class. str(error) is a clean one-line message that never contains the token."""


class FatalError(GitHubError):
    """Every later request would fail too (bad token, rate limit). Only the CLI catches this."""


class RequestError(GitHubError):
    """This one request failed (timeout, network, 5xx). Callers may record it and continue."""


class GitHubClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "gh-audit",
            }
        )

    def get_json(self, path: str):
        response = self._get(API_URL + path)
        return response.json()

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        return self.session.get(url, params=params, timeout=TIMEOUT_SECONDS)
```
Why a `Session`: it sends the same headers on every request and reuses the connection, so repeated calls are faster.

**Step 4: Run.** `python -m pytest`. Expected: all pass (10).

**Step 5: Commit.**
```bash
git add src/gh_audit/client.py tests/test_client.py
git commit -m "Add GitHubClient with auth headers, timeout and error classes"
```

---

#### Task 6: Status codes (401, other errors, allowed 404)

**Files:**
- Modify: `src/gh_audit/client.py`, `tests/test_client.py`

**Step 1: Add the failing tests.** Update the import line at the top of `tests/test_client.py`:
```python
from gh_audit.client import API_URL, FatalError, GitHubClient, RequestError
```
Then append:
```python
# ---------- status codes ----------

@responses.activate
def test_401_is_fatal(client):
    responses.get(f"{API_URL}/user", status=401)
    with pytest.raises(FatalError, match="invalid or expired"):
        client.get_json("/user")


@responses.activate
@pytest.mark.parametrize("status", [404, 500, 502, 418])
def test_other_statuses_are_request_errors(client, status):
    responses.get(f"{API_URL}/user", status=status)
    with pytest.raises(RequestError, match=f"HTTP {status}"):
        client.get_json("/user")


@responses.activate
def test_404_returns_none_when_allowed(client):
    responses.get(f"{API_URL}/repos/o/r/readme", status=404)
    assert client.get_json("/repos/o/r/readme", allow_404=True) is None


@responses.activate
def test_allow_404_does_not_hide_other_errors(client):
    responses.get(f"{API_URL}/repos/o/r/readme", status=500)
    with pytest.raises(RequestError):
        client.get_json("/repos/o/r/readme", allow_404=True)
```

**Step 2: Run.** `python -m pytest tests/test_client.py`
Expected: **FAIL**. Some fail with `DID NOT RAISE`, and some with a `TypeError` about `allow_404`.

**Step 3: Implement.** Replace `get_json` in the class:
```python
    def get_json(self, path: str, allow_404: bool = False):
        """GET one resource. With allow_404=True a 404 returns None instead of raising."""
        response = self._get(API_URL + path)
        if allow_404 and response.status_code == 404:
            return None
        _raise_for_status(response)
        return response.json()
```
Then add this module-level function **below the class**:
```python
def _raise_for_status(response: requests.Response) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    if status == 401:
        raise FatalError("GitHub token is invalid or expired")
    raise RequestError(f"GitHub returned HTTP {status}")
```
Why `allow_404` is a flag and not "never raise on 404": for the README, a 404 is a normal answer ("there isn't one"). For `/user`, a 404 is a genuine failure. Only the caller knows which applies.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/client.py tests/test_client.py
git commit -m "Map 401 to FatalError and other failures to RequestError"
```

---

#### Task 7: 403/429 (rate limits and permissions)

**Files:**
- Modify: `src/gh_audit/client.py`, `tests/test_client.py`

**Step 1: Add the failing tests.** Add `from datetime import datetime` at the top of the test file, then append:
```python
@responses.activate
@pytest.mark.parametrize("status", [403, 429])
def test_primary_rate_limit_is_fatal_and_shows_reset_time(client, status):
    reset = 1_791_000_000
    responses.get(
        f"{API_URL}/user",
        status=status,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)},
    )
    expected = datetime.fromtimestamp(reset).strftime("%H:%M")
    with pytest.raises(FatalError, match=f"rate limit hit, resets at {expected}"):
        client.get_json("/user")


@responses.activate
def test_secondary_rate_limit_shows_retry_after(client):
    responses.get(f"{API_URL}/user", status=403, headers={"retry-after": "30"})
    with pytest.raises(FatalError, match="try again in 30s"):
        client.get_json("/user")


@responses.activate
def test_429_without_headers_is_still_a_rate_limit(client):
    responses.get(f"{API_URL}/user", status=429)
    with pytest.raises(FatalError, match="rate limit"):
        client.get_json("/user")


@responses.activate
def test_plain_403_means_missing_permission(client):
    responses.get(f"{API_URL}/user", status=403, headers={"x-ratelimit-remaining": "4999"})
    with pytest.raises(FatalError, match="lacks permission"):
        client.get_json("/user")
```
Note how the expected reset time is computed in the test the same way as in the code (local time). Hard-coding `"14:32"` would make the test pass or fail depending on your timezone.

**Step 2: Run.** Expected: **FAIL**. They raise `RequestError` ("HTTP 403") instead of `FatalError`.

**Step 3: Implement.** Add `from datetime import datetime` to the top of `client.py`. In `_raise_for_status`, insert this block **between** the 401 check and the final `raise`:
```python
    if status in (403, 429):
        if response.headers.get("x-ratelimit-remaining") == "0":
            reset = int(response.headers.get("x-ratelimit-reset", "0"))
            reset_time = datetime.fromtimestamp(reset).strftime("%H:%M")
            raise FatalError(f"GitHub rate limit hit, resets at {reset_time}")
        if status == 429 or "retry-after" in response.headers:
            wait = response.headers.get("retry-after", "60")
            raise FatalError(f"GitHub rate limit hit, try again in {wait}s")
        raise FatalError("GitHub token lacks permission for this request")
```
Header lookups are case-insensitive in `requests`, so `x-ratelimit-remaining` matches however GitHub capitalizes it.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/client.py tests/test_client.py
git commit -m "Report rate limits and missing permissions as FatalError"
```

---

#### Task 8: Network failures and bad JSON

**Files:**
- Modify: `src/gh_audit/client.py`, `tests/test_client.py`

**Step 1: Add the failing tests.** Add `import requests` at the top of the test file, then append:
```python
# ---------- network failures ----------

@responses.activate
def test_timeout_is_a_request_error(client):
    responses.get(f"{API_URL}/user", body=requests.Timeout())
    with pytest.raises(RequestError, match="timed out after 10s"):
        client.get_json("/user")


@responses.activate
def test_connection_failure_is_a_request_error(client):
    responses.get(f"{API_URL}/user", body=requests.ConnectionError())
    with pytest.raises(RequestError, match="could not connect"):
        client.get_json("/user")


@responses.activate
def test_invalid_json_is_a_request_error(client):
    responses.get(f"{API_URL}/user", body="<html>not json</html>")
    with pytest.raises(RequestError, match="valid JSON"):
        client.get_json("/user")
```

**Step 2: Run.** Expected: **FAIL**. Raw `requests` exceptions (`Timeout`, `ConnectionError`, `JSONDecodeError`) escape instead of `RequestError`.

**Step 3: Implement.** Replace `_get`:
```python
    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        try:
            return self.session.get(url, params=params, timeout=TIMEOUT_SECONDS)
        except requests.Timeout:
            raise RequestError(f"timed out after {TIMEOUT_SECONDS}s") from None
        except requests.ConnectionError:
            raise RequestError("could not connect to GitHub") from None
        except requests.RequestException:
            raise RequestError("request to GitHub failed") from None
```
Add this module-level function at the bottom of the file:
```python
def _parse_json(response: requests.Response):
    try:
        return response.json()
    except ValueError:
        raise RequestError("GitHub sent a response that isn't valid JSON") from None
```
In `get_json`, change `return response.json()` to `return _parse_json(response)`.

Notes:
- **The `except` order matters.** `requests.ConnectTimeout` is both a `Timeout` and a `ConnectionError`, and listing `Timeout` first reports it as a timeout. `RequestException` is the base class, so it goes last.
- **`from None`** stops Python from attaching the original `requests` exception, which can include request details.
- `requests`' JSON error is a subclass of `ValueError`, so catching `ValueError` covers every version of `requests`.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/client.py tests/test_client.py
git commit -m "Turn timeouts, connection errors and bad JSON into RequestError"
```

---

#### Task 9: Pagination

**Files:**
- Modify: `src/gh_audit/client.py`, `tests/test_client.py`

**Step 1: Add the failing tests.** Add `from responses import matchers` at the top of the test file, then append:
```python
# ---------- pagination ----------

@responses.activate
def test_get_pages_follows_next_links_until_the_last_page(client):
    first_params = {"per_page": "100"}
    responses.get(
        f"{API_URL}/user/repos",
        json=[{"name": "a"}, {"name": "b"}],
        headers={"Link": f'<{API_URL}/user/repos?page=2>; rel="next"'},
        match=[matchers.query_param_matcher(first_params)],
    )
    responses.get(
        f"{API_URL}/user/repos",
        json=[{"name": "c"}],
        match=[matchers.query_param_matcher({"page": "2"})],
    )
    items = client.get_pages("/user/repos", {"per_page": 100})
    assert [item["name"] for item in items] == ["a", "b", "c"]
    assert len(responses.calls) == 2


@responses.activate
def test_get_pages_with_no_results(client):
    responses.get(f"{API_URL}/user/repos", json=[])
    assert client.get_pages("/user/repos", {}) == []


@responses.activate
def test_get_pages_raises_if_a_later_page_fails(client):
    responses.get(
        f"{API_URL}/user/repos",
        json=[{"name": "a"}],
        headers={"Link": f'<{API_URL}/user/repos?page=2>; rel="next"'},
        match=[matchers.query_param_matcher({})],
    )
    responses.get(
        f"{API_URL}/user/repos",
        status=502,
        match=[matchers.query_param_matcher({"page": "2"})],
    )
    with pytest.raises(RequestError, match="HTTP 502"):
        client.get_pages("/user/repos", {})
```
`query_param_matcher` matches the **exact** set of query parameters. Page 2 must arrive with only `page=2`. That proves we don't re-send the first page's parameters, the bug described in 3.2.

**Step 2: Run.** Expected: **FAIL**, `AttributeError: 'GitHubClient' object has no attribute 'get_pages'`.

**Step 3: Implement.** Add this method to the class, after `get_json`:
```python
    def get_pages(self, path: str, params: dict) -> list:
        """GET a list endpoint and follow Link rel="next" until the last page."""
        items = []
        url, page_params = API_URL + path, params
        while url:
            response = self._get(url, page_params)
            _raise_for_status(response)
            items.extend(_parse_json(response))
            # The next URL already carries every query parameter, so don't send them twice.
            url, page_params = response.links.get("next", {}).get("url"), None
        return items
```

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/client.py tests/test_client.py
git commit -m "Follow Link rel=next pagination in get_pages"
```

---

#### Task 10: Guard test: the token never appears in error messages

This is a **guard test**: the code already behaves correctly, so it passes right away. It exists so a future change can't quietly break this rule. Because it won't fail first on its own, Step 2 makes it fail on purpose to prove it works.

**Files:**
- Modify: `tests/test_client.py`

**Step 1: Add the test.** Change the client import to also bring in `GitHubError`:
```python
from gh_audit.client import API_URL, FatalError, GitHubClient, GitHubError, RequestError
```
Then append:
```python
# ---------- token never leaks ----------

@responses.activate
@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": 401},
        {"status": 403},
        {"status": 429},
        {"status": 500},
        {"body": requests.Timeout()},
        {"body": requests.ConnectionError()},
        {"body": "not json"},
    ],
)
def test_error_messages_never_contain_the_token(client, kwargs):
    responses.get(f"{API_URL}/user", **kwargs)
    with pytest.raises(GitHubError) as caught:
        client.get_json("/user")
    assert FAKE_TOKEN not in str(caught.value)
```

**Step 2: Prove the test can fail.** Temporarily change the 401 message in `client.py` to `f"bad token {response.request.headers['Authorization']}"` and run `python -m pytest -k never_contain`. Expected: the 401 case **FAILS**. **Undo the change**, then run again. Expected: all 7 pass.

**Step 3: Run.** `python -m pytest`. Expected: all pass.

**Step 4: Commit.**
```bash
git add tests/test_client.py
git commit -m "Guard test: error messages never contain the token"
```

---

### Phase 3: Fetch

`fetch.py` is about **what** we ask GitHub for. It uses the client and builds `Repo` objects.

#### Task 11: `parse_repo` (GitHub JSON → `Repo`)

**Files:**
- Create: `src/gh_audit/fetch.py`, `tests/test_fetch.py`

**Step 1: Write the failing tests in `tests/test_fetch.py`.**
```python
from datetime import datetime, timezone

from factories import make_raw_repo
from gh_audit.fetch import parse_repo


# ---------- parse_repo ----------

def test_parse_repo_keeps_the_fields_we_use():
    repo = parse_repo(make_raw_repo())
    assert repo.name == "good-repo"
    assert repo.description == "A tidy repo"
    assert repo.license == "MIT License"
    assert repo.topics == ["python"]
    assert repo.language == "Python"
    assert repo.size == 120
    assert repo.stars == 3
    assert repo.forks == 1
    assert repo.open_issues == 2
    assert repo.pushed_at == datetime(2026, 9, 1, 8, 30, tzinfo=timezone.utc)


def test_parse_repo_handles_missing_optional_values():
    repo = parse_repo(make_raw_repo(description=None, license=None, language=None, pushed_at=None))
    assert repo.description is None
    assert repo.license is None
    assert repo.language is None
    assert repo.pushed_at is None


def test_parse_repo_leaves_readme_unchecked():
    repo = parse_repo(make_raw_repo())
    assert repo.has_readme is None
    assert repo.readme_error is None
```
(The first test checks many fields at once. That's a deliberate exception to "one behavior per test", because the single behavior is "map the fields".)

**Step 2: Run.** Expected: **FAIL**, `ModuleNotFoundError: No module named 'gh_audit.fetch'`.

**Step 3: Implement `src/gh_audit/fetch.py`.**
```python
"""Decides what to ask GitHub for and turns the answers into Repo objects."""

from datetime import datetime

from gh_audit.models import Repo


def parse_repo(raw: dict) -> Repo:
    """Keep only the fields gh-audit uses from GitHub's ~80-field repo object."""
    license_info = raw.get("license")
    return Repo(
        name=raw["name"],
        description=raw.get("description"),
        license=license_info["name"] if license_info else None,
        topics=raw.get("topics", []),
        language=raw.get("language"),
        size=raw.get("size", 0),
        stars=raw.get("stargazers_count", 0),
        forks=raw.get("forks_count", 0),
        open_issues=raw.get("open_issues_count", 0),
        pushed_at=_parse_time(raw.get("pushed_at")),
    )


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    # Python 3.10's fromisoformat() can't read the trailing "Z" GitHub uses (3.11+ can).
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
```
`raw["name"]` uses brackets on purpose: every repo has a name, and if one ever doesn't, a loud `KeyError` is better than an empty table row.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/fetch.py tests/test_fetch.py
git commit -m "Parse GitHub repo JSON into Repo"
```

---

#### Task 12: `fetch_login` and `fetch_repos` (skipping forks and archived repos)

**Files:**
- Modify: `src/gh_audit/fetch.py`, `tests/test_fetch.py`

**Step 1: Add the failing tests.** Replace the imports at the top of `tests/test_fetch.py` with:
```python
from datetime import datetime, timezone

import pytest
import responses

from factories import FAKE_TOKEN, make_raw_repo
from gh_audit.client import API_URL, GitHubClient
from gh_audit.fetch import fetch_repos, parse_repo


@pytest.fixture
def client():
    return GitHubClient(FAKE_TOKEN)
```
Append:
```python
# ---------- fetch_repos ----------

@responses.activate
def test_fetch_repos_skips_and_counts_forks_and_archived(client):
    responses.get(
        f"{API_URL}/user/repos",
        json=[
            make_raw_repo(name="mine"),
            make_raw_repo(name="forked", fork=True),
            make_raw_repo(name="old", archived=True),
            make_raw_repo(name="forked-and-old", fork=True, archived=True),
        ],
    )
    kept, forks, archived = fetch_repos(client)
    assert [raw["name"] for raw in kept] == ["mine"]
    assert forks == 2  # a fork that is also archived counts once, as a fork
    assert archived == 1


@responses.activate
def test_fetch_repos_asks_only_for_public_repos_the_user_owns(client):
    responses.get(f"{API_URL}/user/repos", json=[])
    fetch_repos(client)
    params = responses.calls[0].request.params
    assert params == {"visibility": "public", "affiliation": "owner", "per_page": "100"}
```

**Step 2: Run.** Expected: **FAIL**, `ImportError: cannot import name 'fetch_repos'`.

**Step 3: Implement.** In `fetch.py`, add below the existing imports:
```python
from gh_audit.client import GitHubClient

REPO_LIST_PARAMS = {"visibility": "public", "affiliation": "owner", "per_page": 100}


def fetch_login(client: GitHubClient) -> str:
    """Who owns the token. Also proves the token works before any real work starts."""
    return client.get_json("/user")["login"]


def fetch_repos(client: GitHubClient) -> tuple[list[dict], int, int]:
    """Return (kept raw repos, skipped forks, skipped archived)."""
    kept, forks, archived = [], 0, 0
    for raw in client.get_pages("/user/repos", REPO_LIST_PARAMS):
        if raw["fork"]:
            forks += 1
        elif raw["archived"]:
            archived += 1
        else:
            kept.append(raw)
    return kept, forks, archived
```
`fetch_repos` returns the **raw** dicts, not `Repo`s, because the README step still needs `full_name`, which `Repo` doesn't keep. `fetch_login` gets its test in Task 14, as part of `fetch_all`.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/fetch.py tests/test_fetch.py
git commit -m "List owned public repos, skipping and counting forks and archived"
```

---

#### Task 13: `fetch_readme` (found / missing / unknown)

**Files:**
- Modify: `src/gh_audit/fetch.py`, `tests/test_fetch.py`

**Step 1: Add the failing tests.** Update the test imports:
```python
import requests
from gh_audit.client import API_URL, FatalError, GitHubClient
from gh_audit.fetch import fetch_readme, fetch_repos, parse_repo
```
Append:
```python
# ---------- fetch_readme ----------

@responses.activate
def test_readme_found(client):
    responses.get(f"{API_URL}/repos/octocat/good-repo/readme", json={"name": "README.md"})
    assert fetch_readme(client, "octocat/good-repo") == (True, None)


@responses.activate
def test_readme_missing(client):
    responses.get(f"{API_URL}/repos/octocat/good-repo/readme", status=404)
    assert fetch_readme(client, "octocat/good-repo") == (False, None)


@responses.activate
def test_readme_timeout_becomes_unknown_with_reason(client):
    responses.get(f"{API_URL}/repos/octocat/good-repo/readme", body=requests.Timeout())
    assert fetch_readme(client, "octocat/good-repo") == (None, "timed out after 10s")


@responses.activate
def test_readme_fatal_error_is_not_swallowed(client):
    responses.get(f"{API_URL}/repos/octocat/good-repo/readme", status=401)
    with pytest.raises(FatalError):
        fetch_readme(client, "octocat/good-repo")
```
The last test is the important one. It proves we catch **only** `RequestError`, so a dead token still stops the run.

**Step 2: Run.** Expected: **FAIL**, `ImportError: cannot import name 'fetch_readme'`.

**Step 3: Implement.** Change the client import in `fetch.py` to:
```python
from gh_audit.client import GitHubClient, RequestError
```
Add after `parse_repo`:
```python
def fetch_readme(client: GitHubClient, full_name: str) -> tuple[bool | None, str | None]:
    """Return (has_readme, error). (True, None) found, (False, None) missing, (None, reason) unknown."""
    try:
        found = client.get_json(f"/repos/{full_name}/readme", allow_404=True)
    except RequestError as error:
        return None, str(error)
    return found is not None, None
```

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/fetch.py tests/test_fetch.py
git commit -m "Check README per repo; record request failures as unknown"
```

---

#### Task 14: `fetch_all` (the whole network phase)

**Files:**
- Modify: `src/gh_audit/fetch.py`, `tests/test_fetch.py`

**Step 1: Add the failing tests.** Update the fetch import:
```python
from gh_audit.fetch import fetch_all, fetch_readme, fetch_repos, parse_repo
```
Append:
```python
# ---------- fetch_all ----------

def _register_user_and_repos(*raws):
    responses.get(f"{API_URL}/user", json={"login": "octocat"})
    responses.get(f"{API_URL}/user/repos", json=list(raws))


@responses.activate
def test_fetch_all_with_readmes(client):
    _register_user_and_repos(make_raw_repo(name="a", full_name="octocat/a"),
                             make_raw_repo(name="b", full_name="octocat/b"))
    responses.get(f"{API_URL}/repos/octocat/a/readme", json={})
    responses.get(f"{API_URL}/repos/octocat/b/readme", status=404)

    login, repos, forks, archived = fetch_all(client, with_readme=True)

    assert login == "octocat"
    assert [(r.name, r.has_readme) for r in repos] == [("a", True), ("b", False)]
    assert (forks, archived) == (0, 0)


@responses.activate
def test_fetch_all_without_readmes_makes_no_readme_calls(client):
    _register_user_and_repos(make_raw_repo())
    fetch_all(client, with_readme=False)
    assert [call.request.path_url.split("?")[0] for call in responses.calls] == [
        "/user",
        "/user/repos",
    ]


@responses.activate
def test_fetch_all_continues_after_one_readme_fails(client):
    _register_user_and_repos(make_raw_repo(name="a", full_name="octocat/a"),
                             make_raw_repo(name="b", full_name="octocat/b"))
    responses.get(f"{API_URL}/repos/octocat/a/readme", body=requests.Timeout())
    responses.get(f"{API_URL}/repos/octocat/b/readme", json={})

    _, repos, _, _ = fetch_all(client, with_readme=True)

    assert repos[0].has_readme is None
    assert repos[0].readme_error == "timed out after 10s"
    assert repos[1].has_readme is True


@responses.activate
def test_fetch_all_reports_progress(client):
    _register_user_and_repos(make_raw_repo(name="a", full_name="octocat/a"))
    responses.get(f"{API_URL}/repos/octocat/a/readme", body=requests.Timeout())
    messages = []

    fetch_all(client, with_readme=True, progress=messages.append)

    assert "Checking README 1/1: a" in messages
    assert "README check failed for a: timed out after 10s" in messages


@responses.activate
def test_fetch_all_stops_when_the_token_is_bad(client):
    responses.get(f"{API_URL}/user", status=401)
    with pytest.raises(FatalError):
        fetch_all(client, with_readme=True)
    assert len(responses.calls) == 1  # never got as far as listing repos
```

**Step 2: Run.** Expected: **FAIL**, `ImportError: cannot import name 'fetch_all'`.

**Step 3: Implement.** Add `from collections.abc import Callable` to the imports in `fetch.py`, then add before `_parse_time`:
```python
def fetch_all(
    client: GitHubClient,
    with_readme: bool,
    progress: Callable[[str], None] = lambda message: None,
) -> tuple[str, list[Repo], int, int]:
    """Run every GitHub call in order. FatalError passes straight through to the caller."""
    progress("Checking token...")
    login = fetch_login(client)
    progress(f"Listing public repos for {login}...")
    raws, forks, archived = fetch_repos(client)
    repos = []
    for number, raw in enumerate(raws, start=1):
        repo = parse_repo(raw)
        if with_readme:
            progress(f"Checking README {number}/{len(raws)}: {repo.name}")
            repo.has_readme, repo.readme_error = fetch_readme(client, raw["full_name"])
            if repo.readme_error:
                progress(f"README check failed for {repo.name}: {repo.readme_error}")
        repos.append(repo)
    return login, repos, forks, archived
```
Why a `progress` callback instead of printing: fetch stays free of output code, so tests can collect messages in a list, and the CLI decides they go to stderr.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/fetch.py tests/test_fetch.py
git commit -m "Add fetch_all to run the whole network phase with progress"
```

---

### Phase 4: Checks

`checks.py` is **pure**: `Repo` in, `Finding`s out, with no network, printing or clock. "Now" is a parameter. Tests need no mocks at all.

#### Task 15: Healthy repo and the README check

**Files:**
- Create: `src/gh_audit/checks.py`, `tests/test_checks.py`

**Step 1: Write the failing tests in `tests/test_checks.py`.**
```python
from datetime import timedelta

import pytest

from factories import NOW, make_repo
from gh_audit.checks import check_repo


def checks_failed(repo):
    return [finding.check for finding in check_repo(repo, NOW)]


def test_healthy_repo_has_no_findings():
    assert check_repo(make_repo(), NOW) == []


# ---------- README ----------

def test_missing_readme_is_an_error():
    [finding] = check_repo(make_repo(has_readme=False), NOW)
    assert (finding.check, finding.severity, finding.status) == ("missing-readme", "error", "fail")


def test_unknown_readme_keeps_the_reason():
    repo = make_repo(has_readme=None, readme_error="timed out after 10s")
    [finding] = check_repo(repo, NOW)
    assert finding.check == "missing-readme"
    assert finding.status == "unknown"
    assert finding.message == "timed out after 10s"
```
`[finding] = ...` is a neat trick: it fails if the list doesn't contain **exactly one** item, so the test also proves no extra findings appeared.

**Step 2: Run.** Expected: **FAIL**, `ModuleNotFoundError: No module named 'gh_audit.checks'`.

**Step 3: Implement `src/gh_audit/checks.py`.**
```python
"""Hygiene checks. Pure functions: Repo in, Findings out. No network, no printing."""

from datetime import datetime

from gh_audit.models import Finding, Repo


def check_repo(repo: Repo, now: datetime) -> list[Finding]:
    """Return every failed or unknown check for one repo, errors first."""
    findings = []

    def add(check: str, severity: str, message: str, status: str = "fail") -> None:
        findings.append(Finding(repo.name, check, severity, status, message))

    if repo.has_readme is None:
        add("missing-readme", "error", repo.readme_error or "README not checked", status="unknown")
    elif not repo.has_readme:
        add("missing-readme", "error", "No README")
    return findings
```

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/checks.py tests/test_checks.py
git commit -m "Add README check, including unknown results"
```

---

#### Task 16: License, description and empty-repo checks

**Files:**
- Modify: `src/gh_audit/checks.py`, `tests/test_checks.py`

**Step 1: Append the failing tests.**
```python
# ---------- license, description, empty ----------

def test_missing_license_is_an_error():
    [finding] = check_repo(make_repo(license=None), NOW)
    assert (finding.check, finding.severity) == ("missing-license", "error")


@pytest.mark.parametrize("description", [None, "", "   "])
def test_blank_description_is_an_error(description):
    [finding] = check_repo(make_repo(description=description), NOW)
    assert (finding.check, finding.severity) == ("missing-description", "error")


def test_size_zero_is_an_empty_repo():
    assert checks_failed(make_repo(size=0)) == ["empty-repo"]


def test_size_one_is_not_empty():
    assert checks_failed(make_repo(size=1)) == []
```

**Step 2: Run.** Expected: **FAIL** (no findings are produced). `test_size_one_is_not_empty` passes already and acts as a boundary guard.

**Step 3: Implement.** In `check_repo`, add these lines **after** the README block and before `return findings`:
```python
    if not repo.license:
        add("missing-license", "error", "No license")
    if not (repo.description or "").strip():
        add("missing-description", "error", "No description")
    if repo.size == 0:
        add("empty-repo", "error", "Repository is empty")
```
`(repo.description or "").strip()` turns `None` into `""`, then strips whitespace, so one condition covers all three blank cases.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/checks.py tests/test_checks.py
git commit -m "Add license, description and empty-repo checks"
```

---

#### Task 17: Topics and stale warnings

**Files:**
- Modify: `src/gh_audit/checks.py`, `tests/test_checks.py`

**Step 1: Append the failing tests.**
```python
# ---------- warnings ----------

def test_no_topics_is_a_warning():
    [finding] = check_repo(make_repo(topics=[]), NOW)
    assert (finding.check, finding.severity) == ("missing-topics", "warning")


def test_push_more_than_365_days_ago_is_stale():
    repo = make_repo(pushed_at=NOW - timedelta(days=366))
    [finding] = check_repo(repo, NOW)
    assert (finding.check, finding.severity) == ("stale", "warning")
    assert finding.message == "No push since 2025-10"


def test_push_exactly_365_days_ago_is_not_stale():
    assert checks_failed(make_repo(pushed_at=NOW - timedelta(days=365))) == []


def test_unknown_push_date_is_not_stale():
    assert checks_failed(make_repo(pushed_at=None)) == []
```
These are the boundary tests from 3.5, rule 4: 366 days is stale, 365 isn't, and no date isn't.

**Step 2: Run.** Expected: the first two **FAIL**, and the last two pass already as guards.

**Step 3: Implement.** Change the datetime import to `from datetime import datetime, timedelta` and add a constant under the imports:
```python
STALE_AFTER = timedelta(days=365)
```
In `check_repo`, add before `return findings`:
```python
    if not repo.topics:
        add("missing-topics", "warning", "No topics")
    if repo.pushed_at is not None and now - repo.pushed_at > STALE_AFTER:
        add("stale", "warning", f"No push since {repo.pushed_at:%Y-%m}")
```
`>` (not `>=`) is what makes "exactly 365 days" not stale. Both datetimes must be timezone-aware, because Python refuses to subtract an aware datetime from a naive one. `fetch` produces aware UTC datetimes, and the CLI passes `datetime.now(timezone.utc)`.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/checks.py tests/test_checks.py
git commit -m "Add missing-topics and stale warnings"
```

---

#### Task 18: `check_all`, plus a guard on finding order

**Files:**
- Modify: `src/gh_audit/checks.py`, `tests/test_checks.py`

**Step 1: Add the failing tests.** Change the import to `from gh_audit.checks import check_all, check_repo`, then append:
```python
# ---------- combinations ----------

def test_empty_repo_reports_every_problem_errors_first():
    repo = make_repo(has_readme=False, license=None, description=None, size=0, topics=[])
    assert checks_failed(repo) == [
        "missing-readme",
        "missing-license",
        "missing-description",
        "empty-repo",
        "missing-topics",
    ]


def test_check_all_keeps_repo_names():
    findings = check_all([make_repo(name="a", license=None), make_repo(name="b")], NOW)
    assert [(f.repo, f.check) for f in findings] == [("a", "missing-license")]
```

**Step 2: Run.** Expected: **FAIL**, `ImportError: cannot import name 'check_all'`.

**Step 3: Implement.** Append to `checks.py`:
```python
def check_all(repos: list[Repo], now: datetime) -> list[Finding]:
    return [finding for repo in repos for finding in check_repo(repo, now)]
```

**Step 4: Run.** `python -m pytest`. Expected: all pass. Your `checks.py` should now be about 35 lines.

**Step 5: Commit.**
```bash
git add src/gh_audit/checks.py tests/test_checks.py
git commit -m "Add check_all and guard the order findings are reported in"
```

---

### Phase 5: Render

`render.py` is also pure. It takes an `AuditResult` and either prints tables to a `Console` it's **given**, or returns a JSON string. Read 2.8 again before starting.

#### Task 19: Formatting helpers

**Files:**
- Create: `src/gh_audit/render.py`, `tests/test_render.py`

**Step 1: Write the failing tests in `tests/test_render.py`.**
```python
from datetime import datetime, timezone

import pytest

from gh_audit.render import format_month, format_size


# ---------- formatting helpers ----------

@pytest.mark.parametrize(
    "size_kb, expected",
    [(0, "0 MB"), (50, "<0.1 MB"), (103, "0.1 MB"), (1536, "1.5 MB"), (204_800, "200.0 MB")],
)
def test_format_size(size_kb, expected):
    assert format_size(size_kb) == expected


def test_format_month():
    assert format_month(datetime(2025, 8, 23, tzinfo=timezone.utc)) == "2025-08"
    assert format_month(None) == "—"
```

**Step 2: Run.** Expected: **FAIL**, `ModuleNotFoundError`.

**Step 3: Implement `src/gh_audit/render.py`.**
```python
"""Turns an AuditResult into tables or JSON. Never calls the API, never judges repos."""

from datetime import datetime


# ---------- formatting helpers ----------

def format_size(size_kb: int) -> str:
    if size_kb == 0:
        return "0 MB"
    mb = size_kb / 1024
    if mb < 0.1:
        return "<0.1 MB"
    return f"{mb:.1f} MB"


def format_month(value: datetime | None) -> str:
    return value.strftime("%Y-%m") if value else "—"
```

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/render.py tests/test_render.py
git commit -m "Add size and month formatting helpers"
```

---

#### Task 20: Summary (buckets, counts, line)

**Files:**
- Modify: `src/gh_audit/render.py`, `tests/test_render.py`

**Step 1: Add the failing tests.** Replace the imports at the top of `tests/test_render.py` with the block below, and add the `make_result` helper under them:
```python
from datetime import datetime, timezone

import pytest

from factories import make_finding, make_repo
from gh_audit.models import AuditResult
from gh_audit.render import format_month, format_size, repo_bucket, summarize, summary_line


def make_result(repos=None, findings=None, forks=0, archived=0):
    return AuditResult(
        user="octocat",
        repos=repos if repos is not None else [make_repo()],
        findings=findings or [],
        skipped_forks=forks,
        skipped_archived=archived,
    )
```
Append:
```python
# ---------- summary ----------

def test_repo_bucket_priority():
    error = make_finding(severity="error")
    warning = make_finding(check="missing-topics", severity="warning")
    unknown = make_finding(check="missing-readme", status="unknown")
    assert repo_bucket([]) == "clean"
    assert repo_bucket([warning]) == "warnings"
    assert repo_bucket([warning, unknown]) == "unknown"
    assert repo_bucket([warning, unknown, error]) == "errors"


def test_summarize_counts_each_repo_once():
    result = make_result(
        repos=[make_repo(name="a"), make_repo(name="b"), make_repo(name="c")],
        findings=[
            make_finding(repo="a", check="missing-license"),
            make_finding(repo="a", check="missing-readme"),
            make_finding(repo="b", check="missing-topics", severity="warning"),
        ],
        forks=2,
        archived=1,
    )
    assert summarize(result, show_checks=True) == {
        "audited": 3,
        "skipped_forks": 2,
        "skipped_archived": 1,
        "errors": 1,
        "unknown": 0,
        "warnings": 1,
        "clean": 1,
    }


def test_summarize_info_only_has_no_check_counts():
    assert summarize(make_result(), show_checks=False) == {
        "audited": 1,
        "skipped_forks": 0,
        "skipped_archived": 0,
    }


def test_summary_line_with_checks():
    summary = {"audited": 9, "skipped_forks": 2, "skipped_archived": 1,
               "errors": 6, "unknown": 1, "warnings": 2, "clean": 0}
    assert summary_line(summary) == (
        "9 repos audited · 6 with errors · 1 unknown · 2 warnings only · 0 clean"
        " · skipped 2 forks, 1 archived"
    )


def test_summary_line_info_only():
    summary = {"audited": 9, "skipped_forks": 0, "skipped_archived": 0}
    assert summary_line(summary) == "9 repos audited · skipped 0 forks, 0 archived"
```
In `test_summarize_counts_each_repo_once`, repo "a" has **two** errors but counts as **one** repo with errors. That's what the name promises.

**Step 2: Run.** Expected: **FAIL**, `ImportError`.

**Step 3: Implement.** Add to the imports in `render.py`:
```python
from collections import Counter

from gh_audit.models import AuditResult, Finding
```
Add this section **above** the formatting helpers:
```python
# ---------- summary ----------

def repo_bucket(findings: list[Finding]) -> str:
    """Put one repo's findings into exactly one bucket: errors > unknown > warnings > clean."""
    if any(f.status == "fail" and f.severity == "error" for f in findings):
        return "errors"
    if any(f.status == "unknown" for f in findings):
        return "unknown"
    if findings:
        return "warnings"
    return "clean"


def summarize(result: AuditResult, show_checks: bool) -> dict:
    summary = {
        "audited": len(result.repos),
        "skipped_forks": result.skipped_forks,
        "skipped_archived": result.skipped_archived,
    }
    if show_checks:
        by_repo = _findings_by_repo(result)
        buckets = Counter(repo_bucket(by_repo[repo.name]) for repo in result.repos)
        for bucket in ("errors", "unknown", "warnings", "clean"):
            summary[bucket] = buckets[bucket]
    return summary


def summary_line(summary: dict) -> str:
    parts = [f"{summary['audited']} repos audited"]
    if "errors" in summary:
        parts += [
            f"{summary['errors']} with errors",
            f"{summary['unknown']} unknown",
            f"{summary['warnings']} warnings only",
            f"{summary['clean']} clean",
        ]
    parts.append(
        f"skipped {summary['skipped_forks']} forks, {summary['skipped_archived']} archived"
    )
    return " · ".join(parts)
```
Add at the bottom of the file (the hygiene table reuses it in Task 22):
```python
def _findings_by_repo(result: AuditResult) -> dict[str, list[Finding]]:
    by_repo: dict[str, list[Finding]] = {repo.name: [] for repo in result.repos}
    for finding in result.findings:
        by_repo[finding.repo].append(finding)
    return by_repo
```
`summarize` returns a dict on purpose: the JSON output in Task 23 uses that exact dict, so the table and the JSON can never disagree.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/render.py tests/test_render.py
git commit -m "Add summary buckets and summary line"
```

---

#### Task 21: Info table and `print_tables`

**Files:**
- Modify: `src/gh_audit/render.py`, `tests/test_render.py`

**Step 1: Add the failing tests.** Add `import io` and `from rich.console import Console` to the top of the test file, and add `print_tables` to the `gh_audit.render` import. Add this helper under `make_result`:
```python
def render_text(result, show_info=True, show_checks=True):
    """Print to a fake terminal and return plain text (no colors, fixed width)."""
    buffer = io.StringIO()
    console = Console(file=buffer, width=120, color_system=None)
    print_tables(result, show_info, show_checks, console)
    return buffer.getvalue()
```
Append:
```python
# ---------- tables ----------

def test_summary_is_printed_first():
    text = render_text(make_result())
    assert text.startswith("1 repos audited")


def test_info_table_columns_and_values():
    repo = make_repo(name="lens_slice", language=None, size=1536, open_issues=4,
                     pushed_at=datetime(2025, 8, 23, tzinfo=timezone.utc))
    text = render_text(make_result(repos=[repo]), show_checks=False)
    assert "Info" in text
    for expected in ["Repository", "Language", "Last push", "Open issues", "Size",
                     "lens_slice", "—", "2025-08", "4", "1.5 MB"]:
        assert expected in text
    assert "Stars" not in text  # stars stay in the JSON only
    assert "Hygiene" not in text
```

**Step 2: Run.** Expected: **FAIL**, `ImportError: cannot import name 'print_tables'`.

**Step 3: Implement.** Add to the imports in `render.py`:
```python
from rich.console import Console
from rich.table import Table
```
Change the models import to `from gh_audit.models import AuditResult, Finding, Repo`, and add under the imports:
```python
HEADER_STYLE = "bold magenta"
```
Add this section after the formatting helpers:
```python
# ---------- tables ----------

def info_table(repos: list[Repo]) -> Table:
    table = Table(title="Info", header_style=HEADER_STYLE)
    table.add_column("Repository")
    table.add_column("Language", justify="center")
    table.add_column("Last push", justify="center")
    table.add_column("Open issues", justify="right")
    table.add_column("Size", justify="right")
    for repo in sorted(repos, key=lambda r: r.name.lower()):
        table.add_row(
            repo.name,
            repo.language or "—",
            format_month(repo.pushed_at),
            str(repo.open_issues),
            format_size(repo.size),
        )
    return table


def print_tables(result: AuditResult, show_info: bool, show_checks: bool, console: Console) -> None:
    console.print(summary_line(summarize(result, show_checks)))
    if show_info:
        console.print(info_table(result.repos))
```
Why `console` is a parameter: the CLI passes the real terminal, and tests pass a `StringIO` console. Render never creates its own console, so it never writes anywhere unexpected.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/render.py tests/test_render.py
git commit -m "Add Info table and print_tables"
```

---

#### Task 22: Hygiene table

**Files:**
- Modify: `src/gh_audit/render.py`, `tests/test_render.py`

**Step 1: Append the failing tests.**
```python
def test_hygiene_table_groups_by_severity():
    result = make_result(
        repos=[make_repo(name="messy")],
        findings=[
            make_finding(repo="messy", check="missing-readme"),
            make_finding(repo="messy", check="missing-license"),
            make_finding(repo="messy", check="missing-topics", severity="warning"),
        ],
    )
    text = render_text(result, show_info=False)
    assert "✗ 2 errors" in text
    assert "missing-readme, missing-license" in text
    assert "⚠ 1 warning" in text
    assert "Info" not in text


def test_hygiene_table_shows_unknown_with_reason():
    result = make_result(
        repos=[make_repo(name="lens_slice")],
        findings=[make_finding(repo="lens_slice", check="missing-readme", status="unknown",
                               message="timed out after 10s")],
    )
    text = render_text(result, show_info=False)
    assert "? 1 unknown" in text
    assert "missing-readme (timed out after 10s)" in text


def test_hygiene_table_shows_clean_repos():
    text = render_text(make_result(repos=[make_repo(name="portfolio")]), show_info=False)
    assert "✓ clean" in text


def test_hygiene_table_puts_worst_repos_first():
    result = make_result(
        repos=[make_repo(name="clean-one"), make_repo(name="one-warning"),
               make_repo(name="two-errors"), make_repo(name="one-error")],
        findings=[
            make_finding(repo="one-warning", check="missing-topics", severity="warning"),
            make_finding(repo="two-errors", check="missing-readme"),
            make_finding(repo="two-errors", check="missing-license"),
            make_finding(repo="one-error", check="missing-license"),
        ],
    )
    text = render_text(result, show_info=False)
    order = [text.index(name) for name in ["two-errors", "one-error", "one-warning", "clean-one"]]
    assert order == sorted(order)
```
The sorting test gives the repos in a **scrambled** order on purpose. If they were already in the expected order, the test would pass even with no sorting.

**Step 2: Run.** Expected: **FAIL**. The text has no `✗`, `⚠`, `?` or `✓`, because no hygiene table is printed yet.

**Step 3: Implement.** Add `from rich.text import Text` to the imports, and under `HEADER_STYLE` add:
```python
STYLES = {"error": "red", "warning": "yellow", "unknown": "blue", "clean": "green"}
```
Add after `info_table`:
```python
def hygiene_table(result: AuditResult) -> Table:
    table = Table(title="Hygiene", header_style=HEADER_STYLE)
    table.add_column("Repository")
    table.add_column("Status")
    table.add_column("Findings")
    by_repo = _findings_by_repo(result)
    for repo in sorted(result.repos, key=lambda r: _worst_first(r, by_repo[r.name])):
        rows = _status_rows(by_repo[repo.name])
        for index, (status, findings_text, style) in enumerate(rows):
            name = repo.name if index == 0 else ""
            table.add_row(name, Text(status, style=style), Text(findings_text, style=style))
    return table


def _status_rows(findings: list[Finding]) -> list[tuple[str, str, str]]:
    """One row per group (errors, warnings, unknown) that has findings, or one 'clean' row."""
    groups = [
        ("✗", "error", [f for f in findings if f.status == "fail" and f.severity == "error"]),
        ("⚠", "warning", [f for f in findings if f.status == "fail" and f.severity == "warning"]),
        ("?", "unknown", [f for f in findings if f.status == "unknown"]),
    ]
    rows = []
    for symbol, kind, group in groups:
        if not group:
            continue
        label = kind if len(group) == 1 else f"{kind}s"
        names = [f.check if kind != "unknown" else f"{f.check} ({f.message})" for f in group]
        rows.append((f"{symbol} {len(group)} {label}", ", ".join(names), STYLES[kind]))
    return rows or [("✓ clean", "", STYLES["clean"])]


def _worst_first(repo: Repo, findings: list[Finding]) -> tuple:
    counts = Counter(
        f.severity if f.status == "fail" else "unknown" for f in findings
    )
    return (-counts["error"], -counts["unknown"], -counts["warning"], repo.name.lower())
```
At the end of `print_tables`, add:
```python
    if show_checks:
        console.print(hygiene_table(result))
```
Notes:
- **`Text(..., style=...)` instead of `"[red]...[/]"` markup.** Rich treats `[...]` inside a string as markup, so data containing brackets would garble the output. `Text` objects are never parsed as markup.
- **Sorting with negative counts:** Python sorts ascending, so `-2 < -1 < 0` puts the most errors first. The name is the final tie-breaker, so the order is always the same from run to run.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/render.py tests/test_render.py
git commit -m "Add Hygiene table grouped by severity, worst repos first"
```

---

#### Task 23: JSON output

**Files:**
- Modify: `src/gh_audit/render.py`, `tests/test_render.py`

**Step 1: Add the failing tests.** Add `import json` to the test imports, and add `to_json` to the `gh_audit.render` import. Append:
```python
# ---------- JSON ----------

def test_json_has_user_summary_repos_and_findings():
    result = make_result(
        repos=[make_repo(name="a", pushed_at=datetime(2025, 8, 23, 15, 42, tzinfo=timezone.utc))],
        findings=[make_finding(repo="a")],
    )
    data = json.loads(to_json(result, show_info=True, show_checks=True))
    assert data["user"] == "octocat"
    assert data["summary"]["errors"] == 1
    assert data["repos"][0]["name"] == "a"
    assert data["repos"][0]["pushed_at"] == "2025-08-23T15:42:00Z"
    assert data["repos"][0]["stars"] == 0
    assert data["findings"] == [{"repo": "a", "check": "missing-license", "severity": "error",
                                 "status": "fail", "message": "No license"}]


def test_json_info_only_drops_findings():
    data = json.loads(to_json(make_result(), show_info=True, show_checks=False))
    assert "findings" not in data
    assert "errors" not in data["summary"]
    assert "repos" in data


def test_json_checks_only_drops_repos():
    data = json.loads(to_json(make_result(), show_info=False, show_checks=True))
    assert "repos" not in data
    assert data["findings"] == []


def test_json_handles_missing_push_date():
    data = json.loads(to_json(make_result(repos=[make_repo(pushed_at=None)]), True, True))
    assert data["repos"][0]["pushed_at"] is None
```
The tests parse the output with `json.loads` and check the data. They don't compare raw strings, because whitespace and key order would make string comparisons fragile.

**Step 2: Run.** Expected: **FAIL**, `ImportError: cannot import name 'to_json'`.

**Step 3: Implement.** Add `import json` at the top of `render.py`, and add this section **above** `_findings_by_repo`:
```python
# ---------- JSON ----------

def to_json(result: AuditResult, show_info: bool, show_checks: bool) -> str:
    data = {"user": result.user, "summary": summarize(result, show_checks)}
    if show_info:
        data["repos"] = [_repo_dict(repo) for repo in result.repos]
    if show_checks:
        data["findings"] = [vars(finding) for finding in result.findings]
    return json.dumps(data, indent=2)


def _repo_dict(repo: Repo) -> dict:
    data = dict(vars(repo))
    if repo.pushed_at is not None:
        data["pushed_at"] = repo.pushed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    return data
```
Notes:
- `vars(obj)` gives a dataclass's fields as a dict. `dict(...)` makes a copy, so changing `pushed_at` doesn't touch the real `Repo`.
- `json.dumps` keeps its default `ensure_ascii=True`: an emoji in a description becomes `\ud83d...`. That's ugly but **always** safe to print, even on a Windows console that can't show Unicode.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/render.py tests/test_render.py
git commit -m "Add JSON output with section filtering"
```

---

### Phase 6: CLI

`cli.py` is the conductor. It parses flags, loads the token, calls fetch → checks → render, and returns the exit code. It holds no logic of its own beyond that.

#### Task 24: `parse_args` and `exit_code`

**Files:**
- Create: `src/gh_audit/cli.py`, `tests/test_cli.py`

**Step 1: Write the failing tests in `tests/test_cli.py`.**
```python
import pytest

from factories import make_finding
from gh_audit.cli import exit_code, parse_args


# ---------- parse_args ----------

def test_no_flags_shows_everything_as_tables():
    args = parse_args([])
    assert (args.info, args.checks, args.json) == (False, False, False)


def test_info_and_checks_cannot_be_combined(capsys):
    with pytest.raises(SystemExit) as caught:
        parse_args(["--info", "--checks"])
    assert caught.value.code == 2  # argparse's own usage-error code
    assert "not allowed with" in capsys.readouterr().err


# ---------- exit_code ----------

def test_exit_code_rules():
    error = make_finding(severity="error")
    warning = make_finding(severity="warning")
    unknown = make_finding(status="unknown")
    assert exit_code([]) == 0
    assert exit_code([warning]) == 0
    assert exit_code([warning, error]) == 1
    assert exit_code([error, unknown]) == 2
```
On an invalid combination, argparse prints usage to stderr and calls `sys.exit(2)`, which surfaces as `SystemExit`. That happens to match our "tool couldn't run" code.

**Step 2: Run.** Expected: **FAIL**, `ModuleNotFoundError: No module named 'gh_audit.cli'`.

**Step 3: Implement `src/gh_audit/cli.py`.**
```python
"""Entry point: parse flags, run fetch -> checks -> render, choose the exit code."""

import argparse

from gh_audit.models import Finding

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_TOOL_FAILED = 2


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gh-audit",
        description="Audit your own public GitHub repos for basic hygiene.",
    )
    sections = parser.add_mutually_exclusive_group()
    sections.add_argument("--info", action="store_true", help="show only the Info section")
    sections.add_argument("--checks", action="store_true", help="show only the Hygiene section")
    parser.add_argument("--json", action="store_true", help="print JSON instead of tables")
    return parser.parse_args(argv)


def exit_code(findings: list[Finding]) -> int:
    if any(f.status == "unknown" for f in findings):
        return EXIT_TOOL_FAILED
    if any(f.status == "fail" and f.severity == "error" for f in findings):
        return EXIT_FINDINGS
    return EXIT_OK
```
`parse_args(None)` makes argparse read `sys.argv`, which is what the real command does. Tests pass a list instead.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/cli.py tests/test_cli.py
git commit -m "Add CLI flags and exit-code rules"
```

---

#### Task 25: `main`, happy paths

**Files:**
- Modify: `src/gh_audit/cli.py`, `tests/test_cli.py`

**Step 1: Add the failing tests.** Replace the imports at the top of `tests/test_cli.py` with:
```python
import json

import pytest
import requests
import responses

from factories import FAKE_TOKEN, make_finding, make_raw_repo
from gh_audit.cli import exit_code, main, parse_args
from gh_audit.client import API_URL


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)


def register_github(*raws, readme_status=200):
    """Fake a whole GitHub account: /user, /user/repos and one README per repo."""
    responses.get(f"{API_URL}/user", json={"login": "octocat"})
    responses.get(f"{API_URL}/user/repos", json=list(raws))
    for raw in raws:
        responses.get(f"{API_URL}/repos/{raw['full_name']}/readme",
                      json={}, status=readme_status)
```
Append:
```python
# ---------- main: happy paths ----------

@responses.activate
def test_clean_account_exits_0(token, capsys):
    register_github(make_raw_repo())
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "1 repos audited" in out
    assert "✓ clean" in out


@responses.activate
def test_error_finding_exits_1(token):
    register_github(make_raw_repo(license=None))
    assert main([]) == 1


@responses.activate
def test_unknown_readme_exits_2_but_still_prints_results(token, capsys):
    raw = make_raw_repo()
    responses.get(f"{API_URL}/user", json={"login": "octocat"})
    responses.get(f"{API_URL}/user/repos", json=[raw])
    responses.get(f"{API_URL}/repos/{raw['full_name']}/readme", body=requests.Timeout())
    assert main([]) == 2
    captured = capsys.readouterr()
    assert "missing-readme (timed out after 10s)" in captured.out
    assert "README check failed" in captured.err


@responses.activate
def test_info_only_skips_readme_calls_and_never_exits_1(token):
    register_github(make_raw_repo(license=None))
    assert main(["--info"]) == 0
    assert not any("/readme" in call.request.url for call in responses.calls)


@responses.activate
def test_json_output_is_valid_and_progress_stays_off_stdout(token, capsys):
    register_github(make_raw_repo())
    main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)  # fails if any progress text leaked into stdout
    assert data["user"] == "octocat"
    assert "Checking token" in captured.err


@responses.activate
def test_json_checks_only(token, capsys):
    register_github(make_raw_repo(topics=[]))
    main(["--json", "--checks"])
    data = json.loads(capsys.readouterr().out)
    assert "repos" not in data
    assert data["findings"][0]["check"] == "missing-topics"
```
`test_info_only_skips_readme_calls_and_never_exits_1` registers README URLs, so it would **pass even if** README calls were made. That's why it also checks `responses.calls`.

**Step 2: Run.** Expected: **FAIL**, `ImportError: cannot import name 'main'`.

**Step 3: Implement.** Replace the imports at the top of `cli.py` with:
```python
import argparse
from datetime import datetime, timezone

from rich.console import Console

from gh_audit.auth import load_token
from gh_audit.checks import check_all
from gh_audit.client import GitHubClient
from gh_audit.fetch import fetch_all
from gh_audit.models import AuditResult, Finding
from gh_audit.render import print_tables, to_json
```
Append:
```python
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    show_info = not args.checks
    show_checks = not args.info
    out = Console()
    err = Console(stderr=True)

    token = load_token()
    user, repos, forks, archived = fetch_all(
        GitHubClient(token),
        with_readme=show_checks,
        progress=lambda message: err.print(message, style="dim", markup=False),
    )

    findings = check_all(repos, datetime.now(timezone.utc)) if show_checks else []
    result = AuditResult(user, repos, findings, forks, archived)

    if args.json:
        print(to_json(result, show_info, show_checks))
    else:
        print_tables(result, show_info, show_checks, out)
    return exit_code(findings)
```
Notes:
- **The consoles are created inside `main`,** not at import time, so pytest's `capsys` (which swaps `sys.stdout` per test) captures them.
- **`markup=False`** on progress messages: repo names and error reasons are data, not Rich markup.
- **JSON uses plain `print`,** not `out.print`. Rich would add colors and wrap long lines, which would corrupt the JSON.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/cli.py tests/test_cli.py
git commit -m "Wire fetch, checks and render together in main"
```

---

#### Task 26: `main`, failure paths and token-leak guard

**Files:**
- Modify: `src/gh_audit/cli.py`, `tests/test_cli.py`

**Step 1: Append the failing tests.**
```python
# ---------- main: failures ----------

@responses.activate
def test_missing_token_exits_2_with_help(capsys):
    assert main([]) == 2
    err = capsys.readouterr().err
    assert "GitHub token not found" in err
    assert "personal-access-tokens/new" in err
    assert len(responses.calls) == 0  # never contacted GitHub


@responses.activate
@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"status": 401}, "invalid or expired"),
        ({"status": 429}, "rate limit"),
        ({"body": requests.ConnectionError()}, "could not connect"),
    ],
)
def test_fatal_errors_exit_2_with_one_clean_line(token, capsys, kwargs, message):
    responses.get(f"{API_URL}/user", **kwargs)
    assert main([]) == 2
    captured = capsys.readouterr()
    assert message in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


@responses.activate
def test_repo_list_failure_aborts(token, capsys):
    responses.get(f"{API_URL}/user", json={"login": "octocat"})
    responses.get(f"{API_URL}/user/repos", body=requests.Timeout())
    assert main([]) == 2
    assert "Error: timed out after 10s" in capsys.readouterr().err


@responses.activate
@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_token_never_appears_in_any_output(token, capsys, status):
    responses.get(f"{API_URL}/user", status=status)
    main([])
    captured = capsys.readouterr()
    assert FAKE_TOKEN not in captured.out + captured.err
```
`test_missing_token_exits_2_with_help` uses `@responses.activate` even though it shouldn't make any requests. If the code wrongly tried to call GitHub, `responses` blocks it, so the test fails safely instead of reaching the internet.

**Step 2: Run.** Expected: **FAIL**. Exceptions escape from `main` instead of an exit code being returned.

**Step 3: Implement.** Update the imports in `cli.py`:
```python
from gh_audit.auth import MISSING_TOKEN_MESSAGE, load_token
from gh_audit.client import GitHubClient, GitHubError
```
In `main`, replace everything from `token = load_token()` down to the end of the `fetch_all(...)` call with:
```python
    token = load_token()
    if token is None:
        err.print(MISSING_TOKEN_MESSAGE, style="red", markup=False, highlight=False)
        return EXIT_TOOL_FAILED

    try:
        user, repos, forks, archived = fetch_all(
            GitHubClient(token),
            with_readme=show_checks,
            progress=lambda message: err.print(message, style="dim", markup=False),
        )
    except GitHubError as error:
        err.print(f"Error: {error}", style="bold red", markup=False, highlight=False)
        return EXIT_TOOL_FAILED
```
Notes:
- **We catch `GitHubError`, the base class,** so both kinds abort here. That covers a `FatalError` anywhere, and a `RequestError` from `/user` or `/user/repos`. A README `RequestError` never reaches this point, because `fetch_readme` already handled it.
- **We catch nothing else.** A genuine bug (say a `KeyError`) should still show a traceback, because hiding bugs makes them impossible to fix. The "no stack traces" rule is about *expected* failures.
- **`highlight=False`** stops Rich from auto-coloring numbers and URLs inside the message.

**Step 4: Run.** `python -m pytest`. Expected: all pass.

**Step 5: Commit.**
```bash
git add src/gh_audit/cli.py tests/test_cli.py
git commit -m "Handle missing token and GitHub errors with exit code 2"
```

---

#### Task 27: `python -m gh_audit`, plus checks of the installed command

**Files:**
- Create: `src/gh_audit/__main__.py`

**Step 1: Create `src/gh_audit/__main__.py`.**
```python
from gh_audit.cli import main

raise SystemExit(main())
```
This makes `python -m gh_audit` behave exactly like `gh-audit`.

**Step 2: Check what you can, safely.** These commands make **no network calls**.
```bash
python -m pytest                 # all tests pass (103)
gh-audit --help                  # shows usage with --info/--checks/--json
gh-audit --info --checks         # "not allowed with" error, exit code 2
```
**Don't run plain `gh-audit` yourself.** Depending on how your machine is set up, it could pick up a real token.

**Step 3: Live check (the project owner does this).** Ask the owner to run these commands with their real token and confirm the results:
```bash
gh-audit                         # summary line, Info and Hygiene tables
gh-audit --checks; echo $?       # exit code 1 if any repo has an error
gh-audit --json | python -m json.tool > /dev/null && echo "valid JSON"
gh-audit --json --info
```
Record anything surprising they report as a new task. Don't patch it silently.

**Step 4: Commit.**
```bash
git add src/gh_audit/__main__.py
git commit -m "Support python -m gh_audit"
```

---

### Phase 7: Cleanup

#### Task 28: Dockerfile

**Files:**
- Modify: `Dockerfile`

**Step 1: Replace `Dockerfile`.**
```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

ENTRYPOINT ["gh-audit"]
```
- **The token is never baked into the image.** There's no `ENV GITHUB_TOKEN`, and `.env` files aren't copied (the existing `.dockerignore` already excludes `.env`). The token is passed at run time.
- There's no `-it` (the tool never prompts) and no `-v` (it writes no files).
- `ENTRYPOINT` means flags after the image name go straight to `gh-audit`.

**Step 2: Build and smoke-test.** These steps make no network calls to GitHub.
```bash
docker build -t gh-audit .
docker run --rm gh-audit --help
docker run --rm gh-audit; echo $?     # "GitHub token not found", exit 2
```

**Step 3: Live check (owner):** `docker run --rm --env-file ~/.config/gh-audit/.env gh-audit --checks`
Note for the README: Docker's `--env-file` doesn't strip quotes, so the line must be `GITHUB_TOKEN=abc`, not `GITHUB_TOKEN="abc"`.

**Step 4: Commit.**
```bash
git add Dockerfile
git commit -m "Rebuild Docker image around the gh-audit command"
```

---

#### Task 29: README

**Files:**
- Modify: `README.md`

**Step 1: Replace `README.md` with the content below.** Use a real `gh-audit` output from the owner's live check (Task 27) for the example output, or keep the sample shown.

````markdown
# gh-audit

Audits **your own public GitHub repos** for basic hygiene, and shows key repo info in one place.

## What it checks

| Check | Severity |
|---|---|
| `missing-readme` | error |
| `missing-license` | error |
| `missing-description` | error |
| `empty-repo` | error |
| `missing-topics` | warning |
| `stale` (no push in over 12 months) | warning |

Forks and archived repos are skipped and counted in the summary.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/Krishpatel-161-amt/github-profile-auditor.git
cd github-profile-auditor
python -m pip install .
```

## Token

1. Create a fine-grained token at <https://github.com/settings/personal-access-tokens/new>
   with **Repository access: "Public repositories (read-only)"** and an expiry date (for example 90 days).
2. Either set it in your environment:
   ```bash
   export GITHUB_TOKEN=your_token
   ```
   or put it in `~/.config/gh-audit/.env`:
   ```
   GITHUB_TOKEN=your_token
   ```
   On Linux/macOS, restrict the file: `chmod 600 ~/.config/gh-audit/.env`

The environment variable wins if both are set. The token is never printed.

## Usage

```bash
gh-audit              # summary, Info table, Hygiene table
gh-audit --info       # Info only (faster: no README checks)
gh-audit --checks     # Hygiene only
gh-audit --json       # JSON to stdout (combine with --info or --checks)
gh-audit --json > report.json
```

Progress messages go to stderr, so redirected JSON stays valid.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | No errors (warnings allowed) |
| 1 | At least one error finding |
| 2 | The audit couldn't complete: missing/invalid token, rate limit, network failure, or a check that couldn't run |

## Docker

```bash
docker build -t gh-audit .
docker run --rm --env-file ~/.config/gh-audit/.env gh-audit --checks
```

`--env-file` doesn't strip quotes: write `GITHUB_TOKEN=abc`, not `GITHUB_TOKEN="abc"`.

## Example output

```
5 repos audited · 3 with errors · 0 unknown · 1 warnings only · 1 clean · skipped 2 forks, 1 archived
                                                  Hygiene
┌────────────────────────┬──────────────┬──────────────────────────────────────────────────────────────────┐
│ Repository             │ Status       │ Findings                                                         │
├────────────────────────┼──────────────┼──────────────────────────────────────────────────────────────────┤
│ iam-access-provisioner │ ✗ 4 errors   │ missing-readme, missing-license, missing-description, empty-repo │
│                        │ ⚠ 1 warning  │ missing-topics                                                   │
│ github-profile-auditor │ ✓ clean      │                                                                  │
└────────────────────────┴──────────────┴──────────────────────────────────────────────────────────────────┘
```

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Tests never touch the real GitHub API or your token: HTTP is faked with `responses`.

## License

MIT
````

**Step 2: Commit.**
```bash
git add README.md
git commit -m "Rewrite README for gh-audit"
```

---

#### Task 30: Remove the old script, final check, merge

**Files:**
- Delete: `github_auditor.py`, `requirements.txt`

**Step 1: Make sure nothing references the old files.**
```bash
git grep -n -e "github_auditor" -e "requirements.txt" -e "xhtml2pdf" -- . ':!docs/'
```
Expected: no output. If anything shows up, update it first.

**Step 2: Delete.**
```bash
git rm github_auditor.py requirements.txt
```

**Step 3: Full check from a clean environment.**
```bash
python -m venv /tmp/gh-audit-check
# Windows: python -m venv %TEMP%\gh-audit-check
/tmp/gh-audit-check/bin/python -m pip install -e ".[dev]"
/tmp/gh-audit-check/bin/python -m pytest
```
Expected: **103 passed**.

**Step 4: Commit.**
```bash
git commit -m "Remove the old single-file auditor and requirements.txt"
```

**Step 5: Merge (with the owner's go-ahead).**
```bash
git checkout master
git merge --no-ff refactor/gh-audit
git push origin master
```
(The `v0-mvp` tag still points to the original script if anyone needs it.)

---

## Appendix A: Final file tree

```
pyproject.toml
README.md
LICENSE
Dockerfile
.dockerignore
.gitignore
docs/
  github-api-reference.md
  github-api-full-report.md
  plans/2026-10-10-gh-audit-implementation-plan.md
src/gh_audit/
  __init__.py      # docstring only
  __main__.py      # python -m gh_audit
  models.py        # Repo, Finding, AuditResult                (~40 lines)
  auth.py          # load_token, CONFIG_PATH, MISSING_TOKEN_MESSAGE (~30)
  client.py        # GitHubClient, GitHubError/FatalError/RequestError (~90)
  fetch.py         # parse_repo, fetch_login/_repos/_readme/_all (~80)
  checks.py        # check_repo, check_all                     (~40)
  render.py        # summary, tables, JSON                     (~160)
  cli.py           # parse_args, exit_code, main               (~70)
tests/
  conftest.py      # autouse: hide the real token
  factories.py     # make_repo, make_raw_repo, make_finding, NOW, FAKE_TOKEN
  test_auth.py     # 7 tests
  test_client.py   # 28 tests (counting parametrize cases)
  test_fetch.py    # 14 tests
  test_checks.py   # 15 tests
  test_render.py   # 21 tests
  test_cli.py      # 18 tests
```

**Who may import whom** (enforce this in review):

| Module | May import |
|---|---|
| `models` | stdlib only |
| `auth` | `python-dotenv` |
| `client` | `requests` |
| `fetch` | `client`, `models` |
| `checks` | `models` |
| `render` | `models`, `rich` |
| `cli` | everything above |

If `checks` or `render` ever imports `client` or `requests`, the design is broken.

## Appendix B: Reference links

**GitHub REST API**
- List repos for the authenticated user: <https://docs.github.com/en/rest/repos/repos#list-repositories-for-the-authenticated-user>
- Get a repository README: <https://docs.github.com/en/rest/repos/contents#get-a-repository-readme>
- Get the authenticated user: <https://docs.github.com/en/rest/users/users#get-the-authenticated-user>
- Pagination: <https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api>
- Rate limits: <https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api>
- Project notes: `docs/github-api-reference.md`

**Python and tools**
- pytest fixtures: <https://docs.pytest.org/en/stable/how-to/fixtures.html>
- monkeypatch: <https://docs.pytest.org/en/stable/how-to/monkeypatch.html>
- tmp_path: <https://docs.pytest.org/en/stable/how-to/tmp_path.html>
- capsys: <https://docs.pytest.org/en/stable/how-to/capture-stdout-stderr.html>
- parametrize: <https://docs.pytest.org/en/stable/how-to/parametrize.html>
- responses: <https://github.com/getsentry/responses>
- rich tables: <https://rich.readthedocs.io/en/stable/tables.html>
- rich console: <https://rich.readthedocs.io/en/stable/console.html>
- argparse mutual exclusion: <https://docs.python.org/3/library/argparse.html#mutual-exclusion>
- python-dotenv `dotenv_values`: <https://pypi.org/project/python-dotenv/>
- Writing pyproject.toml: <https://packaging.python.org/en/latest/guides/writing-pyproject-toml/>
- setuptools src layout: <https://setuptools.pypa.io/en/latest/userguide/package_discovery.html>
