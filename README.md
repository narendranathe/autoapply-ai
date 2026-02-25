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

## Deployment (Render)

Defined in `render.yaml` — Render Blueprint provisions:
- Web service (Docker, `backend/Dockerfile`, free tier)
- PostgreSQL (free tier, `autoapply_prod`)
- Redis (free tier)

`start.sh` runs `alembic upgrade head` then `uvicorn` on startup — zero manual DB setup.

**Required env vars to set manually in Render dashboard:**

```
CLERK_SECRET_KEY
CLERK_FRONTEND_API_URL
GITHUB_TOKEN
GITHUB_VAULT_OWNER
GITHUB_VAULT_REPO
EXTENSION_ID          (set after Chrome Web Store approval)
```

`FERNET_KEY` and `JWT_SECRET` are auto-generated by Render (`generateValue: true`).

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
| Extension build | Clean (503ms, 41 modules) |
| ruff / black / mypy | All passing |
| Docker (local) | postgres + db_test + redis up, both migrations applied |
| GitHub repo | `narendranathe/autoapply-ai` — main branch current |
| Resume vault repo | `narendranathe/resume-vault` (private) — created |
| Clerk | `feasible-liger-35` (test instance) — JWKS verified |
| Render deploy | Pending — CI was fixed, retry after CI goes green |
| Chrome extension | `extension/dist/` built, ready for Web Store submission |
