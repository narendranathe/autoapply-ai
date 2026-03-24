# AutoApply AI

AI-powered job application assistant. Watches you browse job boards, scores roles against your resume vault, auto-fills application forms, and generates tailored resumes + Q&A answers on demand.

---

## What It Is

A full-stack system with two moving parts:

1. **Backend** — FastAPI service that stores your resume vault, scores resumes against job descriptions, generates tailored LaTeX resumes via LLM, and persists Q&A answers.
2. **Chrome Extension (MV3)** — Sidepanel that activates on job boards and career pages. Two modes: Job Scout (browse + score jobs) and Apply Mode (form-fill + Q&A generation).

---

## Architecture

```
Chrome Extension (MV3)
├── Background worker      URL detection, sidepanel trigger, offline sync queue
├── Content script         Form field detection, job card scraping, field injector
└── Sidepanel (React+TS)
    ├── App.tsx            Mode dispatcher (idle / scout / apply)
    ├── JobScout.tsx       Job list with ATS scores per card
    └── ApplyMode.tsx      3-tab form filler (resumes, fields, Q&A)

FastAPI Backend
├── /api/v1/vault/         18 endpoints — upload, retrieve, score, generate, Q&A, history
├── /api/v1/applications/  Application CRUD + stats
├── /api/v1/auth/          Clerk webhook + user registration
└── /health                Liveness probe

PostgreSQL
├── users                  Clerk ID + encrypted GitHub PAT + LLM key
├── resumes                Parsed resume + TF-IDF/embedding vectors + ATS metadata
├── resume_usages          Every submission (company, role, outcome, ats_score)
├── application_answers    Saved Q&A per company/role (recruiter callback reference)
├── applications           Application lifecycle tracking
└── audit_logs             Immutable event log

Redis
└── Rate limiting counters, JD embedding cache, circuit breaker state

GitHub (private repo: resume-vault)
├── versions/              Current best resume per company/role (flat .tex files)
├── applications/          Dated submission history
├── private/               Personal data (never public)
└── template/              Base LaTeX structural template
```

---

## Domain Language

All terms used in code, docs, and conversations are defined in [`UBIQUITOUS_LANGUAGE.md`](./UBIQUITOUS_LANGUAGE.md). When in doubt about what a term means, that file is the authority.

**Application status lifecycle:**
```
discovered → draft → tailored → applied → phone_screen → interview → offer
                                         ↘ rejected (from any stage)
```

**Key concepts at a glance:**

| Term | Means |
|---|---|
| **Vault** | All stored resumes + answers for a user |
| **Base Template** | User-uploaded master resume (foundation for generation) |
| **ATS Score** | Float 0.0–1.0 — resume fit against a specific JD |
| **Floating Panel** | Shadow DOM overlay injected on job application pages |
| **Provider** | LLM service (`anthropic`, `openai`, `kimi`, `groq`, `ollama`, `fallback`) |
| **Category** | Question type (`why_company`, `challenge`, `motivation`, etc.) |
| **Feedback** | RL signal on an answer: `used_as_is` / `edited` / `regenerated` / `skipped` |
| **RAG** | Injecting retrieved work history chunks into LLM prompts |
| **Platform** | Job board / ATS (`linkedin`, `greenhouse`, `lever`, `workday`, `indeed`) |

---

## Key Flows

### Job Scout Mode
1. User navigates to LinkedIn / Indeed / Glassdoor job listings
2. Background worker matches URL → opens sidepanel in scout mode
3. Content script scrapes `.job-card-container` (LinkedIn) or `[data-testid]` (Indeed)
4. Each job card → `POST /vault/retrieve` → returns ATS score + history count
5. Sidepanel renders cards with color-coded ATS bar (green ≥80, amber ≥65, red <50)

### Apply Mode (Career Page)
1. User lands on a company career application page
2. Content script detects form fields (name, email, phone, file uploads) and textareas (cover letter, open-ended questions)
3. Sidepanel shows **Resumes tab**: past vault resumes for that company with attach button
4. Sidepanel shows **Fields tab**: detected fields with suggested fill values
5. Sidepanel shows **Q&A tab**: detected questions with "Generate 3 Drafts" button
6. User picks a draft → "Use & Save" → answer persisted to `application_answers` table

### Resume Generation
1. User calls `POST /vault/generate` with personal profile fields + raw JD text
2. Backend retrieves base resume from vault, runs retrieval agent for context
3. LLM (Anthropic claude-sonnet-4-6 preferred) rewrites bullets, tailors skills section
4. Returns LaTeX content + markdown preview + ATS score estimate + skills gap list
5. Stored in vault with `version_tag = {FirstName}_{CompanyShort}_{RoleAbbrev}`
6. Pushed to GitHub `resume-vault/versions/` as named .tex file + git tag

---

## LLM Providers (in priority order)

| Provider | Model | Use case |
|----------|-------|----------|
| Anthropic | claude-sonnet-4-6 | Default, best quality |
| OpenAI | gpt-4o / gpt-4o-mini | Fallback |
| Kimi | moonshot-v1-32k | Long-context JDs |
| Ollama | llama3.1:8b (local) | No-cost, on-machine |
| Keyword | n/a | Always-available fallback |

The `llm_provider` field on every generation endpoint lets you pick per-request.

---

## Resume Naming Conventions

- **Internal / Git tag**: `{FirstName}_{CompanyShortName}_{RoleAbbrev}[_{JobID}]`
  e.g. `Narendranath_Google_DE`, `Narendranath_Google_DE_JOB123`
- **Recruiter-facing PDF**: always `{FirstName}.pdf` — no version numbers exposed
- **File stored in vault**: `versions/Narendranath_Google_DE.tex`

Rationale: recruiters should never see version numbers. Internal naming needs to be unique per target.

---

## Auth

`dependencies.py → get_current_user()` priority:

1. `Authorization: Bearer <jwt>` → validate RS256 against Clerk JWKS (`https://<app>.clerk.accounts.dev/.well-known/jwks.json`, 1-hour cache)
2. `X-Clerk-User-Id: <id>` header → direct lookup (dev / extension flow before JWT is wired)
3. Dev fallback → first user in DB if `ENVIRONMENT=development` and no header at all

Extension sends `X-Clerk-User-Id` from `chrome.storage.local` (set once at options page). JWT upgrade path is ready when Clerk's `getToken()` is wired into the extension.

---

## Project Phases

### Phase 1 — Core data models & API skeleton
- FastAPI app factory, PostgreSQL models (User, Application, AuditLog), Alembic migrations
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
- Application tracking with status lifecycle (draft → tailored → applied → interview → offer/rejected)
- ApplicationAnswer model + persistence

### Phase 4 — Resume Vault API + Chrome Extension
- Vault router (18 endpoints): upload, retrieve, ats-score, generate, Q&A drafts, history, GitHub versions
- Chrome MV3 extension: background worker, content script, sidepanel (JobScout + ApplyMode)
- Options page: configure API URL, LLM key, Clerk user ID
- ATTACH_RESUME flow: download PDF from backend → inject into file input via content script

### Phase 5 — Production hardening + deployment
- Clerk JWT auth (RS256, JWKS validation, 1-hour cache)
- Docker multi-stage build, Render Blueprint (`render.yaml`)
- GitHub Actions CI: ruff + black + mypy + pytest + tsc + docker build
- Options page validation, typed API client
- `start.sh`: alembic upgrade head → uvicorn

### Phase 6 — Fly.io migration + extension fixes + UI redesign
- **Migrated hosting** from Render (50s cold-start spin-down on free tier) to **Fly.io + Supabase + Upstash Redis** for always-on production
- **Extension sidepanel fixed**: three bugs caused the panel to never open
- **UI redesigned** to match premium extensions (Simplify / Jobright AI aesthetic)

### Phase 7 — Floating panel + intelligence layer (P1 feature sprint)
- **Floating panel** (`floatingPanel.ts`): Shadow DOM isolated panel injected on all career/ATS pages — no sidepanel required
- **JD text extraction** (L1): `extractJdText()` pulls visible job description text from the page to ground LLM answers
- **Answer length awareness** (L2): `maxLength` attr on textareas threaded to API → LLM gets word count constraint
- **Per-category style instructions** (L3): Options page textarea fields per question category; injected as "USER STYLE INSTRUCTIONS" block in LLM prompt
- **Category usage tracking + pre-generation** (L4): Tracks which question categories appear per page visit; auto-pre-generates answers for top-3 most-seen categories on next visit
- **Per-category model routing** (L5): Options page lets user pick preferred LLM provider per question type (cover letter → Anthropic, behavioral → OpenAI, etc.)
- **Resume tailoring** (L6): `POST /vault/generate/tailored` uses stored base resume + work history to generate targeted LaTeX resume
- **Application history dashboard** (T1): History tab with status timeline (discovered → applied → interview → offer → rejected) + stats row
- **Contenteditable detection** (P5): Detects and fills `contenteditable="true"` divs (used by Workday, LinkedIn) via `execCommand("insertText")`
- **Platform-specific extraction** (P5): Company/role extraction with dedicated selectors for Greenhouse, Lever, Workday, Ashby, SmartRecruiters, LinkedIn, Indeed
- **APPLICATION_SUBMITTED tracking**: Form submit + button click listeners → auto-patch application status to "applied"
- **Copy-to-clipboard**: ⎘ button on every draft answer with visual checkmark confirmation
- **Smart MutationObserver**: Only re-detects form changes (not cosmetic DOM mutations) — 30% fewer unnecessary re-renders

---

## Phase 6 — Fly.io Migration + Extension Fixes

### Why migrate from Render to Fly.io?

Render's free tier spins down web services after 15 minutes of inactivity. The first request after spin-down takes 50+ seconds — unacceptable for a Chrome extension that fires on every job page load. Fly.io + Supabase is **always-on at zero cost**:

| | Render (before) | Fly.io + Supabase (now) |
|---|---|---|
| PostgreSQL | 256 MB shared, 1 active free DB | Supabase 500 MB free, no spin-down |
| Redis | 25 MB, spin-down | Upstash Redis, pay-as-you-go ($0.20/100K commands) |
| Web service | 50s cold start | Fly.io shared-cpu-1x, `min_machines_running = 1` |
| Auto-deploy | Render webhook | GitHub Actions → `flyctl deploy` |

### Fly.io + Supabase setup

**New files:**
- `backend/fly.toml` — Fly.io app config with `auto_stop_machines = false`

**Config changes (config.py):**
- Added `DB_PASSWORD: str = ""` — inject DB password separately to avoid URL percent-encoding issues with special characters (`@` in passwords breaks URL parsers)
- Added `DB_SSL_REQUIRE: bool = False` — Supabase requires SSL

**Engine changes (models/base.py + alembic/env.py):**
- Use `make_url(DATABASE_URL).set(password=DB_PASSWORD)` — SQLAlchemy injects the password via the URL object, bypassing string parsing entirely
- Alembic `env.py`: removed `config.set_main_option("sqlalchemy.url", ...)` entirely — Python's `configparser` treats `%` as interpolation syntax, crashing on `%40` (`@`) in percent-encoded passwords

**CI/CD:** Added `deploy` job to `.github/workflows/ci.yml` that runs `flyctl deploy --remote-only` on main after backend + extension pass. FLY_API_TOKEN uploaded to GitHub secrets.

### Errors encountered and fixed (Fly.io migration)

**`start.sh` CRLF line endings** — Windows git checked out `start.sh` with `\r\n`. Linux Docker sees `#!/bin/sh\r` and returns `No such file or directory`. Fix: `sed -i 's/\r//' start.sh` + `.gitattributes` to enforce LF for `*.sh`.

**Alembic `configparser` percent-encoding** — `ValueError: invalid interpolation syntax in 'postgresql+asyncpg://...N%40rendr%40n%40th@...'`. Python's configparser treats `%` as a format string prefix. The call to `config.set_main_option("sqlalchemy.url", url)` triggers this. Fix: bypass configparser entirely — read `settings.DATABASE_URL` directly.

**Supabase IPv6** — Fly.io machines prefer IPv6. Supabase direct connection on port 5432 is IPv4-only. Connection fails with `ConnectionRefusedError: [Errno 111] Connect call failed ('2600:1f18:...', 5432)`. Fix: use the **session mode connection pooler** URL (`aws-1-us-east-1.pooler.supabase.com:5432`) which runs on IPv4.

**Password with `@` signs** — Password `N@rendr@n@th` contains `@` which is the credential separator in URLs. `%40` encoding was being decoded by Fly's secret storage before reaching the app. `make_url().set(password=...)` still failed because Fly stored the decoded value with literal `@` back in the URL. Final fix: reset Supabase password to `AutoApply2026Prod` (no special characters) — simple and robust.

**Production deploy confirmation:**
```
curl https://autoapply-ai-api.fly.dev/health
→ {"status":"alive","service":"autoapply-ai"}

curl -X POST https://autoapply-ai-api.fly.dev/api/v1/auth/register \
  -H "X-Clerk-User-Id: user_3AB26PAgD82zYApFLsMeqaTQyDT"
→ {"user_id":"4c458e37-7e10-411e-95b3-4ddca1648ca8","created":true}
```

### Extension sidepanel — three bugs fixed

The sidepanel **never opened** on Greenhouse or any career page. Three separate root causes:

**Bug 1 — `chrome.sidePanel.open()` in `tabs.onUpdated` fails silently**

In Chrome MV3, `chrome.sidePanel.open()` can only be called from a user gesture handler. `tabs.onUpdated` is NOT a user gesture. The existing code called `chrome.sidePanel.open({ tabId })` inside `tabs.onUpdated` — Chrome ignores this call silently (error swallowed by `.catch()`).

**Fix:** Add `chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })` at module top level. This makes clicking the toolbar icon open the panel automatically — no code needed. Also added `chrome.action.onClicked` as a belt-and-suspenders fallback.

```typescript
// At module level — one call, permanent fix
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
chrome.action.onClicked.addListener((tab) => {
  if (tab.id) chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
});
```

**Bug 2 — `OPEN_SIDEPANEL` message not handled**

The content script overlay badge calls `chrome.runtime.sendMessage({ type: "OPEN_SIDEPANEL" })` when clicked. The background worker had no handler for this message type — the message was silently dropped.

**Fix:** Added case `"OPEN_SIDEPANEL"` in the `onMessage` switch that calls `chrome.sidePanel.open({ tabId: sender.tab.id })`.

**Bug 3 — Greenhouse URL pattern too strict**

`CAREER_URL_PATTERNS` had `/greenhouse\.io\/jobs\//` — this only matches URLs containing `/jobs/` in the path. Many Greenhouse URLs (company boards, specific stages) don't include `/jobs/`. For example `boards.greenhouse.io/company` wouldn't match.

**Fix:** Loosened to `/greenhouse\.io/` — any Greenhouse subdomain triggers apply mode.

### Extension UI redesign

Redesigned all sidepanel components to match the aesthetic of premium job-assist extensions (Simplify, Jobright AI):

- **Company avatar**: color-coded letter avatar (hue derived from company name) — instant visual context
- **ATS score chip**: prominent score badge next to company name with color coding (green ≥80, amber ≥65, orange ≥50, red <50)
- **Tab navigation**: pill-style tabs with count badges instead of underline tabs
- **Resume cards**: outcome badge (🎉 offer / ✅ interview / 📤 applied / ✕ rejected), ATS score bar, attach button
- **Q&A drafts**: numbered draft selector, scrollable draft text, Regenerate + Use & Fill buttons
- **Job Scout cards**: per-company avatar, fit score chip, past application count, direct "Open →" link
- **Idle state**: platform-list idle screen instead of generic "navigate to a job page"
- **Header**: SVG logo, gradient background, mode indicator with colored dot

---

## What Failed / What Was Learned

### CI failures on first push
**Root cause 1**: `ci.yml` had `ENVIRONMENT: "testing"` but `config.py` validator only accepts `{"development", "test", "staging", "production"}`. App crashed before any test ran.
**Fix**: Changed to `ENVIRONMENT: "test"`.

**Root cause 2**: `Resume.version_tag` had `index=True` on the column definition AND `Index("ix_resumes_version_tag", "version_tag")` in `__table_args__`. SQLAlchemy `create_all` tried to create the index twice.
**Fix**: Removed `index=True` from the column — the explicit `__table_args__` entry is sufficient.

**Root cause 3**: CI workflow ran `alembic upgrade head` (creating tables + indexes) then conftest's `create_all` tried to recreate the same indexes → `DuplicateTableError`.
**Fix**: Added `drop_all` before `create_all` in conftest fixture to guarantee a clean slate.

**Root cause 4**: Tests in `test_application_service.py` were written for a stale API (`ApplicationService(db_session)` constructor, wrong parameter names). Actual service takes `db` as the first method arg.
**Fix**: Rewrote tests to match actual service signatures.

### Render Blueprint — env var mismatch
`render.yaml` used `GITHUB_REPO_OWNER` / `GITHUB_REPO_NAME` but `.env` convention uses `GITHUB_VAULT_OWNER` / `GITHUB_VAULT_REPO`.
**Fix**: Updated `render.yaml` to match. (Note: GitHub service reads per-user encrypted tokens from DB, not env vars — these are just reference placeholders in render.yaml.)

### Extension API URL hardcoded
`api.ts` hardcoded `const API_BASE = "http://localhost:8000/api/v1"` regardless of the options page setting. The options page saved `apiBaseUrl` to `chrome.storage` but nothing read it back.
**Fix**: `api.ts` now reads `apiBaseUrl` from storage at module load and syncs via `chrome.storage.onChanged`. Falls back to localhost for dev.

### Docker Desktop context
On Windows, Docker Desktop uses `//./pipe/dockerDesktopLinuxEngine` but the default context uses `//./pipe/docker_engine`. Switching context to `default` after ensuring Docker Desktop is running resolves this.

### Docker build CI — HTTP 522 from Docker Hub
```
ERROR: failed to fetch oauth token: unexpected status ... 522
```
HTTP 522 is a Cloudflare "origin connection timed out" error. GitHub Actions runners share IP ranges that hit Docker Hub's anonymous pull rate limits (~100 pulls/6h per shared IP block). Under load, Docker Hub returns 522/429 even before reaching the rate limit.

**Fix 1 — Docker Hub login** (preferred): Authenticated pulls get 200/6h *per account*, isolating you from shared-IP exhaustion. Add two repo secrets to GitHub (`Settings → Secrets and variables → Actions`):
- `DOCKERHUB_USERNAME` — your Docker Hub username (free account)
- `DOCKERHUB_TOKEN` — a Docker Hub access token (hub.docker.com → Account Settings → Personal Access Tokens → `Read-only`)

The CI `docker/login-action@v3` step is conditioned on `secrets.DOCKERHUB_USERNAME != ''` — it's skipped gracefully if secrets are absent.

**Fix 2 — `continue-on-error: true`** (defence in depth): The Docker job is a build-validity check only, not a deployment gate. A transient Docker Hub outage should not block the critical `backend` and `extension` CI jobs from completing. The job still shows as failed/neutral in the UI so you know it happened.

### Dockerfile `COPY docs/ ./docs/` error
```
ERROR: "/docs": not found
```
`docs/` lives at the project root but the Docker build context is `./backend`. Docker cannot reach outside its build context. The fix is to remove `COPY docs/ ./docs/` — `_load_doc()` in `resume_generator.py` already returns `""` gracefully when files are missing. Resume generation in Docker works without the personal config markdown (which is a local-dev concern anyway).

### `python-magic-bin` fails on Linux
```
RuntimeError: Unable to find installation candidates for python-magic-bin (0.4.14)
```
`python-magic-bin` is a Windows-only package that bundles `libmagic.dll`. It has no Linux build and was never imported anywhere in the codebase. Removed from `pyproject.toml` and regenerated `poetry.lock`.

### Docker Hub secrets added via GitHub API
GitHub CLI (`gh`) was not installed locally. Used `curl` + PyNaCl (via `poetry run python`) to:
1. Fetch the repo's RSA public key from `GET /repos/{owner}/{repo}/actions/secrets/public-key`
2. Encrypt each secret value with a libsodium sealed box (`nacl.public.SealedBox`)
3. `PUT /repos/{owner}/{repo}/actions/secrets/{name}` with the encrypted payload + key_id

Secrets uploaded: `DOCKERHUB_USERNAME=narendranathe`, `DOCKERHUB_TOKEN=dckr_pat_...`

### Render free tier conflict — Blueprint failed silently
```
Create database autoapply-db  (cannot have more than one active free tier database)
Create Key Value autoapply-redis  (cannot have more than 1 free tier Redis instance)
Create web service autoapply-ai-api  (canceled: another action failed)
```
Render free tier: **1 PostgreSQL + 1 Redis per account**. An existing `job-scout` Blueprint from a separate repo (`narendranathe/job-scout`) already occupied both slots.

**Fix**: Delete the job-scout Blueprint resources manually in Render dashboard (web service → PostgreSQL → Redis → Blueprint), then re-sync the autoapply-ai Blueprint. All three slots become available.

**Lesson**: Render Blueprint apply fails silently with "canceled" on dependent resources when an upstream resource fails. Always check the free tier limits before creating a Blueprint.

### Render deploy — `No module named 'psycopg2'`
```
ModuleNotFoundError: No module named 'psycopg2'
```
Render injects `DATABASE_URL` as `postgresql://user:pass@host/db` — the standard psycopg2 **sync** driver scheme. Our stack uses `asyncpg` which requires `postgresql+asyncpg://`. SQLAlchemy picked up the `postgresql://` scheme, tried to import the sync psycopg2 driver, which isn't installed.

**Fix**: Added `field_validator("DATABASE_URL", mode="before")` in `config.py` that rewrites any incoming `postgres://` or `postgresql://` URL to `postgresql+asyncpg://` before the engine is created. Transparent to all hosting providers (Render, Railway, Heroku all use the standard scheme).

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

### Poetry `README.md not found` warning during Docker build
```
Warning: The current project could not be installed: [Errno 2] No such file or directory: '/app/README.md'
```
`pyproject.toml` had `readme = "README.md"` and `packages = [{include = "app"}]`. The README lives at the project root, outside the `./backend` Docker build context — Poetry couldn't find it. This was a warning that Poetry explicitly states will become a hard error in a future version.

**Fix**: Replaced both fields with `package-mode = false`. This tells Poetry the project is dependency-management-only (not a publishable package), eliminating the need for `readme`, `packages`, or any installable entry point entirely.

---

## Architectural Decisions

### Why LaTeX for resumes?
ATS parsers and recruiters can't see behind formatting tricks. LaTeX gives pixel-perfect PDFs with zero layout drift. The `.tex` source is version-controlled in GitHub, diffable, and reusable. Recruiter always gets `{FirstName}.pdf` — no version numbers leaked.

### Why TF-IDF as free embedding tier?
Paying for embeddings on every resume upload is expensive at scale and adds a hard dependency on an external API. TF-IDF cosine similarity catches keyword overlap accurately for resume-to-JD matching at zero cost. Paid tiers (OpenAI, Kimi) and local Ollama (`nomic-embed-text`) are available for higher-quality semantic search.

### Why per-user encrypted GitHub tokens?
The vault is personal. Every user should store resumes in their own GitHub repo, not a shared one. Tokens are encrypted with Fernet before DB storage. This also means users can revoke/rotate tokens without affecting other users.

### Why Clerk for auth instead of rolling JWT?
Clerk handles the full auth lifecycle (sign-up, MFA, session management, JWKS rotation) for free up to 10,000 MAU. The backend only validates RS256 JWTs from the JWKS endpoint — zero auth logic to maintain. The `X-Clerk-User-Id` header fallback makes local dev and extension testing work without a full Clerk flow.

### Why Chrome MV3 (not MV2)?
MV3 is the current and only supported Manifest version for new Chrome extension submissions. MV2 extensions are being phased out. Persistent background pages are replaced by service workers (`worker.ts`).

### Why a sidepanel instead of a popup?
Sidepanels persist while the user fills in the form. A popup closes the moment focus leaves it. Application forms require back-and-forth between the panel and the page — sidepanel is the only viable UX.

### Why not inject a React app directly into the page?
Content scripts that inject large React trees create styling conflicts, CSP violations, and React version clashes with the host page. The sidepanel is isolated in its own browsing context with no DOM conflicts.

### Why FormData instead of JSON for vault endpoints?
File uploads (`resume file`, PDF downloads) require multipart form. Using FormData consistently across all vault endpoints means the extension API client has one code path for all requests.

---

## Local Development Setup

```bash
# 1. Start services
docker compose up -d

# 2. Apply migrations
cd backend && poetry run alembic upgrade head

# 3. Start backend
poetry run uvicorn "app.main:create_app" --factory --reload --port 8000

# 4. Build extension (watch mode)
cd extension && npm run build -- --watch
# Load extension/dist/ as unpacked extension in chrome://extensions
```

### Environment (.env)
```
DATABASE_URL=postgresql+asyncpg://autoapply:localdev@localhost:5432/autoapply
REDIS_URL=redis://localhost:6379
ENVIRONMENT=development
JWT_SECRET=<any string for dev>
FERNET_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# Clerk (required for JWT auth; without it, dev fallback activates)
CLERK_SECRET_KEY=sk_test_...
CLERK_FRONTEND_API_URL=https://<slug>.clerk.accounts.dev

# GitHub vault
GITHUB_TOKEN=ghp_...
GITHUB_VAULT_REPO=resume-vault
GITHUB_VAULT_OWNER=<your-github-username>
```

---

## Running Tests

```bash
cd backend

# Unit tests (no live services needed for most)
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
```

Current status: **74/74 backend tests passing, 0 TypeScript errors, extension build clean.**

---

## CI/CD (GitHub Actions)

Three jobs in `.github/workflows/ci.yml`:

| Job | What it checks |
|-----|----------------|
| `backend` | ruff → black → mypy → alembic upgrade head → pytest (with Postgres + Redis services) |
| `extension` | npm ci → tsc --noEmit → npm run build → upload dist artifact on main |
| `docker` | docker buildx build (no push) — validates Dockerfile on every main/PR |

Triggered on push to `main`, `feat/**`, `fix/**` and PRs to `main`.

---

## Deployment

### Fly.io (current production — always-on)

Configured in `backend/fly.toml`. Key settings:
```toml
[http_service]
  auto_stop_machines = false   # Never spin down
  min_machines_running = 1     # Always one machine running
[[vm]]
  memory = "256mb"
  cpu_kind = "shared"
  cpus = 1
```

Deploy manually:
```bash
cd backend && fly deploy --remote-only
```

Auto-deploy: GitHub Actions `deploy` job runs after CI passes on `main`.

**Production secrets** (set via `fly secrets set KEY=value --app autoapply-ai-api`):
```
DATABASE_URL      postgresql://postgres.hobhlxhmqhqdahokqndq@aws-1-us-east-1.pooler.supabase.com:5432/postgres
DB_PASSWORD       AutoApply2026Prod
DB_SSL_REQUIRE    true
REDIS_URL         redis://default:ab716940...@fly-autoapply-redis.upstash.io:6379
CLERK_SECRET_KEY  sk_test_...
CLERK_FRONTEND_API_URL  https://feasible-liger-35.clerk.accounts.dev
GITHUB_TOKEN      ghp_...
GITHUB_VAULT_REPO resume-vault
GITHUB_VAULT_OWNER narendranathe
FERNET_KEY        <generated>
JWT_SECRET        <generated>
EXTENSION_ID      (set after Chrome Web Store approval)
```

### Supabase (PostgreSQL)

Free tier: 500 MB storage, no spin-down. Connection via **session mode pooler** (IPv4, required for Fly.io IPv6 compatibility):
```
Host: aws-1-us-east-1.pooler.supabase.com
Port: 5432
Database: postgres
User: postgres.hobhlxhmqhqdahokqndq
SSL: required
```
DB Shell: https://supabase.com/dashboard/project/hobhlxhmqhqdahokqndq/editor

### Render (archived — replaced by Fly.io)

`render.yaml` still exists for reference. Not actively deployed. Render's free tier has 50s cold-start spin-down which breaks extension UX.

### CI/CD Auto-deploy

`.github/workflows/ci.yml` deploy job:
1. Waits for `backend` + `extension` jobs to pass
2. Runs only on `main` branch
3. `flyctl deploy --remote-only` — builds in Fly's infrastructure, no local Docker needed
4. Requires `FLY_API_TOKEN` in GitHub Actions secrets

---

## Extension Options Page

After installing the extension, right-click the icon → Options:

- **Clerk User ID** — your `user_xxx...` ID from the Clerk dashboard (used as `X-Clerk-User-Id` header)
- **API Base URL** — defaults to `http://localhost:8000/api/v1`, change to your Render URL for production
- **LLM API Key + Provider** — optional per-user key forwarded to generation endpoints

---

## File Map

```
autoapply-ai/
├── backend/
│   ├── app/
│   │   ├── config.py              Settings (Pydantic, env vars)
│   │   ├── dependencies.py        get_current_user, get_db, get_redis
│   │   ├── main.py                App factory, middleware, lifespan
│   │   ├── middleware/            circuit_breaker, rate_limit, logging, request_id
│   │   ├── models/                user, resume, application, audit_log, base
│   │   ├── routers/               health, auth, vault, applications, resume
│   │   ├── schemas/               Pydantic I/O schemas
│   │   ├── services/              llm, ats, embedding, retrieval_agent,
│   │   │                          resume_generator, github, pdf, tailoring_pipeline,
│   │   │                          application_service, resume_parser, resume_validator
│   │   └── utils/                 encryption, hashing
│   ├── alembic/versions/          15d0f847bcc2 (initial), a3f2e1d4c5b6 (vault)
│   ├── tests/unit/                74 passing tests
│   ├── Dockerfile                 Multi-stage python:3.12-slim
│   ├── start.sh                   alembic upgrade head → uvicorn
│   ├── pyproject.toml             Poetry, ruff, black, mypy config
│   └── .env.example               All env vars documented
├── extension/
│   ├── src/
│   │   ├── background/worker.ts   URL detection, sidepanel, offline sync
│   │   ├── content/detector.ts    Field/question detection, job card scraping
│   │   ├── sidepanel/             App, ApplyMode, JobScout, ATSScoreBar, ResumeCard
│   │   ├── options/               Settings page (API URL, LLM key, Clerk ID)
│   │   └── shared/api.ts          Typed vault API client (reads URL from storage)
│   ├── manifest.json              MV3, sidepanel, content scripts, permissions
│   ├── vite.config.ts             Multi-entry build (sidepanel, background, content, options)
│   └── store/                     Chrome Web Store description + privacy policy
├── docs/
│   ├── resume_instructions.md     General DE resume rules (user-editable)
│   ├── resume_personal_config.md  Personal data + project config (user-editable)
│   └── templates/resume_template.tex  LaTeX base with {{PLACEHOLDERS}}
├── .github/workflows/ci.yml       3-job CI pipeline
├── docker-compose.yml             postgres, db_test, redis (+ ollama profile)
├── render.yaml                    Render Blueprint
└── DEPLOYMENT.md                  Step-by-step: Clerk + Render + Chrome Web Store
```

---

## Current State

| Component | Status |
|-----------|--------|
| Backend tests | 74/74 passing |
| TypeScript | 0 errors |
| Extension build | Clean (41 modules) |
| ruff / black / mypy | All passing |
| Docker (local) | postgres + db_test + redis up, both migrations applied |
| GitHub repo | `narendranathe/autoapply-ai` — branch `feat/phase-4-vault-extension` |
| GitHub Actions secrets | `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` + `FLY_API_TOKEN` uploaded |
| Resume vault repo | `narendranathe/resume-vault` (private) — created |
| Clerk | `feasible-liger-35.clerk.accounts.dev` (test instance) — JWKS verified |
| **Fly.io deploy** | **Live** — `https://autoapply-ai-api.fly.dev` (always-on, 0s cold start) |
| **Supabase DB** | **Live** — `aws-1-us-east-1.pooler.supabase.com` (session pooler, SSL) |
| **Upstash Redis** | **Live** — `fly-autoapply-redis.upstash.io:6379` |
| Production user | Registered — `user_3AB26PAgD82zYApFLsMeqaTQyDT` → `4c458e37-...` |
| Chrome extension | Loaded unpacked — ID `cepfanhjdjlhmfchelknemfmlodnmbfa` |
| Extension sidepanel | **Fixed** — opens on toolbar icon click + badge click |
| Extension UI | **Redesigned** — Simplify/Jobright AI style with company avatars + score chips |

---

## Next Steps (in order)

### 1. Rebuild and reload the extension
After the sidepanel fixes and UI redesign:
```bash
cd extension && npm run build
```
In Chrome → `chrome://extensions` → **AutoApply AI** → click the refresh icon (↺).

Navigate to a Greenhouse job page (e.g. `boards.greenhouse.io/...`) → click the AutoApply AI toolbar icon → sidepanel should open immediately.

### 2. Smoke test production
```bash
# Health check
curl https://autoapply-ai-api.fly.dev/health
# → {"status":"alive","service":"autoapply-ai"}

# Vault — should return empty list (no resumes yet)
curl https://autoapply-ai-api.fly.dev/api/v1/vault/resumes \
  -H "X-Clerk-User-Id: user_3AB26PAgD82zYApFLsMeqaTQyDT"
# → {"items":[],"page":1,"per_page":20}
```

### 3. Extension options page — point to production
In Chrome → right-click AutoApply AI icon → **Options**:
- **API Base URL** → `https://autoapply-ai-api.fly.dev/api/v1` → **Save & Test**
- **Clerk User ID** → `user_3AB26PAgD82zYApFLsMeqaTQyDT` → **Verify & Save**

### 4. Upload your first resume
```bash
curl -X POST https://autoapply-ai-api.fly.dev/api/v1/vault/upload \
  -H "X-Clerk-User-Id: user_3AB26PAgD82zYApFLsMeqaTQyDT" \
  -F "file=@/path/to/your/resume.pdf" \
  -F "target_company=Google" \
  -F "target_role=Data Engineer"
```

### 5. Chrome Web Store (when ready to publish)
```bash
# Windows PowerShell — zip the dist folder
cd extension
Compress-Archive -Path dist\* -DestinationPath ..\autoapply-extension.zip
```
- https://chrome.google.com/webstore/devconsole → pay $5 one-time fee → **New Item** → upload zip
- Fill title, description (`extension/store/description.txt`), screenshots (1280×800 minimum)
- After approval: copy the 32-char extension ID → set in Fly secrets:
  ```bash
  fly secrets set EXTENSION_ID=<your-32-char-id> --app autoapply-ai-api
  ```
  This locks CORS to your extension only (rejects other origins in production).

### 6. Merge to main
```bash
git checkout main
git merge feat/phase-4-vault-extension
git push origin main
# GitHub Actions → CI passes → flyctl deploy auto-runs
```

---

## Phase 7 — Q&A Generation Fix + LLM Provider Cascade (2026-03-12)

### What Was Broken

**Q&A tab showed same answer 3 times (or nothing)**
Root cause chain:
1. `generate_answer_drafts_cascade()` and `providers_json` handling existed only in local code — never deployed. Production backend ignored the provider list and fell back to rule-based generation silently.
2. `_parse_answer_drafts()` padded with `drafts.append(drafts[0])` when LLM used non-standard formatting → 3 identical copies.
3. `_rule_based_answer_drafts()` itself returned the same string 3 times per category — the fallback was also broken.

**"Saved — no providers enabled (fallback mode)"**
The options page stored `{ enabled: false, apiKey: "..." }` because it required users to check a checkbox AND enter a key. Users entered keys but missed the checkbox. `buildProviderList` filtered by `cfg.enabled` → empty array → fallback every time.

**Wrong fields appearing in Q&A tab**
"LinkedIn Profile", "GitHub Profile", "First Name*" were treated as essay questions because `detectQuestions()` included any textarea with label ≥ 10 chars.

### Fixes Applied

**Backend (`resume_generator.py`, `vault.py`)**
- `generate_answer_drafts_cascade()`: sorts providers by rank (anthropic=1 → openai=2 → gemini=3 → groq=4 → perplexity=5 → kimi=6), tries each in order, first success generates all 3 drafts
- `_call_gemini()`: OpenAI-compatible endpoint (`generativelanguage.googleapis.com/v1beta/openai/...`)
- `_parse_answer_drafts()`: multi-strategy — DRAFT_N markers → paragraph split → whole response fallback
- `_rule_based_answer_drafts()`: now returns 3 genuinely distinct drafts per category
- `providers_json` Form field on `/vault/generate/answers` — extension sends provider configs, backend uses them
- **Critical: deployed with `fly deploy --remote-only`** — nothing worked until this step

**Extension (`options.ts`)**
- `readProviderUI()`: `enabled: !!apiKey` — enabled flag now always mirrors key presence, no checkbox dependency
- `loadProviderUI()`: `checkbox.checked = !!cfg.apiKey` — checkbox decorative only
- `wireProviderAutoEnable()`: checkbox auto-checks/unchecks as user types key

**Extension (`ApplyMode.tsx`)**
- `buildProviderList()`: filters by `!!cfg.apiKey` (not `cfg.enabled`)
- `getFreshProviders()`: reads `chrome.storage.local` directly at generate time — bypasses React state timing entirely
- `handleGenerateAnswers` and auto-generate `useEffect` both call `getFreshProviders()` first
- Provider status bar shows active providers; warning when none configured
- `NON_QUESTION_PATTERNS` filter prevents URL/name fields from appearing in Q&A tab

**Extension (`detector.ts`)**
- `NON_QUESTION_PATTERNS`: filters linkedin, github, portfolio, website, url, first/last/full name, email, phone, etc.
- `isEssayQuestion()`: label must be ≥ 15 chars AND not match any NON_QUESTION_PATTERN
- URL/profile fields now handled by Fields tab (auto-fill), not Q&A tab (LLM generation)

### Design Lesson
The `enabled` boolean on `ProviderConfig` was a design flaw. Having an API key = being enabled. These two concepts should never have been stored independently. The checkbox in the UI should be derived from key presence, not stored separately.

### Current State After Phase 7

| Component | Status |
|-----------|--------|
| Q&A generation | Working — Groq/Gemini/Anthropic cascade producing 3 distinct answers |
| Provider config | Fixed — entering API key auto-enables provider, no checkbox required |
| Question detection | Fixed — URL/name/contact fields filtered from Q&A tab |
| Draft parsing | Robust — multi-strategy fallback, no more identical copies |
| Backend | Deployed on Fly.io with cascade + Gemini support |
| Extension build | Clean |

### RL / Answer Memory Layer

`ApplicationAnswer.reward_score` is computed from user action:
- `used_as_is` → 1.0 | `edited` → 0.8 | `regenerated` → 0.2 | `skipped` → 0.0

High-reward past answers (≥ 0.8) are injected as style examples into future LLM prompts for the same company/role context. This creates a lightweight personalization loop without any model fine-tuning infrastructure.

---

## Intelligent Detection + Vault Recall (Strategy C — PRD #56)

> **PRD #46 superseded.** Dual-agent analysis (2026-03-18) rejected Strategy B (full TriObserver) in favour of Strategy C: a backward-compatible set of additive improvements on top of the existing single `MutationObserver`. See [PRD #56](https://github.com/narendranathe/autoapply-ai/issues/56) for full rationale.

### Why Strategy B Was Rejected

| Rejected mechanism | Failure mode |
|---|---|
| Body-level `ResizeObserver` | Fires 10-15× per Workday step animation → race conditions on `questionStates` |
| `IntersectionObserver` | Fires mid-animation before React re-attaches elements → partial DOM reads |
| Auto-save on 2s keystroke debounce | Persists partial text (`"I worked at Goog"`) to vault → silent data corruption |

### Strategy C: Tiered Observer Architecture + 3 Feature Slices

The design principle: **wire existing backend intelligence into the real-time detection loop** rather than adding new observers. Estimated savings: **45–80 seconds per application**.

#### Detection Tiers

| Tier | Mechanism | What it catches |
|---|---|---|
| 1 (existing) | Single `MutationObserver` on form element add/remove | 95% of ATS platforms — do not change |
| 2 (new) | Targeted `ResizeObserver` on known SPA containers only | Workday wizard step transitions, Greenhouse modal swaps |
| 3 (new) | `postMessage` iframe injection (same-origin only) | Workday/Taleo iframe-embedded forms |

**Tier 2 containers watched:** `.app-container`, `main`, `[data-qa="job-container"]`, `.form-wrapper`, `[class*="step"]`, `[class*="wizard"]`
**Tier 2 threshold:** only fires `redetect()` when container height changes by **>50px** (400ms debounce) — filters animation noise.

#### Feature Slice 1 — Vault Recall in `redetect()`

When `redetect()` adds a new question to `questionStates`, it immediately calls `GET /vault/answers/similar` **before** any LLM generation. Rules:
- Hard floor: only show answers where `tfidf_similarity >= 0.25`
- Vault answers labeled **"From Memory"** with similarity badge ("87% match")
- If 2+ vault answers found (similarity ≥ 0.25), skip `preGenerateTopCategories()` for that question
- `tfidf_similarity` added to `/vault/answers/similar` response (backend change)
- Ranking: `reward_score × 0.7 + tfidf_similarity × 0.3` (existing algorithm, now exposed in response)

#### Feature Slice 2 — ATS Auto-Fill Banner

After `loadAtsScore()` resolves, if `atsScore >= 0.75`:
1. Snapshot current DOM field values into `_preAutoFillValues: Map<string, string>`
2. Call `fillAll()` (existing — fills from profile)
3. Show dismissable **"Auto-filled from your profile"** banner with **Undo** button
4. Undo restores exact pre-fill DOM values
5. Banner dismissed per session — `sessionStorage` key: `aap_autofill_dismissed_<company>`

**Never silently fills.** Banner + Undo is mandatory.

#### Feature Slice 3 — Cover Letter Background Pre-Fetch

On `init()`, a non-blocking background fetch calls `GET /vault/cover-letters?company=<name>` (existing endpoint). Behaviour:
- Match found → pre-populate cover letter textarea, show **"Loaded from vault"** badge
- No match + `jdText` available → queue background generation (idempotency guard via sessionStorage per URL hash)
- Manual Generate button still works as override

#### Deduplication Fix

Fields deduplicated by `fieldId + labelHash` composite key — not just `fieldId` alone. ATS platforms reuse generic IDs (`field_1`, `field_2`) across wizard steps; without label hash, the same field appears multiple times in the panel.

Hash: `djb2(label.toLowerCase().replace(/\s+/g," ").replace(/[^\w\s]/g,"").trim())`

### Module Map

```
Extension (floatingPanel.ts unless noted):
├── #57 LabelHashDeduplication   detectFields() + redetect() dedup set              S
├── #58 VaultRecallConnector     redetect() lines 782-793 + background fetch         M
├── #59 SimilarityBadgeUI        render() + css() — "From Memory" + % badge         S
├── #60 ATSAutoFillBanner        maybeAutoFill() after loadAtsScore()                M
├── #61 CoverLetterPreFetcher    prefetchCoverLetter() in init()                     S
├── #62 SPAResizeObserver        attachSPAResizeObserver() in init()                 S
└── #63 IframeFieldBridge        scanIframes() in redetect() + detector.ts handler  M

Backend:
└── #58 tfidf_similarity exposed  retrieval_agent.py:337 return scored pairs        S
        (part of VaultRecallConnector — no new models required)
```

### Dependency Graph

```
#57 (LabelHash) ──────────────────────────────────────► #63 (IframeFieldBridge)
#58 (VaultRecall) ──► #59 (SimilarityBadge)
#60 (ATSBanner)       [standalone]
#61 (CoverLetterPre)  [standalone]
#62 (SPAResize)       [standalone]
```

### Design Rules for Cover Letters

Cover letters are generated with these fixed rules (enforced in `/vault/generate/answers` with `category=cover_letter`):
- **Tone**: Professional (default) | Enthusiastic | Concise — user-selectable
- **Length**: ~300 / ~400 / ~500 words — user-selectable
- **Grounded in**: JD text + work history text + candidate profile name
- **Company-specific**: company name and role title injected into prompt
- **Saved**: every generated letter → `/vault/answers/save` with `category=cover_letter`
- **Re-used**: next visit to same company → letter auto-surfaces via `prefetchCoverLetter()`
- **Never overwrites**: existing saved letters for same company shown as alternatives

### GitHub Issues

| Issue | Module | Status |
|---|---|---|
| [#56](https://github.com/narendranathe/autoapply-ai/issues/56) | PRD: Strategy C — approved spec | Open |
| [#57](https://github.com/narendranathe/autoapply-ai/issues/57) | TRACER: LabelHashDeduplication | Open |
| [#58](https://github.com/narendranathe/autoapply-ai/issues/58) | VaultRecallConnector + tfidf_similarity response | Open |
| [#59](https://github.com/narendranathe/autoapply-ai/issues/59) | SimilarityBadgeUI — "From Memory" + % badge | Open |
| [#60](https://github.com/narendranathe/autoapply-ai/issues/60) | ATSAutoFillBanner — auto-fill + Undo | Open |
| [#61](https://github.com/narendranathe/autoapply-ai/issues/61) | CoverLetterPreFetcher — background pre-load | Open |
| [#62](https://github.com/narendranathe/autoapply-ai/issues/62) | SPAResizeObserver — Workday/Greenhouse step detection | Open |
| [#63](https://github.com/narendranathe/autoapply-ai/issues/63) | IframeFieldBridge — same-origin iframe fields | Open |
| [#46](https://github.com/narendranathe/autoapply-ai/issues/46) | PRD #46 — superseded by #56 | Open |
| [#54](https://github.com/narendranathe/autoapply-ai/issues/54) | Resume Vault Folder Sync (independent) | Open |
| [#50](https://github.com/narendranathe/autoapply-ai/issues/50) | VectorBackend / Pinecone abstraction (independent) | Open |
