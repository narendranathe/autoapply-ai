# JobScout — Resume Guide

How to build ATS-optimized resumes for data engineering, ML engineering, and
software engineering roles. Fork-friendly — replace all examples with your own experience.

---

## Resume Naming Conventions

Name your resume files with a role suffix so the tracker knows which version you used:

| Suffix | Role |
|--------|------|
| `_DE` or `_data` | Data Engineering |
| `_SWE` or `_SE` | Software Engineering |
| `_AE` | Analytics Engineer |
| `_AI` | AI Engineer |
| `_ML` | ML Engineer / MLOps |
| `standard` | General / Default |

Upload each variation via `POST /api/resume` with `{"resume_text": "...", "version": "_DE"}`.

---

## Core Principles

1. **Single page** — always
2. **Align with the JD** — every bullet ties to a role qualification
3. **Formula**: "Accomplished [X] as measured by [Y], by doing [Z]"
4. **Quantify everything** — %, TPS, hours saved, cost reduction, latency
5. **4-6 bullets per role** — concise over exhaustive
6. **ATS keywords**: embed naturally in context, not as bare lists
7. **Standard job titles** — align internal titles to common search terms
8. **Research the company** — echo culture/mission in your positioning

---

## Build Workflow

### Step 1 — Skills Gap Analysis
> "Analyze this JD and my resume. Identify the top 5 skills missing or weakly represented.
> For each, suggest 1-2 quantifiable achievements I could adapt. Use action verbs."

### Step 2 — Tailored Bullet Points
> "Rewrite my experience section to align with this JD. Use JD keywords naturally,
> start with strong action verbs, quantify where possible. Limit to 4-6 bullets per role."

### Step 3 — ATS Optimization
> "Optimize my resume for ATS compatibility with this JD. Keywords in context,
> consistent formatting, flag employment gaps and suggest subtle framing."

### Step 4 — Professional Summary
> "Write a 4-5 sentence summary based on this JD and my background.
> Highlight my unique value, incorporate 3-4 JD terms, end with a forward-looking statement."

---

## Positioning by Role Type

| Role | Lead With |
|------|-----------|
| Data Engineer | Python, Spark, Kafka, Airflow, ETL pipelines, cloud data platforms |
| Analytics Engineer | dbt, Snowflake, dimensional modeling, semantic layers, BI tools |
| ML Engineer | MLflow, feature engineering, model serving, MLOps, LangChain, RAG |
| Software Engineer | FastAPI, REST APIs, CI/CD, Docker, PostgreSQL, system design |

---

## LaTeX Template

Uses the Jake's Resume base format. Requires: `latexsym`, `fullpage`, `titlesec`,
`enumitem`, `hyperref`, `fancyhdr`, `tabularx`.

```latex
\documentclass[letterpaper,11pt]{article}
% ... (standard packages) ...

\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeProjectHeading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \small#1 & #2 \\
    \end{tabular*}\vspace{-7pt}
}
```

**Sections order**: Heading → Education → Experience → Projects → Certifications → Skills

**Skills format**: Comma-separated within category rows, not bullet lists.

```latex
\textbf{Languages \& ML}{: Python, SQL, Bash, MLflow, Airflow, LangChain, RAG} \\
\textbf{Data \& Cloud}{: Spark, Kafka, Databricks, Delta Lake, Azure, AWS, Docker} \\
\textbf{Tools}{: FastAPI, Streamlit, Power BI, Git, CI/CD, Elasticsearch} \\
```

Full template reference: [github.com/narendranathe/resume2](https://github.com/narendranathe/resume2)

---

## Profile Relevance Scoring

JobScout scores every job against your profile in `backend/config/profile.py`:

| Component | Weight |
|-----------|--------|
| Core skills match | 40% |
| Secondary skills match | 20% |
| Title relevance | 15% |
| Location preference | 10% |
| Experience level | 10% |
| Sponsorship signal | 5% |

Jobs below `min_score_threshold` (default `0.30`) are filtered out before storage.
Dream company alerts fire at `DREAM_ALERT_SCORE` (default `0.70`).

---

## What Gets Filtered Out

The scraper pre-filters titles before scoring. Excluded categories:
- Field operators, data entry, data collectors
- HR, recruiter, talent acquisition
- Sales, marketing, brand, social media
- Medical, clinical, healthcare
- Trades (HVAC, electrician, etc.)
- Customer support, retail, cashier
- Administrative, receptionist, coordinator

Only roles that combine a data/ML/AI signal **with** an engineering/technical context word pass through.

---

## 2026 Resume Expectations for Data Engineers

### Purpose

This page captures the 2026 resume expectations for a modern **data engineer** (increasingly a *software engineer specialized in data*) and translates them into *what to show on a resume*.

---

### Executive Summary (2026 signal)

In 2026, strong resumes show:

- **Software craftsmanship**, not just Python syntax.
- **Platform thinking**: reliability, testing, CI/CD, and operational maturity.
- **AI readiness** through *data platform robustness* (semantic layer, governance, workload isolation), not "random AI tools."
- **Architecture + FinOps**: defend trade-offs, cost awareness, and open table formats.
- **Orchestration + data quality** as non-negotiables (contracts, observability, guardrails).

---

### Phase 1: Software Craftsmanship Over Syntax

A 2026 data engineer is a **software engineer for data**. The bar is writing **robust, modular, testable code** that survives cloud outages, schema changes, and bad API responses without late-night firefighting.

Key roadmap: Testing (Pytest) · CI/CD (GitHub Actions, Databricks Asset Bundles) · Containerization (Docker)

**What to show on resume:**
- Modular Python packages for pipelines (clear interfaces, reusable components)
- Unit tests with quantified incident reduction
- CI/CD for data code (deployments, validations, automated tests)
- Containerized runtimes for dev-to-prod consistency
- Resilience for API failures and schema drift

**Keywords:** unit tests, integration tests, CI/CD, Docker, error handling, retries, idempotency, backoff, dead-letter queues, incident reduction, audit readiness

**Bullet templates:**
- "Built Pytest test suite + CI pipeline (GitHub Actions) for X pipelines, reducing production data defects by Y% and cutting on-call pages by Z."
- "Refactored monolithic ingestion job into modular components and added contract tests to handle schema drift with zero manual intervention."

---

### Phase 2: AI Infrastructure & Semantic Layers

AI projects fail mostly due to **engineering** (not math). The data engineer builds the plumbing that keeps AI alive: handle schema drift, isolate compute, own the semantic layer so metrics are consistent across dashboards, AI agents, and finance stakeholders.

**What to show:**
- Governed semantic layer / metrics definitions (single source of truth)
- Standardized business logic in the warehouse/lakehouse
- Workload isolation to protect production reporting
- Improved time-to-ship for DS/ML via data contracts and reliability

**Keywords:** semantic layer, governed metrics, workload isolation, schema drift handling, LLM-ready metrics, retrieval-ready datasets

**Bullet templates:**
- "Created governed metric definitions for X KPIs used by Finance + ML pipelines, reducing metric discrepancies from N to 0 across dashboards and models."
- "Isolated model-training workloads from BI queries using separate compute + priority policies, improving dashboard latency by X%."

---

### Phase 3: Architecture & Governance

Cloud cost is under audit. Storage is cheap, **compute is expensive**. Strategy beats syntax.

**What to show:**
- Architecture decisions tied to business needs (latency, freshness, cost)
- Concrete cost/performance wins
- Governance: access controls, lineage, documentation, standards
- Deep Spark performance literacy if you claim Spark (partitioning, shuffle, broadcast joins)

**Keywords:** FinOps, cost optimization, TCO, partitioning, pruning, Parquet, compaction, shuffle reduction, broadcast joins, Delta Lake, Iceberg, RBAC, auditability

**Bullet templates:**
- "Reduced warehouse compute cost by X% by rewriting joins, adding partitioning, and optimizing file layout."
- "Designed batch-first architecture for daily SLA use case, avoiding unnecessary streaming spend and saving ~$X/month."

---

### Phase 4: Orchestration & Data Quality

Cron jobs are not acceptable. Engineers need orchestration with dependencies, retries, backfills. Data quality is no longer optional — bad data can trigger automated AI actions with real consequences.

**What to show:**
- Production orchestration ownership (not hobby DAGs)
- Backfill strategy + idempotency + SLAs
- Data quality checks and incident prevention
- Monitoring: metrics, alerts, lineage, freshness, volume, null rates

**Keywords:** orchestration, DAGs, dependency management, backfills, SLAs/SLOs, data contracts, schema enforcement, data observability, Great Expectations, Monte Carlo

**Bullet templates:**
- "Implemented automated data validation suite (schema + freshness + volume), preventing X classes of incidents and improving trust in executive metrics."
- "Built backfill-safe pipelines with idempotent loads and automated retry policies, cutting recovery time from X hours to Y."

---

### Resume Checklist (quick scan)

**Must-have proof points:**
- [ ] 2–4 bullets demonstrating **testing + CI/CD**
- [ ] 2 bullets showing **reliability** (resilience, schema drift, incident reduction)
- [ ] 1–2 bullets showing **architecture trade-offs** with cost reasoning
- [ ] If listing Spark, can defend performance concepts with examples
- [ ] Orchestration ownership (Airflow/Dagster/Databricks Jobs) in production context
- [ ] Data quality and observability implementation (not just "care about quality")
- [ ] Semantic layer / metrics consistency work (especially for AI readiness)

**Red flags to remove:**
- Vague claims ("optimized pipelines", "improved performance") without metrics
- Listing many tools without a story of impact
- AI buzzwords without platform fundamentals (quality, governance, cost, reliability)

---

### Metrics & Evidence Bank (fill these in)

Use this section to draft numbers you can reuse in bullets.

- Cost savings: $___ /month or ___% compute reduction
- Reliability: ___% fewer incidents, ___ fewer on-call pages
- Latency: ___% faster dashboards / jobs
- Quality: ___% reduction in failed loads / data defects
- Delivery speed: models shipped in ___ days vs ___ weeks

---

### Google's Resume Formula

"Accomplished [X] as measured by [Y], by doing [Z]."

- Align skills and experience directly with job description qualifications
- Be specific: what was the outcome, how did you measure success
- One page — clear and succinct wins
- Show career progression and growth, not just titles
- Integrate keywords naturally into achievements, not as keyword-stuffed lists
- Use standard, recognizable job titles that recruiters search for
- Tailor each version to echo the company's values and role specifics
