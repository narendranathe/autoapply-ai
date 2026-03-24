# AutoApply AI

**Apply smarter, not harder.** AutoApply AI watches you browse job boards, scores every role against your Resume Vault, auto-fills application forms, and generates tailored resumes and Q&A answers — all without leaving the page.

---

## What It Does

Three surfaces that work together:

### Extension — Floating Panel + Sidepanel
A Chrome MV3 extension that activates on job boards and career pages. The **Floating Panel** is a Shadow DOM overlay injected directly onto application pages — it shows your ATS Score against the live JD, your Resume Vault, and an LLM-powered Q&A generator without opening a side pane. The **Sidepanel** provides two modes:

- **Job Scout** — Browse LinkedIn, Indeed, or Glassdoor and see ATS Score chips on every job card, color-coded by fit. Past Application history surfaces inline.
- **Apply Mode** — Four tabs: Resumes (past Vault entries for this company), Fields (auto-fill DetectedFields), Q&A (generate 3 drafts per DetectedQuestion), Answers (search your Answer Vault).

### Dashboard
A React + Vite web app (Vercel) with Clerk authentication. Seven pages covering the full Application lifecycle — kanban board, Resume Vault editor, Answer Vault, Cover Letter library, Job Scout, and profile management.

### Backend
A FastAPI service (Fly.io, always-on) with 40+ endpoints covering the full lifecycle: Resume upload and parsing, ATS scoring, LLM-powered tailoring, Q&A draft generation, Application tracking, GitHub Vault commits, and profile sync.

---

## Architecture

```
Chrome Extension (MV3)
├── Background worker        URL detection, Sidepanel trigger, Offline Queue drain
├── Content script           DetectedField / DetectedQuestion detection, job card scraping
├── Floating Panel           Shadow DOM overlay — ATS bar, Resume Vault, LLM picker
└── Sidepanel (React + TS)
    ├── App.tsx              Mode dispatcher (idle / scout / apply)
    ├── JobScout.tsx         Job list with ATS Score per card
    └── ApplyMode.tsx        4-tab: Resumes, Fields, Q&A, Answer Vault

Dashboard (React + Vite — Vercel)
├── /                        Home — stats, mini-kanban, watchlist, activity feed
├── /applications            Kanban + detail drawer + Application status timeline
├── /resumes                 Resume Vault — Monaco LaTeX editor + PDF.js split-pane
├── /cover-letters           Cover letter library + SSE streaming generator
├── /job-scout               Job discovery with fit score cards
├── /vault                   Answer Vault — category tabs, search, reward score badges
└── /settings                Profile, UserProviderConfig, work history, extension status

FastAPI Backend (Fly.io — always-on)
├── /api/v1/vault/           Upload, retrieve, ATS score, generate, Q&A drafts,
│                            Answer Vault CRUD, cover letters, GitHub push
├── /api/v1/applications/    Application CRUD + stats + funnel metrics
├── /api/v1/auth/            Clerk webhook, User profile GET/PATCH
├── /api/v1/users/           UserProviderConfig, GitHub token, WorkHistoryEntry
└── /health                  Liveness probe

PostgreSQL (Supabase)
├── users                    Clerk ID + 14 profile fields + encrypted GitHub PAT
├── resumes                  Parsed Resume + TF-IDF/embedding vectors + ATS metadata
├── resume_usages            Every submission — company, role, outcome, ATS Score
├── application_answers      ApplicationAnswer + RL reward signal
├── applications             Application lifecycle + notes
├── work_history_entries     WorkHistoryEntry — structured employment/education
├── user_provider_configs    UserProviderConfig — Fernet-encrypted API keys
├── document_chunks          DocumentChunk with embedding_vector for RAG retrieval
└── audit_logs               Immutable event log

Redis (Upstash)
└── Rate limiting counters, JD embedding cache, circuit breaker state

GitHub (private repo: resume-vault)
├── versions/                Current best Resume per company/role (.tex files)
├── applications/            Dated submission history
├── private/                 Personal data (never public)
└── template/                Base LaTeX structural template
```

---

## Domain Language

All terms used in code, conversations, and documentation are defined in [`UBIQUITOUS_LANGUAGE.md`](./UBIQUITOUS_LANGUAGE.md). That file is the authority — when a term is ambiguous, check there first.

**Key terms at a glance:**

| Term | Meaning |
|---|---|
| **Application** | One job application attempt — created automatically when the extension detects a job page |
| **Vault** | All stored Resumes and ApplicationAnswers for a User |
| **Base Template** | User-uploaded master Resume used as foundation for all generation |
| **Generated Resume** | A Resume produced by the LLM tailoring pipeline for a specific JD |
| **ATS Score** | Float 0.0–1.0 estimating Resume fit against a specific JD. ≥ 0.95 = Best Match |
| **Floating Panel** | Shadow DOM overlay injected on career pages — no Sidepanel required |
| **Provider** | An LLM service: `anthropic`, `openai`, `kimi`, `groq`, `gemini`, `ollama`, or `fallback` |
| **Platform** | The job board or ATS hosting the application (`linkedin`, `greenhouse`, `lever`, `workday`, `indeed`) |
| **Category** | Question type for routing and prompt selection (`why_company`, `challenge`, `leadership`, etc.) |
| **Feedback** | User's explicit signal on an ApplicationAnswer: `used_as_is` / `edited` / `regenerated` / `skipped` |
| **RAG** | Injecting retrieved DocumentChunks into LLM prompts to ground answers in real work history |
| **DetectedField** | A form input identified on the page with its type, current value, and suggested fill value |
| **DetectedQuestion** | An open-ended text question on the page, with Category and character limit |
| **PageContext** | Metadata extracted from the current job page: company, role, Platform, JD text, detected fields and questions |

---

## Key Flows

### Job Scout
1. User navigates to LinkedIn, Indeed, or Glassdoor job listings.
2. Background worker matches the URL and opens the Sidepanel in scout mode.
3. Content script scrapes job cards from the page.
4. Each card is scored against the Resume Vault — ATS Score and past Application count returned.
5. Sidepanel renders cards with color-coded ATS Score chips: green ≥ 0.80, amber ≥ 0.65, red < 0.50.

### Apply Mode
1. User lands on a company career application page.
2. Content script detects DetectedFields (name, email, phone, file uploads) and DetectedQuestions (cover letter, open-ended essays).
3. Floating Panel appears with the current ATS Score, Resume Vault entries for this company, and a per-question LLM picker.
4. Sidepanel Apply Mode shows four tabs — Resumes, Fields, Q&A, Answer Vault.
5. User picks a Q&A draft → "Use & Save" → persisted as an ApplicationAnswer with a reward signal.
6. When the form is submitted, the Application status automatically advances to `applied`.

### Resume Generation
1. User requests a tailored Resume for a specific JD.
2. Backend retrieves the Base Template from the Vault and runs the RAG retrieval agent to pull relevant WorkHistoryEntry bullets.
3. LLM rewrites bullet points and the skills section against the JD.
4. Returns LaTeX source, markdown preview, ATS Score estimate, and a skills_gap list.
5. Stored in the Vault with `version_tag = {FirstName}_{CompanyShort}_{RoleAbbrev}` and pushed to the GitHub Vault Repo.

---

## Application Status Lifecycle

Every Application moves through a forward-only status chain:

```
discovered → draft → tailored → applied → phone_screen → interview → offer
                                        ↘ rejected (from any stage)
```

| Status | When it's set |
|---|---|
| `discovered` | User visits a job page; no Resume selected yet |
| `draft` | A Resume has been selected but not yet tailored |
| `tailored` | The LLM tailoring pipeline has run for this JD |
| `applied` | The `APPLICATION_SUBMITTED` signal fires from the content script |
| `phone_screen` | Recruiter screening call scheduled or completed |
| `interview` | Candidate is in the interview loop |
| `offer` | Offer received |
| `rejected` | Rejected at any stage |

---

## LLM Providers

Providers are tried in priority order per-request. The first to succeed generates all three drafts.

| Priority | Provider | Model | Best for |
|---|---|---|---|
| 1 | Anthropic | claude-sonnet-4-6 | Default — highest quality |
| 2 | OpenAI | gpt-4o / gpt-4o-mini | Strong fallback |
| 3 | Gemini | gemini-1.5-flash | OpenAI-compatible endpoint |
| 4 | Groq | llama3-70b | Fast, free tier |
| 5 | Kimi | moonshot-v1-32k | Long-context JDs |
| 6 | Ollama | llama3.1:8b | Local, no-cost |
| 7 | Fallback | — | Keyword-based; always available |

Each User configures their own Providers via the extension Options page or Dashboard Settings. Having an API key = Provider is enabled. Per-question CategoryModelRoutes let users map any Category to a preferred Provider (e.g., cover letters → Anthropic, behavioral → Groq).

---

## Quick Start

```bash
# 1. Start Postgres + Redis
docker compose up -d

# 2. Apply database migrations
cd backend && poetry run alembic upgrade head

# 3. Start the backend
poetry run uvicorn "app.main:create_app" --factory --reload --port 8000

# 4. Build the extension (watch mode)
cd extension && npm run build -- --watch
# Load extension/dist/ as an unpacked extension in chrome://extensions
```

**Minimum `.env` for local development:**
```bash
DATABASE_URL=postgresql+asyncpg://autoapply:localdev@localhost:5432/autoapply
REDIS_URL=redis://localhost:6379
ENVIRONMENT=development
JWT_SECRET=any-string-for-dev
FERNET_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

See [`backend/.env.example`](./backend/.env.example) for all variables including Clerk, GitHub Vault, and LLM provider keys.

---

## Dashboard

Sign in with the same Clerk account used in the extension Options page — your profile auto-syncs across both surfaces.

| Page | Purpose |
|---|---|
| Home (`/`) | Application stats, mini-kanban snapshot, watchlist companies, activity feed |
| Applications (`/applications`) | Full Application list with kanban view, detail drawer, status timeline, notes |
| Resumes (`/resumes`) | Upload and manage the Resume Vault; Monaco LaTeX editor with PDF.js live preview |
| Cover Letters (`/cover-letters`) | Cover letter library with SSE streaming generator per company/role |
| Job Scout (`/job-scout`) | Discover and score job postings; fit score cards with ATS Score and skills gap |
| Vault (`/vault`) | Search and manage Answer Vault entries by Category, keyword, and reward score |
| Settings (`/settings`) | Profile fields, UserProviderConfig (LLM keys), WorkHistoryEntry management |

---

## Current State

> Phase 8 — 2026-03-23

| Component | Status |
|---|---|
| Backend API | Live — `https://autoapply-ai-api.fly.dev` (always-on, 0s cold start) |
| Database | Live — Supabase PostgreSQL, 11 migrations applied |
| Redis | Live — Upstash |
| Dashboard | Deployed on Vercel — Clerk auth, 9 pages, profile sync |
| Floating Panel | Live — Shadow DOM, teal/obsidian design, ATS bar, Resume Vault, LLM picker |
| Sidepanel | Live — 4 tabs: Resumes, Fields, Q&A, Answer Vault |
| Profile sync | Live — 14 profile fields synced extension ↔ Dashboard ↔ backend |
| Backend tests | ~355 tests across 39 files |
| TypeScript | 0 errors |
| Extension build | Clean — two-build architecture (ES modules + IIFE content scripts) |
| E2E tests | Playwright: 9 Dashboard tests; pytest API: 34 pass, 9 xfail |
| Open P0 issues | 4 security issues — fix before public launch (see Roadmap) |

---

## Roadmap

Full issue tracker: [`narendranathe/autoapply-ai`](https://github.com/narendranathe/autoapply-ai/issues)

### P0 — Security (required before public launch)

| Issue | What |
|---|---|
| [#89](https://github.com/narendranathe/autoapply-ai/issues/89) | `/auth/register` has no authentication — account takeover vector |
| [#90](https://github.com/narendranathe/autoapply-ai/issues/90) | JWT validation skipped when `CLERK_FRONTEND_API_URL` is unset |
| [#91](https://github.com/narendranathe/autoapply-ai/issues/91) | Offline Queue drain hardcodes `localhost:8000` — production edits silently fail |
| [#92](https://github.com/narendranathe/autoapply-ai/issues/92) | CORS wildcard `chrome-extension://*` when `EXTENSION_ID` is unset in production |

### P1 — Dashboard v2 (in progress)

| Issue | What |
|---|---|
| [#69](https://github.com/narendranathe/autoapply-ai/issues/69) | Dashboard v2 PRD |
| [#71](https://github.com/narendranathe/autoapply-ai/issues/71) – [#76](https://github.com/narendranathe/autoapply-ai/issues/76) | Home, Applications, Job Scout, Cover Letters, Resumes, Answer Vault pages |

### P1 — Extension Intelligence (Strategy C)

| Issue | What |
|---|---|
| [#56](https://github.com/narendranathe/autoapply-ai/issues/56) | Strategy C PRD — tiered detection + Vault recall + ATS auto-fill |
| [#58](https://github.com/narendranathe/autoapply-ai/issues/58) – [#63](https://github.com/narendranathe/autoapply-ai/issues/63) | VaultRecallConnector, SimilarityBadge, ATS Auto-Fill Banner, CoverLetterPreFetch, SPAResizeObserver, IframeFieldBridge |

### P2 — Growth

| Issue | What |
|---|---|
| [#93](https://github.com/narendranathe/autoapply-ai/issues/93) | Stripe billing — subscription plans |
| [#94](https://github.com/narendranathe/autoapply-ai/issues/94) | Chrome Web Store submission |
| [#95](https://github.com/narendranathe/autoapply-ai/issues/95) | Email monitoring — auto-update Application status from recruiter emails |

---

## Contributing

**Branch naming:** `feat/<description>`, `fix/<description>`, `chore/<description>`

**CI requirements — all must pass before merge:**

| Job | Checks |
|---|---|
| `backend` | ruff → black → mypy → alembic upgrade head → pytest |
| `extension` | npm ci → tsc --noEmit → npm run build |
| `docker` | docker buildx build — Dockerfile validity |

Triggered on push to `main`, `feat/**`, `fix/**`, and all PRs to `main`.

---

## Specs

All implementation detail, architectural decisions, phase histories, bug post-mortems, migration notes, and deployment config live in [`specs/README.md`](./specs/README.md).
