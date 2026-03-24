# AutoApply AI — Engineering Reference

> This is the engineering source of truth: implementation decisions, phase history,
> bug logs, migration details, deployment config, and architecture rationale.
>
> For the product story (what, why, for whom), see the root [`README.md`](../README.md).
> For canonical domain terms, see [`UBIQUITOUS_LANGUAGE.md`](../UBIQUITOUS_LANGUAGE.md).

---

## Table of Contents

1. [Phase History](#phase-history)
2. [Architectural Decisions](#architectural-decisions)
3. [What Failed / Lessons Learned](#what-failed--lessons-learned)
4. [Fly.io Migration Detail](#flyio-migration-detail)
5. [Extension Bug Fixes](#extension-bug-fixes)
6. [CI/CD Details](#cicd-details)
7. [Deployment Config](#deployment-config)
8. [Strategy C Deep Dive](#strategy-c-deep-dive)
9. [Environment Variables](#environment-variables)
10. [Local Dev Setup](#local-dev-setup)
11. [Running Tests](#running-tests)
12. [Q&A Generation Fix (Phase 7)](#qa-generation-fix-phase-7)

---

## Phase History

### Phase 1 — Core data models & API skeleton

- FastAPI app factory, PostgreSQL models (`User`, `Application`, `AuditLog`), Alembic migrations
- Health endpoint, rate limiting, circuit breaker, request-ID middleware
- Resume parser (PDF, DOCX, TEX) + validator
- Application CRUD router

### Phase 2 — Resume intelligence engine

- TF-IDF embedding service (free tier, always computed)
- ATS scoring service: keyword coverage, skills gap, quantification score, MQ coverage
- LLM service: multi-provider (Anthropic, OpenAI, Kimi, Ollama, keyword fallback)
- Tailoring pipeline + resume generator (LaTeX output)

### Phase 3 — GitHub version control + application tracking

- GitHub service: vault folder structure, commit/push, list versions, tag creation
- Retrieval agent: semantic company matching, Levenshtein fuzzy matching, reuse recommendation
- Application tracking with status lifecycle (`draft → tailored → applied → interview → offer/rejected`)
- `ApplicationAnswer` model + persistence

### Phase 4 — Resume Vault API + Chrome Extension

- Vault router (18 endpoints): upload, retrieve, ats-score, generate, Q&A drafts, history, GitHub versions
- Chrome MV3 extension: background worker, content script, sidepanel (`JobScout` + `ApplyMode`)
- Options page: configure API URL, LLM key, Clerk user ID
- ATTACH_RESUME flow: download PDF from backend → inject into file input via content script

### Phase 5 — Production hardening + deployment

- Clerk JWT auth (RS256, JWKS validation, 1-hour cache)
- Docker multi-stage build, Render Blueprint (`render.yaml`)
- GitHub Actions CI: ruff + black + mypy + pytest + tsc + docker build
- Options page validation, typed API client
- `start.sh`: `alembic upgrade head` → `uvicorn`

### Phase 6 — Fly.io migration + extension fixes + UI redesign

- **Migrated hosting** from Render (50s cold-start spin-down) to **Fly.io + Supabase + Upstash Redis** for always-on production
- **Extension sidepanel fixed**: three bugs caused the panel to never open (see [Extension Bug Fixes](#extension-bug-fixes))
- **UI redesigned** to match premium extensions (Simplify / Jobright AI aesthetic):
  - Company avatar: color-coded letter avatar (hue derived from company name)
  - ATS score chip: prominent score badge with color coding (green ≥80, amber ≥65, orange ≥50, red <50)
  - Tab navigation: pill-style tabs with count badges
  - Resume cards: outcome badge (🎉 offer / ✅ interview / 📤 applied / ✕ rejected), ATS score bar, attach button
  - Q&A drafts: numbered draft selector, Regenerate + Use & Fill buttons
  - Job Scout cards: fit score chip, past application count, "Open →" link
  - Idle state: platform-list screen instead of generic message
  - Header: SVG logo, gradient background, mode indicator dot

### Phase 7 — Floating panel + intelligence layer (P1 feature sprint) — 2026-03-12

- **Floating panel** (`floatingPanel.ts`): Shadow DOM isolated panel injected on all career/ATS pages
- **JD text extraction** (L1): `extractJdText()` pulls visible job description text from the page
- **Answer length awareness** (L2): `maxLength` attr on textareas threaded to API → LLM gets word count constraint
- **Per-category style instructions** (L3): Options page textarea fields per question category; injected as "USER STYLE INSTRUCTIONS" block in LLM prompt
- **Category usage tracking + pre-generation** (L4): Auto-pre-generates answers for top-3 most-seen categories on next page visit
- **Per-category model routing** (L5): Options page maps each question Category to a preferred Provider
- **Resume tailoring** (L6): `POST /vault/generate/tailored` — Base Template + work history → targeted LaTeX resume
- **Application history tab** (T1): Status timeline (discovered → offer) + stats row
- **Contenteditable detection** (P5): Detects and fills `contenteditable="true"` divs (Workday, LinkedIn)
- **Platform-specific extraction** (P5): Dedicated selectors for Greenhouse, Lever, Workday, Ashby, SmartRecruiters, LinkedIn, Indeed
- **APPLICATION_SUBMITTED tracking**: Form submit + button click listeners → auto-patch Application status to `applied`
- **Copy-to-clipboard**: ⎘ button on every draft answer with visual checkmark confirmation
- **Smart MutationObserver**: Only re-detects form changes — 30% fewer unnecessary re-renders
- **Q&A generation cascade fix** — see [Q&A Generation Fix](#qa-generation-fix-phase-7)

### Phase 8 — Dashboard v2 + Profile Sync + Floating Panel — 2026-03-21

- **Dashboard v2** (`dashboard/`): 9-page React + Vite app on Vercel — Applications, Resumes, Cover Letters, Answer Vault, Job Scout, Mirror, Reflection, Settings
- **Teal/obsidian design system**: `#0a0b0d` obsidian, `#00c4b4` teal, `#e0e4ef` mercury
- **Two-build extension architecture**: `vite.config.ts` (ES modules) + `build-content.mjs` (IIFE via Vite programmatic API) — fixed "Cannot use import statement outside a module" crash
- **Floating panel redesign**: FAB toggle, full-height obsidian panel, spring slide-in, ATS bar, Resume Vault section, LLM picker, "Best Match" glow for ATS ≥ 0.95
- **Profile sync**: 14 new `users` columns + `GET/PATCH /auth/me` — synced across extension, Dashboard, and backend
- **Answers vault tab**: New "Answers" tab in `ApplyMode.tsx` — search, category filter, inline edit/delete
- **QA agents (Track 1)**: Architecture critique (6 P0 security issues, #85), API integration tests (34/43 pass, #87), Playwright E2E (7/9 pass, #84)
- **Production hotfix**: Missing `notes` column Alembic migration applied to Supabase — all `/applications` routes restored from 500

---

## Architectural Decisions

### Why LaTeX for resumes?

ATS parsers and recruiters can't see behind formatting tricks. LaTeX gives pixel-perfect PDFs with zero layout drift. The `.tex` source is version-controlled in GitHub, diffable, and reusable. Recruiter always gets `{FirstName}.pdf` — no version numbers leaked.

### Why TF-IDF as the free embedding tier?

Paying for embeddings on every resume upload is expensive at scale and adds a hard dependency on an external API. TF-IDF cosine similarity catches keyword overlap accurately for resume-to-JD matching at zero cost. Paid tiers (OpenAI, Kimi) and local Ollama (`nomic-embed-text`) are available for higher-quality semantic search.

### Why per-user encrypted GitHub tokens?

The Vault is personal. Every User stores resumes in their own GitHub repo, not a shared one. Tokens are encrypted with Fernet before DB storage. Users can revoke/rotate tokens without affecting others.

### Why Clerk for auth instead of rolling JWT?

Clerk handles the full auth lifecycle (sign-up, MFA, session management, JWKS rotation) for free up to 10,000 MAU. The backend only validates RS256 JWTs from the JWKS endpoint — zero auth logic to maintain. The `X-Clerk-User-Id` header fallback makes local dev and extension testing work without a full Clerk flow.

### Why Chrome MV3 (not MV2)?

MV3 is the current and only supported Manifest version for new Chrome extension submissions. MV2 extensions are being phased out. Persistent background pages are replaced by service workers (`worker.ts`).

### Why a Sidepanel instead of a popup?

Sidepanels persist while the user fills in the form. A popup closes the moment focus leaves it. Application forms require back-and-forth between the panel and the page — Sidepanel is the only viable UX.

### Why not inject a React app directly into the page?

Content scripts that inject large React trees create styling conflicts, CSP violations, and React version clashes with the host page. The Sidepanel is isolated in its own browsing context with no DOM conflicts.

### Why FormData instead of JSON for vault endpoints?

File uploads (resume file, PDF downloads) require multipart form. Using FormData consistently across all vault endpoints gives the extension API client one code path for all requests.

### Auth resolution priority (`dependencies.py → get_current_user()`)

1. `Authorization: Bearer <jwt>` → validate RS256 against Clerk JWKS (`https://<app>.clerk.accounts.dev/.well-known/jwks.json`, 1-hour cache)
2. `X-Clerk-User-Id: <id>` header → direct DB lookup (dev / extension flow before JWT is wired)
3. Dev fallback → first user in DB if `ENVIRONMENT=development` and no header present

### LLM Provider enabled flag design rule

The `enabled` boolean on `ProviderConfig` was a design flaw. **Having an API key = being enabled.** These two concepts should never be stored independently. Convention in both `floatingPanel.ts` and `ApplyMode.tsx`: `enabled: !!cfg.apiKey`.

---

## What Failed / Lessons Learned

### CI failures on first push

**Root cause 1**: `ci.yml` had `ENVIRONMENT: "testing"` but `config.py` validator only accepts `{"development", "test", "staging", "production"}`. App crashed before any test ran.
**Fix**: Changed to `ENVIRONMENT: "test"`.

**Root cause 2**: `Resume.version_tag` had `index=True` on the column definition AND `Index("ix_resumes_version_tag", "version_tag")` in `__table_args__`. SQLAlchemy `create_all` tried to create the index twice.
**Fix**: Removed `index=True` from the column — the explicit `__table_args__` entry is sufficient.

**Root cause 3**: CI workflow ran `alembic upgrade head` then conftest's `create_all` tried to recreate the same indexes → `DuplicateTableError`.
**Fix**: Added `drop_all` before `create_all` in conftest fixture to guarantee a clean slate.

**Root cause 4**: Tests in `test_application_service.py` were written for a stale API (`ApplicationService(db_session)` constructor, wrong parameter names).
**Fix**: Rewrote tests to match actual service signatures.

---

### Render Blueprint — env var mismatch

`render.yaml` used `GITHUB_REPO_OWNER` / `GITHUB_REPO_NAME` but `.env` convention uses `GITHUB_VAULT_OWNER` / `GITHUB_VAULT_REPO`.
**Fix**: Updated `render.yaml` to match.

---

### Extension API URL hardcoded

`api.ts` hardcoded `const API_BASE = "http://localhost:8000/api/v1"` regardless of the options page setting.
**Fix**: `api.ts` now reads `apiBaseUrl` from storage at module load and syncs via `chrome.storage.onChanged`. Falls back to localhost for dev.

---

### Docker Desktop context (Windows)

On Windows, Docker Desktop uses `//./pipe/dockerDesktopLinuxEngine` but the default context uses `//./pipe/docker_engine`. Switching context to `default` after ensuring Docker Desktop is running resolves this.

---

### Docker build CI — HTTP 522 from Docker Hub

```
ERROR: failed to fetch oauth token: unexpected status ... 522
```

HTTP 522 = Cloudflare "origin connection timed out". GitHub Actions runners share IPs that hit Docker Hub's anonymous pull rate limits (~100 pulls/6h per shared IP block).

**Fix 1 — Docker Hub login**: Authenticated pulls get 200/6h *per account*. Add `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` as repo secrets. The `docker/login-action@v3` step skips gracefully if secrets are absent.

**Fix 2 — `continue-on-error: true`**: The Docker job is a build-validity check only, not a deployment gate. A transient Docker Hub outage should not block `backend` and `extension` CI jobs.

---

### Dockerfile `COPY docs/ ./docs/` error

```
ERROR: "/docs": not found
```

`docs/` lives at the project root but the Docker build context is `./backend`. Docker cannot reach outside its build context. Fix: remove `COPY docs/ ./docs/` — `_load_doc()` in `resume_generator.py` already returns `""` gracefully when files are missing.

---

### `python-magic-bin` fails on Linux

```
RuntimeError: Unable to find installation candidates for python-magic-bin (0.4.14)
```

`python-magic-bin` is a Windows-only package that bundles `libmagic.dll`. It has no Linux build. Removed from `pyproject.toml`.

---

### Docker Hub secrets added via GitHub API

GitHub CLI (`gh`) was not installed locally. Used `curl` + PyNaCl (`nacl.public.SealedBox`) to:
1. Fetch the repo's RSA public key from `GET /repos/{owner}/{repo}/actions/secrets/public-key`
2. Encrypt each secret value with a libsodium sealed box
3. `PUT /repos/{owner}/{repo}/actions/secrets/{name}` with encrypted payload + key_id

---

### Render free tier conflict — Blueprint failed silently

```
Create database autoapply-db  (cannot have more than one active free tier database)
Create Key Value autoapply-redis  (cannot have more than 1 free tier Redis instance)
Create web service autoapply-ai-api  (canceled: another action failed)
```

An existing `job-scout` Blueprint already occupied both free-tier slots.
**Fix**: Delete job-scout Blueprint resources in Render dashboard, then re-sync the autoapply-ai Blueprint.
**Lesson**: Render Blueprint apply fails silently with "canceled" when an upstream resource fails.

---

### Render deploy — `No module named 'psycopg2'`

Render injects `DATABASE_URL` as `postgresql://` (psycopg2 sync scheme). Our stack requires `postgresql+asyncpg://`.
**Fix**: Added `field_validator("DATABASE_URL", mode="before")` in `config.py`:

```python
@field_validator("DATABASE_URL", mode="before")
@classmethod
def fix_database_url(cls, v: str) -> str:
    if v.startswith("postgres://"):
        return v.replace("postgres://", "postgresql+asyncpg://", 1)
    if v.startswith("postgresql://"):
        return v.replace("postgresql://", "postgresql+asyncpg://", 1)
    return v
```

---

### Poetry `README.md not found` during Docker build

```
Warning: The current project could not be installed: [Errno 2] No such file or directory: '/app/README.md'
```

`pyproject.toml` had `readme = "README.md"` and `packages = [{include = "app"}]`. The README is outside the `./backend` Docker build context.
**Fix**: Replaced both fields with `package-mode = false` — Poetry treats the project as dependency-management-only.

---

### Dashboard blank screen — placeholder Clerk key

`dashboard/.env.local` had `VITE_CLERK_PUBLISHABLE_KEY=pk_test_placeholder`. Clerk v5 rejects this with a fatal error on mount, crashing the entire React tree. The `AuthProvider` bypass doesn't fire because the key string IS set, just invalid.
**Fix**: Set the actual Clerk publishable key, or leave it empty to trigger the dev bypass. Tracked in [#84](https://github.com/narendranathe/autoapply-ai/issues/84).

---

### Production 500 — notes column missing in Supabase

Alembic migration `d1e5f3a4b2c6` (adds `notes TEXT` to `applications`) was never applied to the production Supabase database. SQLAlchemy tried to SELECT the `notes` column → DB rejected → all `/applications` routes returned 500.
**Fix**: Applied migration via `fly ssh console` + `python -m alembic upgrade head`. Tracked in [#87](https://github.com/narendranathe/autoapply-ai/issues/87).

---

## Fly.io Migration Detail

### Why migrate from Render to Fly.io?

| | Render (before) | Fly.io + Supabase (now) |
|---|---|---|
| PostgreSQL | 256 MB shared, 1 active free DB | Supabase 500 MB free, no spin-down |
| Redis | 25 MB, spin-down | Upstash Redis, pay-as-you-go ($0.20/100K commands) |
| Web service | 50s cold start | Fly.io shared-cpu-1x, `min_machines_running = 1` |
| Auto-deploy | Render webhook | GitHub Actions → `flyctl deploy` |

### New / changed files

- `backend/fly.toml` — `auto_stop_machines = false`, `min_machines_running = 1`
- `config.py`: added `DB_PASSWORD: str = ""` and `DB_SSL_REQUIRE: bool = False`
- `models/base.py`: `make_url(DATABASE_URL).set(password=DB_PASSWORD)` — SQLAlchemy injects password via URL object
- `alembic/env.py`: removed `config.set_main_option("sqlalchemy.url", ...)` — `configparser` treats `%` as interpolation, crashing on `%40` in percent-encoded passwords
- `.github/workflows/ci.yml`: added `deploy` job (runs `flyctl deploy --remote-only` on `main`)

### Errors and fixes during migration

**`start.sh` CRLF line endings** — Windows git checked out `start.sh` with `\r\n`. Linux Docker sees `#!/bin/sh\r`.
**Fix**: `sed -i 's/\r//' start.sh` + `.gitattributes` enforcing LF for `*.sh`.

**Alembic `configparser` percent-encoding** — `ValueError: invalid interpolation syntax` on `%40` in DB password URL.
**Fix**: Read `settings.DATABASE_URL` directly; bypass `configparser` entirely.

**Supabase IPv6** — Fly.io machines prefer IPv6. Supabase direct connection on port 5432 is IPv4-only.
**Fix**: Use session mode pooler URL (`aws-1-us-east-1.pooler.supabase.com:5432`) which runs on IPv4.

**Password with `@` signs** — `N@rendr@n@th` contains `@` (credential separator in URLs). `make_url().set(password=...)` still failed because Fly stored the decoded value with literal `@`.
**Final fix**: Reset Supabase password to `AutoApply2026Prod` (no special characters).

### Production deploy confirmation

```bash
curl https://autoapply-ai-api.fly.dev/health
# → {"status":"alive","service":"autoapply-ai"}

curl -X POST https://autoapply-ai-api.fly.dev/api/v1/auth/register \
  -H "X-Clerk-User-Id: user_3AB26PAgD82zYApFLsMeqaTQyDT"
# → {"user_id":"4c458e37-7e10-411e-95b3-4ddca1648ca8","created":true}
```

---

## Extension Bug Fixes

### Three bugs that caused the Sidepanel to never open

**Bug 1 — `chrome.sidePanel.open()` in `tabs.onUpdated` fails silently**

In Chrome MV3, `chrome.sidePanel.open()` can only be called from a user gesture handler. `tabs.onUpdated` is NOT a user gesture — Chrome ignores the call silently.

**Fix:**
```typescript
// At module level — one call, permanent fix
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
chrome.action.onClicked.addListener((tab) => {
  if (tab.id) chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
});
```

**Bug 2 — `OPEN_SIDEPANEL` message not handled**

Content script calls `chrome.runtime.sendMessage({ type: "OPEN_SIDEPANEL" })` when the overlay badge is clicked. Background worker had no handler — message dropped silently.

**Fix:** Added `case "OPEN_SIDEPANEL"` in the `onMessage` switch calling `chrome.sidePanel.open({ tabId: sender.tab.id })`.

**Bug 3 — Greenhouse URL pattern too strict**

`CAREER_URL_PATTERNS` had `/greenhouse\.io\/jobs\//` — only matched URLs with `/jobs/` in the path. `boards.greenhouse.io/company` didn't match.

**Fix:** Loosened to `/greenhouse\.io/` — any Greenhouse subdomain triggers Apply Mode.

---

### IIFE build fix — "Cannot use import statement outside a module"

Content scripts cannot use ES module `import` syntax. The original single `vite.config.ts` build emitted content scripts as ES modules with shared chunk imports.

**Fix — two-build architecture:**
- `vite.config.ts` — ES module build for Sidepanel, background worker, options page
- `build-content.mjs` — IIFE build via Vite programmatic API for `detector.ts` and `floatingPanel.ts`

Key Vite config for IIFE:
```js
// build-content.mjs
rollupOptions: {
  output: {
    format: 'iife',
    dir: resolve(__dirname, 'dist'),
    entryFileNames: '[name].js',
  }
}
```

Do NOT use `build.lib` (no `.js` extension) or `output.file` (unsupported for multiple entries).

---

### Manifest invalid wildcard patterns

Chrome MV3 rejects wildcard host segments in `content_scripts[].matches`:
```
// INVALID — Chrome rejects these:
"*://careers.*.*/*"
"*://jobs.*.*/*"
"*://apply.*.*/*"
```
**Fix:** Removed the three invalid patterns from `manifest.json`.

---

## CI/CD Details

Three jobs in `.github/workflows/ci.yml`. Triggered on push to `main`, `feat/**`, `fix/**` and PRs to `main`.

| Job | Checks |
|---|---|
| `backend` | ruff → black → mypy → alembic upgrade head → pytest (Postgres + Redis services) |
| `extension` | npm ci → tsc --noEmit → npm run build → upload dist artifact on main |
| `docker` | docker buildx build (no push) — Dockerfile validity |

### `backend` job detail

- Spins up `postgres:15` and `redis:7` as GitHub Actions services
- `ENVIRONMENT=test`, `DATABASE_URL` → service container, `REDIS_URL`, `JWT_SECRET`, `FERNET_KEY`
- `alembic upgrade head` creates schema, then `pytest tests/ -v`

### `extension` job detail

- Runs `npm ci` in `./extension`
- `npx tsc --noEmit` — type validation only
- `npm run build` — triggers both `vite.config.ts` and `build-content.mjs`
- On `main`: uploads `extension/dist/` as CI artifact

### `docker` job detail

- `docker/login-action@v3` — skipped gracefully if `DOCKERHUB_USERNAME` secret absent
- `docker buildx build` — validates multi-stage Dockerfile with `./backend` as build context
- `continue-on-error: true` — Docker Hub transient failures don't block the deployment gate

### `deploy` job detail

- Depends on `backend` + `extension` passing
- Runs only on `main`
- `flyctl deploy --remote-only` — builds in Fly's infrastructure
- Requires `FLY_API_TOKEN` in GitHub Actions secrets

### GitHub Actions secrets

| Secret | Purpose |
|---|---|
| `DOCKERHUB_USERNAME` | Authenticated Docker Hub pulls (200/6h per account) |
| `DOCKERHUB_TOKEN` | Docker Hub access token (read-only) |
| `FLY_API_TOKEN` | Fly.io deploy auth |

---

## Deployment Config

### Fly.io

`backend/fly.toml`:
```toml
[http_service]
  auto_stop_machines = false
  min_machines_running = 1
[[vm]]
  memory = "256mb"
  cpu_kind = "shared"
  cpus = 1
```

**Manual deploy:**
```bash
cd backend && fly deploy --remote-only
```

**Production secrets** (`fly secrets set KEY=value --app autoapply-ai-api`):
```
DATABASE_URL        postgresql://postgres.hobhlxhmqhqdahokqndq@aws-1-us-east-1.pooler.supabase.com:5432/postgres
DB_PASSWORD         AutoApply2026Prod
DB_SSL_REQUIRE      true
REDIS_URL           redis://default:<token>@fly-autoapply-redis.upstash.io:6379
CLERK_SECRET_KEY    sk_test_...
CLERK_FRONTEND_API_URL  https://feasible-liger-35.clerk.accounts.dev
GITHUB_TOKEN        ghp_...
GITHUB_VAULT_REPO   resume-vault
GITHUB_VAULT_OWNER  narendranathe
FERNET_KEY          <generated>
JWT_SECRET          <generated>
EXTENSION_ID        (set after Chrome Web Store approval)
```

### Supabase (PostgreSQL)

Free tier: 500 MB, no spin-down. **Always use the session mode pooler URL** (IPv4, required for Fly.io):

```
Host:     aws-1-us-east-1.pooler.supabase.com
Port:     5432
Database: postgres
User:     postgres.hobhlxhmqhqdahokqndq
SSL:      required
```

DB Shell: https://supabase.com/dashboard/project/hobhlxhmqhqdahokqndq/editor

Do NOT use the direct `db.*.supabase.co:5432` URL — IPv6 only, fails on Fly.io.

### Upstash Redis

`fly-autoapply-redis.upstash.io:6379`. Pay-as-you-go, $0.20/100K commands. Used for: rate limiting, JD embedding cache, circuit breaker state.

### Render (archived)

`render.yaml` exists for reference. Not deployed. Free tier 50s cold-start breaks extension UX.

### Clerk

Instance: `feasible-liger-35.clerk.accounts.dev`.
JWKS: `https://feasible-liger-35.clerk.accounts.dev/.well-known/jwks.json` (1-hour backend cache).

### Dashboard (Vercel)

`dashboard/.env.local`:
```bash
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
VITE_API_BASE_URL=https://autoapply-ai-api.fly.dev/api/v1
```

`vercel.json` configures SPA routing (all paths → `index.html`) and `installCommand: "npm install --legacy-peer-deps"` (React 19 / next-themes peer dep conflict).

### Chrome Web Store packaging

```bash
cd extension && npm run build
# PowerShell:
Compress-Archive -Path dist\* -DestinationPath ..\autoapply-extension.zip
```

After approval, lock CORS:
```bash
fly secrets set EXTENSION_ID=<32-char-id> --app autoapply-ai-api
```

Current unpacked extension ID: `cepfanhjdjlhmfchelknemfmlodnmbfa`

### Resume naming conventions

- **Internal / Git tag**: `{FirstName}_{CompanyShortName}_{RoleAbbrev}[_{JobID}]` e.g. `Narendranath_Google_DE`
- **Recruiter-facing PDF**: always `{FirstName}.pdf` — no version numbers exposed
- **File stored in vault**: `versions/Narendranath_Google_DE.tex`

---

## Strategy C Deep Dive

> PRD #46 superseded. Dual-agent analysis (2026-03-18) rejected Strategy B (full TriObserver) in favour of Strategy C. See [PRD #56](https://github.com/narendranathe/autoapply-ai/issues/56).

### Why Strategy B Was Rejected

| Rejected mechanism | Failure mode |
|---|---|
| Body-level `ResizeObserver` | Fires 10–15× per Workday step animation → race conditions on `questionStates` |
| `IntersectionObserver` | Fires mid-animation before React re-attaches elements → partial DOM reads |
| Auto-save on 2s keystroke debounce | Persists partial text (`"I worked at Goog"`) to Vault → silent data corruption |

### Detection Tiers

| Tier | Mechanism | What it catches |
|---|---|---|
| 1 (existing) | Single `MutationObserver` on form element add/remove | 95% of ATS platforms — do not change |
| 2 (new) | Targeted `ResizeObserver` on known SPA containers | Workday wizard step transitions, Greenhouse modal swaps |
| 3 (new) | `postMessage` iframe injection (same-origin only) | Workday/Taleo iframe-embedded forms |

**Tier 2 containers**: `.app-container`, `main`, `[data-qa="job-container"]`, `.form-wrapper`, `[class*="step"]`, `[class*="wizard"]`
**Tier 2 threshold**: only fires `redetect()` when container height changes by **>50px** (400ms debounce).

### Feature Slice 1 — Vault Recall in `redetect()`

When `redetect()` adds a new DetectedQuestion, it immediately calls `GET /vault/answers/similar` **before** any LLM generation:
- Hard floor: `tfidf_similarity >= 0.25`
- Vault answers labeled **"From Memory"** with similarity badge ("87% match")
- If 2+ vault answers found, skip `preGenerateTopCategories()` for that question
- Ranking: `reward_score × 0.7 + tfidf_similarity × 0.3`

### Feature Slice 2 — ATS Auto-Fill Banner

After `loadAtsScore()` resolves, if `atsScore >= 0.75`:
1. Snapshot DOM field values into `_preAutoFillValues: Map<string, string>`
2. Call `fillAll()` (fills from Profile)
3. Show dismissable **"Auto-filled from your profile"** banner with **Undo**
4. Banner dismissed per session via `sessionStorage` key: `aap_autofill_dismissed_<company>`

**Never silently fills.** Banner + Undo is mandatory.

### Feature Slice 3 — Cover Letter Background Pre-Fetch

On `init()`, non-blocking background fetch calls `GET /vault/cover-letters?company=<name>`:
- Match found → pre-populate cover letter textarea + **"Loaded from vault"** badge
- No match + `jdText` available → queue background generation (idempotency guard via sessionStorage per URL hash)
- Manual Generate button always works as override

### Deduplication Fix

Fields deduplicated by `fieldId + labelHash` composite key. ATS platforms reuse generic IDs (`field_1`, `field_2`) across wizard steps.

Hash: `djb2(label.toLowerCase().replace(/\s+/g," ").replace(/[^\w\s]/g,"").trim())`

### Module Map

```
Extension (floatingPanel.ts unless noted):
├── #57 LabelHashDeduplication   detectFields() + redetect() dedup set              S
├── #58 VaultRecallConnector     redetect() + background fetch                       M
├── #59 SimilarityBadgeUI        render() + css() — "From Memory" + % badge         S
├── #60 ATSAutoFillBanner        maybeAutoFill() after loadAtsScore()                M
├── #61 CoverLetterPreFetcher    prefetchCoverLetter() in init()                     S
├── #62 SPAResizeObserver        attachSPAResizeObserver() in init()                 S
└── #63 IframeFieldBridge        scanIframes() in redetect() + detector.ts handler  M

Backend:
└── #58 tfidf_similarity exposed  retrieval_agent.py — return scored pairs           S
```

### Dependency Graph

```
#57 (LabelHash) ──────────────────────────────────────► #63 (IframeFieldBridge)
#58 (VaultRecall) ──► #59 (SimilarityBadge)
#60 (ATSBanner)       [standalone]
#61 (CoverLetterPre)  [standalone]
#62 (SPAResize)       [standalone]
```

### Cover Letter generation rules

- **Tone**: Professional (default) | Enthusiastic | Concise — user-selectable
- **Length**: ~300 / ~400 / ~500 words — user-selectable
- **Grounded in**: JD text + WorkHistoryEntry bullets + User name
- **Saved**: every generated letter → `/vault/answers/save` with `category=cover_letter`
- **Re-used**: next visit to same company → auto-surfaced via `prefetchCoverLetter()`
- **Never overwrites**: existing saved letters shown as alternatives

---

## Environment Variables

### Backend — full `.env` reference

```bash
# Database
DATABASE_URL=postgresql+asyncpg://autoapply:localdev@localhost:5432/autoapply
# Validator in config.py auto-rewrites postgres:// and postgresql:// → postgresql+asyncpg://
# Production (session mode pooler, IPv4):
# postgresql://postgres.hobhlxhmqhqdahokqndq@aws-1-us-east-1.pooler.supabase.com:5432/postgres

DB_PASSWORD=          # Separate password field — avoids URL percent-encoding issues
                      # Production: AutoApply2026Prod
DB_SSL_REQUIRE=false  # Set true for Supabase

# Redis
REDIS_URL=redis://localhost:6379
# Production: redis://default:<token>@fly-autoapply-redis.upstash.io:6379

# App
ENVIRONMENT=development   # development | test | staging | production
JWT_SECRET=<any string for dev>
FERNET_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# Clerk
CLERK_SECRET_KEY=sk_test_...
CLERK_FRONTEND_API_URL=https://<slug>.clerk.accounts.dev
# Production: https://feasible-liger-35.clerk.accounts.dev

# GitHub vault
GITHUB_TOKEN=ghp_...
GITHUB_VAULT_REPO=resume-vault
GITHUB_VAULT_OWNER=narendranathe

# Extension CORS — set to specific extension ID in production
EXTENSION_ID=   # Current unpacked ID: cepfanhjdjlhmfchelknemfmlodnmbfa
```

### `chrome.storage.local` keys

| Key | Contents |
|---|---|
| `clerkUserId` | Authenticated User's Clerk ID |
| `apiBaseUrl` | Backend API base URL (default: `http://localhost:8000/api/v1`) |
| `providerConfigs` | Array of UserProviderConfig objects |
| `profile` | User's 14 profile fields |
| `promptTemplates` | Custom per-category prompt overrides |
| `categoryModelRoutes` | Per-category preferred Provider mapping |
| `categoryUsage` | Count of questions seen per category |
| `offline_queue` | Array of pending OfflineEdit sync jobs |

### Dashboard — `.env.local`

```bash
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
VITE_API_BASE_URL=https://autoapply-ai-api.fly.dev/api/v1
```

---

## Local Dev Setup

```bash
# 1. Start Postgres + Redis
docker compose up -d

# 2. Apply migrations
cd backend && poetry run alembic upgrade head

# 3. Start backend
poetry run uvicorn "app.main:create_app" --factory --reload --port 8000

# 4. Build extension (watch mode)
cd extension && npm run build -- --watch
# Load extension/dist/ as unpacked extension in chrome://extensions

# 5. Start dashboard (optional)
cd dashboard && npm install --legacy-peer-deps && npm run dev
```

### Docker Compose services

| Service | Port | Purpose |
|---|---|---|
| postgres | 5432 | Primary dev database |
| db_test | 5433 | Isolated test database (separate from dev) |
| redis | 6379 | Rate limiting, caching |
| ollama (profile) | 11434 | Local LLM — `docker compose --profile ollama up` |

### Alembic migrations (11 in order)

1. `15d0f847bcc2` — initial schema (users, applications, audit_log)
2. `a3f2e1d4c5b6` — resume vault (resumes, resume_usages, application_answers)
3. `f3a7b1c2d4e5` — provider configs (user_provider_configs)
4. `c9f4a2b3d1e5` — work history (work_history_entries)
5. `e2f6a3b4c7d8` — document chunks (document_chunks with embedding_vector)
6. `a1b2c3d4e5f6` — file hash (resume file_hash for deduplication)
7. `b8e3f9a1c2d4` — answer feedback (reward_score on application_answers)
8. `d1e5f3a4b2c6` — notes (notes column on applications)
9. `a4b8c2d6e1f9` — profile fields (14 new columns on users)
10. `45ca64ce5f2e` — merge migration (consolidates parallel branches)

---

## Running Tests

```bash
cd backend

# Unit + integration tests
ENVIRONMENT=test \
DATABASE_URL="postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test" \
REDIS_URL="redis://localhost:6379" \
JWT_SECRET="any" \
FERNET_KEY="x_fMBr_lJSHIVPOtMtFxnq5RZ34kEFiL-7UEiM-JKYA=" \
poetry run pytest tests/ -v

# Lint + format + types
poetry run ruff check app/ tests/
poetry run black --check app/ tests/
poetry run mypy app/

# Extension typecheck + build
cd ../extension && npx tsc --noEmit && npm run build

# Dashboard E2E (requires Vite dev server running)
cd dashboard && npx playwright test
# 9 tests — 7/9 passing, 2 known failures in #84
```

**Current status**: ~355 backend tests across 39 files, 0 TypeScript errors, extension build clean.

### Test database notes

`db_test` runs on port 5433 (separate from dev on 5432). Conftest runs `drop_all` + `create_all` each test session — needed because `alembic upgrade head` creates indexes before conftest, and a subsequent `create_all` without `drop_all` causes `DuplicateTableError`.

---

## Q&A Generation Fix (Phase 7)

### What Was Broken

**Symptom 1: Q&A tab showed the same answer 3 times**

Root cause chain:
1. `generate_answer_drafts_cascade()` and `providers_json` handling existed only locally — never deployed. Production ignored the Provider list and fell back to rule-based generation silently.
2. `_parse_answer_drafts()` padded with `drafts.append(drafts[0])` when LLM used non-standard formatting → 3 identical copies.
3. `_rule_based_answer_drafts()` itself returned the same string 3 times per category.

**Symptom 2: "Saved — no providers enabled (fallback mode)"**

Options page stored `{ enabled: false, apiKey: "..." }` — users entered keys but missed the checkbox. `buildProviderList` filtered by `cfg.enabled` → empty array → Fallback every time.

**Symptom 3: Wrong fields appearing in Q&A tab**

"LinkedIn Profile", "GitHub Profile", "First Name*" treated as essay questions — `detectQuestions()` included any textarea with label ≥ 10 chars.

### Fixes Applied

**Backend** (`resume_generator.py`, `vault.py`):
- `generate_answer_drafts_cascade()`: ranks anthropic=1 → openai=2 → gemini=3 → groq=4 → perplexity=5 → kimi=6
- `_call_gemini()`: OpenAI-compatible endpoint at `generativelanguage.googleapis.com/v1beta/openai/...`
- `_parse_answer_drafts()`: multi-strategy — `DRAFT_N` markers → paragraph split → whole response fallback
- `_rule_based_answer_drafts()`: returns 3 genuinely distinct drafts per category
- **Critical: deployed with `fly deploy --remote-only`** — nothing worked until this step

**Extension** (`options.ts`):
- `readProviderUI()`: `enabled: !!apiKey` — enabled flag mirrors key presence, no checkbox needed
- `wireProviderAutoEnable()`: checkbox auto-checks/unchecks as user types

**Extension** (`ApplyMode.tsx`):
- `buildProviderList()`: filters by `!!cfg.apiKey` (not `cfg.enabled`)
- `getFreshProviders()`: reads `chrome.storage.local` directly at generate time — bypasses React state timing
- `NON_QUESTION_PATTERNS`: prevents URL/name/contact fields appearing in Q&A tab

**Extension** (`detector.ts`):
- `isEssayQuestion()`: label must be ≥ 15 chars AND not match `NON_QUESTION_PATTERN`
- URL/profile fields handled by Fields tab, not Q&A tab

### Design Lesson

The `enabled` boolean on `ProviderConfig` was a design flaw. **Having an API key = being enabled.** The checkbox in the UI must derive from key presence, not be stored independently.

### RL / Answer Memory Layer

`ApplicationAnswer.reward_score` computed from Feedback:

| Feedback | reward_score |
|---|---|
| `used_as_is` | 1.0 |
| `edited` | 0.8 |
| `regenerated` | 0.2 |
| `skipped` | 0.0 |

High-reward past answers (≥ 0.8) injected as style examples into future LLM prompts for the same company/role context — lightweight personalization without fine-tuning.

---

*Last updated: 2026-03-23. For canonical terms, see [`UBIQUITOUS_LANGUAGE.md`](../UBIQUITOUS_LANGUAGE.md).*
