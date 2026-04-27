# Resume Intelligence Layer — Design Spec
**Date:** 2026-04-27
**Status:** Approved
**Source inspiration:** [santifer/career-ops](https://github.com/santifer/career-ops)
**Target repo:** autoapply-ai (Option B — stateful intelligence in autoapply-ai, stateless compute in tailor-resume-work)

---

## 1. Problem Statement

autoapply-ai currently returns a single ATS score and a list of rewritten bullets. Career-ops demonstrated that the right output is richer: dimensional offer grading, accumulated STAR narratives reusable across applications, negotiation scripts grounded in the candidate's proven wins, and structured JD data pulled from portals before the user even pastes a JD. This spec extends autoapply-ai with those five capabilities.

---

## 2. Architecture

### Two-tier split (permanent)

```
tailor-resume-work/web_app/       ← stateless compute engine
  POST /api/v1/resume/tailor      ← parse + score + LaTeX render  (exists, bugs fixed)
  POST /api/v1/resume/score       ← ATS score only                (new, thin)
  POST /api/v1/resume/parse       ← artifact → canonical Profile JSON (new)

autoapply-ai/backend/             ← stateful intelligence layer
  POST /api/v1/offer/evaluate     ← NEW: dimensional A-F offer scoring (9 dimensions)
  POST /api/v1/offer/negotiate    ← NEW: negotiation script generator
  GET/POST /api/v1/vault/stories  ← NEW: story bank CRUD
  POST /api/v1/vault/stories/match← NEW: match stories to a JD
  POST /api/v1/vault/portal/scan  ← NEW: structured JD from Greenhouse/Lever/Ashby
```

**Rule:** All user state (story bank entries, offer evaluations, negotiation scripts, portal scan cache) lives in autoapply-ai's Postgres. The standalone is called only for CPU-heavy LaTeX generation and formula-based scoring. The Chrome extension calls autoapply-ai for everything.

---

## 3. Standalone Engine Bug Fixes (tailor-resume-work)

Three bugs to fix before new work begins:

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `web_app/backend/app/routes/resume.py:131` | `artifacts=[tmp_path]` passes `str` but `TailorConfig.artifacts` expects `List[Tuple[str, str]]` | `artifacts=[(tmp_path, artifact_format)]` |
| 2 | `web_app/backend/app/routes/resume.py:93` | `result.gap_summary` is `List[str]` but `TailorResponse.gap_summary` expects `str` | `"\n".join(result.gap_summary)` |
| 3 | `web_app/backend/app/routes/resume.py:96` | `result.report` accessed but `TailorResult` has no `.report` field | Use `json.dumps({"top_missing": [...], "keyword_gaps": [...], "recommendations": [...]})` from `result.report` (which is a `GapReport`) |

Two new thin endpoints:
- `POST /api/v1/resume/score` — accepts `jd_text` + `resume_text` (plain), returns `ATSScoreResult` from `ats_scorer.score()`. No LaTeX output.
- `POST /api/v1/resume/parse` — accepts `artifact` file upload, returns canonical Profile JSON. Used by autoapply-ai to populate story bank from an uploaded resume.

---

## 4. Dimensional Offer Scoring

### New files
- `autoapply-ai/backend/app/models/offer_evaluation.py` — `OfferEvaluation` SQLAlchemy model
- `autoapply-ai/backend/app/routers/vault/offer.py` — `POST /api/v1/vault/offer/evaluate` and `POST /api/v1/vault/offer/negotiate`
- `autoapply-ai/backend/app/services/offer_scoring_service.py` — scoring logic

### Dimensions

| Dimension | Weight | Scoring method |
|---|---|---|
| `role_match` | 25% | ATS formula score from jd_gap_analyzer (calls standalone `/resume/score`) |
| `compensation_fit` | 15% | JD keyword regex: salary bands, equity mentions vs. $150k+ target |
| `sponsorship_likelihood` | 15% | Claude-haiku: classify JD + company for H1B sponsorship signal |
| `tech_stack_fit` | 15% | JD overlap with Naren's canonical stack (from WorkHistoryEntry tools) |
| `growth_trajectory` | 10% | Regex: Senior/Staff/Lead/Principal scope language in JD |
| `remote_flexibility` | 8% | Regex: remote/hybrid/onsite classification |
| `company_stability` | 5% | Dream company list lookup (Anthropic, Google, Databricks, etc.) |
| `interview_difficulty` | 4% | Regex: "LeetCode", "system design", "take-home", "coding challenge" |
| `culture_signals` | 3% | Claude-haiku: collaborative vs. competitive language, DE&I signals |

**Grade thresholds:** A ≥ 90 | B 75–89 | C 60–74 | D 45–59 | F < 45

**LLM usage:** Only `sponsorship_likelihood` and `culture_signals` use Claude-haiku. Everything else is formula-based (zero API cost per evaluation).

### OfferEvaluation model fields
```
id, user_id, jd_text_hash (SHA-256), company_name, role_title,
dimension_scores (JSONB), overall_grade (str), overall_score (float),
recommendation (str), created_at
```

### Response shape
```json
{
  "grade": "B",
  "overall_score": 78.4,
  "recommendation": "Strong match on role and tech. Low sponsorship signal — verify H1B before applying.",
  "dimensions": {
    "role_match": {"score": 82, "weight": 0.25, "label": "Strong"},
    "sponsorship_likelihood": {"score": 45, "weight": 0.15, "label": "Uncertain", "note": "JD silent on visa — research company history"}
  }
}
```

---

## 5. Story Bank

### New files
- `autoapply-ai/backend/app/models/story.py` — `StoryEntry` SQLAlchemy model
- `autoapply-ai/backend/app/routers/vault/stories.py` — CRUD + match endpoint
- `autoapply-ai/backend/app/services/story_service.py` — match logic

### StoryEntry model fields
```
id, user_id,
skill_tags (JSONB list[str]),   -- e.g. ["spark", "cost_optimization", "finops"]
domain (str),                   -- testing_ci_cd | orchestration | architecture_finops |
                                   streaming_realtime | ml_ai_platform | cloud_infra |
                                   leadership_ownership | sql_data_modeling |
                                   data_quality_observability | semantic_layer_governance
situation (str, max 200 chars), -- compressed context
action (str, max 150 chars),    -- STAR Action, ≤30 words
result (str, max 150 chars),    -- quantified outcome, ≤20 words, metric required
reflection (str, max 200 chars),-- what you'd do differently / what you learned (career-ops addition)
quality_score (float),          -- STAR compliance score from star_validator (0.0–1.0)
use_count (int, default 0),     -- times surfaced in a tailoring/interview run
last_used_at (timestamp, nullable),
created_at
```

**Domain values** align exactly with `SIGNAL_TAXONOMY` keys in `jd_gap_analyzer.py` for direct overlap scoring.

### Routes (`/api/v1/vault/stories`)
- `POST /vault/stories` — create story; auto-scores via `star_validator.bullet_quality_score()`; increments `use_count` to 0
- `GET /vault/stories?domain=&skill=&min_quality=` — list with filters, ordered by `quality_score DESC`
- `DELETE /vault/stories/{id}` — remove
- `POST /vault/stories/match` — accepts `jd_text`; returns top-5 stories ranked by skill_tag overlap against JD signal categories; increments `use_count` and sets `last_used_at` on matched stories

### Match algorithm
1. Run `jd_gap_analyzer.analyze_category_coverage(jd_text, "")` → returns `Dict[str, Dict]` keyed by signal category name (e.g. `"architecture_finops"`, `"orchestration"`).
2. For each story, compute overlap score: `sum(data["jd_frequency"] for cat, data in coverage.items() if cat in story.skill_tags and data["jd_keywords"])`.
3. Multiply by `story.quality_score` to surface high-quality stories first.
4. Return top-5 ordered by this weighted overlap score descending.

### Integration with existing features
- `vault/interview.py` `generate_interview_prep()` — call `stories/match` before generating suggested answers; inject top-3 matched stories into the LLM prompt as "proven narratives to draw from."
- `routers/tailor.py` proxy — after a successful tailoring run, extract the top bullets from the tailored resume and offer to save them as StoryEntry candidates (fire-and-forget, non-blocking).

---

## 6. Negotiation Scripts

### Endpoint
`POST /api/v1/vault/offer/negotiate` (same router as offer evaluate — `vault/offer.py`)

### Input
```json
{
  "company_name": "Databricks",
  "role_title": "Senior Data Engineer",
  "jd_text": "...",
  "current_offer": {"base": 145000, "equity": "0.05%", "bonus": 10},
  "target_salary": 175000
}
```

### LLM call
Claude-Sonnet via `LLMGateway`. Grounded in the user's top 3 quantified wins pulled from `WorkHistoryEntry` (same pattern as `interview.py`). System prompt emphasises: use only verified metrics from the candidate's history; never fabricate numbers.

### Response shape
```json
{
  "anchor_statement": "Based on the scope and my track record cutting $4.1k/month on AKS...",
  "talking_points": ["...", "...", "..."],
  "counter_script": "I'm very excited about this role. The offer is a strong start — I was expecting something closer to $175k given...",
  "walkaway_line": "I appreciate the offer, but I'm not able to accept below $160k given my current compensation.",
  "equity_reframe": "The 0.05% vests over 4 years — at a $10B valuation that's $50k/year...",
  "h1b_leverage_note": "Databricks has 94% H1B approval rate — you hold more leverage here than typical."
}
```

No new DB model — response returned to client only. Client stores it if desired (Chrome extension clipboard or display).

---

## 7. Portal Scanner

### New files
- `autoapply-ai/backend/app/models/portal_scan.py` — `PortalScanCache` SQLAlchemy model
- `autoapply-ai/backend/app/routers/vault/portal.py` — `POST /api/v1/vault/portal/scan`
- `autoapply-ai/backend/app/services/portal_scanner_service.py` — board detection + fetch logic

### PortalScanCache model fields
```
id, user_id,
company_name (str), job_id (str), board_type (str),  -- greenhouse|lever|ashby|wellfound|manual
job_url (str),
scan_result (JSONB),   -- title, location, remote_policy, requirements,
                          responsibilities, compensation_min, compensation_max
created_at, last_accessed_at,
is_stale (bool, default False)  -- user-triggered flag for force-refresh
```

**No TTL / no expiry.** Follows the Storage Fallback Pattern from `tailor-resume-work/CLAUDE.md`: data persists indefinitely. Rationale: JDs don't mutate post-posting; when the same role is retrieved again for re-tailoring or interview prep, the scan must still be present.

`is_stale=True` + `POST /vault/portal/scan?refresh=true` triggers a re-fetch and resets the flag.

### Board detection logic (`portal_scanner_service.py`)
```python
BOARD_PATTERNS = {
    "greenhouse": re.compile(r"boards\.greenhouse\.io/(\w+)/jobs/(\d+)"),
    "lever":      re.compile(r"jobs\.lever\.co/(\w+)/(.+)"),
    "ashby":      re.compile(r"jobs\.ashbyhq\.com/(\w+)/(.+)"),
    "wellfound":  re.compile(r"wellfound\.com/jobs/(\d+)"),
}
```

**Public API endpoints (no auth required for published jobs):**
- Greenhouse: `GET https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}`
- Lever: `GET https://api.lever.co/v0/postings/{company}/{posting_id}`
- Ashby: `GET https://api.ashbyhq.com/posting-api/job-board/{company}/jobs` (filtered by job slug)
- Wellfound: no stable public API — use `httpx` page fetch + structured extraction via Claude-haiku

### Response shape
```json
{
  "cached": false,
  "board_type": "greenhouse",
  "title": "Senior Data Engineer",
  "company": "Databricks",
  "location": "Remote — US",
  "remote_policy": "remote",
  "compensation_min": 150000,
  "compensation_max": 190000,
  "requirements": ["5+ years data engineering", "Apache Spark", "Delta Lake"],
  "responsibilities": ["Design and build large-scale data pipelines", "..."],
  "apply_url": "https://boards.greenhouse.io/databricks/jobs/12345",
  "job_id": "12345",
  "manual_entry": false
}
```

### Integration
- Chrome extension `worker.ts` detects Greenhouse/Lever/Ashby career pages. On detection, it can POST the job URL to `/vault/portal/scan` and cache the result before the user opens the sidepanel — the structured JD is ready instantly.
- `offer/evaluate` can accept a `job_id` + `company_name` and pull the cached scan instead of requiring raw `jd_text` input.

---

## 8. Database Migrations

Three new migrations in `autoapply-ai/backend/alembic/versions/`:

| Migration | Table | Key columns |
|---|---|---|
| `add_offer_evaluations` | `offer_evaluations` | `user_id`, `jd_text_hash`, `dimension_scores JSONB`, `overall_grade`, `overall_score` |
| `add_story_entries` | `story_entries` | `user_id`, `skill_tags JSONB`, `domain`, `action`, `result`, `reflection`, `quality_score`, `use_count` |
| `add_portal_scan_cache` | `portal_scan_cache` | `user_id`, `company_name`, `job_id`, `board_type`, `scan_result JSONB`, `is_stale` |

Indexes:
- `story_entries`: `(user_id, domain)`, `(user_id, quality_score DESC)`
- `portal_scan_cache`: `(user_id, company_name, job_id)` UNIQUE, `(is_stale)`
- `offer_evaluations`: `(user_id, jd_text_hash)` for deduplication

---

## 9. Testing Strategy

Each new feature gets its own test file mirroring the existing pattern:

| Test file | What it covers |
|---|---|
| `tests/test_offer_scoring_service.py` | Formula scoring per dimension; Claude-haiku mock for sponsorship/culture; grade thresholds |
| `tests/test_story_bank.py` | CRUD routes; match algorithm ranking; quality_score auto-computation; use_count increment |
| `tests/test_negotiation.py` | LLM prompt construction; WorkHistoryEntry grounding; response shape validation |
| `tests/test_portal_scanner.py` | Board detection regex; Greenhouse/Lever API mock responses; cache hit/miss; `is_stale` refresh |
| `tests/test_standalone_bugs.py` | Three bug fixes in `tailor-resume-work/web_app/routes/resume.py` |

All LLM calls mocked via `monkeypatch` — no API keys in CI.

---

## 10. Vault Router Registration

The new sub-routers register via the existing `vault/__init__.py` aggregator pattern:

```python
# vault/__init__.py additions
from app.routers.vault.offer import router as offer_router
from app.routers.vault.stories import router as stories_router
from app.routers.vault.portal import router as portal_router
```

---

## 11. Ubiquitous Language Additions

New terms to add to `autoapply-ai/UBIQUITOUS_LANGUAGE.md` (or create if absent):

| Term | Definition |
|---|---|
| **OfferEvaluation** | A scored dimensional breakdown of a JD across 9 weighted dimensions, yielding an A–F grade and recommendation. Distinct from ATS Score Estimate (which measures resume-JD keyword fit only). |
| **StoryEntry** | A reusable STAR+Reflection narrative asset. Not tied to a specific application. Indexed by `domain` and `skill_tags` for cross-JD retrieval. |
| **Reflection** | The fourth component of a StoryEntry (beyond Situation, Action, Result): what you'd do differently or what you learned. Sourced from career-ops. |
| **PortalScanCache** | A persisted structured JD record fetched from a known ATS board (Greenhouse, Lever, Ashby, Wellfound). No TTL — retained indefinitely per the Storage Fallback Pattern. |
| **NegotiationScript** | A stateless LLM-generated set of talking points, counter-offer script, and walkaway line grounded in the candidate's verified work history metrics. Not persisted. |
| **DimensionalScore** | The per-dimension numeric score (0–100) inside an OfferEvaluation. Nine dimensions weighted by importance. |

---

## 12. Out of Scope

- Portal scanner for LinkedIn (requires auth — not a public API)
- PDF compilation in the standalone (users use Overleaf or local pdflatex per existing `pdf_export.md`)
- Real-time streaming of negotiation script generation
- Multi-user story bank sharing
