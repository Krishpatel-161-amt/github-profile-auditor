# CLAUDE.md

gh-audit: a CLI that audits the token owner's public GitHub repos. The design and step-by-step plan live in `docs/plans/2026-10-10-gh-audit-implementation-plan.md`. Read it before doing anything, and follow it exactly. If something is unclear or doesn't match, stop and ask.

- **Token privacy:** never read any `.env` file, print environment variables, or run the tool against real GitHub. Tests use fake tokens and `responses`. The owner does every "live check (owner)" step.
- **Work in batches:** do only the tasks you're asked to. After each one, show the test output and the commit.
- **Run tests:** `python -m pytest` (after `python -m pip install -e ".[dev]"`).
