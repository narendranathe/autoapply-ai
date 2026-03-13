// Typed API client — talks to the FastAPI backend (URL configurable via options page)

import type { ATSScoreResult, ResumeCard } from "./types";

const API_DEFAULT = "https://autoapply-ai-api.fly.dev/api/v1";

// Resolved at startup from chrome.storage; falls back to localhost for dev.
let _apiBase = API_DEFAULT;
let _clerkUserId: string | null = null;
let _clerkToken: string | null = null;     // RS256 JWT from Clerk session
let _clerkTokenExp: number = 0;            // expiry unix timestamp (seconds)

// Single promise that resolves once storage has been read.
let _initPromise: Promise<void> | null = null;

function ensureInit(): Promise<void> {
  if (!_initPromise) {
    _initPromise = chrome.storage.local
      .get(["apiBaseUrl", "clerkUserId", "clerkToken", "clerkTokenExp"])
      .then((data) => {
        if (data.apiBaseUrl) _apiBase = data.apiBaseUrl as string;
        if (data.clerkUserId) _clerkUserId = data.clerkUserId as string;
        if (data.clerkToken) _clerkToken = data.clerkToken as string;
        if (data.clerkTokenExp) _clerkTokenExp = data.clerkTokenExp as number;
      });
  }
  return _initPromise;
}

// Keep in sync with storage changes after init.
chrome.storage.onChanged.addListener((changes) => {
  if (changes.apiBaseUrl?.newValue) _apiBase = changes.apiBaseUrl.newValue as string;
  if (changes.apiBaseUrl && !changes.apiBaseUrl.newValue) _apiBase = API_DEFAULT;
  if (changes.clerkUserId?.newValue) _clerkUserId = changes.clerkUserId.newValue as string;
  if (changes.clerkToken?.newValue) _clerkToken = changes.clerkToken.newValue as string;
  if (changes.clerkTokenExp?.newValue) _clerkTokenExp = changes.clerkTokenExp.newValue as number;
});

function getApiBase(): string {
  return _apiBase;
}

// ── Auth token ─────────────────────────────────────────────────────────────
// Set once when the user signs in via Clerk. Sent on every request so the
// backend can resolve the authenticated user.

export function setClerkUserId(id: string | null) {
  _clerkUserId = id;
  if (id) {
    chrome.storage.local.set({ clerkUserId: id });
  } else {
    chrome.storage.local.remove("clerkUserId");
  }
}

/**
 * Store a Clerk RS256 JWT for use as Authorization: Bearer.
 * exp is the JWT expiry unix timestamp (seconds); pass 0 to clear.
 */
export function setClerkToken(token: string | null, exp = 0) {
  _clerkToken = token;
  _clerkTokenExp = exp;
  if (token) {
    chrome.storage.local.set({ clerkToken: token, clerkTokenExp: exp });
  } else {
    chrome.storage.local.remove(["clerkToken", "clerkTokenExp"]);
  }
}

/** Whether the stored JWT is still valid (with 30-second buffer). */
export function isClerkTokenValid(): boolean {
  if (!_clerkToken) return false;
  if (_clerkTokenExp === 0) return true;  // no expiry known — assume valid
  return Date.now() / 1000 < _clerkTokenExp - 30;
}

/** Restore auth state from storage on extension startup. */
export async function restoreClerkUserId(): Promise<void> {
  const data = await chrome.storage.local.get(["clerkUserId", "clerkToken", "clerkTokenExp"]);
  if (data.clerkUserId) _clerkUserId = data.clerkUserId as string;
  if (data.clerkToken) _clerkToken = data.clerkToken as string;
  if (data.clerkTokenExp) _clerkTokenExp = data.clerkTokenExp as number;
}

function authHeaders(): Record<string, string> {
  // Prefer JWT Bearer token (RS256, verified by backend JWKS) over plain user ID
  if (_clerkToken && isClerkTokenValid()) {
    return { "Authorization": `Bearer ${_clerkToken}` };
  }
  return _clerkUserId ? { "X-Clerk-User-Id": _clerkUserId } : {};
}

// ── HTTP helpers ───────────────────────────────────────────────────────────

async function post<T>(path: string, body: FormData | Record<string, unknown>): Promise<T> {
  await ensureInit();
  const isForm = body instanceof FormData;
  const resp = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: isForm
      ? authHeaders()
      : { "Content-Type": "application/json", ...authHeaders() },
    body: isForm ? body : JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`API ${path} failed (${resp.status}): ${err}`);
  }
  return resp.json() as Promise<T>;
}

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  await ensureInit();
  const url = new URL(`${getApiBase()}${path}`);
  if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const resp = await fetch(url.toString(), { headers: authHeaders() });
  if (!resp.ok) throw new Error(`API GET ${path} failed (${resp.status})`);
  return resp.json() as Promise<T>;
}

async function patch<T>(path: string, body: FormData): Promise<T> {
  await ensureInit();
  const resp = await fetch(`${getApiBase()}${path}`, {
    method: "PATCH",
    headers: authHeaders(),
    body,
  });
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`API PATCH ${path} failed (${resp.status}): ${err}`);
  }
  return resp.json() as Promise<T>;
}

async function patchJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  await ensureInit();
  const resp = await fetch(`${getApiBase()}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`API PATCH ${path} failed (${resp.status}): ${err}`);
  }
  return resp.json() as Promise<T>;
}

// ── Response types ─────────────────────────────────────────────────────────

export interface RetrieveResponse {
  company_history: ResumeCard[];
  best_match: ResumeCard | null;
  positioning_summary: string | null;
  reuse_recommendation: "reuse" | "tweak" | "generate_new";
  ats_result: ATSScoreResult | null;
}

export interface AnswerResponse {
  drafts: string[];
  draft_providers?: string[];   // parallel to drafts — which LLM generated each
  previously_used: string | null;
  previously_used_at: string | null;
  question_category: string;
}

export interface SaveAnswerResponse {
  answer_id: string;
  word_count: number;
  question_hash: string;
  saved: boolean;
}

export interface SimilarAnswer {
  answer_id: string;
  question_text: string;
  answer_text: string;
  company_name: string;
  question_category: string;
  reward_score: number | null;
  feedback: string;
  word_count: number;
  created_at: string;
}

export interface SimilarAnswersResponse {
  answers: SimilarAnswer[];
  total: number;
}

export interface ResumeListResponse {
  items: Array<{
    resume_id: string;
    filename: string;
    version_tag: string | null;
    target_company: string | null;
    target_role: string | null;
    ats_score: number | null;
    bullet_count: number;
    is_base_template: boolean;
    is_generated: boolean;
    github_path: string | null;
    created_at: string;
  }>;
  page: number;
  per_page: number;
}

export interface GenerateResumeResponse {
  resume_id: string;
  version_tag: string;
  recruiter_filename: string;
  latex_content: string;
  markdown_preview: string;
  ats_score_estimate: number | null;
  skills_gap: string[];
  changes_summary: string;
  llm_provider_used: string;
  warnings: string[];
}

export interface InterviewQuestion {
  question: string;
  category: "behavioral" | "motivation" | "technical" | "general";
  suggested_answer: string;
}

export interface GenerateTailoredResponse {
  resume_id: string;
  version_tag: string;
  markdown_preview: string;
  ats_score_estimate: number | null;
  ats_score_before: number | null;
  skills_gap: string[];
  changes_summary: string;
  llm_provider_used: string;
  warnings: string[];
}

// ── Vault endpoints ────────────────────────────────────────────────────────

export const vaultApi = {
  /** Semantic retrieval: find past resumes for a company + JD */
  retrieve(companyName: string, jdText?: string): Promise<RetrieveResponse> {
    const fd = new FormData();
    fd.append("company_name", companyName);
    if (jdText) fd.append("jd_text", jdText);
    return post("/vault/retrieve", fd);
  },

  /** ATS score: score a stored resume against a JD */
  atsScore(jdText: string, resumeId?: string, resumeText?: string): Promise<ATSScoreResult> {
    const fd = new FormData();
    fd.append("jd_text", jdText);
    if (resumeId) fd.append("resume_id", resumeId);
    if (resumeText) fd.append("resume_text", resumeText);
    return post("/vault/ats-score", fd);
  },

  /** Generate answer drafts — all enabled providers run in parallel */
  generateAnswers(params: {
    questionText: string;
    questionCategory: string;
    companyName: string;
    roleTitle: string;
    jdText: string;
    workHistoryText: string;
    maxLength?: number;    // textarea character limit — passed to LLM to respect
    categoryInstructions?: string;  // per-category style instructions from settings
    providers?: Array<{ name: string; apiKey: string; model?: string }>;
    // legacy single-provider fallback
    llmProvider?: string;
    llmApiKey?: string;
    ollamaModel?: string;
  }): Promise<AnswerResponse> {
    const fd = new FormData();
    fd.append("question_text", params.questionText);
    fd.append("question_category", params.questionCategory);
    fd.append("company_name", params.companyName);
    fd.append("role_title", params.roleTitle);
    fd.append("jd_text", params.jdText);
    fd.append("work_history_text", params.workHistoryText);
    if (params.maxLength) fd.append("max_length", String(params.maxLength));
    if (params.categoryInstructions) fd.append("category_instructions", params.categoryInstructions);
    if (params.providers && params.providers.length > 0) {
      fd.append("providers_json", JSON.stringify(
        params.providers.map((p) => ({ name: p.name, api_key: p.apiKey, model: p.model ?? "" }))
      ));
    } else {
      if (params.llmProvider) fd.append("llm_provider", params.llmProvider);
      if (params.llmApiKey) fd.append("llm_api_key", params.llmApiKey);
      if (params.ollamaModel) fd.append("ollama_model", params.ollamaModel);
    }
    return post("/vault/generate/answers", fd);
  },

  /** Save accepted answer */
  saveAnswer(params: {
    questionText: string;
    questionCategory: string;
    answerText: string;
    companyName: string;
    roleTitle?: string;
    jobId?: string;
    wasDefault?: boolean;
    llmProviderUsed?: string;
  }): Promise<SaveAnswerResponse> {
    const fd = new FormData();
    fd.append("question_text", params.questionText);
    fd.append("question_category", params.questionCategory);
    fd.append("answer_text", params.answerText);
    fd.append("company_name", params.companyName);
    if (params.roleTitle) fd.append("role_title", params.roleTitle);
    if (params.jobId) fd.append("job_id", params.jobId);
    fd.append("was_default", params.wasDefault ? "true" : "false");
    if (params.llmProviderUsed) fd.append("llm_provider_used", params.llmProviderUsed);
    return post("/vault/answers/save", fd);
  },

  /** Record outcome of a generated answer (RL reward signal) */
  recordFeedback(params: {
    answerId: string;
    feedback: "used_as_is" | "edited" | "regenerated" | "skipped";
    editedAnswer?: string;
  }): Promise<{ answer_id: string; feedback: string; reward_score: number; edit_distance: number }> {
    const fd = new FormData();
    fd.append("feedback", params.feedback);
    if (params.editedAnswer) fd.append("edited_answer", params.editedAnswer);
    return patch(`/vault/answers/${params.answerId}/feedback`, fd);
  },

  /** Find best past answers for a question category (bandit policy) */
  getSimilarAnswers(params: {
    questionText: string;
    questionCategory: string;
    topK?: number;
  }): Promise<SimilarAnswersResponse> {
    const p = new URLSearchParams({
      question_text: params.questionText,
      question_category: params.questionCategory,
      top_k: String(params.topK ?? 3),
    });
    return get(`/vault/answers/similar?${p.toString()}`);
  },

  /** All resumes and answers for a company (recruiter callback reference) */
  companyHistory(companyName: string): Promise<{ company: string; resumes: ResumeCard[]; answers: unknown[] }> {
    return get(`/vault/history/${encodeURIComponent(companyName)}`);
  },

  /** List all resumes in vault */
  listResumes(company?: string): Promise<ResumeListResponse> {
    return get("/vault/resumes", company ? { company } : undefined);
  },

  /** Upload a resume file to the vault from the sidepanel */
  uploadResume(params: {
    file: File;
    targetCompany?: string;
    targetRole?: string;
    isBaseTemplate?: boolean;
  }): Promise<{
    resume_id: string;
    filename: string;
    file_type: string;
    bullet_count: number;
    skills_detected: string[];
    version_tag: string | null;
    parse_warnings: string[];
  }> {
    const fd = new FormData();
    fd.append("file", params.file, params.file.name);
    if (params.targetCompany) fd.append("target_company", params.targetCompany);
    if (params.targetRole) fd.append("target_role", params.targetRole);
    fd.append("is_base_template", params.isBaseTemplate ? "true" : "false");
    return post("/vault/upload", fd);
  },

  /** Get a single resume with full content */
  getResume(resumeId: string): Promise<{
    resume_id: string;
    filename: string;
    version_tag: string | null;
    target_company: string | null;
    target_role: string | null;
    ats_score: number | null;
    bullet_count: number;
    is_base_template: boolean;
    is_generated: boolean;
    github_path: string | null;
    latex_content: string | null;
    markdown_content: string | null;
    raw_text: string | null;
    created_at: string;
  }> {
    return get(`/vault/resumes/${resumeId}`);
  },

  /** Delete a resume from the vault */
  deleteResume(resumeId: string): Promise<void> {
    return ensureInit().then(() =>
      fetch(`${getApiBase()}/vault/resumes/${resumeId}`, {
        method: "DELETE",
        headers: authHeaders(),
      }).then(() => undefined)
    );
  },

  /** Generate a tailored resume from an existing vault resume + JD context */
  generateTailored(params: {
    baseResumeId: string;
    jdText: string;
    companyName: string;
    roleTitle?: string;
    providers?: Array<{ name: string; apiKey: string; model?: string }>;
  }): Promise<GenerateTailoredResponse> {
    const fd = new FormData();
    fd.append("base_resume_id", params.baseResumeId);
    fd.append("jd_text", params.jdText);
    fd.append("company_name", params.companyName);
    if (params.roleTitle) fd.append("role_title", params.roleTitle);
    if (params.providers?.length) {
      fd.append("providers_json", JSON.stringify(
        params.providers.map((p) => ({ name: p.name, api_key: p.apiKey, model: p.model ?? "" }))
      ));
    }
    return post("/vault/generate/tailored", fd);
  },

  /** T3: Generate 10 likely interview questions + suggested answers for a role */
  interviewPrep(params: {
    companyName: string;
    roleTitle?: string;
    jdText?: string;
    providers?: Array<{ name: string; apiKey: string; model?: string }>;
  }): Promise<{ questions: InterviewQuestion[]; total: number }> {
    const fd = new FormData();
    fd.append("company_name", params.companyName);
    if (params.roleTitle) fd.append("role_title", params.roleTitle);
    if (params.jdText) fd.append("jd_text", params.jdText);
    if (params.providers?.length) {
      fd.append("providers_json", JSON.stringify(
        params.providers.map((p) => ({ name: p.name, api_key: p.apiKey, model: p.model ?? "" }))
      ));
    }
    return post("/vault/interview-prep", fd);
  },

  /** Generate cover letter drafts — one per provider, parallel execution */
  generateCoverLetter(params: {
    companyName: string;
    roleTitle?: string;
    jdText?: string;
    tone?: "professional" | "enthusiastic" | "concise" | "conversational";
    wordLimit?: number;
    candidateName?: string;
    providers?: Array<{ name: string; apiKey: string; model?: string }>;
  }): Promise<{ drafts: string[]; draft_providers: string[]; tone: string; word_limit: number }> {
    const fd = new FormData();
    fd.append("company_name", params.companyName);
    if (params.roleTitle) fd.append("role_title", params.roleTitle);
    if (params.jdText) fd.append("jd_text", params.jdText);
    if (params.tone) fd.append("tone", params.tone);
    if (params.wordLimit) fd.append("word_limit", String(params.wordLimit));
    if (params.candidateName) fd.append("candidate_name", params.candidateName);
    if (params.providers?.length) {
      fd.append("providers_json", JSON.stringify(
        params.providers.map((p) => ({ name: p.name, api_key: p.apiKey, model: p.model ?? "" }))
      ));
    }
    return post("/vault/generate/cover-letter", fd);
  },

  /** List saved cover letters, optionally filtered by company */
  listCoverLetters(company?: string, limit?: number): Promise<{
    items: Array<{
      id: string;
      company_name: string;
      role_title: string | null;
      answer_text: string;
      word_count: number;
      reward_score: number | null;
      llm_provider_used: string | null;
      created_at: string;
    }>;
    total: number;
  }> {
    const params: Record<string, string> = {};
    if (company) params.company = company;
    if (limit) params.limit = String(limit);
    return get("/vault/cover-letters", params);
  },

  /** Shorten an answer draft to fit within a character limit */
  trimAnswer(params: {
    answerText: string;
    maxChars: number;
    providers?: Array<{ name: string; apiKey: string; model?: string }>;
  }): Promise<{ trimmed: string; char_count: number; provider_used: string }> {
    const fd = new FormData();
    fd.append("answer_text", params.answerText);
    fd.append("max_chars", String(params.maxChars));
    if (params.providers?.length) {
      fd.append("providers_json", JSON.stringify(
        params.providers.map((p) => ({ name: p.name, api_key: p.apiKey, model: p.model ?? "" }))
      ));
    }
    return post("/vault/generate/answers/trim", fd);
  },

  /** Generate a 2-4 sentence professional summary tailored to a role */
  generateSummary(params: {
    companyName: string;
    roleTitle: string;
    jdText: string;
    wordLimit?: number;
    candidateName?: string;
    providers?: Array<{ name: string; apiKey: string; model?: string }>;
  }): Promise<{ summary: string; provider_used: string; word_count: number }> {
    const fd = new FormData();
    fd.append("company_name", params.companyName);
    fd.append("role_title", params.roleTitle);
    fd.append("jd_text", params.jdText);
    if (params.wordLimit != null) fd.append("word_limit", String(params.wordLimit));
    if (params.candidateName) fd.append("candidate_name", params.candidateName);
    if (params.providers?.length) {
      fd.append("providers_json", JSON.stringify(
        params.providers.map((p) => ({ name: p.name, api_key: p.apiKey, model: p.model ?? "" }))
      ));
    }
    return post("/vault/generate/summary", fd);
  },

  /** Generate XYZ-formula resume bullets for a specific role */
  generateBullets(params: {
    companyName: string;
    roleTitle: string;
    jdText: string;
    numBullets?: number;
    targetCompany?: string;
    providers?: Array<{ name: string; apiKey: string; model?: string }>;
  }): Promise<{ bullets: string[]; provider_used: string; count: number }> {
    const fd = new FormData();
    fd.append("company_name", params.companyName);
    fd.append("role_title", params.roleTitle);
    fd.append("jd_text", params.jdText);
    if (params.numBullets != null) fd.append("num_bullets", String(params.numBullets));
    if (params.targetCompany) fd.append("target_company_for_context", params.targetCompany);
    if (params.providers?.length) {
      fd.append("providers_json", JSON.stringify(
        params.providers.map((p) => ({ name: p.name, api_key: p.apiKey, model: p.model ?? "" }))
      ));
    }
    return post("/vault/generate/bullets", fd);
  },

  /** Get per-user vault analytics: answer stats, reward scores, top companies */
  getAnalytics(): Promise<{
    answers: {
      total: number;
      avg_reward_score: number | null;
      feedback_distribution: Record<string, number>;
      by_category: Record<string, { count: number; avg_reward: number | null; acceptance_rate: number | null }>;
    };
    resumes: { total: number; unique_companies: number };
    top_companies_by_answers: Array<{ company: string; answer_count: number }>;
  }> {
    return get("/vault/analytics");
  },
};

// ── Application Tracking API ────────────────────────────────────────────────

export interface TrackedApplication {
  id: string;
  company_name: string;
  role_title: string;
  job_url: string | null;
  platform: string | null;
  status: string;
  created_at: string;
  similarity_score: number | null;
  changes_summary: string | null;
  rewrite_strategy: string | null;
  notes: string | null;
}

export const applicationsApi = {
  /**
   * Upsert a lightweight "discovered" record when Apply Mode activates.
   * Idempotent — safe to call on every page load.
   */
  track(params: {
    companyName: string;
    roleTitle: string;
    jobUrl?: string;
    platform?: string;
  }): Promise<{ application_id: string; status: string; created: boolean }> {
    return post("/applications/track", {
      company_name: params.companyName,
      role_title: params.roleTitle,
      job_url: params.jobUrl ?? null,
      platform: params.platform ?? null,
    });
  },

  /** List all applications, optionally filtered by company */
  list(company?: string): Promise<{ items: TrackedApplication[]; total: number }> {
    return get("/applications", company ? { company } : undefined);
  },

  /** Update status of an application */
  updateStatus(applicationId: string, status: string): Promise<{ id: string; status: string }> {
    return patchJson(`/applications/${applicationId}`, { status });
  },

  /** Update (or clear) notes on an application */
  updateNotes(applicationId: string, notes: string | null): Promise<{ id: string; notes: string | null }> {
    return patchJson(`/applications/${applicationId}/notes`, { notes });
  },

  /** Get application statistics */
  getStats(): Promise<{ total: number; by_status: Record<string, number>; unique_companies: number }> {
    return get("/applications/stats");
  },
};

// ── Work History types ──────────────────────────────────────────────────────

export interface WorkHistoryEntry {
  id: string;
  entry_type: string;
  company_name: string;
  role_title: string;
  start_date: string;
  end_date: string | null;
  is_current: boolean;
  location: string | null;
  bullets: string[];
  technologies: string[];
  team_size: number | null;
  sort_order: number;
  created_at: string;
}

export interface WorkHistoryListResponse {
  entries: WorkHistoryEntry[];
  total: number;
}

export interface WorkHistoryTextResponse {
  text: string;
  entry_count: number;
}

export interface WorkHistoryEntryIn {
  entry_type?: string;
  company_name: string;
  role_title: string;
  start_date: string;
  end_date?: string;
  is_current?: boolean;
  location?: string;
  bullets?: string[];
  technologies?: string[];
  team_size?: number;
  sort_order?: number;
}

// ── Work History API ────────────────────────────────────────────────────────

export const workHistoryApi = {
  list(): Promise<WorkHistoryListResponse> {
    return get("/work-history");
  },

  getText(): Promise<WorkHistoryTextResponse> {
    return get("/work-history/text");
  },

  create(entry: WorkHistoryEntryIn): Promise<{ id: string; created: boolean }> {
    return post("/work-history", entry as unknown as Record<string, unknown>);
  },

  async update(entryId: string, entry: Partial<WorkHistoryEntryIn>): Promise<{ id: string; updated: boolean }> {
    await ensureInit();
    const resp = await fetch(`${getApiBase()}/work-history/${entryId}`, {
      method: "PATCH",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(entry),
    });
    return resp.json();
  },

  async delete(entryId: string): Promise<void> {
    await ensureInit();
    await fetch(`${getApiBase()}/work-history/${entryId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
  },

  importFromResume(
    file: File,
    providers?: Array<{ name: string; apiKey: string; model?: string }>
  ): Promise<{
    created: number;
    skipped: number;
    total_extracted: number;
    provider_used: string;
    detected_profile: Partial<{
      firstName: string; lastName: string; email: string; phone: string;
      linkedinUrl: string; githubUrl: string; portfolioUrl: string;
    }>;
  }> {
    const fd = new FormData();
    fd.append("file", file, file.name);
    if (providers?.length) {
      fd.append("providers_json", JSON.stringify(
        providers.map((p) => ({ name: p.name, api_key: p.apiKey, model: p.model ?? "" }))
      ));
    }
    return post("/work-history/import-from-resume", fd);
  },
};
