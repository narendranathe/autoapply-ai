# Narendranath Edara — Personal Resume Data

**Senior AI Platform Engineer · Applied AI Systems · LLM Infrastructure**

Dallas, TX · edara.narendranath@gmail.com · (573) 466-6656
[LinkedIn](https://linkedin.com/in/narendranathe) · [GitHub](https://github.com/narendranathe) · [Portfolio](https://narendranathe.github.io) · [Substack](https://narendranathe.substack.com)

> PRIVATE — gitignored. Single source of truth for all resume versions.
> Claude uses this for semantic search when building tailored resumes.
> Mirrored at: autoapply-ai/resume-personal.md
> Instructions guide (public): resume.md

---

## Profile

AI platform engineer building production LLM systems, retrieval pipelines, and governed AI-enabled data products. At ExponentHR I led enterprise data platform modernization across ETL, CI/CD, database automation, and analytics delivery supporting 400 enterprise clients. Outside work I shipped AutoApply AI and tailor-resume across FastAPI backends, Chrome extensions, RAG, multi-provider model routing, packaging, CI, and live deployments. I design and ship production AI systems, not just prototypes. Targeting Senior AI Platform Engineer, Applied AI Engineer, Backend Engineer, AI, and ML Platform Engineer roles. Requires H1B transfer sponsorship.

---

## Technical Skills

**Languages & AI:** Python, SQL, T-SQL, TypeScript, PySpark, Bash, RAG, LLM Integration, Vector Search, Model Routing, Prompt/Context Engineering, Evaluation Loops
**Platforms & Data:** FastAPI, PostgreSQL, pgvector, Kafka, Spark, Databricks, SQL Server, Supabase, Redis, ETL/ELT, Data Modeling, Azure (AKS, DevOps), AWS (S3, EC2), Docker, Kubernetes
**Product & Infrastructure:** React, Chrome MV3, Streamlit, MLflow, CI/CD (GitHub Actions, Azure DevOps), Prometheus, Grafana, Swagger/OpenAPI, Claude API, MCP Servers

---

## Professional Experience

### Data Engineer
**ExponentHR** · Dallas, TX · Jul 2024 – Present

*Enterprise HR/payroll data platform. Own data infrastructure, deployment pipelines, and developer tooling across multi-tenant SQL Server environments.*

- **Built and deployed an Azure DevOps-driven database copy-down automation framework** for Contained Always-On Availability Groups, automating the full lifecycle: restore, security configuration, recovery model switch to FULL, AAG listener registration, and CDC instance setup — eliminated ~1 hour of manual IT effort per request across 20+ daily database refresh requests from dev, test, and business validation teams, turning a multi-step ops process into a single parameterized pipeline trigger.
- **Compressed deployment cycles from 3 months to 14 days** by implementing Scrum sprints, aligning four cross-functional teams (dev/test/IT/business), and owning end-to-end CI/CD through Azure DevOps — the bottleneck was handoffs between teams, not code; restructuring the process removed 11 weeks of waiting.
- **Reengineered CDC-based SSIS ETL pipelines** from full-table reloads to incremental change capture, reducing nightly batch runtime from ~30 minutes to under 8 minutes and cutting SQL Server compute costs by roughly 67% — the key was switching from `TRUNCATE → INSERT` to CDC log-based extraction with merge upserts, which eliminates full-table I/O overhead and unnecessary data shuffling across the payroll schema.
- **Owned production recovery for payroll-critical databases** using containerized AAG failover, maintaining 98% uptime SLA with sub-hour restore targets — this included diagnosing and resolving CDC capture job failures caused by missing SQL Agent jobs after failover events.

*Technologies: SQL Server, T-SQL, SSIS/CDC, Azure DevOps, Contained AAG, CI/CD, Python*

### Data Engineer
**Missouri S&T** · Rolla, MO · Aug 2023 – Jul 2024

*Research and production ML systems during Master's program. Built cloud-native anomaly detection services and published peer-reviewed NLP research.*

- **Engineered Azure AI Anomaly Detector pipelines** selecting optimal algorithms per time-series profile (seasonality, trend, noise), achieving 95%+ detection accuracy and enabling proactive alerting before application failures surfaced — the system caught a production memory leak 4 hours before it would have caused an outage.
- **Implemented tunable sensitivity thresholds per monitored service** that filtered out ~250 weekly non-actionable P3 alerts, moving the signal-to-noise ratio from 1:5 to 1:1.2 — this effectively ended "alert blindness" during on-call rotations and restored team trust in the anomaly detection system.
- **Migrated anomaly detection from static D-Series VMs to AKS with HPA** (Horizontal Pod Autoscaler), increasing average CPU utilization from 12% to 64% — consolidated the workload from 20 dedicated nodes to a dynamic 4–8 node cluster, cutting monthly Azure spend by $3,200 while maintaining 99.9% availability.
- **Published peer-reviewed research** on sentiment analysis as a visitor feedback tool — compared VADER lexicon vs. RoBERTa transformers on Yelp/TripAdvisor review data, with TF-IDF feature extraction, PCA, and clustering (K-Means, DBSCAN) for strategic segmentation (Journal of Nonprofit & Public Sector Marketing, Taylor & Francis, 2025).

*Technologies: Azure AI, AKS, Kubernetes, Python, Hugging Face, NLTK, spaCy, REST APIs, Docker*

### Engineering Intern
**C2FO** · Leawood, KS · Jun 2023 – Aug 2023

- **Analyzed financial transaction patterns using SQL** across millions of supplier payment records to identify adoption friction points — findings shaped the product roadmap for the next two quarters.
- **Authored data-driven PRDs** that linked user segmentation to feature prioritization, cutting the product team's planning cycle in half by replacing anecdotal prioritization with transaction-backed evidence.

*Technologies: SQL, Product Analytics, Data-Driven PRDs*

### Business Intelligence Analyst · Supply
**udaan.com** · India · Sep 2020 – Mar 2021

- **Built demand forecasting models** for inventory allocation across regional warehouses — contributed to ~$4M in annualized savings by reducing dead inventory and emergency restocking.
- **Drove fulfillment rate to 99.3%** through statistical capacity planning across first-mile to last-mile operations.
- **Developed ETL pipelines feeding Power BI dashboards** for finance and operations teams, replacing weekly manual Excel consolidation with automated daily refreshes.

*Technologies: Python, SQL, Power BI, Forecasting Models, ETL, Statistical Modeling*

### Business Analyst
**Zomato** · Hyderabad, India · Mar 2018 – Sep 2020

- **Designed a real-time competitor analytics platform** that tracked pricing, delivery times, and restaurant coverage — data fed pricing strategy changes contributing to a 9% market share gain in contested metro markets.
- **Optimized search relevance** by building ranking models incorporating contextual signals (time of day, location, cuisine affinity, past orders) — improved search-to-conversion across millions of daily queries.
- **Built an Elasticsearch-powered enterprise search engine** indexing 100K+ internal documents with intelligent ranking — reduced Support Desk ticket volume by ~80%.
- **Awarded "Meal for One Champion"** for contributions to solo-order growth through targeted discount strategy analysis and A/B-tested campaign optimization.

*Technologies: Elasticsearch, SQL, Ranking Models, A/B Testing, Real-time Analytics, Python*

---

## Featured Projects

### AutoApply AI — AI-Powered Job Application Platform
**Live:** [autoapply-ai-api.fly.dev](https://autoapply-ai-api.fly.dev) · Chrome MV3 Extension · Supabase + Upstash Redis · **Stack:** FastAPI + Claude Sonnet + PostgreSQL

- Production AI platform with FastAPI backend, Chrome MV3 extension, React dashboard, Supabase PostgreSQL, and Upstash Redis — 40+ endpoints, 11 ATS adapters, and 355+ backend tests across resume tailoring, Q&A generation, vault search, and application tracking
- Multi-provider routing layer (Claude Sonnet → GPT-4o → Gemini → Groq → Kimi → Ollama → keyword fallback) grounds generations in pgvector + TF-IDF retrieval, persists feedback with a reward layer, and supports live job-page autofill through a Shadow DOM UI

### tailor-resume — Resume Tailoring Engine, MCP Server, and PyPI Package
**GitHub:** [narendranathe/tailor-resume](https://github.com/narendranathe/tailor-resume) · **Live:** Streamlit + Fly.io · **PyPI:** `tailor-resume`

- Built a developer-facing applied AI tool with four surfaces — CLI, Streamlit app, typed MCP server, and Python package — for ATS gap analysis, profile extraction, and LaTeX resume rendering
- Shipped a zero-config core pipeline with 190 tests, hosted MCP on Fly.io, packaged distribution via PyPI metadata, and clean interfaces for `extract_profile`, `analyze_gap`, `render_latex`, and `run_pipeline`

### Real-Time Fraud Detection ML Platform
- 100+ TPS, sub-ms P99 latency · Kafka + LightGBM + MLflow · Prometheus + Grafana · Airflow orchestration · Docker

---

## Education

**M.S. Information Science & Technology** — Missouri S&T — Jan 2022 – Dec 2023 — GPA: 4.0
**B.Tech Mechanical Engineering** — Gayatri Vidya Parishad College of Engineering, India — 2013–2017

---

## Certifications

- **DP-700:** Microsoft Fabric Data Engineer Associate (2026)
- **AI-900:** Azure AI Fundamentals (2024)
- **Databricks Generative AI Fundamentals** (2026)
- **Microsoft Applied Skills:** Data Warehouse in Microsoft Fabric
- **HackerRank:** SQL Advanced
- **Scrum Alliance:** Certified Scrum Product Owner (CSPO)
- **Publication:** "Sentiment Analysis for Visitor Feedback" — Taylor & Francis, 2025 — [DOI](https://doi.org/10.1080/10495142.2025.2525123)

---

## Positioning Notes

**Enterprise platform ownership.** ExponentHR is the anchor story for ETL modernization, CI/CD acceleration, database automation, and measurable operational impact across 400 clients.

**Applied AI product shipping.** AutoApply AI and tailor-resume prove I can ship user-facing AI systems end to end: backend APIs, model routing, retrieval, packaging, browser surfaces, persistence, CI, and production deployment.

**Operational depth.** My best systems combine AI with platform fundamentals: observability, cost control, fault tolerance, tests, and infrastructure choices that can survive production use.

---

## Resume Versions & Targeting

| Version Key | Target | Emphasis |
|-------------|--------|----------|
| `_AIP` / `_ai_platform` | AI Platform Engineer | LLM backends, retrieval/RAG, model routing, governance, observability |
| `_AAI` / `_applied_ai` | Applied AI Engineer | user-facing AI products, product integration, extension/dashboard surfaces |
| `_ML` / `_ml` | ML Platform / ML Engineer | MLflow, inference, streaming, monitoring, model deployment |
| `_DE` / `_data` | Data Platform / Senior Data Engineer | ETL/CDC, Spark/Kafka, platform architecture, data modeling |
| `_AE` / `_ae` | Analytics / Semantic Layer Engineer | metrics, governance, semantic models, BI modernization |
| `_GS` | Goldman Sachs | Quant/Finance DE focus |
| `_Amazon` | Amazon | Scale + reliability |
| `_{Company}_{Role}` | Company-specific | Full JD customization |
| `standard` | General | Narendranath.pdf fallback |

---

## Links

- **Portfolio:** https://narendranathe.github.io
- **GitHub:** https://github.com/narendranathe
- **LinkedIn:** https://linkedin.com/in/narendranathe
- **Substack:** https://narendranathe.substack.com
- **JobScout:** https://narendranathe.github.io/job-scout
- **Resume PDF:** https://github.com/narendranathe/resume2/releases/download/resume/Narendranath.pdf
- **Research DOI:** https://doi.org/10.1080/10495142.2025.2525123

---

## Full LaTeX Template

```latex
%-------------------------
% Resume in Latex
% Author : Narendranath Edara
% Based off of: https://github.com/narendranathe/resume2
% License : MIT
%------------------------

\documentclass[letterpaper,11pt]{article}

\usepackage{latexsym}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{marvosym}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}
\usepackage[english]{babel}
\usepackage{tabularx}
\input{glyphtounicode}

\pagestyle{fancy}
\fancyhf{}
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

\addtolength{\oddsidemargin}{-0.5in}
\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.5in}
\addtolength{\textheight}{1.0in}

\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}

\titleformat{\section}{
  \vspace{-4pt}\scshape\raggedright\large
}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]

\pdfgentounicode=1

\newcommand{\resumeItem}[1]{\item\small{{#1 \vspace{-2pt}}}}
\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}
\newcommand{\resumeSubSubheading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \textit{\small#1} & \textit{\small #2} \\
    \end{tabular*}\vspace{-7pt}
}
\newcommand{\resumeProjectHeading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \small#1 & #2 \\
    \end{tabular*}\vspace{-7pt}
}
\newcommand{\resumeSubItem}[1]{\resumeItem{#1}\vspace{-4pt}}
\renewcommand\labelitemii{$\vcenter{\hbox{\tiny$\bullet$}}$}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}

\begin{document}

\begin{center}
    \textbf{\Huge \scshape Narendranath Edara} \\ \vspace{1pt}
    \small +1 (573) 466-6656 $|$ \href{mailto:edara.narendranath@gmail.com}{\underline{edara.narendranath@gmail.com}} $|$
    \href{https://www.linkedin.com/in/narendranathe/}{\underline{linkedin.com/in/narendranathe}} $|$
    \href{https://narendranathe.github.io}{\underline{narendranathe.github.io}}
\end{center}

\section{Education}
  \resumeSubHeadingListStart
    \resumeSubheading
      {Missouri University of Science and Technology}{Rolla, MO}
      {Master of Science in Information Science and Technology}{Jan. 2022 -- Dec. 2023}
  \resumeSubHeadingListEnd

\section{Experience}
  \resumeSubHeadingListStart

    \resumeSubheading
      {Data Engineer}{July 2024 -- Present}
      {ExponentHR}{Dallas, TX}
      \resumeItemListStart
        \resumeItem{Built and deployed Azure DevOps--driven Contained AAG automation framework with parameterized restore, security, recovery-model, and CDC setup — eliminated \textasciitilde 1 hour of manual effort per request across 20+ daily database refreshes for dev, test, and business validation teams}
        \resumeItem{Compressed deployment cycles from 3 months to 14 days by owning CI/CD end-to-end through Azure DevOps and restructuring cross-team handoffs that accounted for 11 weeks of idle time}
        \resumeItem{Reengineered CDC-based ETL from full-table reloads to incremental change capture with merge upserts, cutting nightly batch runtime from \textasciitilde 30 minutes to under 8 minutes and reducing compute costs by \textasciitilde 67\%}
        \resumeItem{Owned production recovery for payroll-critical databases using containerized AAG failover, restoring CDC-dependent workloads with sub-hour targets and tighter operational playbooks}
      \resumeItemListEnd

    \resumeSubheading
      {Data Engineer}{Aug. 2023 -- July 2024}
      {Missouri S\&T}{Rolla, MO}
      \resumeItemListStart
        \resumeItem{Engineered Azure AI Anomaly Detector pipelines selecting optimal algorithms per time-series profile, achieving 95\%+ detection accuracy — caught a production memory leak 4 hours before it would have caused an outage}
        \resumeItem{Implemented tunable sensitivity thresholds per monitored service, filtering out \textasciitilde 250 weekly non-actionable P3 alerts and moving the signal-to-noise ratio from 1:5 to 1:1.2}
        \resumeItem{Migrated anomaly detection from static D-Series VMs to AKS with HPA, increasing average CPU utilization from 12\% to 64\% — consolidated from 20 nodes to a dynamic 4--8 node cluster, cutting monthly Azure spend by \$3,200 while maintaining 99.9\% availability}
      \resumeItemListEnd

    \resumeSubheading
      {Business Analyst}{Mar. 2018 -- Sept. 2020}
      {Zomato}{Hyderabad, India}
      \resumeItemListStart
        \resumeItem{Built real-time competitor analytics platform tracking pricing, delivery times, and coverage — data fed pricing strategy changes contributing to 9\% market share gain in contested metros}
        \resumeItem{Optimized search relevance with ranking models incorporating contextual signals (time, location, cuisine affinity), improving search-to-conversion across millions of daily queries}
        \resumeItem{Built Elasticsearch enterprise search indexing 100K+ internal documents with intelligent ranking, reducing Support Desk ticket volume by \textasciitilde 80\%}
      \resumeItemListEnd

  \resumeSubHeadingListEnd

\section{Projects}
    \resumeSubHeadingListStart
      \resumeProjectHeading
          {\textbf{Real-Time Fraud Detection Platform} $|$ \emph{PySpark, Kafka, Airflow, MLflow, Docker, Prometheus, Grafana}}{2026}
          \resumeItemListStart
            \resumeItem{Built streaming inference serving 100+ TPS with sub-ms latency using Kafka consumers and containerized LightGBM endpoints trained on 100K transactions with MLflow experiment tracking}
            \resumeItem{Implemented Prometheus + Grafana observability stack with Airflow-orchestrated training/inference pipelines in fully Dockerized infrastructure}
          \resumeItemListEnd
      \resumeProjectHeading
          {\textbf{Automated Portfolio Risk Analytics} $|$ \emph{Kafka, Spark Streaming, FastAPI, Docker, Streamlit}}{2025}
          \resumeItemListStart
            \resumeItem{Built Kafka + Spark Structured Streaming pipeline at 47.8 TPS processing 15K+ records with 5-second windowed VaR calculations (95\%/99\% confidence) served via FastAPI + Streamlit}
            \resumeItem{Designed one-command Docker Compose deployment covering Kafka, Spark, API, and dashboard infrastructure}
          \resumeItemListEnd
    \resumeSubHeadingListEnd

\section{Certifications \& Publications}
 \begin{itemize}[leftmargin=0.15in, label={}]
    \small{\item{
     \textbf{DP-700}{: Microsoft Certified Data Engineer Associate $|$} \textbf{Publication}{: Sentiment Analysis for Visitor Insights -- \href{https://doi.org/10.1080/10495142.2025.2525123}{\underline{DOI}}}
    }}
 \end{itemize}

\section{Technical Skills}
 \begin{itemize}[leftmargin=0.15in, label={}]
    \small{\item{
     \textbf{Languages \& ML}{: Python, SQL, Bash, MLflow, Airflow, Feature Engineering, Model Serving, LangChain, RAG} \\
     \textbf{Data \& Cloud}{: Spark, Kafka, Databricks, Delta Lake, PostgreSQL, SQL Server, ETL/ELT, Data Modeling, Azure (AKS, DevOps), AWS (S3), Docker, Kubernetes} \\
     \textbf{Tools}{: FastAPI, Streamlit, Elasticsearch, pgvector, Git, CI/CD, Prometheus, Grafana, Swagger/OpenAPI, Claude API} \\
    }}
 \end{itemize}

\end{document}
```

---

*Last updated: March 2026 · Resume Base v5*
