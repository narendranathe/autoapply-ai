# Resume Intelligence Layer — Design Spec
**Date:** 2026-04-27
**Status:** Revised after 4-agent parallel critique
**Source inspiration:** [santifer/career-ops](https://github.com/santifer/career-ops)
**Target repo:** autoapply-ai (Option B — stateful intelligence in autoapply-ai, stateless compute in tailor-resume-work)

---

## 1. Problem Statement

autoapply-ai currently returns a single ATS score and rewritten bullets. Career-ops demonstrated the right output is richer: dimensional offer grading, accumulated STAR narratives reusable across applications, negotiation scripts grounded in verified wins, and structured JD data pulled from portals before the user pastes anything. This spec extends autoapply-ai with those capabilities.

---

## 2. Architecture

### Two-tier split (permanent)

```
tailor-resume-work/web_app/          ← stateless compute engine (no user state)
  POST /api/v1/resume/tailor         ← parse + score + LaTeX render  (exists, bugs fixed)
  POST /api/v1/resume/score          ← ATS score only                (new, thin)
  POST /api/v1/resume/parse          ← artifact → canonical Profile JSON (new)

autoapply-ai/backend/                ← stateful intelligence layer
  POST /api/v1/vault/offer/evaluate  ← NEW: dimensional A-F offer scoring (9 dimensions)
  POST /api/v1/vault/offer/negotiate ← NEW: negotiation script generator (v2 target, see §6)
  GET/POST /api/v1/vault/stories     ← NEW: story bank CRUD
  POST /api/v1/vault/stories/match   ← NEW: match stories to a JD
  POST /api/v1/vault/portal/scan     ← NEW: structured JD from Greenhouse/Lever/Ashby
```

**All new routes are under `/api/v1/vault/`** — they register through `vault/__init__.py` which is mounted at that prefix in `main.py`. Section 2 of the original spec incorrectly showed them at `/api/v1/offer/...` — that path does not exist in this codebase.

**Rule:** All user state lives in autoapply-ai's Postgres. The standalone is called only for CPU-heavy LaTeX generation and formula-based scoring via HTTP. The Chrome extension calls autoapply-ai for everything.

### `jd_gap_analyzer` / `star_validator` import resolution

These modules live in `tailor-resume-work/tailor_resume/_scripts/` and are **not on autoapply-ai's Python path**. A direct import will fail at runtime with `ModuleNotFoundError`.

**Decision for v1: vendor the relevant logic inline.** Copy the core scoring logic from both modules into `autoapply-ai/backend/app/services/story_service.py` and `offer_scoring_service.py` as private helper functions. Do NOT import from the standalone package. This avoids cross-repo dependency at the cost of minor duplication. Document with a comment: `# vendored from tailor-resume-work; keep in sync with jd_gap_analyzer.SIGNAL_TAXONOMY`.

If/when this logic stabilises it can be extracted to a shared internal package. That is a future refactor, not v1 scope.

---

## 3. Standalone Engine Bug Fixes (tailor-resume-work)

Three bugs to fix before the thin endpoints land:

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `routes/resume.py:131` | `artifacts=[tmp_path]` passes `str`; `TailorConfig.artifacts` expects `List[Tuple[str, str]]` | `artifacts=[(tmp_path, artifact_format)]` |
| 2 | `routes/resume.py:93` | `result.gap_summary` is `List[str]`; `TailorResponse.gap_summary` expects `str` | `"\n".join(result.gap_summary)` |
| 3 | `routes/resume.py:96` | `result.report` accessed but `TailorResult` has no `.report` — it has a `GapReport` object at `result.report` with fields `.top_missing`, `.keyword_gaps`, `.ats_score_estimate`, `.recommendations` | Serialize: `json.dumps({"top_missing": [...], "keyword_gaps": result.report.keyword_gaps, "recommendations": result.report.recommendations, "ats_score": result.report.ats_score_estimate})` — verify exact `GapReport` field names against `resume_types.py` before writing |

**Note:** These bugs do not block slices 1–4. They block the standalone's own `/tailor` endpoint and the `role_match` HTTP call from offer scoring. Fix them in parallel with or just before Slice 4 (offer scoring).

Two new thin endpoints:
- `POST /api/v1/resume/score` — `jd_text` + `resume_text` (plain) → `ATSScoreResult` from `ats_scorer.score()`. No LaTeX.
- `POST /api/v1/resume/parse` — artifact file upload → canonical Profile JSON. Used by autoapply-ai's bulk story bank import.

---

## 4. Dimensional Offer Scoring

### New files
- `app/models/offer_evaluation.py` — `OfferEvaluation` SQLAlchemy model
- `app/routers/vault/offer.py` — `POST /api/v1/vault/offer/evaluate` and `/negotiate`
- `app/services/offer_scoring_service.py` — scoring logic + vendored category coverage

### Dimensions (9 total, weights sum to 100%)

| Dimension | Weight | Scoring method |
|---|---|---|
| `role_match` | 25% | ATS formula: vendored `analyze_category_coverage()` against user's default/selected resume. See request schema below. |
| `compensation_fit` | 18% | JD regex for salary bands when present; fallback to static tier lookup by `(role_title, company_tier)` when absent. Dream companies default to `compensation_tier=senior_de` ($150k–$220k band) |
| `sponsorship_likelihood` | 15% | Claude-haiku classify JD + company for H1B signals; regex fallback scanning "visa sponsorship", "H1B", "must be authorized to work without sponsorship" |
| `tech_stack_fit` | 15% | JD keyword overlap with vendored `SIGNAL_TAXONOMY` against user's `WorkHistoryEntry` tool mentions |
| `growth_trajectory` | 10% | Regex: Senior/Staff/Lead/Principal/Architect scope language |
| `remote_flexibility` | 8% | Regex: remote/hybrid/onsite classification |
| `company_stability` | 5% | Dream company list lookup — note: this measures **brand prestige**, not financial stability. Rename to `brand_prestige` if surfacing to user. |
| `interview_difficulty` | 4% | Regex: "LeetCode", "system design", "take-home", "coding challenge", "onsite loop" |

**Removed from original spec:** `culture_signals` (3% weight, LLM cost per evaluation, negligible grade impact — removed entirely).

**Grade thresholds:** A ≥ 90 | B 75–89 | C 60–74 | D 45–59 | F < 45

**BYOK fallback per LLM-dependent dimension:**
- `sponsorship_likelihood`: if no LLM key → regex-only fallback (scan JD + company name for known sponsorship phrases). Score 40 if silent on sponsorship, 70 if positive signals, 10 if explicit "no sponsorship."
- `culture_signals`: removed — no fallback needed.
- All formula dimensions (7/8): zero API cost, always available.

### Standalone unavailability strategy

When `tailor-resume-work` is unreachable, `role_match` cannot be computed. Behavior:
- Default: `DEGRADE_WITHOUT_ROLE_MATCH` — score all other dimensions, set `role_match` to `null`, reduce overall weight denominator accordingly, include `"degraded_dimensions": ["role_match"]` in response.
- Log `[offer_eval] user={id} standalone_unavailable=true` at WARN level.
- Do NOT return 503 — a partial grade is more useful than an error.

### Request schema

```json
{
  "jd_text": "...",
  "company_name": "Databricks",
  "role_title": "Senior Data Engineer",
  "resume_id": "uuid-optional",
  "portal_scan_id": "uuid-optional"
}
```

`resume_id`: optional. If omitted, use the user's most recently uploaded/generated resume (`ORDER BY created_at DESC LIMIT 1`). If no resume on file, skip `role_match` dimension.

`portal_scan_id`: optional. If provided, pull `jd_text` from `PortalScanCache.scan_result` instead of request body.

Idempotency: `POST /vault/offer/evaluate` is **idempotent on `(user_id, jd_text_hash)`**. If a matching evaluation exists, return it with `"cached": true` in the response. Force re-run with `?refresh=true`.

### Response schema

```json
{
  "evaluation_id": "uuid",
  "cached": false,
  "grade": "B",
  "overall_score": 78.4,
  "recommendation": "Strong match on role and tech. Low sponsorship signal — verify H1B before applying.",
  "standalone_available": true,
  "degraded_dimensions": [],
  "dimensions": {
    "role_match": {"score": 82, "weight": 0.25, "label": "Strong"},
    "sponsorship_likelihood": {"score": 45, "weight": 0.15, "label": "Uncertain",
      "note": "JD silent on visa — research company history"}
  }
}
```

### OfferEvaluation model fields
```
id: UUID PK
user_id: UUID FK → users.id ON DELETE CASCADE, index=True
resume_id: UUID FK → resumes.id ON DELETE SET NULL, nullable=True
jd_text_hash: String(64) NOT NULL, index=True
company_name: String(200) NOT NULL
role_title: String(200) NOT NULL
dimension_scores: JSONB NOT NULL  ← validated by Pydantic DimensionScore model before write
overall_grade: String(1) NOT NULL  ← CHECK (overall_grade IN ('A','B','C','D','F'))
overall_score: Float NOT NULL  ← CHECK (overall_score >= 0 AND overall_score <= 100)
recommendation: Text NOT NULL
created_at, updated_at  ← TimestampMixin
```

**Table args:**
```python
UniqueConstraint("user_id", "jd_text_hash", name="uq_offer_eval_user_jd"),
Index("ix_offer_eval_user_created", "user_id", "created_at"),
```

---

## 5. Story Bank

### New files
- `app/models/story.py` — `StoryEntry` SQLAlchemy model
- `app/routers/vault/stories.py` — CRUD + match endpoint
- `app/services/story_service.py` — scoring + match logic (vendored SIGNAL_TAXONOMY inline)

### StoryEntry model fields
```
id: UUID PK
user_id: UUID FK → users.id ON DELETE CASCADE, index=True
skill_tags: JSONB NOT NULL  ← list[str]; values drawn from SIGNAL_TAXONOMY keys
domain: String(50) NOT NULL  ← CHECK constraint with 10 valid values (see below)
situation: String(200) NOT NULL
action: String(150) NOT NULL   ← STAR Action, ≤30 words
result_text: String(150) NOT NULL  ← renamed from 'result' to avoid ORM reserved word collision
reflection: String(200) nullable=True  ← v1: store but do not surface in match/interview
quality_score: Float NOT NULL  ← CHECK (quality_score >= 0.0 AND quality_score <= 1.0)
use_count: Integer NOT NULL, default=0, server_default="0"
last_used_at: timestamp nullable=True
created_at, updated_at  ← TimestampMixin
```

**`domain` CHECK constraint** (10 valid values aligned with vendored `SIGNAL_TAXONOMY`):
```sql
CHECK (domain IN (
  'testing_ci_cd', 'orchestration', 'architecture_finops',
  'streaming_realtime', 'ml_ai_platform', 'cloud_infra',
  'leadership_ownership', 'sql_data_modeling',
  'data_quality_observability', 'semantic_layer_governance'
))
```
Using a CHECK constraint on `String(50)` rather than a Postgres enum avoids the non-transactional `ALTER TYPE ADD VALUE` DDL pitfall in Alembic.

**Table args:**
```python
Index("ix_story_entries_user_domain", "user_id", "domain"),
Index("ix_story_entries_user_quality", "user_id", "quality_score"),
# GIN index — must be created CONCURRENTLY in migration for production safety:
# CREATE INDEX CONCURRENTLY ix_story_entries_skill_tags ON story_entries USING GIN (skill_tags)
```

### Quality scoring (vendored inline, no standalone import)

Auto-score on `POST /vault/stories`:
```python
def _auto_score(action: str, result_text: str) -> float:
    """Inline STAR compliance score — vendored from star_validator logic."""
    combined = f"{action} {result_text}"
    has_action = any(v in combined.lower().split()[:6] for v in ACTION_VERBS)
    has_result = bool(re.search(r'\b\d+(\.\d+)?\s?%|\$\s?\d[\d,]*|from\b.{3,40}\bto\b', combined))
    return round(0.5 * int(has_action) + 0.5 * int(has_result), 2)
```

### Routes (`/api/v1/vault/stories`)
- `POST /vault/stories` — create; auto-score `quality_score`; ownership: `user_id = current_user.id`
- `GET /vault/stories?domain=&skill=&min_quality=0.5` — list filtered, ordered by `quality_score DESC`; ownership enforced
- `DELETE /vault/stories/{id}` — verify `story.user_id == current_user.id` before delete
- `POST /vault/stories/match` — input: `jd_text`; returns top-5 stories; increments `use_count`, sets `last_used_at` (synchronous write, same request)

### Match algorithm (vendored inline)

```python
# Vendored from jd_gap_analyzer.SIGNAL_TAXONOMY — keep in sync
SIGNAL_TAXONOMY = {
    "testing_ci_cd": ["test", "pytest", "ci", "cd", "github actions", ...],
    ...
}

def match_stories_to_jd(jd_text: str, stories: list[StoryEntry]) -> list[StoryEntry]:
    jd_lower = jd_text.lower()
    # Per-category JD frequency
    category_freq = {
        cat: sum(jd_lower.count(kw) for kw in kws)
        for cat, kws in SIGNAL_TAXONOMY.items()
    }
    def story_score(s: StoryEntry) -> float:
        overlap = sum(category_freq.get(tag, 0) for tag in s.skill_tags)
        return overlap * s.quality_score
    return sorted(stories, key=story_score, reverse=True)[:5]
```

### Bulk import path (required for day-one value)

Without pre-populated stories the match feature returns nothing. Add:
- `POST /vault/stories/import` — accepts a `resume_id`; calls standalone `/resume/parse` to get canonical Profile JSON; auto-creates `StoryEntry` candidates from each role's bullets (domain inferred from `jd_gap_analyzer` taxonomy overlap against bullet text); sets `quality_score` via inline scorer; returns list of created entries for user review.
- This is the onboarding flow: upload resume → import stories → review/edit → start matching.

### Integration with existing features

**`vault/interview.py` enhancement:** Before generating suggested answers, call `stories/match` with the `jd_text`. Inject top-3 matched stories into the LLM system prompt:
```
Proven narratives to draw from:
1. Action: {story.action} | Result: {story.result_text}
...
Use these as grounding — do not fabricate new achievements.
```

**`routers/tailor.py` integration (separate ticket):** After a successful tailoring run, offer to extract top bullets as `StoryEntry` candidates. This requires a UI flow and is out of scope for v1 story bank slice.

**`reflection` field:** Store in DB, do not surface in match algorithm, interview prep injection, or any v1 UI. Revisit in v2 when behavioral interview prep is a dedicated feature.

---

## 6. Negotiation Scripts

**Status: v2 target. Excluded from v1 scope.**

Rationale: Negotiation happens once per offer cycle, deep in the funnel. Naren needs to optimize top-of-funnel first (story bank, offer scoring). Build this when he is consistently reaching offer stage.

**When built, add minimal persistence (not stateless):**
```
negotiation_scripts table:
id, user_id, offer_evaluation_id (FK, nullable),
company_name, role_title,
offer_data JSONB,      ← current_offer + target_salary inputs
script_result JSONB,   ← full response
created_at
```
Rationale: multi-round negotiations span multiple days. The Chrome extension clipboard is ephemeral. Without persistence the second-round counter has no memory of the first.

**`equity` input must be structured, not a string:**
```json
"equity": {"percentage": 0.0005, "vesting_years": 4, "cliff_months": 12}
```
The `equity_reframe` requires arithmetic. A string `"0.05%"` requires fragile regex parsing and the valuation source must be an explicit required input field — the LLM must not fabricate company valuations.

**LLM routing:** Uses user's configured provider cascade (same as `interview.py`) — not always-Anthropic. Falls back to a structured template response if no LLM key is available.

---

## 7. Portal Scanner

### New files
- `app/models/portal_scan.py` — `PortalScanCache` SQLAlchemy model
- `app/routers/vault/portal.py` — `POST /api/v1/vault/portal/scan`
- `app/services/portal_scanner_service.py` — board detection + fetch + circuit breaker

### PortalScanCache model fields
```
id: UUID PK
user_id: UUID FK → users.id ON DELETE CASCADE, index=True
company_name: String(200) NOT NULL
job_id: String(200) NOT NULL  ← slug or numeric ID; 200 chars covers all board types
board_type: String(50) NOT NULL  ← CHECK (board_type IN ('greenhouse','lever','ashby','wellfound','manual'))
job_url: String(2048) NOT NULL
compensation_min: Integer nullable=True  ← promoted from scan_result JSONB for direct SQL queries
compensation_max: Integer nullable=True  ← promoted from scan_result JSONB
scan_result: JSONB NOT NULL  ← title, location, remote_policy, requirements, responsibilities, schema_version
schema_version: Integer NOT NULL, default=1, server_default="1"  ← bump when scan_result shape changes
created_at, updated_at  ← TimestampMixin
last_accessed_at: timestamp nullable=True
is_stale: Boolean NOT NULL, default=False, server_default="false"
```

**No TTL / no expiry.** Follows the Storage Fallback Pattern: data persists indefinitely. Force-refresh: `POST /vault/portal/scan?refresh=true` re-fetches, resets `is_stale=False`.

**Table args:**
```python
UniqueConstraint("user_id", "board_type", "job_id", name="uq_portal_scan_user_board_job"),
# NOT (user_id, company_name, job_id) — company_name is free-text, unreliable as a key
Index("ix_portal_scan_user_company", "user_id", "company_name"),
# Partial index on is_stale — boolean indexes have catastrophic selectivity:
# CREATE INDEX ix_portal_scan_stale ON portal_scan_cache (user_id) WHERE is_stale = true
```

### Board detection and fetch logic

```python
BOARD_PATTERNS = {
    "greenhouse": re.compile(r"boards\.greenhouse\.io/(\w+)/jobs/(\d+)"),
    "lever":      re.compile(r"jobs\.lever\.co/([\w-]+)/([a-f0-9-]+)"),
    "ashby":      re.compile(r"jobs\.ashbyhq\.com/([\w-]+)/([^/?]+)"),
    "wellfound":  re.compile(r"wellfound\.com/jobs/(\d+)"),
}
```

**Ashby note:** `GET /posting-api/job-board/{company}/jobs` returns ALL jobs, not a single job. Must iterate the response list to find the entry matching the captured job slug via `jobPostingPath` field. This is O(n) over the company's open roles. Mitigate: cache the full job list per company for 1 hour in Redis (`portal:ashby:{company}:jobs`) to avoid re-fetching on repeat scans.

**Wellfound:** Deferred from v1. Wellfound is a React SPA — a plain `httpx` GET returns an empty shell. Proper implementation requires a headless browser (Playwright). Include in v1 as `board_type="manual"` fallback only. Revisit in v2 with Playwright service.

**HTTP timeouts (explicit per board):**
```python
BOARD_TIMEOUTS = {
    "greenhouse": httpx.Timeout(connect=3.0, read=8.0),
    "lever":      httpx.Timeout(connect=3.0, read=8.0),
    "ashby":      httpx.Timeout(connect=3.0, read=12.0),  # list fetch is slower
}
```

**Retry:** 1 retry with 1s delay on 5xx from any board API.

**Circuit breaker:** Define `portal_circuit = CircuitBreaker(name="portal_scanner", failure_threshold=3, recovery_timeout=120)` in `circuit_breaker.py`. Apply at per-board fetch function level (not service level) so Greenhouse down doesn't kill Lever scans.

**`schema_version` field:** When `scan_result` JSONB shape changes in a future version, increment `schema_version` default. Background job or on-demand: re-fetch records where `schema_version < CURRENT_VERSION`.

### Response schema
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
  "responsibilities": ["Design and build large-scale data pipelines"],
  "apply_url": "https://boards.greenhouse.io/databricks/jobs/12345",
  "job_id": "12345",
  "schema_version": 1,
  "manual_entry": false
}
```

**Unsupported board:** return `{"manual_entry": true, "board_type": null, "cached": false}` with HTTP 200. Do not 422 — the user can paste the JD manually.

### Chrome extension integration (separate ticket)

`worker.ts` detecting ATS URLs and pre-caching scans before the user opens the sidepanel is a non-trivial extension change. Scope it as a separate ticket. The portal scanner backend can ship and be useful (called manually from the sidepanel) without extension pre-caching. When the extension integration ships, add a `"status": "scanning"` response for in-flight Wellfound scans.

---

## 8. Database Migrations

Three new migrations in `backend/alembic/versions/`:

| Migration | Table | Key constraints |
|---|---|---|
| `add_offer_evaluations` | `offer_evaluations` | FK `user_id→users.id CASCADE`, FK `resume_id→resumes.id SET NULL`, UNIQUE `(user_id, jd_text_hash)`, CHECK on grade/score |
| `add_story_entries` | `story_entries` | FK `user_id→users.id CASCADE`, CHECK on `domain`, CHECK on `quality_score`, GIN index on `skill_tags` |
| `add_portal_scan_cache` | `portal_scan_cache` | FK `user_id→users.id CASCADE`, UNIQUE `(user_id, board_type, job_id)`, partial index on `is_stale` |

**All migrations must include:**
- `upgrade()` function
- `downgrade()` function that drops indexes first, then the table (reverse dependency order)
- GIN indexes created with `postgresql_concurrently=True` in `autocommit_block` to avoid table locks
- New models imported in `app/models/__init__.py` — required for Alembic autogenerate and `Base.metadata` in tests

**Supabase RLS:** Not required. autoapply-ai uses Clerk auth + service role key, not Supabase Auth. Existing tables have no RLS policies — maintain that convention.

---

## 9. Cross-Cutting Concerns

### LLM Gateway — `model` parameter required

The current `LLMGateway` hardcodes `claude-sonnet-4-6` in `_call_anthropic()`. Offer scoring needs `claude-haiku-4-5-20251001` for cost efficiency. Before offer scoring ships:

```python
# Add to LLMGateway.generate() signature:
async def generate(self, ..., model: str | None = None) -> str:
    # If model specified, override provider default
```

This is a gateway change that must land before `offer_scoring_service.py` is written.

### Rate limiting — new paths

Add to `_LLM_PATHS` in `rate_limit.py`:
```python
"/api/v1/vault/offer/evaluate",
"/api/v1/vault/offer/negotiate",
"/api/v1/vault/stories/match",
"/api/v1/vault/portal/scan",  # Wellfound uses LLM; other boards are pure HTTP
```

### Structured logging pattern

Follow existing convention — log on every request with `user_id`, key metrics, and latency:
```python
logger.info(f"[offer_eval] user={user.id} grade={grade} score={score:.1f} cached={cached}")
logger.info(f"[story_match] user={user.id} stories_matched={n} jd_chars={len(jd_text)}")
logger.info(f"[portal_scan] user={user.id} board={board_type} cached={cached} latency_ms={ms}")
```

### Ownership validation (all write endpoints)

Explicitly required: every `DELETE`, `PATCH`, and read-by-ID endpoint must verify `record.user_id == current_user.id`. The `GET /vault/stories` list query must include `WHERE user_id = :current_user_id`. This applies to all five new routers without exception.

---

## 10. Vault Router Registration

```python
# vault/__init__.py additions
from app.routers.vault.offer import router as offer_router
from app.routers.vault.stories import router as stories_router
from app.routers.vault.portal import router as portal_router

router.include_router(offer_router)
router.include_router(stories_router)
router.include_router(portal_router)
```

No route ordering conflicts with existing paths. The `sys.modules` test patching pattern is in sub-modules (`generate.py`, `answers.py`), not in `__init__.py` itself — adding new routers here creates zero additional test complexity.

---

## 11. Testing Strategy

| Test file | What it covers |
|---|---|
| `tests/test_offer_scoring_service.py` | Formula scoring per dimension; Haiku mock for sponsorship; grade thresholds; standalone unavailable degradation; `resume_id` resolution logic; idempotency on hash collision |
| `tests/test_story_bank.py` | CRUD routes; match algorithm ranking; inline quality score; `use_count` increment; bulk import from Profile JSON; ownership verification on delete; interview.py story injection |
| `tests/test_portal_scanner.py` | Board detection regex; Greenhouse/Lever mock responses via `pytest-httpx`; cache hit/miss; `is_stale` refresh; unsupported board returns `manual_entry: true`; Ashby list iteration |
| `tests/test_standalone_bugs.py` | Three bug fixes in `tailor-resume-work/web_app/routes/resume.py` |
| `tests/test_vault_router_registration.py` | `GET /api/v1/vault/stories` returns 401 (not 404) — proves router is wired |
| `tests/test_models_registered.py` | `"story_entries"`, `"offer_evaluations"`, `"portal_scan_cache"` present in `Base.metadata.tables` |

**New test dependency:** `pytest-httpx` for mocking `httpx` calls in portal scanner tests. Not currently in `pyproject.toml` — add it.

**LLM calls:** All mocked via `monkeypatch` — no API keys in CI.

---

## 12. Recommended Slice Order (PDD — ship value earliest)

| Slice | Feature | Why this order | Dependencies |
|---|---|---|---|
| 1 | Story Bank (§5) | Pure CRUD + deterministic match. Zero external APIs. Unblocks `interview.py` enhancement. Day-one interactive value. | None |
| 2 | Offer Scoring (§4) | 7/8 dimensions are formula-only. H1B `sponsorship_likelihood` has outsized personal value. Depends on `story_entries` table existing (for story-grounded recommendations, optional). | LLMGateway `model` param (§9) |
| 3 | Portal Scanner (§7) | Enables offer scoring to accept `portal_scan_id` instead of raw JD paste. | None beyond DB migration |
| 4 | Standalone fixes + thin endpoints (§3) | Fixes `role_match` HTTP call from offer scoring; enables bulk story import via `/resume/parse`. | tailor-resume-work fixes |
| v2 | Negotiation Scripts (§6) | Low frequency until Naren is at offer stage. No migration needed when ready. | Offer scoring (for context) |

---

## 13. Success KPIs

The spec previously had no measurable success criteria. These 5 KPIs determine whether the system improves Naren's job search outcomes:

| KPI | Definition | Target |
|---|---|---|
| **Sponsorship false positive rate** | % of roles graded "likely sponsors" (score ≥ 70) that upon manual/recruiter verification do not sponsor H1B | < 20% within 30 days |
| **Story bank coverage** | % of 10 signal categories with ≥ 2 stories at `quality_score ≥ 0.7` | ≥ 80% (8/10 domains) within 2 weeks of onboarding |
| **Grade vs. response rate** | % of Grade A/B applications that generate any recruiter response vs. C/D/F | A/B produces ≥ 2× response rate within 60 days |
| **Time to application** | Median time from portal scan cache hit to application submission for Greenhouse/Lever roles | < 20 min (vs. pre-feature baseline) |
| **Story reuse rate** | % of stories with `use_count ≥ 3` within 30 days | ≥ 40% — measures whether bank is functioning as reusable asset |

---

## 14. Open Decisions (must resolve before implementation plan)

These questions have no answer in the current spec. Resolve them before writing the implementation plan:

| # | Question | Options | Recommended |
|---|---|---|---|
| 1 | How does autoapply-ai access `jd_gap_analyzer`/`star_validator`? | (a) vendor inline, (b) HTTP to standalone, (c) shared package | **(a) vendor inline for v1** — lowest friction, documented in §2 |
| 2 | Which resume does `role_match` score against when `resume_id` is omitted? | Most recent upload / user-designated default / skip dimension | **Most recent upload; skip if none** |
| 3 | Is `POST /offer/evaluate` idempotent on `jd_text_hash`? | Return cached / always new row / `?refresh=true` toggle | **Idempotent; `?refresh=true` for force re-run** — documented in §4 |
| 4 | Does negotiation use the user's provider cascade or always Anthropic? | Always Anthropic / provider cascade like `interview.py` | **Provider cascade** — consistent with existing pattern |
| 5 | Wellfound in v1? | Defer / httpx + haiku / Playwright | **Defer to v2; stub as `manual_entry: true`** — documented in §7 |
| 6 | Portal scanner Chrome extension integration — in v1 scope? | In-scope / separate ticket | **Separate ticket** — documented in §7 |
| 7 | `GapReport` field names for Bug 3 fix? | Verify against `resume_types.py` before writing | **Verify before implementation** — `GapReport.keyword_gaps` vs `GapReport.kw_gaps` differs across script versions |

---

## 15. Out of Scope

- Workday portal scanner (Goldman, JP Morgan, Citadel, Microsoft — requires auth session, no public API)
- LinkedIn portal scanner (requires auth)
- PDF compilation in the standalone (users use Overleaf or local pdflatex)
- Real-time streaming of any LLM response
- Multi-user story bank sharing
- System design prep (different artifact type from STAR narratives — future spec)
- `tailor.py` fire-and-forget story extraction (requires extension UI — separate ticket)
- Stage tracker / application funnel outcome tracking (high value, separate spec)
- Company-level H1B intelligence from DOL OFLC data (high value, separate data pipeline)
