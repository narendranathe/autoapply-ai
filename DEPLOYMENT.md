# AutoApply AI — Deployment Guide

> End-to-end instructions: Render (backend), Clerk (auth), Chrome Web Store (extension).

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Git | any | Version control |
| Python | 3.12 | Backend runtime |
| Poetry | 1.8.x | Python dependency management |
| Node.js | 20 | Extension build |
| Docker | 24+ | Local dev + Render build |
| psql | any | Database smoke-tests |

---

## 1. Clerk Authentication Setup

### 1a. Create Clerk account
1. Go to [clerk.com](https://clerk.com) → **Sign Up** (free tier supports up to 10,000 MAU)
2. Create application → choose **Email + Password** + **Google OAuth** sign-in methods

### 1b. Collect Clerk credentials
In **Clerk Dashboard → API Keys**:
```
CLERK_PUBLISHABLE_KEY=pk_live_...
CLERK_SECRET_KEY=sk_live_...
CLERK_FRONTEND_API_URL=https://YOUR-INSTANCE.clerk.accounts.dev
```

### 1c. Configure Clerk webhook (for user registration)
1. **Clerk Dashboard → Webhooks → Add Endpoint**
2. Endpoint URL: `https://your-render-service.onrender.com/api/v1/auth/register`
3. Events: `user.created`, `user.updated`
4. Copy the **Signing Secret** → add to env as `CLERK_WEBHOOK_SECRET`

---

## 2. Deploy Backend to Render

### 2a. Connect repo to Render
1. [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint**
2. Connect GitHub → select this repository
3. Render reads `render.yaml` at the project root and provisions:
   - **autoapply-ai-api** — Docker web service (free tier)
   - **autoapply-db** — PostgreSQL (free tier, 1 GB)
   - **autoapply-redis** — Redis (free tier)

### 2b. Set secret environment variables
After blueprint provision, go to **autoapply-ai-api → Environment** and set:

| Key | Value | Source |
|-----|-------|--------|
| `CLERK_SECRET_KEY` | `sk_live_...` | Clerk Dashboard |
| `CLERK_FRONTEND_API_URL` | `https://YOUR.clerk.accounts.dev` | Clerk Dashboard |
| `GITHUB_TOKEN` | `ghp_...` (PAT with `repo` scope) | GitHub → Settings → Tokens |
| `GITHUB_REPO_OWNER` | your GitHub username | GitHub |
| `GITHUB_REPO_NAME` | `resume-vault` | your private GitHub repo |
| `SENTRY_DSN` | _(optional)_ | Sentry project DSN |
| `EXTENSION_ID` | _(set after Chrome Web Store publish)_ | Chrome Web Store |

> `FERNET_KEY` and `JWT_SECRET` are **auto-generated** by Render via `generateValue: true` in `render.yaml`.

### 2c. First deploy
Render triggers a Docker build automatically. Monitor at **autoapply-ai-api → Logs**.

`start.sh` runs `alembic upgrade head` before starting uvicorn, so migrations run automatically on each deploy.

### 2d. Verify deployment
```bash
# Health check
curl https://your-render-service.onrender.com/health

# Expected response:
# {"status": "healthy", "environment": "production", ...}
```

---

## 3. GitHub Private Resume Vault Setup

The backend reads/writes resumes from a private GitHub repository. Create it once:

```bash
# Create private repo at GitHub (UI or gh CLI)
gh repo create resume-vault --private

# Create required directory structure
mkdir -p resume-vault/{versions,applications,private,template}
touch resume-vault/.gitkeep

# Push structure
cd resume-vault && git init && git add . && git commit -m "init vault"
gh repo set-default resume-vault
git push -u origin main
```

Then set `GITHUB_REPO_OWNER` and `GITHUB_REPO_NAME` in your Render environment.

---

## 4. Build & Submit Chrome Extension

### 4a. Install dependencies and build
```bash
cd extension
npm ci
npm run build
# Output: extension/dist/
```

### 4b. Test locally before publishing
1. Open `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** → select `extension/dist/`
4. Visit `linkedin.com/jobs` or any `greenhouse.io` job page
5. The side panel should open automatically

### 4c. Update API base URL for production
Before building for the store, update `extension/src/shared/api.ts`:
```typescript
// Change this line:
const API_BASE = "http://localhost:8000/api/v1";
// To your Render URL:
const API_BASE = "https://autoapply-ai-api.onrender.com/api/v1";
```
Then rebuild: `npm run build`

### 4d. Package for Chrome Web Store
```bash
cd extension
# Build production bundle (runs scripts/verify-manifest.mjs — fails if any
# localhost / 127.0.0.1 entry remains in dist/manifest.json host_permissions).
npm run build

# Zip the dist folder (not the dist folder itself — zip its contents)
cd dist && zip -r ../autoapply-ai.zip . && cd ..
```

> `npm run build` runs in production mode and the Vite plugin in
> `extension/vite.config.ts` strips every loopback entry from `host_permissions`
> before writing `dist/manifest.json`. Use `npm run build:dev` when loading the
> extension locally against `http://localhost:8000` — that build keeps the
> loopback permission so the dev server is reachable.

### 4e. Submit to Chrome Web Store
1. Go to [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole)
2. Pay one-time $5 developer registration fee
3. **Add new item** → upload `autoapply-ai.zip`
4. Fill in store listing (use `extension/store/description.txt`)
5. Upload screenshots (1280×800 or 640×400) — minimum 1 required
6. Privacy policy URL: host `extension/store/privacy_policy.md` publicly (GitHub Pages or similar)
7. Submit for review (usually 1–3 business days)

### 4f. Set Extension ID in backend
After your extension is published:
1. Find your **Extension ID** in the Chrome Web Store URL: `...detail/YOUR_EXTENSION_ID`
2. Set it on the backend (required when `ENVIRONMENT=production`):
   - Render: dashboard → autoapply-ai-api → Environment → `EXTENSION_ID=YOUR_EXTENSION_ID`
   - Fly.io: `fly secrets set EXTENSION_ID=YOUR_EXTENSION_ID`
3. This restricts CORS to that one extension. The backend refuses to start in
   production without it — the `chrome-extension://*` wildcard in
   `ALLOWED_ORIGINS` would otherwise let any installed extension call the API.

---

## 5. Local Development

### 5a. Start all services
```bash
# From project root
docker compose up -d
# Starts: postgres:5432, db_test:5433, redis:6379
# Optional Ollama: docker compose --profile ollama up -d
```

### 5b. Run backend locally
```bash
cd backend

# Copy and edit environment variables
cp .env.example .env
# Edit .env with your actual values

# Install dependencies
poetry install

# Run migrations
poetry run alembic upgrade head

# Start development server (auto-reload)
poetry run uvicorn app.main:create_app --factory --reload --port 8000
```

### 5c. Run extension locally
```bash
cd extension
npm ci
npm run dev        # Vite dev build with watch mode (keeps localhost host_permission)
# or
npm run build:dev  # One-shot dev build (keeps localhost host_permission)
# or
npm run build      # Production build (strips localhost host_permission)
```

Load `extension/dist/` as unpacked extension in Chrome.

### 5d. Run tests
```bash
cd backend
poetry run pytest tests/ -v
```

---

## 6. Environment Variables Reference

See `backend/.env.example` for the full list with descriptions.

| Variable | Required | Notes |
|----------|----------|-------|
| `DATABASE_URL` | ✅ | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `REDIS_URL` | ✅ | Redis URL |
| `FERNET_KEY` | ✅ | 32-byte base64 key — generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `JWT_SECRET` | ✅ | Random secret for internal JWT tokens |
| `CLERK_SECRET_KEY` | ✅ | From Clerk Dashboard |
| `CLERK_FRONTEND_API_URL` | ✅ | Your Clerk instance URL |
| `GITHUB_TOKEN` | ✅ | GitHub PAT with `repo` scope |
| `GITHUB_REPO_OWNER` | ✅ | GitHub username |
| `GITHUB_REPO_NAME` | ✅ | Private resume vault repo name |
| `ENVIRONMENT` | — | `development` / `production` / `testing` |
| `OLLAMA_BASE_URL` | — | Default: `http://localhost:11434` |
| `EXTENSION_ID` | ✅ (prod) | Required when `ENVIRONMENT=production`; set after Chrome Web Store publish |
| `SENTRY_DSN` | — | Sentry error tracking (optional) |

---

## 7. CI/CD

GitHub Actions runs on every push:
- **Backend**: ruff lint → black format → mypy typecheck → pytest
- **Extension**: tsc typecheck → vite build
- **Dashboard**: tsc typecheck → eslint → vite build
- **Docker**: builds backend image (no push, validates Dockerfile)

See `.github/workflows/ci.yml`.

### Required GitHub Actions secrets

| Secret | Used by | Purpose |
|--------|---------|---------|
| `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` | `docker` job | Authenticated Docker Hub pulls (avoid rate limits) |
| `FLY_API_TOKEN` | `deploy` job | Fly.io deploy on `main` |
| `VITE_CLERK_PUBLISHABLE_KEY_TEST` | `dashboard` job | Clerk publishable key (test instance) injected into the dashboard Vite build. Must be a Clerk **test** publishable key — `pk_test_...` — taken from Clerk Dashboard → API Keys → Development instance. Never use the production key here. |

---

## 8. Render Free Tier Limitations

| Limit | Free Tier |
|-------|-----------|
| Web service | Spins down after 15 min inactivity (cold start ~30s) |
| PostgreSQL | 1 GB storage, expires after 90 days without activity |
| Redis | 25 MB, no persistence |

For production use beyond hobby tier, upgrade to Render's **Starter plan** ($7/month per service).

---

## 9. Troubleshooting

**502 on first request after idle**
- Free tier spins down. First request triggers cold start. Normal behavior.

**Migration fails on deploy**
- Check `DATABASE_URL` is set correctly in Render env vars
- Render logs → look for `alembic.exc.` errors

**Extension side panel doesn't open**
- Check `chrome://extensions/` → AutoApply AI → inspect service worker for errors
- Verify `API_BASE` in `api.ts` points to your deployed Render URL

**CORS errors in extension**
- Set `EXTENSION_ID` to your published extension's ID
  (Render dashboard or `fly secrets set EXTENSION_ID=<id>`)
- In dev: `EXTENSION_ID` can be left empty (allows all origins)
- In production: the backend raises `RuntimeError` at startup if `EXTENSION_ID` is unset

**Clerk auth 401**
- Verify `CLERK_FRONTEND_API_URL` matches your Clerk instance (no trailing slash)
- Check that the extension calls `setClerkUserId()` after successful Clerk auth
