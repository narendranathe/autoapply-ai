// Typed API client — talks to the FastAPI backend at localhost:8000

const API_BASE = "http://localhost:8000/api/v1";

async function post<T>(path: string, body: FormData | Record<string, unknown>): Promise<T> {
  const isForm = body instanceof FormData;
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: isForm ? undefined : { "Content-Type": "application/json" },
    body: isForm ? body : JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`API ${path} failed (${resp.status}): ${err}`);
  }
  return resp.json() as Promise<T>;
}

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const resp = await fetch(url.toString());
  if (!resp.ok) throw new Error(`API GET ${path} failed (${resp.status})`);
  return resp.json() as Promise<T>;
}

// ── Vault endpoints ────────────────────────────────────────────────────────

export interface RetrieveResponse {
  company_history: unknown[];
  best_match: unknown | null;
  positioning_summary: string | null;
  reuse_recommendation: string;
  ats_result: unknown | null;
}

export const vaultApi = {
  /** Semantic retrieval: find past resumes for a company + JD */
  retrieve(companyName: string, jdText?: string): Promise<RetrieveResponse> {
    const fd = new FormData();
    fd.append("company_name", companyName);
    if (jdText) fd.append("jd_text", jdText);
    return post("/vault/retrieve", fd);
  },

  /** ATS score: score a stored resume against a JD */
  atsScore(jdText: string, resumeId?: string, resumeText?: string): Promise<unknown> {
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
  }): Promise<{ drafts: string[]; previously_used: string | null }> {
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
  }): Promise<{ answer_id: string; saved: boolean }> {
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

  /** All resumes and answers for a company (recruiter callback reference) */
  companyHistory(companyName: string): Promise<unknown> {
    return get(`/vault/history/${encodeURIComponent(companyName)}`);
  },

  /** List all resumes in vault */
  listResumes(company?: string): Promise<{ items: unknown[] }> {
    return get("/vault/resumes", company ? { company } : undefined);
  },
};
