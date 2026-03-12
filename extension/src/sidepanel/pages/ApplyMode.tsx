import React, { useEffect, useRef, useState } from "react";
import type { ATSScoreResult, PageContext, ResumeCard } from "../../shared/types";
import { applicationsApi, vaultApi, workHistoryApi, type RetrieveResponse, type SimilarAnswer, type TrackedApplication } from "../../shared/api";
import ATSScoreBar from "../components/ATSScoreBar";
import ResumeCardComponent from "../components/ResumeCard";

interface Props { context: PageContext }

type Tab = "resumes" | "fields" | "questions";

function scoreColor(s: number): string {
  if (s >= 80) return "#10b981";
  if (s >= 65) return "#f59e0b";
  if (s >= 50) return "#f97316";
  return "#f87171";
}

function CompanyAvatar({ name }: { name: string }) {
  const initial = (name || "?")[0].toUpperCase();
  const hue = name.charCodeAt(0) % 360;
  return (
    <div style={{
      width: 40,
      height: 40,
      borderRadius: 10,
      background: `hsl(${hue}, 50%, 25%)`,
      border: `1px solid hsl(${hue}, 50%, 35%)`,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontWeight: 700,
      fontSize: 16,
      color: `hsl(${hue}, 70%, 85%)`,
      flexShrink: 0,
    }}>
      {initial}
    </div>
  );
}

interface UserProfile {
  firstName?: string;
  lastName?: string;
  email?: string;
  phone?: string;
  city?: string;
  state?: string;
  zip?: string;
  country?: string;
  linkedinUrl?: string;
  githubUrl?: string;
  portfolioUrl?: string;
  degree?: string;
  yearsExperience?: string;
  sponsorship?: string;
  salary?: string;
}

function getProfileValue(fieldType: string, profile: UserProfile | null): string {
  if (!profile) return "";
  const isUS = !profile.country || profile.country.toLowerCase().includes("united states") || profile.country.toLowerCase() === "us";
  const map: Record<string, string | undefined> = {
    first_name: profile.firstName,
    last_name: profile.lastName,
    full_name: [profile.firstName, profile.lastName].filter(Boolean).join(" "),
    email: profile.email,
    phone: profile.phone,
    address: profile.city && profile.state ? `${profile.city}, ${profile.state}` : profile.city,
    city: profile.city,
    state: profile.state,
    zip: profile.zip,
    country: profile.country || "United States",
    us_resident: isUS ? "Yes" : "No",
    linkedin: profile.linkedinUrl,
    github: profile.githubUrl,
    portfolio: profile.portfolioUrl,
    website: profile.portfolioUrl,
    degree: profile.degree,
    years_experience: profile.yearsExperience,
    salary: profile.salary,
    sponsorship: profile.sponsorship,
  };
  return map[fieldType] ?? "";
}

export default function ApplyMode({ context }: Props) {
  const [tab, setTab] = useState<Tab>("resumes");
  const [resumes, setResumes] = useState<ResumeCard[]>([]);
  const [ats, setAts] = useState<ATSScoreResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string[]>>({});
  const [selectedAnswers, setSelectedAnswers] = useState<Record<string, number>>({});
  const [savingAnswer, setSavingAnswer] = useState<string | null>(null);
  const [generatingAnswer, setGeneratingAnswer] = useState<string | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [workHistoryText, setWorkHistoryText] = useState<string>("");
  const [providers, setProviders] = useState<Array<{ name: string; apiKey: string; model?: string }>>([]);
  const [providersLoaded, setProvidersLoaded] = useState(false);
  const [draftProviders, setDraftProviders] = useState<Record<string, string[]>>({});
  // answerId is set after saveAnswer — needed to record feedback
  const [savedAnswerIds, setSavedAnswerIds] = useState<Record<string, string>>({});
  const [generationErrors, setGenerationErrors] = useState<Record<string, string>>({});
  // "From Memory" similar answers per question
  const [memoryAnswers, setMemoryAnswers] = useState<Record<string, SimilarAnswer[]>>({});
  // C3: edited answer text — tracks live edits to LLM drafts before saving
  const [editedTexts, setEditedTexts] = useState<Record<string, string>>({});
  // C2: resume upload state
  const [uploadError, setUploadError] = useState<string>("");
  const [uploadSuccess, setUploadSuccess] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // C5/C6: application tracking
  const [trackedAppId, setTrackedAppId] = useState<string | null>(null);
  const [pastApplications, setPastApplications] = useState<TrackedApplication[]>([]);

  const PROVIDER_RANK: Record<string, number> = { anthropic: 1, openai: 2, gemini: 3, groq: 4, perplexity: 5, kimi: 6 };
  const PROVIDER_MODELS: Record<string, string> = { anthropic: "claude-sonnet-4-6", openai: "gpt-4o", gemini: "gemini-1.5-flash", groq: "llama-3.3-70b-versatile", perplexity: "sonar", kimi: "moonshot-v1-32k" };

  function buildProviderList(configs: Record<string, { enabled?: boolean; apiKey: string; model?: string }>) {
    return Object.entries(configs)
      .filter(([, cfg]) => !!cfg.apiKey)   // enabled = has a key, full stop
      .map(([name, cfg]) => ({ name, apiKey: cfg.apiKey, model: cfg.model || PROVIDER_MODELS[name] || "" }))
      .sort((a, b) => (PROVIDER_RANK[a.name] ?? 50) - (PROVIDER_RANK[b.name] ?? 50));
  }

  // Read providers fresh from storage every time — bypasses all React state race conditions
  async function getFreshProviders(): Promise<Array<{ name: string; apiKey: string; model: string }>> {
    return new Promise((resolve) => {
      chrome.storage.local.get("providerConfigs", (data) => {
        if (!data.providerConfigs) { resolve([]); return; }
        resolve(buildProviderList(data.providerConfigs as Record<string, { enabled?: boolean; apiKey: string; model?: string }>));
      });
    });
  }

  useEffect(() => {
    chrome.storage.local.get(["profile", "providerConfigs"], (data) => {
      if (data.profile) setProfile(data.profile as UserProfile);
      if (data.providerConfigs) setProviders(buildProviderList(data.providerConfigs as Record<string, { enabled: boolean; apiKey: string; model: string }>));
      setProvidersLoaded(true);
    });

    const onChanged = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area !== "local") return;
      if (changes.profile?.newValue) setProfile(changes.profile.newValue as UserProfile);
      if (changes.providerConfigs?.newValue) setProviders(buildProviderList(changes.providerConfigs.newValue as Record<string, { enabled: boolean; apiKey: string; model: string }>));
    };
    chrome.storage.onChanged.addListener(onChanged);
    return () => chrome.storage.onChanged.removeListener(onChanged);
  }, []);

  // Fetch work history text from backend (used to ground LLM answers)
  useEffect(() => {
    workHistoryApi
      .getText()
      .then((res) => {
        if (res.text) setWorkHistoryText(res.text);
      })
      .catch(() => {}); // silently fail — backend may be unreachable
  }, []);

  useEffect(() => {
    if (!context.company) return;
    setLoading(true);
    vaultApi
      .retrieve(context.company)
      .then((res: RetrieveResponse) => {
        setResumes(res.company_history ?? []);
        if (res.ats_result) setAts(res.ats_result);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [context.company]);

  // C5: Auto-track this application visit (upsert — idempotent)
  useEffect(() => {
    if (!context.company) return;
    applicationsApi
      .track({
        companyName: context.company,
        roleTitle: context.roleTitle,
        jobUrl: context.jobUrl,
        platform: context.platform,
      })
      .then((res) => {
        setTrackedAppId(res.application_id);
      })
      .catch(() => {}); // non-blocking — tracking failure must never disrupt the UX
  }, [context.company, context.jobUrl]);

  // C6: Fetch past applications for this company to show the "already applied" indicator
  useEffect(() => {
    if (!context.company) return;
    applicationsApi
      .list(context.company)
      .then((res) => {
        // Exclude the current visit record; show previous applied/interview/offer records
        const meaningful = res.items.filter(
          (a) => ["applied", "tailored", "interview", "offer", "rejected"].includes(a.status)
        );
        setPastApplications(meaningful);
      })
      .catch(() => {});
  }, [context.company]);

  // Fetch "From Memory" similar answers whenever questions change
  useEffect(() => {
    if (context.openQuestions.length === 0) return;
    context.openQuestions.forEach((q) => {
      vaultApi
        .getSimilarAnswers({ questionText: q.questionText, questionCategory: q.category, topK: 3 })
        .then((res) => {
          if (res.answers.length > 0) {
            setMemoryAnswers((prev) => ({ ...prev, [q.questionId]: res.answers }));
          }
        })
        .catch(() => {}); // silently fail — no history yet
    });
  }, [context.openQuestions]);

  // C2: Upload a resume file from the sidepanel
  const handleResumeUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!e.target.files) return;
    // Reset input so same file can be re-selected after error
    e.target.value = "";
    if (!file) return;

    const ALLOWED = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/x-tex", "text/plain"];
    const ALLOWED_EXT = /\.(pdf|docx|tex|txt)$/i;
    if (!ALLOWED.includes(file.type) && !ALLOWED_EXT.test(file.name)) {
      setUploadError("Unsupported file type. Please upload a PDF, DOCX, or .tex file.");
      return;
    }
    const MAX_MB = 5;
    if (file.size > MAX_MB * 1024 * 1024) {
      setUploadError(`File too large. Maximum size is ${MAX_MB} MB.`);
      return;
    }

    setUploading(true);
    setUploadError("");
    setUploadSuccess("");
    try {
      const res = await vaultApi.uploadResume({
        file,
        targetCompany: context.company || undefined,
        targetRole: context.roleTitle || undefined,
      });
      setUploadSuccess(`Uploaded "${res.filename}" (${res.bullet_count} bullets detected)`);
      // Refresh resume list
      const updated = await vaultApi.retrieve(context.company);
      setResumes(updated.company_history ?? []);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed. Try again.");
    } finally {
      setUploading(false);
    }
  };

  // C2: Delete a resume from the vault
  const handleResumeDelete = async (resumeId: string) => {
    try {
      await vaultApi.deleteResume(resumeId);
      setResumes((prev) => prev.filter((r) => r.resumeId !== resumeId));
    } catch {
      // Silently fail — resume still shows
    }
  };

  const handleFillAll = () => {
    context.detectedFields.forEach((f) => {
      const value = getProfileValue(f.fieldType, profile);
      if (value) chrome.runtime.sendMessage({ type: "FILL_FIELD", payload: { fieldId: f.fieldId, value } });
    });
  };

  const handleAttach = (resume: ResumeCard) => {
    if (!resume.githubPath) return;
    const fileInput = context.detectedFields.find((f) => f.fieldType === "resume_upload");
    if (!fileInput) return;
    chrome.runtime.sendMessage({ type: "ATTACH_RESUME", payload: { fieldId: fileInput.fieldId, pdfUrl: resume.githubPath } });
  };

  const handleFillField = (fieldId: string, value: string) => {
    chrome.runtime.sendMessage({ type: "FILL_FIELD", payload: { fieldId, value } });
  };

  const handleGenerateAnswers = async (questionId: string, questionText: string, category: string, isRegenerate = false) => {
    // Read providers directly from storage — never relies on potentially-stale React state
    const freshProviders = await getFreshProviders();
    if (freshProviders.length === 0) {
      setGenerationErrors((prev) => ({ ...prev, [questionId]: "No API key found. Open Settings → enter any Groq or Gemini key → Save LLM Settings." }));
      return;
    }
    if (isRegenerate) {
      if (savedAnswerIds[questionId]) {
        vaultApi.recordFeedback({ answerId: savedAnswerIds[questionId], feedback: "regenerated" }).catch(() => {});
      }
      setAnswerDrafts((prev) => { const n = { ...prev }; delete n[questionId]; return n; });
      setDraftProviders((prev) => { const n = { ...prev }; delete n[questionId]; return n; });
      setEditedTexts((prev) => { const n = { ...prev }; delete n[questionId]; return n; });
    }
    setGeneratingAnswer(questionId);
    setGenerationErrors((prev) => { const n = { ...prev }; delete n[questionId]; return n; });
    try {
      const res = await vaultApi.generateAnswers({
        questionText,
        questionCategory: category,
        companyName: context.company,
        roleTitle: context.roleTitle,
        jdText: "",
        workHistoryText,
        providers: freshProviders,
      });
      if (!res.drafts?.length) {
        setGenerationErrors((prev) => ({ ...prev, [questionId]: "All providers failed — check your API keys in Settings." }));
        return;
      }
      setAnswerDrafts((prev) => ({ ...prev, [questionId]: res.drafts }));
      setSelectedAnswers((prev) => ({ ...prev, [questionId]: 0 }));
      // C3: pre-fill editor with first draft
      setEditedTexts((prev) => ({ ...prev, [questionId]: res.drafts[0] ?? "" }));
      if (res.draft_providers?.length) {
        setDraftProviders((prev) => ({ ...prev, [questionId]: res.draft_providers! }));
      } else {
        setGenerationErrors((prev) => ({ ...prev, [questionId]: "⚠ LLM fallback used — showing placeholder answers. Check your API keys." }));
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Generation failed";
      setGenerationErrors((prev) => ({ ...prev, [questionId]: msg }));
    } finally {
      setGeneratingAnswer(null);
    }
  };

  const handleSaveAnswer = async (questionId: string, questionText: string, category: string) => {
    const idx = selectedAnswers[questionId] ?? 0;
    const originalDraft = answerDrafts[questionId]?.[idx] ?? "";
    // C3: use the edited version if the user changed the text
    const finalText = (editedTexts[questionId] ?? originalDraft).trim();
    if (!finalText) return;

    const wasEdited = finalText !== originalDraft.trim();

    setSavingAnswer(questionId);
    try {
      const saved = await vaultApi.saveAnswer({
        questionText,
        questionCategory: category,
        answerText: finalText,
        companyName: context.company,
        roleTitle: context.roleTitle,
        llmProviderUsed: draftProviders[questionId]?.[0],
      });
      setSavedAnswerIds((prev) => ({ ...prev, [questionId]: saved.answer_id }));
      // Record appropriate feedback — edited text signals lower confidence than used-as-is
      vaultApi.recordFeedback({
        answerId: saved.answer_id,
        feedback: wasEdited ? "edited" : "used_as_is",
        editedAnswer: wasEdited ? finalText : undefined,
      }).catch(() => {});
      chrome.runtime.sendMessage({ type: "FILL_ANSWER", payload: { questionId, text: finalText } });
    } finally {
      setSavingAnswer(null);
    }
  };

  const handleUseMemoryAnswer = (questionId: string, questionText: string, category: string, memory: SimilarAnswer) => {
    // Fill the textarea with this memory answer and record feedback on the original
    vaultApi.recordFeedback({ answerId: memory.answer_id, feedback: "used_as_is" }).catch(() => {});
    // Also save it as a new answer for the current context
    vaultApi.saveAnswer({
      questionText,
      questionCategory: category,
      answerText: memory.answer_text,
      companyName: context.company,
      roleTitle: context.roleTitle,
    }).catch(() => {});
    chrome.runtime.sendMessage({ type: "FILL_ANSWER", payload: { questionId, text: memory.answer_text } });
  };

  // Keep a ref to the latest providers so auto-generate always uses fresh values
  const providersRef = React.useRef(providers);
  providersRef.current = providers;
  const workHistoryRef = React.useRef(workHistoryText);
  workHistoryRef.current = workHistoryText;

  // Track which question IDs have been auto-triggered so we only fire once per question
  const autoTriggeredRef = React.useRef<Set<string>>(new Set());

  // Auto-generate when Q&A tab is active and new questions appear
  useEffect(() => {
    if (tab !== "questions") return;
    if (context.openQuestions.length === 0) return;
    const currentWorkHistory = workHistoryRef.current;

    context.openQuestions.forEach((q) => {
      if (autoTriggeredRef.current.has(q.questionId)) return;
      autoTriggeredRef.current.add(q.questionId);

      setGeneratingAnswer(q.questionId);
      setGenerationErrors((prev) => { const n = { ...prev }; delete n[q.questionId]; return n; });

      // Read providers fresh from storage — no React state dependency
      getFreshProviders().then((freshProviders) => {
        if (freshProviders.length === 0) {
          autoTriggeredRef.current.delete(q.questionId); // allow retry once user adds a key
          setGeneratingAnswer((cur) => cur === q.questionId ? null : cur);
          setGenerationErrors((prev) => ({ ...prev, [q.questionId]: "No API key found. Open Settings → enter any Groq or Gemini key → Save LLM Settings." }));
          return;
        }
        return vaultApi.generateAnswers({
          questionText: q.questionText,
          questionCategory: q.category,
          companyName: context.company,
          roleTitle: context.roleTitle,
          jdText: "",
          workHistoryText: currentWorkHistory,
          providers: freshProviders,
        }).then((res) => {
          if (!res.drafts?.length) {
            setGenerationErrors((prev) => ({ ...prev, [q.questionId]: "All providers failed — check your API keys in Settings." }));
            return;
          }
          setAnswerDrafts((prev) => ({ ...prev, [q.questionId]: res.drafts }));
          setSelectedAnswers((prev) => ({ ...prev, [q.questionId]: 0 }));
          // C3: pre-fill editor with first draft
          setEditedTexts((prev) => ({ ...prev, [q.questionId]: res.drafts[0] ?? "" }));
          if (res.draft_providers?.length) {
            setDraftProviders((prev) => ({ ...prev, [q.questionId]: res.draft_providers! }));
          } else {
            setGenerationErrors((prev) => ({ ...prev, [q.questionId]: "⚠ LLM fallback used — placeholder answers shown. Check your API keys." }));
          }
        }).catch((e) => {
          autoTriggeredRef.current.delete(q.questionId);
          setGenerationErrors((prev) => ({ ...prev, [q.questionId]: e instanceof Error ? e.message : "Generation failed" }));
        }).finally(() => {
          setGeneratingAnswer((cur) => cur === q.questionId ? null : cur);
        });
      });
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, context.openQuestions]);

  const tabs: Array<{ key: Tab; label: string; count: number }> = [
    { key: "resumes", label: "Resumes", count: resumes.length },
    { key: "fields", label: "Fields", count: context.detectedFields.length },
    { key: "questions", label: "Q&A", count: context.openQuestions.length },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 45px)", overflow: "hidden" }}>

      {/* Company context bar */}
      <div style={{
        padding: "10px 14px",
        background: "#0f0f1e",
        borderBottom: "1px solid #1f1f38",
        display: "flex",
        alignItems: "center",
        gap: 10,
        flexShrink: 0,
      }}>
        <CompanyAvatar name={context.company || "?"} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: "#f1f5f9", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {context.company || "Unknown Company"}
          </div>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {context.roleTitle}
          </div>
        </div>
        {ats && (
          <div style={{
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            background: "#12121e",
            border: `1px solid ${scoreColor(ats.overallScore)}44`,
            borderRadius: 10,
            padding: "6px 10px",
          }}>
            <span style={{ fontSize: 16, fontWeight: 800, color: scoreColor(ats.overallScore) }}>
              {ats.overallScore.toFixed(0)}
            </span>
            <span style={{ fontSize: 9, color: "#64748b", fontWeight: 600, letterSpacing: "0.04em" }}>ATS</span>
          </div>
        )}
      </div>

      {/* C6: Already applied indicator */}
      {pastApplications.length > 0 && (
        <div style={{
          padding: "6px 14px",
          background: "#071a12",
          borderBottom: "1px solid #064e3b",
          display: "flex",
          alignItems: "center",
          gap: 6,
          flexShrink: 0,
        }}>
          <span style={{ fontSize: 10 }}>✓</span>
          <span style={{ fontSize: 11, color: "#34d399" }}>
            Applied here before ·{" "}
            {pastApplications[0].role_title}{" "}
            · {new Date(pastApplications[0].created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
            {pastApplications.length > 1 && ` (+${pastApplications.length - 1} more)`}
          </span>
        </div>
      )}

      {/* ATS bar (only when score exists) */}
      {ats && (
        <div style={{ padding: "8px 14px", borderBottom: "1px solid #1a1a2e", background: "#0a0a14", flexShrink: 0 }}>
          <ATSScoreBar score={ats.overallScore} label={`Resume Match · ${ats.matchedKeywords}/${ats.totalJdKeywords} keywords`} />
        </div>
      )}

      {/* Tab navigation */}
      <div style={{
        display: "flex",
        gap: 4,
        padding: "8px 14px",
        borderBottom: "1px solid #1a1a2e",
        background: "#0a0a14",
        flexShrink: 0,
      }}>
        {tabs.map(({ key, label, count }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{
              flex: 1,
              padding: "5px 4px",
              borderRadius: 6,
              border: "none",
              cursor: "pointer",
              fontSize: 11,
              fontWeight: 600,
              transition: "all 0.15s",
              background: tab === key ? "#1e1335" : "transparent",
              color: tab === key ? "#a78bfa" : "#475569",
              outline: tab === key ? "1px solid #3d2b6e" : "none",
            }}
          >
            {label}
            {count > 0 && (
              <span style={{
                marginLeft: 5,
                background: tab === key ? "#2d1b69" : "#1a1a2e",
                color: tab === key ? "#c4b5fd" : "#374151",
                borderRadius: 99,
                padding: "1px 6px",
                fontSize: 10,
              }}>
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8 }}>

        {/* RESUMES TAB */}
        {tab === "resumes" && (
          <>
            {/* Skills gap pills */}
            {ats?.skillsGap && ats.skillsGap.length > 0 && (
              <Section label="Skills Gap">
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {ats.skillsGap.slice(0, 8).map((s) => (
                    <span key={s} style={{
                      background: "#2d1b4e",
                      color: "#c4b5fd",
                      borderRadius: 99,
                      fontSize: 10,
                      padding: "2px 8px",
                      border: "1px solid #3d2560",
                    }}>
                      {s}
                    </span>
                  ))}
                </div>
              </Section>
            )}

            {/* Suggestions */}
            {ats?.suggestions && ats.suggestions.length > 0 && (
              <Section label="Suggestions">
                {ats.suggestions.slice(0, 3).map((s, i) => (
                  <div key={i} style={{
                    display: "flex",
                    gap: 6,
                    fontSize: 11,
                    color: "#94a3b8",
                    lineHeight: 1.5,
                    padding: "4px 0",
                    borderBottom: i < Math.min(ats.suggestions.length, 3) - 1 ? "1px solid #1a1a2e" : "none",
                  }}>
                    <span style={{ color: "#7c3aed", flexShrink: 0 }}>›</span>
                    <span>{s}</span>
                  </div>
                ))}
              </Section>
            )}

            {/* C2: Resume upload */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "#475569", paddingLeft: 2 }}>
                Upload Resume
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.tex,.txt"
                style={{ display: "none" }}
                onChange={handleResumeUpload}
              />
              <button
                onClick={() => { setUploadError(""); setUploadSuccess(""); fileInputRef.current?.click(); }}
                disabled={uploading}
                style={{ ...btnStyle("ghost", uploading), width: "100%", textAlign: "center" }}
              >
                {uploading ? "Uploading…" : "⬆ Upload PDF / DOCX / .tex"}
              </button>
              {uploadError && (
                <div style={{ fontSize: 10, color: "#f87171", padding: "4px 8px", background: "#1a0808", borderRadius: 5, border: "1px solid #7f1d1d" }}>
                  {uploadError}
                </div>
              )}
              {uploadSuccess && (
                <div style={{ fontSize: 10, color: "#6ee7b7", padding: "4px 8px", background: "#071a12", borderRadius: 5, border: "1px solid #064e3b" }}>
                  ✓ {uploadSuccess}
                </div>
              )}
            </div>

            <Section label={`Past Resumes · ${context.company}`}>
              {loading && <LoadingRow />}
              {!loading && resumes.length === 0 && (
                <EmptyState message="No past resumes for this company yet." hint="Upload one above or generate a tailored resume." />
              )}
              {resumes.map((r) => (
                <ResumeCardComponent key={r.resumeId} resume={r} onAttach={() => handleAttach(r)} />
              ))}
            </Section>
          </>
        )}

        {/* FIELDS TAB */}
        {tab === "fields" && (
          <>
            {context.detectedFields.length > 0 && profile && (
              <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 4 }}>
                <button onClick={handleFillAll} style={{ ...btnStyle("primary"), fontSize: 11, padding: "5px 14px" }}>
                  Fill All Fields
                </button>
              </div>
            )}
            {!profile && context.detectedFields.length > 0 && (
              <div style={{
                padding: "8px 12px",
                background: "#1a1200",
                border: "1px solid #78350f",
                borderRadius: 8,
                fontSize: 11,
                color: "#fbbf24",
                marginBottom: 4,
              }}>
                No profile saved. Open <strong>Settings</strong> (extension options) to add your name, email, phone, etc.
              </div>
            )}
            <Section label="Detected Form Fields">
              {context.detectedFields.length === 0 ? (
                <EmptyState message="No fillable fields detected." hint="Fields appear once you navigate to the application form." />
              ) : (
                context.detectedFields.map((f) => {
                  const profileVal = getProfileValue(f.fieldType, profile);
                  return (
                    <div key={f.fieldId} style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "7px 10px",
                      background: "#12121e",
                      border: "1px solid #1f1f38",
                      borderRadius: 8,
                    }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, color: "#cbd5e1", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {f.label || f.fieldType}
                        </div>
                        <div style={{ fontSize: 10, color: "#475569", marginTop: 1 }}>
                          {profileVal ? (
                            <span style={{ color: "#6ee7b7" }}>{profileVal.slice(0, 40)}{profileVal.length > 40 ? "…" : ""}</span>
                          ) : (
                            f.fieldType.replace(/_/g, " ")
                          )}
                        </div>
                      </div>
                      {f.fieldType === "resume_upload" ? (
                        <span style={{ fontSize: 10, background: "#4f46e5", color: "#fff", borderRadius: 4, padding: "2px 7px", fontWeight: 600 }}>
                          PDF
                        </span>
                      ) : null}
                      {profileVal ? (
                        <button
                          onClick={() => handleFillField(f.fieldId, profileVal)}
                          style={btnStyle("fill")}
                        >
                          Fill
                        </button>
                      ) : null}
                    </div>
                  );
                })
              )}
            </Section>
          </>
        )}

        {/* Q&A TAB */}
        {tab === "questions" && (
          <Section label="Open-Ended Questions">
            {/* Provider status — uses React state for display only, actual generation reads storage directly */}
            {providersLoaded && providers.length === 0 && (
              <div style={{ padding: "8px 12px", background: "#1a0d00", border: "1px solid #92400e", borderRadius: 8, fontSize: 11, color: "#fbbf24", marginBottom: 4 }}>
                <strong>No API key found.</strong> Open <strong>Settings</strong> (right-click extension → Options), paste a Groq or Gemini key, click <strong>Save LLM Settings</strong>.
              </div>
            )}
            {providers.length > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, fontSize: 10, color: "#4b5563" }}>
                <span>Using:</span>
                {providers.map((p) => (
                  <span key={p.name} style={{ background: "#071a12", border: "1px solid #064e3b", color: "#6ee7b7", borderRadius: 4, padding: "1px 6px", fontWeight: 700 }}>
                    {p.name.charAt(0).toUpperCase() + p.name.slice(1)}
                  </span>
                ))}
              </div>
            )}
            {context.openQuestions.length === 0 ? (
              <EmptyState message="No open questions detected." hint="Questions appear on forms with text areas." />
            ) : (
              context.openQuestions.map((q) => {
                const drafts = answerDrafts[q.questionId];
                const selectedIdx = selectedAnswers[q.questionId] ?? 0;
                const isGenerating = generatingAnswer === q.questionId;
                return (
                  <div key={q.questionId} style={{
                    background: "#12121e",
                    border: "1px solid #1f1f38",
                    borderRadius: 10,
                    padding: "10px 12px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}>
                    <div style={{ fontSize: 12, color: "#c4b5fd", fontWeight: 600, lineHeight: 1.4 }}>
                      {q.questionText.slice(0, 130)}{q.questionText.length > 130 ? "…" : ""}
                    </div>
                    <div style={{ display: "flex", gap: 6, fontSize: 10, color: "#475569" }}>
                      <span style={{ background: "#1a1a2e", borderRadius: 4, padding: "1px 6px" }}>{q.category.replace(/_/g, " ")}</span>
                      {q.maxLength && (
                        <span style={{ background: "#1a1a2e", borderRadius: 4, padding: "1px 6px" }}>max {q.maxLength}</span>
                      )}
                    </div>

                    {/* From Memory section */}
                    {memoryAnswers[q.questionId] && memoryAnswers[q.questionId].length > 0 && !drafts && (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em", color: "#6ee7b7", textTransform: "uppercase" }}>
                          From Memory · {memoryAnswers[q.questionId].length} past answers
                        </div>
                        {memoryAnswers[q.questionId].map((mem, mi) => (
                          <div key={mem.answer_id} style={{
                            background: "#071a12",
                            border: "1px solid #064e3b",
                            borderRadius: 8,
                            padding: "8px 10px",
                          }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                              <span style={{ fontSize: 10, color: "#34d399" }}>
                                {mem.company_name} · {mem.feedback === "used_as_is" ? "★ Used as-is" : mem.feedback === "edited" ? "✎ Edited" : "saved"}
                              </span>
                              <span style={{ fontSize: 10, color: "#6b7280" }}>
                                {mem.reward_score != null ? `${(mem.reward_score * 100).toFixed(0)}% quality` : ""}
                              </span>
                            </div>
                            <div style={{ fontSize: 11, color: "#94a3b8", lineHeight: 1.5, maxHeight: 80, overflowY: "auto", marginBottom: 6 }}>
                              {mem.answer_text.slice(0, 200)}{mem.answer_text.length > 200 ? "…" : ""}
                            </div>
                            <button
                              onClick={() => handleUseMemoryAnswer(q.questionId, q.questionText, q.category, mem)}
                              style={{ ...btnStyle("fill"), fontSize: 10, background: "#064e3b", color: "#6ee7b7" }}
                            >
                              Use This
                            </button>
                          </div>
                        ))}
                        <div style={{ height: 1, background: "#1a1a2e", margin: "2px 0" }} />
                      </div>
                    )}

                    {!drafts?.length ? (
                      <>
                        <button
                          onClick={() => handleGenerateAnswers(q.questionId, q.questionText, q.category)}
                          disabled={isGenerating}
                          style={btnStyle("generate", isGenerating)}
                        >
                          {isGenerating ? "Generating…" : "✦ Generate 3 Drafts"}
                        </button>
                        {generationErrors[q.questionId] && (
                          <div style={{ fontSize: 10, color: "#f87171", marginTop: 4, padding: "4px 6px", background: "#1a0808", borderRadius: 5, border: "1px solid #7f1d1d" }}>
                            {generationErrors[q.questionId]}
                          </div>
                        )}
                      </>
                    ) : (
                      <>
                        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
                          {draftProviders[q.questionId]?.[0] && (
                            <span style={{ fontSize: 10, color: "#6ee7b7", background: "#071a12", border: "1px solid #064e3b", borderRadius: 4, padding: "1px 7px", fontWeight: 600 }}>
                              via {draftProviders[q.questionId][0].charAt(0).toUpperCase() + draftProviders[q.questionId][0].slice(1)}
                            </span>
                          )}
                          {drafts.map((_, i) => (
                            <button
                              key={i}
                              onClick={() => {
                                setSelectedAnswers((p) => ({ ...p, [q.questionId]: i }));
                                // C3: sync editor to the newly selected draft
                                setEditedTexts((p) => ({ ...p, [q.questionId]: drafts[i] }));
                              }}
                              style={{
                                padding: "3px 10px",
                                borderRadius: 6,
                                border: "none",
                                cursor: "pointer",
                                fontSize: 11,
                                fontWeight: 600,
                                background: selectedIdx === i ? "#4f46e5" : "#1a1a2e",
                                color: selectedIdx === i ? "#fff" : "#64748b",
                              }}
                            >
                              Draft {i + 1}
                            </button>
                          ))}
                          {/* C3: edited indicator */}
                          {editedTexts[q.questionId] != null &&
                           editedTexts[q.questionId] !== drafts[selectedIdx] && (
                            <span style={{ fontSize: 9, color: "#fbbf24", background: "#1a1200", border: "1px solid #78350f", borderRadius: 4, padding: "1px 6px", fontWeight: 700 }}>
                              edited
                            </span>
                          )}
                        </div>
                        {/* C3: editable textarea — user can refine before using */}
                        <textarea
                          value={editedTexts[q.questionId] ?? drafts[selectedIdx]}
                          onChange={(e) => setEditedTexts((p) => ({ ...p, [q.questionId]: e.target.value }))}
                          rows={6}
                          style={{
                            width: "100%",
                            boxSizing: "border-box",
                            fontSize: 12,
                            color: "#d1d5db",
                            lineHeight: 1.6,
                            background: "#0a0a14",
                            borderRadius: 8,
                            padding: "8px 10px",
                            border: "1px solid #1f1f38",
                            resize: "vertical",
                            fontFamily: "system-ui, sans-serif",
                            outline: "none",
                          }}
                        />
                        {generationErrors[q.questionId] && (
                          <div style={{ fontSize: 10, color: "#f87171", padding: "4px 6px", background: "#1a0808", borderRadius: 5, border: "1px solid #7f1d1d" }}>
                            {generationErrors[q.questionId]}
                          </div>
                        )}
                        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                          <button
                            onClick={() => handleGenerateAnswers(q.questionId, q.questionText, q.category, true)}
                            disabled={isGenerating}
                            style={btnStyle("ghost", isGenerating)}
                          >
                            {isGenerating ? "Regenerating…" : "Regenerate"}
                          </button>
                          <button
                            onClick={() => handleSaveAnswer(q.questionId, q.questionText, q.category)}
                            disabled={savingAnswer === q.questionId}
                            style={btnStyle("primary", savingAnswer === q.questionId)}
                          >
                            {savingAnswer === q.questionId ? "Saving…" : "Use & Fill"}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                );
              })
            )}
          </Section>
        )}
      </div>
    </div>
  );
}

// ── Shared sub-components ─────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "#475569",
        paddingLeft: 2,
      }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function EmptyState({ message, hint }: { message: string; hint: string }) {
  return (
    <div style={{
      padding: "20px 16px",
      textAlign: "center",
      background: "#12121e",
      border: "1px dashed #1f1f38",
      borderRadius: 10,
    }}>
      <div style={{ fontSize: 12, color: "#475569", marginBottom: 4 }}>{message}</div>
      <div style={{ fontSize: 11, color: "#334155" }}>{hint}</div>
    </div>
  );
}

function LoadingRow() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {[1, 2].map((i) => (
        <div key={i} style={{
          height: 60,
          background: "linear-gradient(90deg, #12121e 25%, #1a1a2e 50%, #12121e 75%)",
          borderRadius: 10,
          border: "1px solid #1f1f38",
          animation: "pulse 1.5s ease infinite",
        }} />
      ))}
    </div>
  );
}

function btnStyle(variant: "primary" | "ghost" | "generate" | "fill", disabled = false): React.CSSProperties {
  const base: React.CSSProperties = {
    border: "none",
    borderRadius: 7,
    cursor: disabled ? "not-allowed" : "pointer",
    fontWeight: 600,
    fontSize: 11,
    opacity: disabled ? 0.6 : 1,
    transition: "opacity 0.15s",
  };
  if (variant === "primary") return { ...base, background: "#6d28d9", color: "#fff", padding: "5px 14px" };
  if (variant === "ghost") return { ...base, background: "#1a1a2e", color: "#8b5cf6", padding: "5px 12px" };
  if (variant === "generate") return { ...base, background: "#1e1335", color: "#a78bfa", padding: "6px 12px", width: "100%", outline: "1px solid #2d1b69" };
  return { ...base, background: "#1e1b4b", color: "#a5b4fc", padding: "3px 10px" };
}
