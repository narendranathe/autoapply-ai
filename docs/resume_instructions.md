# Resume Construction Rules & Theory
<!-- This file is the grounding context for all LLM resume generation prompts.
     It contains ONLY rules and theory — zero personal data. -->

## Core Principles

### Single Page Rule
Always produce a single-page resume. Length is not a badge of experience — clarity is.
Being clear and succinct are key. Every line must earn its place.

### The XYZ Formula
When in doubt, use: **"Accomplished [X] as measured by [Y], by doing [Z]."**
- X = the outcome or achievement
- Y = the quantitative measure of success
- Z = the action or method used

### Alignment with Job Description
- Align skills and experience directly with the job description
- Tie your work directly to the role qualifications
- Include data wherever possible (percentages, dollar amounts, counts, ratios)

### Minimum Qualifications (MQs)
- Ensure the resume clearly demonstrates alignment with every MQ for the role
- If you meet a MQ, it must be explicitly visible in the resume — do not assume the reader will infer it

---

## Section-by-Section Rules

### Professional Summary (4-5 sentences)
1. Make it engaging — highlight a unique value proposition
2. Incorporate 3-4 key terms from the JD naturally (not stuffed)
3. Reflect quantified impact from past experience
4. End with a forward-looking statement about contributing to the company

### Experience Bullets
- Lead with strong action verbs
- Quantify achievements wherever possible (e.g., "Increased sales by 30%")
- Be specific about projects: what was the outcome? how was success measured?
- Limit to 4-6 bullets per role
- For leadership roles: include team size and scope of work
- Use first-person implied (no "I")

### Career Progression
- Show growth — not just titles, but advancements within companies
- Explain level changes that demonstrate ambition and adaptability
- Use standard, recognizable job titles (e.g., "Software Engineer" not "Technical Staff Engineer")
- Each role should show trajectory, not just activity

### Projects
- Be specific about what was built and why
- Include outcomes and measurements
- Show technical depth relevant to the target role

### Skills Section
- Do NOT keyword-stuff the skills section
- Integrate keywords naturally into bullets where they make contextual sense
- Only list skills you can speak to confidently in an interview
- Group logically (Languages & ML, Data & Cloud, Tools, etc.)

---

## ATS Optimization Rules

### Keywords
- Include core keywords from the JD **in context**, not as a bare list
- Natural integration > keyword stuffing
- ATS parses context too — shallow keyword drops can hurt more than help

### Formatting
- Use standard section headers (Education, Experience, Projects, Skills)
- Bold job titles and company names
- Use standard fonts (no decorative fonts)
- Consistent date formats (e.g., Jan. 2022 — Dec. 2023)
- No tables, text boxes, headers/footers that ATS cannot parse
- Use ATS-parsable LaTeX or clean DOCX — avoid multi-column layouts

### Red Flags to Address
- Employment gaps: address subtly with freelance work, projects, or education
- Title mismatch: align internal title to standard industry equivalent
- Generic bullets: replace with specific, quantified achievements

---

## Skills Gap Analysis Framework

When analyzing a JD against a resume, identify:
1. **Top 5 missing skills/responsibilities** from the JD not represented in the resume
2. For each gap, suggest 1-2 specific, quantifiable achievements from existing experience that could be adapted
3. Output in bullet-point format with action verbs

## Tailored Bullet Point Rules

When rewriting experience bullets:
1. Incorporate relevant JD keywords naturally
2. Start every bullet with a strong action verb
3. Quantify achievements where possible
4. Keep language professional, concise, and first-person implied
5. Limit to 4-6 bullets per role

---

## Company Research Integration

Before generating a resume for a specific company:
- Align language with the company's known values and voice
- Reflect understanding of the company's recent achievements or mission
- Echo the JD's specific phrasing where authentic

---

## 2026 Data Engineer Resume Standards

### Phase 1: Software Craftsmanship
Show engineering rigor — not just Python syntax:
- Modular, testable code (Pytest, CI/CD, GitHub Actions)
- Containerization for reproducibility (Docker)
- Resilience patterns: retries, idempotency, schema drift handling
- Quantify: incident reduction %, deployment frequency improvement

**Keywords that signal real engineering:**
`unit tests, integration tests, CI/CD, Docker, error handling, retries, idempotency, backoff, dead-letter queues, incident reduction, audit readiness`

### Phase 2: AI Infrastructure & Semantic Layers
Show platform thinking, not AI tool usage:
- Governed semantic layer / metrics definitions (single source of truth)
- Standardized business logic in the warehouse/lakehouse
- Workload isolation to protect production from training compute
- LLM-ready, curated datasets

**Keywords:**
`semantic layer, governed metrics, workload isolation, schema drift, backward compatibility, retrieval-ready datasets, LLM-ready metrics`

### Phase 3: Architecture & FinOps
Defend trade-offs — strategy beats syntax:
- Architecture decisions tied to business needs (latency, freshness, cost)
- Concrete cost/performance wins (dollar savings, % compute reduction)
- Deep Spark performance literacy if listing Spark (partitioning, shuffle, broadcast joins)
- Open table formats: Delta Lake, Iceberg

**Keywords:**
`FinOps, cost optimization, TCO, partitioning, compaction, Delta Lake, Iceberg, RBAC, lineage, governance`

### Phase 4: Orchestration & Data Quality
Production ownership, not hobby DAGs:
- Dependency management, retries, backfills, SLAs
- Data contracts, schema enforcement, observability
- Monitoring: freshness, volume, null rates, anomaly detection

**Keywords:**
`Airflow, Dagster, Databricks Jobs, DAGs, backfills, SLAs, data contracts, schema enforcement, observability, Monte Carlo, Great Expectations`

---

## Resume Checklist

Before finalizing any generated resume, verify:
- [ ] At least 2-4 bullets demonstrate testing + CI/CD
- [ ] At least 2 bullets show reliability (resilience, schema drift, incident reduction)
- [ ] At least 1-2 bullets show architecture trade-offs with cost reasoning
- [ ] If Spark is listed: performance concepts are backed by examples
- [ ] Orchestration shown in production context (not just listing tool names)
- [ ] Data quality and observability implementation is demonstrated
- [ ] Semantic layer / metrics consistency work is present (for AI readiness roles)
- [ ] Every bullet is quantified or has a concrete outcome
- [ ] Single page — no exceptions
- [ ] Summary is 4-5 sentences and ends with a forward-looking statement
- [ ] No vague claims without metrics ("optimized pipelines" → give the %)

---

## Anti-Patterns (Never Do)

- Vague claims without metrics: "optimized pipelines", "improved performance"
- Listing many tools without a story of impact
- AI buzzwords without platform fundamentals (quality, governance, cost, reliability)
- Keyword stuffing in skills section
- Responsibilities without outcomes
- Team leadership without team size or scope
- Projects without outcomes or measurements
- Generic professional summary that could apply to anyone
