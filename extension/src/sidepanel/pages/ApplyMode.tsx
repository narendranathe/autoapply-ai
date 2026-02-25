import React, { useEffect, useState } from "react";
import type { ATSScoreResult, PageContext, ResumeCard } from "../../shared/types";
import { vaultApi } from "../../shared/api";
import ATSScoreBar from "../components/ATSScoreBar";
import ResumeCardComponent from "../components/ResumeCard";

interface Props { context: PageContext }

type Tab = "resumes" | "fields" | "questions";

export default function ApplyMode({ context }: Props) {
  const [tab, setTab] = useState<Tab>("resumes");
  const [resumes, setResumes] = useState<ResumeCard[]>([]);
  const [ats, setAts] = useState<ATSScoreResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string[]>>({});
  const [selectedAnswers, setSelectedAnswers] = useState<Record<string, number>>({});
  const [savingAnswer, setSavingAnswer] = useState<string | null>(null);

  useEffect(() => {
    if (!context.company) return;
    setLoading(true);
    vaultApi
      .retrieve(context.company)
      .then((res) => {
        const items = (res.company_history || []) as ResumeCard[];
        setResumes(items);
        if (res.ats_result) setAts(res.ats_result as ATSScoreResult);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [context.company]);

  const handleAttach = (resume: ResumeCard) => {
    if (!resume.githubPath) return;
    const fileInput = context.detectedFields.find((f) => f.fieldType === "resume_upload");
    if (!fileInput) return;
    chrome.runtime.sendMessage({
      type: "ATTACH_RESUME",
      payload: { fieldId: fileInput.fieldId, pdfUrl: resume.githubPath },
    });
  };

  const handleFillField = (fieldId: string, value: string) => {
    chrome.runtime.sendMessage({
      type: "FILL_FIELD",
      payload: { fieldId, value },
    });
  };

  const handleGenerateAnswers = async (questionId: string, questionText: string, category: string) => {
    const res = await vaultApi.generateAnswers({
      questionText,
      questionCategory: category,
      companyName: context.company,
      roleTitle: context.roleTitle,
      jdText: "",
      workHistoryText: "",
    });
    setAnswerDrafts((prev) => ({ ...prev, [questionId]: res.drafts }));
    setSelectedAnswers((prev) => ({ ...prev, [questionId]: 0 }));
  };

  const handleSaveAnswer = async (questionId: string, questionText: string, category: string) => {
    const idx = selectedAnswers[questionId] ?? 0;
    const text = answerDrafts[questionId]?.[idx];
    if (!text) return;
    setSavingAnswer(questionId);
    await vaultApi.saveAnswer({
      questionText,
      questionCategory: category,
      answerText: text,
      companyName: context.company,
      roleTitle: context.roleTitle,
    });
    handleFillField(questionId, text);
    setSavingAnswer(null);
  };

  const S = {
    container: { display: "flex", flexDirection: "column" as const, height: "calc(100vh - 53px)", overflow: "hidden" },
    companyBar: { padding: "12px 16px", borderBottom: "1px solid #1e1e3a", background: "#13131f" },
    companyName: { fontWeight: 700, fontSize: 15, color: "#f1f5f9" },
    roleTitle: { fontSize: 12, color: "#6b7280", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const },
    atsRow: { padding: "10px 16px", borderBottom: "1px solid #1e1e3a" },
    tabs: { display: "flex", borderBottom: "1px solid #1e1e3a" },
    tab: (active: boolean): React.CSSProperties => ({
      flex: 1, padding: "9px 0", textAlign: "center" as const, fontSize: 12, fontWeight: 600,
      cursor: "pointer", color: active ? "#a78bfa" : "#6b7280",
      borderBottom: active ? "2px solid #a78bfa" : "2px solid transparent",
      background: "none", border: "none", outline: "none",
    }),
    body: { flex: 1, overflowY: "auto" as const, padding: 12, display: "flex", flexDirection: "column" as const, gap: 8 },
    sectionLabel: { fontSize: 11, color: "#6b7280", fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase" as const, marginBottom: 4 },
    emptyState: { fontSize: 13, color: "#4b5563", textAlign: "center" as const, padding: "24px 0" },
    fieldRow: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: "1px solid #1a1a2e", fontSize: 12 },
    fieldLabel: { color: "#9ca3af", flex: 1 },
    fieldBadge: (type: string): React.CSSProperties => ({
      fontSize: 10, padding: "2px 6px", borderRadius: 4, fontWeight: 600,
      background: type === "resume_upload" ? "#4f46e5" : "#1e1e3a",
      color: type === "resume_upload" ? "#fff" : "#a78bfa",
    }),
    questionCard: { background: "#13131f", border: "1px solid #1e1e3a", borderRadius: 10, padding: 12, display: "flex", flexDirection: "column" as const, gap: 8 },
    questionText: { fontSize: 12, color: "#c4b5fd", fontWeight: 600 },
    draftText: { fontSize: 12, color: "#d1d5db", lineHeight: 1.5, background: "#0f0f1a", borderRadius: 6, padding: 8 },
    draftTabs: { display: "flex", gap: 4 },
    draftTabBtn: (active: boolean): React.CSSProperties => ({
      fontSize: 11, padding: "3px 8px", borderRadius: 4, cursor: "pointer", border: "none",
      background: active ? "#4f46e5" : "#1e1e3a", color: active ? "#fff" : "#6b7280",
    }),
    generateBtn: { fontSize: 11, padding: "4px 10px", borderRadius: 6, cursor: "pointer", border: "none", background: "#1e1e3a", color: "#a78bfa", fontWeight: 600 },
    saveBtn: { fontSize: 11, padding: "4px 10px", borderRadius: 6, cursor: "pointer", border: "none", background: "#4f46e5", color: "#fff", fontWeight: 600 },
    gapPill: { display: "inline-block", background: "#2d1b4e", color: "#c4b5fd", borderRadius: 99, fontSize: 11, padding: "2px 8px" },
  };

  return (
    <div style={S.container}>
      {/* Company + role */}
      <div style={S.companyBar}>
        <div style={S.companyName}>{context.company || "Unknown Company"}</div>
        <div style={S.roleTitle}>{context.roleTitle}</div>
      </div>

      {/* ATS score strip */}
      {ats && (
        <div style={S.atsRow}>
          <ATSScoreBar score={ats.overallScore} label={`ATS Match: ${ats.overallScore.toFixed(0)}/100`} />
        </div>
      )}

      {/* Tabs */}
      <div style={S.tabs}>
        {(["resumes", "fields", "questions"] as Tab[]).map((t) => (
          <button key={t} style={S.tab(tab === t)} onClick={() => setTab(t)}>
            {t === "resumes" ? `Resumes (${resumes.length})` : t === "fields" ? `Fields (${context.detectedFields.length})` : `Q&A (${context.openQuestions.length})`}
          </button>
        ))}
      </div>

      <div style={S.body}>
        {/* Resumes tab */}
        {tab === "resumes" && (
          <>
            {ats?.skillsGap && ats.skillsGap.length > 0 && (
              <div>
                <div style={S.sectionLabel}>Skills Gap</div>
                <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 4 }}>
                  {ats.skillsGap.slice(0, 6).map((s) => <span key={s} style={S.gapPill}>{s}</span>)}
                </div>
              </div>
            )}
            {ats?.suggestions && ats.suggestions.length > 0 && (
              <div>
                <div style={S.sectionLabel}>Suggestions</div>
                {ats.suggestions.map((s, i) => (
                  <div key={i} style={{ fontSize: 11, color: "#9ca3af", marginBottom: 4, lineHeight: 1.4 }}>• {s}</div>
                ))}
              </div>
            )}
            <div style={S.sectionLabel}>Past Resumes for {context.company}</div>
            {loading && <div style={S.emptyState}>Loading...</div>}
            {!loading && resumes.length === 0 && (
              <div style={S.emptyState}>No past resumes for this company yet.<br />Generate one to get started.</div>
            )}
            {resumes.map((r) => (
              <ResumeCardComponent key={r.resumeId} resume={r} onAttach={() => handleAttach(r)} />
            ))}
          </>
        )}

        {/* Fields tab */}
        {tab === "fields" && (
          <>
            <div style={S.sectionLabel}>Detected Form Fields</div>
            {context.detectedFields.length === 0 && (
              <div style={S.emptyState}>No fillable fields detected on this page.</div>
            )}
            {context.detectedFields.map((f) => (
              <div key={f.fieldId} style={S.fieldRow}>
                <span style={S.fieldLabel}>{f.label || f.fieldType}</span>
                <span style={S.fieldBadge(f.fieldType)}>{f.fieldType.replace("_", " ")}</span>
                {f.suggestedValue && (
                  <button
                    style={{ ...S.generateBtn, marginLeft: 6 }}
                    onClick={() => handleFillField(f.fieldId, f.suggestedValue)}
                  >
                    Fill
                  </button>
                )}
              </div>
            ))}
          </>
        )}

        {/* Questions tab */}
        {tab === "questions" && (
          <>
            <div style={S.sectionLabel}>Open-Ended Questions</div>
            {context.openQuestions.length === 0 && (
              <div style={S.emptyState}>No open-ended questions detected.</div>
            )}
            {context.openQuestions.map((q) => {
              const drafts = answerDrafts[q.questionId];
              const selectedIdx = selectedAnswers[q.questionId] ?? 0;
              return (
                <div key={q.questionId} style={S.questionCard}>
                  <div style={S.questionText}>{q.questionText.slice(0, 120)}{q.questionText.length > 120 ? "…" : ""}</div>
                  <div style={{ fontSize: 10, color: "#6b7280" }}>{q.category} · max {q.maxLength ?? "—"} chars</div>
                  {!drafts ? (
                    <button style={S.generateBtn} onClick={() => handleGenerateAnswers(q.questionId, q.questionText, q.category)}>
                      Generate 3 Drafts
                    </button>
                  ) : (
                    <>
                      <div style={S.draftTabs}>
                        {drafts.map((_, i) => (
                          <button key={i} style={S.draftTabBtn(selectedIdx === i)} onClick={() => setSelectedAnswers((p) => ({ ...p, [q.questionId]: i }))}>
                            Draft {i + 1}
                          </button>
                        ))}
                      </div>
                      <div style={S.draftText}>{drafts[selectedIdx]}</div>
                      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                        <button style={S.generateBtn} onClick={() => handleGenerateAnswers(q.questionId, q.questionText, q.category)}>
                          Regenerate
                        </button>
                        <button
                          style={S.saveBtn}
                          onClick={() => handleSaveAnswer(q.questionId, q.questionText, q.category)}
                          disabled={savingAnswer === q.questionId}
                        >
                          {savingAnswer === q.questionId ? "Saving…" : "Use & Save"}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}
