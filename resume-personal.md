# Narendranath Edara — Personal Resume Data

**Senior Data Engineer · ML Engineer · AI Platform Builder**

Dallas, TX · edara.narendranath@gmail.com · (573) 466-6656
[LinkedIn](https://linkedin.com/in/narendranathe) · [GitHub](https://github.com/narendranathe) · [Portfolio](https://narendranathe.github.io) · [Substack](https://narendranathe.substack.com)

> PRIVATE — gitignored. Single source of truth for all resume versions.
> Claude uses this for semantic search when building tailored resumes.
> Mirrored at: autoapply-ai/resume-personal.md
> Instructions guide (public): resume.md

---

## Profile

Data and ML Engineer with 4+ years building enterprise data platforms, streaming ML pipelines, and self-healing infrastructure. I shipped a CDC reengineering that cut ETL runtime from hours to minutes, compressed a 3-month deployment cycle to 14 days by owning CI/CD end-to-end, and built a zero-cost job discovery platform that scrapes 109 companies every 5 minutes on free-tier infrastructure. My systems monitor themselves, recover without pages, and expose governed metrics to both dashboards and AI agents. Open to Senior Data Engineer, ML Engineer, AI/ML Platform Engineer roles. Requires H1B transfer sponsorship.

---

## Technical Skills

**Languages & ML:** Python, SQL, T-SQL, PySpark, Bash, MLflow, Airflow, Feature Engineering, Model Serving, LangChain, RAG
**Data & Cloud:** Spark, Kafka, Databricks, Delta Lake, Snowflake, PostgreSQL, ETL/ELT, Data Modeling (Star Schema), Azure (AKS, DevOps, Data Factory), AWS (S3, EC2), Microsoft Fabric, Docker, Kubernetes
**Tools & Infrastructure:** FastAPI, Streamlit, Elasticsearch, Power BI, DAX, SSRS, Git, CI/CD (GitHub Actions, Azure DevOps), Prometheus, Grafana, Swagger/OpenAPI, MLflow

---

## Professional Experience

### Data Engineer
**ExponentHR** · Dallas, TX · Jul 2024 – Present

*Enterprise HR/payroll data platform. Own data infrastructure, deployment pipelines, AI analytics layer, and developer tooling across multi-tenant SQL Server environments.*

- **Architected AI-powered embedded analytics on Microsoft Fabric** by migrating legacy SQL reporting to DAX-based semantic models and building AI agents that translate natural-language business questions into optimized SQL — cut client-facing support tickets tied to report requests by ~40% and brought average query response from 12s down to under 4s across Power BI embedded dashboards.
- **Built and deployed an Azure DevOps–driven database copy-down automation framework** for Contained Always-On Availability Groups, automating the full lifecycle: restore, security configuration, recovery model switch to FULL, AAG listener registration, and CDC instance setup — eliminated ~1 hour of manual IT effort per request across 20+ daily database refresh requests from dev, test, and business validation teams, turning a multi-step ops process into a single parameterized pipeline trigger.
- **Compressed deployment cycles from 3 months to 14 days** by implementing Scrum sprints, aligning four cross-functional teams (dev/test/IT/business), and owning end-to-end CI/CD through Azure DevOps — the bottleneck was handoffs between teams, not code; restructuring the process removed 11 weeks of waiting.
- **Reengineered CDC-based SSIS ETL pipelines** from full-table reloads to incremental change capture, reducing nightly batch runtime from ~30 minutes to under 8 minutes and cutting SQL Server compute costs by roughly 67% — the key was switching from `TRUNCATE → INSERT` to CDC log-based extraction with merge upserts, which eliminates full-table I/O overhead and unnecessary data shuffling across the payroll schema.
- **Designed AI-driven sprint automation agents** integrating Git commit logs and Azure DevOps OData APIs to generate real-time velocity dashboards — replaced 15+ hours/sprint of manual status reporting with auto-generated burndown and deployment tracking.
- **Owned production recovery for payroll-critical databases** using containerized AAG failover, maintaining 98% uptime SLA with sub-hour restore targets — this included diagnosing and resolving CDC capture job failures caused by missing SQL Agent jobs after failover events.

*Technologies: SQL Server, T-SQL, SSIS/CDC, Azure DevOps, Microsoft Fabric, Power BI, DAX, SSRS, Contained AAG, CI/CD, AI Agents, Python*

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

### JobScout — Automated Job Discovery & Application Platform
**GitHub:** [narendranathe/job-scout](https://github.com/narendranathe/job-scout) · **Live:** Render + GitHub Pages · **Cost:** $0/month

- Scrapes 109 company career pages across 6 ATS platforms every 5 minutes via tiered scheduling
- Multi-signal relevance engine: core skills (40%) + secondary (20%) + title (15%) + location (10%) + experience (10%) + H1B (5%)
- 95+ tailored resume PDFs indexed with pure-Python TF-IDF — `find_best_resume_for_job()` ranks all resumes vs any JD
- Dream job alerts via Discord + Telegram when high-scoring role appears at target company
- Application tracker: saved → applied → interview → offer → rejected, synced localStorage + Render API
- **Architecture decisions:** Batch over streaming (jobs post hourly) · SQLite WAL over Postgres ($0) · TF-IDF over embeddings (pure Python) · GitHub Actions + Render free tier (~1,080 min/month)
- **Next phase (AutoApply AI):** Chrome MV3 extension + multi-LLM pipeline (Claude behavioral, GPT short, direct lookup factual) + PostgreSQL work history + Redis cache

### Real-Time Fraud Detection ML Platform
- 100+ TPS, sub-ms P99 latency · Kafka + LightGBM + MLflow · Prometheus + Grafana · Airflow orchestration · Docker

### Real-Time Portfolio Risk Analytics Platform
- 47.8 TPS · 15K+ records · <5s VaR latency · Kafka + Spark Structured Streaming + FastAPI + Streamlit

### Sentiment Analysis Research
- Published Taylor & Francis 2025 · VADER vs RoBERTa · 92% classification accuracy · TF-IDF + PCA + K-Means/DBSCAN

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

## Engineering Philosophy

**Self-Recovery Systems.** I design systems that detect, diagnose, and heal without human pages. At ExponentHR, the database copy-down automation tool handles 20+ daily requests end-to-end with a single parameterized pipeline trigger. Containerized AAG failover restores payroll databases in under an hour. In JobScout, dual-source data hooks keep the dashboard alive when the backend sleeps.

**Monitoring & Observability.** Prometheus + Grafana for ML platforms. Discord + Telegram for dream job detection. Dashboard monitor tabs for pipeline status. Every production system exposes its vitals.

**Platform Thinking.** Not pipelines — platforms. Semantic layers for dashboards and LLMs. TF-IDF vault indexing 95+ documents. Relevance engine scoring every job against multi-signal weights.

**Cost-Conscious Architecture.** $0/month for a 109-company scraper. CDC over full-table reload — 30min → 8min, 67% compute savings. Batch over streaming when the SLA allows.

**AI Infrastructure Over AI Buzzwords.** AI agents querying production SQL. LLM pipelines routing to the cheapest model meeting quality bar. Resume matching on TF-IDF, not black-box embeddings.

---

## Resume Versions & Targeting

| Version Key | Target | Emphasis |
|-------------|--------|----------|
| `_DE` / `_data` | Senior Data Engineer | ETL/CDC, Spark/Kafka, pipeline arch, data modeling |
| `_ML` / `_ml` | ML Engineer | MLflow, LightGBM, feature eng, model deployment |
| `_AI` / `_ai` | AI/ML Platform Engineer | LLM integration, RAG, AI agents, semantic layers |
| `_AE` / `_ae` | Analytics Engineer | dbt, Power BI, DAX, semantic models, data quality |
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
        \resumeItem{Architected AI-powered embedded analytics on Microsoft Fabric, migrating legacy SQL to DAX-based semantic models and building AI agents that translate business questions to optimized SQL — cut report-related support tickets by \textasciitilde 40\% and brought query response from 12s to under 4s}
        \resumeItem{Built and deployed Azure DevOps--driven Contained AAG automation framework with parameterized restore, security, recovery-model, and CDC setup — eliminated \textasciitilde 1 hour of manual effort per request across 20+ daily database refreshes for dev, test, and business validation teams}
        \resumeItem{Compressed deployment cycles from 3 months to 14 days by owning CI/CD end-to-end through Azure DevOps and restructuring cross-team handoffs that accounted for 11 weeks of idle time}
        \resumeItem{Reengineered CDC-based ETL from full-table reloads to incremental change capture with merge upserts, cutting nightly batch runtime from \textasciitilde 30 minutes to under 8 minutes and reducing compute costs by \textasciitilde 67\%}
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
     \textbf{Data \& Cloud}{: Spark, Kafka, Databricks, Delta Lake, PostgreSQL, ETL/ELT, Data Modeling, Azure (AKS, DevOps), AWS (S3), Microsoft Fabric, Docker, Kubernetes} \\
     \textbf{Tools}{: FastAPI, Streamlit, Elasticsearch, Power BI, DAX, Git, CI/CD, Prometheus, Grafana, Swagger/OpenAPI} \\
    }}
 \end{itemize}

\end{document}
```

---

*Last updated: March 2026 · Resume Base v5*
