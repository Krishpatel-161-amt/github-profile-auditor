# GitHub REST API — Condensed Reference (Personal Repo Automation)

Source: "GitHub REST API Architecture and Implementation for Personal Repository Automation" (full report: `detailed full report/GitHub REST API for Personal Automation.md`). Items marked **[unverified]** come only from the report and post-date independent knowledge; check GitHub docs/changelog before relying on them. Items marked **[correction]** override the report.

## Request baseline (every call)

```
Authorization: Bearer <token>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28   # always pin explicitly; 2026-03-10 is the newer version with breaking changes
```

Token health check: `GET /user` (200 = valid). Quota check: `GET /rate_limit` (free, doesn't consume quota).

## Authentication

- **Default: fine-grained PAT.** One resource owner, "Only select repositories", least permissions. Max 365-day expiry (use 30–90). Cap: 50 active per account.
- **Classic PAT** only when required: repos where you're an outside collaborator (FG-PATs can't manage those), or FG-PAT coverage gaps (some legacy resources, Checks API, user-level Projects).
- **User-owned GitHub App** for many repos: sign JWT with RSA private key → `POST /app/installations/{installation_id}/access_tokens` → 1-hour token with its own rate-limit pool.
- Storage: OS keychain / Secret Service, or `gh auth token`. Never in code, `.env` committed to git, or shell rc files. CI: encrypted secrets only.
- Rotation: overlap old and new tokens during renewal, then revoke the old one.

### FG-PAT permission map

| Task | Permissions |
|---|---|
| Read files | Contents: Read |
| Create/update/delete files | Contents: Read & write |
| Edit anything in `.github/workflows/` | Contents: R&W **and** Workflows: R&W (otherwise rejected) |
| Issues, labels, comments | Issues: R&W |
| PRs, merging | Pull requests: R&W |
| Dispatch workflows / read runs & logs | Actions: R&W / Actions: Read |
| Repo secrets | Secrets: R&W |
| Create repos (`POST /user/repos`) | Administration: R&W |
| Traffic endpoints | Push (write) access required, even on public repos |

## Rate limits

Primary (rolling hour):

| Context | Limit |
|---|---|
| Unauthenticated | 60/hr per IP |
| PAT (classic or fine-grained) | 5,000/hr per user (all tokens share one bucket) |
| GitHub App installation | 5,000/hr, +50/repo above 20 repos, max 12,500 |
| `GITHUB_TOKEN` in Actions | 1,000/hr per repo |
| Enterprise Cloud user | 15,000/hr |

Secondary (short-term, return 403 or 429):
- Max 100 concurrent requests (REST + GraphQL combined).
- Points budget: 900 points/min; GET/HEAD/OPTIONS = 1 pt, POST/PATCH/PUT/DELETE = 5 pts. **[correction]** The report says "per single endpoint"; GitHub docs describe it as the budget for REST requests overall — treat it as global.
- Max 90s of server CPU time per 60s.
- Content creation (issues, comments, commits, releases): 80/min, 500/hr.

Headers: `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-used`, `x-ratelimit-reset` (UTC epoch), `x-ratelimit-resource` (core, search, …), `retry-after` (secondary limits, seconds).

## Efficiency

- **Conditional requests:** store `ETag`, send `If-None-Match` (or `Last-Modified` → `If-Modified-Since`). 304 = unchanged, empty body, doesn't count against primary limit when authenticated.
- **Pagination:** follow the `rel="next"` URL from the `Link` header until it's absent. Never build page URLs manually (some endpoints use cursors). `per_page` max is usually 100.
- Don't use `sort=updated` when polling across pages: items shift between pages and you miss entries.
- Skip no-op writes: compare content before PUTting (avoids empty commits and CI runs). Use `[skip ci]` in automated commit messages when appropriate.
- Issues endpoints also return PRs: filter out items that have a `pull_request` key.

## Error handling

| Status | Meaning | Action |
|---|---|---|
| 304 | Cache still valid | Use cached data |
| 401 | Bad/expired token | Stop immediately; alert to rotate token |
| 403 | Primary limit hit **or** missing permission | If `x-ratelimit-remaining == 0`, sleep until `x-ratelimit-reset`; else check permissions |
| 404 | Missing resource **or** private repo you can't see (GitHub masks 403 as 404) | Check URL and token scope |
| 410 | API version retired | Update `X-GitHub-Api-Version` |
| 422 | Validation failure | Read `errors` array; don't retry unchanged |
| 429 / 403 secondary | Secondary limit | Wait `retry-after` seconds; if absent and remaining > 0, wait ≥60s, then back off exponentially |
| 5xx | Transient | Exponential backoff with jitter, capped retries |

Don't retry 400/401/404/422.

## Key endpoints

| Method | Endpoint | Use |
|---|---|---|
| GET | `/repos/{o}/{r}/contents/{path}` | Read file, get blob `sha`, check existence |
| PUT | `/repos/{o}/{r}/contents/{path}` | Create/update one file: `message`, base64 `content`, `branch`, `sha` (required if file exists) |
| DELETE | `/repos/{o}/{r}/contents/{path}` | Delete file (needs `sha`, `message`) |
| GET | `/repos/{o}/{r}/git/ref/heads/{branch}` | Branch HEAD commit SHA |
| GET | `/repos/{o}/{r}/git/trees/{sha}?recursive=1` | Full tree (use for dirs >1,000 files) |
| POST | `/repos/{o}/{r}/git/trees` / `git/commits` | Build multi-file tree / commit |
| PATCH | `/repos/{o}/{r}/git/refs/heads/{branch}` | Move branch to new commit |
| GET/POST | `/repos/{o}/{r}/issues` | List (`state=open|closed|all`) / create (`title` required; `body`, `labels`, `assignees`) |
| PATCH | `/repos/{o}/{r}/issues/{n}` | `state` + `state_reason` (`completed`, `not_planned`) |
| POST / PUT | `/repos/{o}/{r}/issues/{n}/labels` | POST appends labels; PUT replaces the whole set |
| POST | `/repos/{o}/{r}/issues/{n}/comments` | Add comment |
| GET/POST | `/repos/{o}/{r}/pulls` | List / create (`head`, `base`, `title`, optional `draft`) |
| PUT | `/repos/{o}/{r}/pulls/{n}/merge` | `merge_method` (merge/squash/rebase); pass `sha` to guard against unexpected changes |
| POST | `/repos/{o}/{r}/actions/workflows/{id or file.yml}/dispatches` | `ref` required; `inputs` max 25 keys |
| GET | `/repos/{o}/{r}/actions/runs` | Poll run status |
| GET | `/repos/{o}/{r}/actions/runs/{id}/logs` | 302 redirect to temporary ZIP URL |
| GET / PUT | `/repos/{o}/{r}/actions/secrets/public-key` / `…/secrets/{name}` | Secret provisioning (see below) |
| POST / PATCH | `/repos/{o}/{r}/actions/variables` / `…/variables/{name}` | Non-secret config values |
| PUT | `/repos/{o}/{r}/environments/{name}` | Deployment environments |
| GET / PATCH | `/user` | Identity & token check / update profile |
| GET | `/repos/{o}/{r}/collaborators/{user}/permission` | admin/write/read/none |
| PUT | `/repos/{o}/{r}/collaborators/{user}` | Invite (`permission`: pull/push/admin) |
| GET | `/repos/{o}/{r}/traffic/views`, `/clones`, `/popular/referrers`, `/popular/paths` | 14-day traffic; needs push access |
| GET | `/repos/{o}/{r}/zipball/{ref}` | Source archive for backups |
| POST | `/user/repos` | Create repo |

### Contents API vs Git Database API

- **Contents API:** one file per request = one commit per file. Fine for single files (README metrics, one config).
- **Git Database API** (atomic multi-file commit):
  1. `GET git/ref/heads/{branch}` → commit SHA
  2. `GET git/commits/{sha}` → root tree SHA
  3. `POST git/trees` with `base_tree` + entries `{path, mode: 100644|100755, type: "blob", content}`
  4. `POST git/commits` with new tree SHA and `parents: [old_commit_sha]`
  5. `PATCH git/refs/heads/{branch}` with new commit SHA

### Secrets (client-side encryption required)

1. `GET …/actions/secrets/public-key` → `key` (base64) + `key_id`
2. Encrypt with LibSodium sealed box (`crypto_box_seal`; Python: PyNaCl `SealedBox`)
3. `PUT …/actions/secrets/{name}` with `{"encrypted_value": b64, "key_id": key_id}`

### Workflow dispatch run IDs

Classic behavior: returns 204 with no run ID, so you poll runs to find it. **[unverified]** Newer versions support `return_run_details: true` to return the run ID and URLs directly.

## Media types (`Accept`)

- `application/vnd.github+json`: default.
- `application/vnd.github.raw+json`: raw file bytes from Contents API (no base64).
- `application/vnd.github.html+json`: rendered Markdown.
- `application/vnd.github.object+json`: consistent object shape for file/dir listings. **[correction]** For 1–100MB files it returns metadata with empty content; use `raw` to actually get the bytes.

## Platform limits

- Contents API: ≤1MB with default media type; 1–100MB with `raw`; >100MB needs git/LFS.
- Directory listing via Contents API: 1,000 files max → use recursive Git Trees.
- Dispatch inputs: 25 max → pack extra config into one JSON-string input.
- FG-PATs: 50 per account.

## Versioning

- Version via `X-GitHub-Api-Version` header, not URL. Omitted = `2022-11-28`.
- Additive changes are backported to all supported versions; old versions are supported ≥24 months after a successor ships.
- Near retirement: `Deprecation` / `Sunset` response headers. Retired: 410 Gone.

## Recent changes (per report, 2025–2026)

- **[unverified]** Stargazer list (`/stargazers`) restricted to repo admins; aggregate star history via `GET /repos/{o}/{r}/traffic/star_history`.
- Events API payloads trimmed (e.g. `author_association`, commit summaries removed); fetch details from Issue/PR/Commit endpoints.
- Dependabot alerts: offset params (`page`, `first`, `last`) deprecated → cursor pagination.
- Projects v2 REST endpoints and sub-issue relationships added.
- **[unverified]** `return_run_details` on workflow dispatch.

## Coding rules for scripts

- Always paginate list endpoints via `Link` headers, including issue comments. (The report's archiver and stale-triage samples fetch only one page. Don't copy that.)
- Set a `timeout=` on every `requests` call; reuse a `requests.Session` with the baseline headers.
- Retry helper must cover: `retry-after`, primary reset, the 60s secondary fallback, and 5xx backoff with jitter.
- Check file existence with GET before PUT to get the `sha`; treat 404 as "create".
- Libraries: Python `requests`/`httpx` for light scripts, PyGithub for full object models; JS Octokit (`paginate`, retry, throttling plugins); Go `google/go-github`.
