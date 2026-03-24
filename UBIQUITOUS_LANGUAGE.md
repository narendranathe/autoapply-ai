# Ubiquitous Language — AutoApply AI

> Domain-Driven Design glossary for the AutoApply AI codebase.
> Every term used in code, conversations, and docs should match exactly what's written here.
> When multiple words exist for the same concept, the **canonical term** is in bold — aliases are listed to avoid.

---

## 1. Core Entities

| Canonical Term | Definition | Aliases to Avoid |
|---|---|---|
| **Application** | A record representing one job application attempt by a User at a specific company/role. Created automatically when the extension detects a job page. | job, submission, entry |
| **Resume** | A stored document (LaTeX source + rendered PDF) in the Vault, associated with a target company and role. | CV, document, file |
| **ApplicationAnswer** | A saved response to a specific open-ended question on a job application, tied to a User and optionally a company. | answer, saved answer, Q&A entry |
| **WorkHistoryEntry** | A structured record of past employment or education (title, company, dates, bullets). | job entry, experience, past job |
| **User** | An authenticated person using AutoApply AI, identified by a Clerk ID and stored in the `users` table. | account, member, person |
| **UserProviderConfig** | A User's stored LLM provider credentials (provider name, encrypted API key, preferred model). | provider settings, LLM config, API key config |
| **DocumentChunk** | A paragraph-sized piece of text extracted from a Resume or WorkHistoryEntry, stored with an embedding vector for RAG retrieval. | chunk, text fragment, passage |

---

## 2. Application Status Lifecycle

Status values flow in this order. Only forward transitions are valid in normal operation.

```
discovered → draft → tailored → applied → phone_screen → interview → offer
                                        ↘ rejected (from any stage)
```

| Status | Definition |
|---|---|
| `discovered` | User visited the job page; no resume selected yet. |
| `draft` | A resume has been selected but not yet tailored to the JD. |
| `tailored` | The resume has been rewritten by the LLM for this specific JD. |
| `applied` | The application was submitted (detected via `APPLICATION_SUBMITTED` message). |
| `phone_screen` | A recruiter screening call has been scheduled or completed. |
| `interview` | The candidate is in the interview loop. |
| `offer` | An offer has been received. |
| `rejected` | The application was rejected at any stage. |

---

## 3. Question Categories

Used to classify open-ended application questions and route them to the right prompt template.

| Category | What it covers |
|---|---|
| `cover_letter` | Free-form cover letter field |
| `why_company` | Why do you want to work here? |
| `why_hire` | Why should we hire you? |
| `about_yourself` | Tell me about yourself |
| `strength` | What is your greatest strength? |
| `weakness` | What is your greatest weakness? |
| `challenge` | Describe a challenge you overcame |
| `leadership` | Describe a leadership experience |
| `conflict` | Describe a conflict and how you resolved it |
| `motivation` | What motivates you? |
| `five_years` | Where do you see yourself in 5 years? |
| `impact` | Describe your most impactful project or contribution |
| `fit` | Why are you a good fit for this role? |
| `sponsorship` | Do you require visa sponsorship? |
| `custom` | Any question that doesn't match the above |

---

## 4. LLM Providers & Generation

| Canonical Term | Definition | Aliases to Avoid |
|---|---|---|
| **Provider** | An LLM service that generates answers or resumes. One of: `anthropic`, `openai`, `kimi`, `groq`, `gemini`, `ollama`, `fallback`. | model, service, AI |
| **Fallback** | Keyword-based answer generation used when all LLM providers fail or are unconfigured. | default, backup |
| **providers_json** | The JSON array of ordered providers passed per-request, each with `provider`, `api_key`, `model`, `enabled`. Tried in order until one succeeds. | provider list, config array |
| **CategoryModelRoute** | A per-category override that maps a question category to a preferred provider. Stored in `chrome.storage.local` as `categoryModelRoutes`. | category routing, per-question LLM |
| **RewriteStrategy** | How aggressively the LLM rewrites a resume bullet. One of: `slight_tweak`, `moderate`, `ground_up`. | rewrite mode, edit level |

### Rewrite Strategy Definitions

| Strategy | Behavior |
|---|---|
| `slight_tweak` | Swap 1–3 keywords; preserve original phrasing |
| `moderate` | Restructure sentences; lead with JD-relevant action verbs |
| `ground_up` | Significantly rephrase while keeping all facts true |

---

## 5. The Vault

The Vault is the central storage system for Resumes, ApplicationAnswers, and cover letters. It has two sub-systems:

| Canonical Term | Definition | Aliases to Avoid |
|---|---|---|
| **Vault** | The collection of all stored Resumes and ApplicationAnswers for a User. | library, storage, bank |
| **Resume Vault** | The subset of the Vault containing Resume documents. | resume library, resume bank |
| **Answer Vault** | The subset of the Vault containing ApplicationAnswers. | answer bank, saved answers, Q&A vault |
| **Base Template** | A User-uploaded resume (`is_base_template=true`) used as the foundation for generated resumes. | master resume, original resume |
| **Generated Resume** | A resume created by the LLM tailoring pipeline (`is_generated=true`). | tailored resume, AI resume |
| **version_tag** | Internal Git tag for a Resume in GitHub (e.g., `Narendranath_Google_DE`). | git tag, version |
| **recruiter_filename** | Human-readable download name for a Resume (e.g., `FirstName_LastName.pdf`). | display name, file name |
| **file_hash** | SHA-256 of the Resume file bytes, used for deduplication. | checksum, hash |

---

## 6. ATS Scoring

ATS = Applicant Tracking System. The ATS score estimates how well a Resume will pass automated screening.

| Canonical Term | Definition |
|---|---|
| **ATS Score** | Float 0.0–1.0 estimating resume compatibility with a specific JD. ≥0.95 = best match (green in UI). |
| **keyword_coverage** | Percentage of JD keywords present in the resume. |
| **skills_gap** | List of skills required by the JD that are absent from the resume. |
| **skills_present** | List of JD skills found in the resume. |
| **quantification_score** | Percentage of bullet points that include measurable metrics. |
| **experience_alignment** | How well the candidate's experience level matches the role's requirements. |
| **mq_coverage** | Must-have qualification coverage — ratio of required qualifications met. |
| **suggestions** | Actionable LLM-generated improvements to raise the ATS score. |

---

## 7. RAG (Retrieval-Augmented Generation)

| Canonical Term | Definition | Aliases to Avoid |
|---|---|---|
| **RAG** | The pattern of injecting retrieved document chunks into LLM prompts to ground answers in the User's actual history. | context injection, memory |
| **rag_context** | The assembled string of retrieved DocumentChunks injected into a prompt. | context, background |
| **embedding_vector** | Dense float array representation of text for similarity search. | embedding, vector, encoding |
| **tfidf_vector** | Sparse TF-IDF vector for fast keyword-based similarity (fallback when no embedding model configured). | tf-idf, sparse vector |
| **top_k** | Number of highest-ranked DocumentChunks retrieved per query. | k, limit, count |
| **similarity_score** | Cosine similarity (0.0–1.0) between query and a DocumentChunk. | score, distance, relevance |
| **ResumeAST** | Abstract Syntax Tree — structured parsed representation of a resume's sections, bullets, and metadata. | parsed resume, resume structure |

---

## 8. Feedback & Reinforcement Learning

The RL layer improves answer quality over time using explicit User feedback signals.

| Canonical Term | Definition | Reward |
|---|---|---|
| **Feedback** | User's explicit signal on an ApplicationAnswer after seeing it. | — |
| `used_as_is` | Answer accepted without any edits. | 1.0 |
| `edited` | Answer was kept but modified before use. | 0.4–0.8 |
| `regenerated` | Answer was discarded; user asked for new drafts. | 0.2 |
| `skipped` | Answer was ignored entirely. | 0.0 |
| `pending` | No feedback received yet (default). | — |
| **reward_score** | Float 0.0–1.0 stored on ApplicationAnswer after feedback. Higher = better. | — |
| **avg_reward_score** | Mean reward across all answers in the Vault. Surfaced in Vault analytics. | — |

---

## 9. Extension Architecture

| Canonical Term | Definition | Aliases to Avoid |
|---|---|---|
| **Floating Panel** | The overlay UI injected into job application pages via a content script, using Shadow DOM isolation. Shows ATS score, Resume suggestions, and Q&A autofill. | popup, overlay, widget |
| **Sidepanel** | Chrome's native side panel showing tabs for Apply Mode, Job Scout, and Answers. | sidebar, drawer |
| **Apply Mode** | The Sidepanel state when the extension detects an active job application page. | application mode, fill mode |
| **Job Scout** | The Sidepanel tab for analyzing job fit, scoring JDs, and discovering roles. | scout mode, job search |
| **Mode** | The current extension state: `idle`, `scout`, or `apply`. | state, status |
| **Platform** | The job board or ATS where a job application is hosted (e.g., `linkedin`, `greenhouse`, `lever`, `workday`, `indeed`). | site, board, ATS |
| **PageContext** | Metadata extracted from the current job page: company, role, platform, JD text, detected fields, detected questions. | page state, job context |
| **DetectedField** | A form field identified on the page, with its type, current value, and suggested fill value. | field, form field, input |
| **DetectedQuestion** | An open-ended text question identified on the page, with its category and character limit. | question, essay field |
| **labelHash** | djb2 hash of a normalized field label, used to deduplicate fields across DOM re-renders. | field id, hash |
| **confidence** | Float 0.0–1.0 indicating how certain the detector is about a field's type or a question's category. | certainty, score |
| **Offline Queue** | A list of pending sync operations stored in `chrome.storage.local` when the User is offline. Drained when connectivity resumes. | queue, pending edits |

---

## 10. Storage Keys (`chrome.storage.local`)

| Key | Contents |
|---|---|
| `clerkUserId` | Authenticated User's Clerk ID |
| `apiBaseUrl` | Backend API base URL |
| `providerConfigs` | Array of UserProviderConfig objects |
| `profile` | User's personal profile fields |
| `promptTemplates` | Custom per-category prompt overrides |
| `categoryModelRoutes` | Per-category preferred provider mapping |
| `categoryUsage` | Count of questions seen per category (drives pre-generation) |
| `offline_queue` | Array of pending OfflineEdit sync jobs |

---

## 11. Application Funnel Metrics

| Canonical Term | Definition |
|---|---|
| **Funnel** | The progression of Applications through status stages, visualized as a funnel chart. |
| **response_rate_pct** | `(interview_count + offer_count) / applied_count` — how often applications get a response. |
| **offer_rate_pct** | `offer_count / non_discovered_count` — how often applications convert to offers. |
| **daily_volume_30d** | Number of applications tracked per day over the last 30 days. |

---

## 12. Auth & Security

| Canonical Term | Definition | Aliases to Avoid |
|---|---|---|
| **Clerk** | The authentication provider. Issues RS256 JWTs. The User's `clerk_id` is the primary user identifier across the system. | auth, login provider |
| **X-Clerk-User-Id** | HTTP header carrying the User's Clerk ID, used as the primary auth mechanism from the extension. | user header, auth header |
| **Fernet** | Symmetric encryption scheme (AES-128-CBC + HMAC) used to encrypt API keys and GitHub tokens at rest. | encryption, cipher |
| **JWKS** | JSON Web Key Set — Clerk's public keys used by the backend to verify RS256 JWTs. | public key, JWT key |
| **ENVIRONMENT** | Deployment context: `development`, `staging`, `production`, or `test`. Controls auth strictness, CORS, and dev fallbacks. | env, stage |

---

## 13. GitHub Vault Integration

| Canonical Term | Definition |
|---|---|
| **Resume Vault Repo** | A User's GitHub repository (default name: `resume-vault`) where generated resumes are committed as `.tex` and `.md` files. |
| **github_path** | Path of a Resume file within the Resume Vault Repo (e.g., `resumes/Narendranath_Google_DE.tex`). |
| **github_commit_sha** | Git commit SHA of the most recent push of a Resume to GitHub. |
| **encrypted_github_token** | The User's GitHub Personal Access Token, encrypted with Fernet before storage. |

---

## 14. Flagged Ambiguities

| Ambiguous Term | Resolution |
|---|---|
| "score" | Always qualify: **ATS score** (resume-to-JD fit), **similarity_score** (vector distance), **reward_score** (RL feedback), **confidence** (field detection). Never use "score" alone. |
| "provider" | Means LLM provider (`anthropic`, `openai`, etc.) — not job board/platform. Use **platform** for the job site. |
| "vault" | Unqualified "vault" = the entire storage system. Use **Resume Vault** or **Answer Vault** when referring to a specific sub-collection. |
| "answer" | Use **ApplicationAnswer** for the stored entity. Use "draft" for unaccepted LLM output before the User accepts it. |
| "mode" | Extension mode (`idle`/`scout`/`apply`) vs. Apply Mode (the Sidepanel tab). Context usually disambiguates; be explicit when not. |
| "generate" | Use **tailor** for adapting an existing resume to a JD. Use **generate** only for creating content from scratch (bullets, summary, cover letter). |
| "template" | Use **Base Template** for the user-uploaded master resume. Never call a generated resume a template. |

---

## 15. Example Dialogue Using Canonical Terms

> **Engineer**: The User opened LinkedIn, the extension switched to **Apply Mode** and the **FloatingPanel** appeared.
>
> **PM**: Did the **PageContext** pick up the JD text?
>
> **Engineer**: Yes — **platform** detected as `linkedin`, **jd_text** extracted. The **ATS score** came back 0.87 against the Base Template.
>
> **PM**: Not high enough. Did the tailoring pipeline run?
>
> **Engineer**: The User clicked tailor — the `moderate` **RewriteStrategy** ran, produced a **Generated Resume** with ATS score 0.96. It got the green "Best Match" border in the panel.
>
> **PM**: Good. What about the open-ended questions?
>
> **Engineer**: Two **DetectedQuestions** — categories `why_company` and `challenge`. The `anthropic` **Provider** generated three drafts each. User accepted the first `why_company` draft unchanged — **Feedback** recorded as `used_as_is`, **reward_score** = 1.0. Edited the `challenge` answer — `edited`, reward 0.6.
>
> **PM**: And the **Application** status?
>
> **Engineer**: Set to `tailored` when the resume was generated, then `applied` when the `APPLICATION_SUBMITTED` message fired from the content script.

---

*Last updated: 2026-03-23. To update: edit `UBIQUITOUS_LANGUAGE.md` and commit.*
