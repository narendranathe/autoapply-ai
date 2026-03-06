// Typed API client — talks to the FastAPI backend (URL configurable via options page)

import type { ATSScoreResult, ResumeCard } from "./types";

const API_DEFAULT = "http://localhost:8000/api/v1";

// Resolved at startup from chrome.storage; falls back to localhost for dev.
let _apiBase = API_DEFAULT;
let _clerkUserId: string | null = null;

// Single promise that resolves once storage has been read.
let _initPromise: Promise<void> | null = null;

function ensureInit(): Promise<void> {
  if (!_initPromise) {
    _initPromise = chrome.storage.local
      .get(["apiBaseUrl", "clerkUserId"])
      .then((data) => {
        if (data.apiBaseUrl) _apiBase = data.apiBaseUrl as string;
        if (data.clerkUserId) _clerkUserId = data.clerkUserId as string;
      });
  }
  return _initPromise;
}

// Keep in sync with storage changes after init.
chrome.storage.onChanged.addListener((changes) => {
  if (changes.apiBaseUrl?.newValue) _apiBase = changes.apiBaseUrl.newValue as string;
  if (changes.apiBaseUrl && !changes.apiBaseUrl.newValue) _apiBase = API_DEFAULT;
  if (changes.clerkUserId?.newValue) _clerkUserId = changes.clerkUserId.newValue as string;
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

/** Restore the Clerk user ID from storage on extension startup. */
export async function restoreClerkUserId(): Promise<void> {
  const { clerkUserId } = await chrome.storage.local.get("clerkUserId");
  if (clerkUserId) _clerkUserId = clerkUserId as string;
}

function authHeaders(): Record<string, string> {
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

  /** Generate answer drafts for an open-ended question */
  generateAnswers(params: {
    questionText: string;
    questionCategory: string;
    companyName: string;
    roleTitle: string;
    jdText: string;
    workHistoryText: string;
    llmProvider?: string;
    llmApiKey?: string;
  }): Promise<AnswerResponse> {
    const fd = new FormData();
    fd.append("question_text", params.questionText);
    fd.append("question_category", params.questionCategory);
    fd.append("company_name", params.companyName);
    fd.append("role_title", params.roleTitle);
    fd.append("jd_text", params.jdText);
    fd.append("work_history_text", params.workHistoryText);
    if (params.llmProvider) fd.append("llm_provider", params.llmProvider);
    if (params.llmApiKey) fd.append("llm_api_key", params.llmApiKey);
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
    return post("/work-history", entry);
  },

  async delete(entryId: string): Promise<void> {
    await ensureInit();
    await fetch(`${getApiBase()}/work-history/${entryId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
  },
};
