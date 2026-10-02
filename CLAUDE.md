# CLAUDE.md

GitHub Repository Audit CLI: audits a user's public repos for missing README, license, description and topics, and prints a findings table.

**Read `SCOPE.md` first.** It records every agreed decision: architecture, rules, failure policy, exit codes, output, and what's out of scope. Don't contradict it silently. Propose a change and update it once agreed.

## Roles

The user defines requirements and makes architecture decisions. Claude is the implementer: it writes the code and explains its technical choices. When a decision is the user's to make, ask instead of assuming.

## Working rules

1. **One slice at a time.** Never build the whole tool in one go. Keep each slice small enough to finish in one sitting.
2. **Review before writing.** Before coding a slice, list its edge cases and write its test cases (pytest) first.
3. **Boring and idiomatic.** Standard Python (`dataclasses`, `typing`), no clever abstractions. Dependencies: `requests`, `python-dotenv`, `argparse`, `rich`; `pytest` for dev only.
4. **Strict error policy.** 404, 401/403/429 and network failures end with a clean one-line message and exit code 2, never a stack trace. Every request has a timeout.
5. **Explain non-obvious lines.** After each slice, give 2–3 concise bullets on why the logic was chosen.

## Token privacy (hard rule)

- Never read `.env`, print environment variables, or run anything that uses the user's real GitHub PAT.
- Tests use fake tokens and mocked HTTP.
- Live runs are done by the user (e.g. `! python github_auditor.py <username>`).
- Code must never echo the token in output or errors.

## References

- `github-api-reference.md`: condensed GitHub REST API reference (primary).
- `detailed full report/GitHub REST API for Personal Automation.md`: full report (fallback). Items marked [unverified] or [correction] in the condensed file take precedence.

## Git workflow

- One short branch per slice (e.g. `slice-1-http-client`), merged into `master` when its tests pass. `master` must always run.
- The old `github_auditor.py` stays the entry point until the final slice switches it to the new `auditor/` package.
- Tag `v0-mvp` marks the original pre-refactor tool.

## Current status

Scope is agreed. Next decisions: folder structure (proposed: `auditor/` package with `client.py`, `fetch.py`, `rules.py`, `render.py`, `cli.py`, plus `tests/`), the fields of `RepoFacts` / `Finding`, and the minimum Python version (suggested 3.10+). After that comes slice 1, the HTTP client.
