import React, { useEffect, useState } from "react";
import type { ATSScoreResult, PageContext, ResumeCard } from "../../shared/types";
import { vaultApi, type RetrieveResponse } from "../../shared/api";
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
  linkedinUrl?: string;
  portfolioUrl?: string;
  yearsExperience?: string;
  sponsorship?: string;
  salary?: string;
}

function getProfileValue(fieldType: string, profile: UserProfile | null): string {
  if (!profile) return "";
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
    linkedin: profile.linkedinUrl,
    portfolio: profile.portfolioUrl,
    website: profile.portfolioUrl,
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

  useEffect(() => {
    // Load profile on mount
    chrome.storage.local.get(["profile"], (data) => {
      if (data.profile) setProfile(data.profile as UserProfile);
    });

    // Re-load whenever the user saves profile in Options
    const onChanged = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === "local" && changes.profile?.newValue) {
        setProfile(changes.profile.newValue as UserProfile);
      }
    };
    chrome.storage.onChanged.addListener(onChanged);
    return () => chrome.storage.onChanged.removeListener(onChanged);
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

  const handleGenerateAnswers = async (questionId: string, questionText: string, category: string) => {
    setGeneratingAnswer(questionId);
    try {
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
    } catch (e) {
      console.error(e);
    } finally {
      setGeneratingAnswer(null);
    }
  };

  const handleSaveAnswer = async (questionId: string, questionText: string, category: string) => {
    const idx = selectedAnswers[questionId] ?? 0;
    const text = answerDrafts[questionId]?.[idx];
    if (!text) return;
    setSavingAnswer(questionId);
    try {
      await vaultApi.saveAnswer({
        questionText,
        questionCategory: category,
        answerText: text,
        companyName: context.company,
        roleTitle: context.roleTitle,
      });
      chrome.runtime.sendMessage({ type: "FILL_ANSWER", payload: { questionId, text } });
    } finally {
      setSavingAnswer(null);
    }
  };

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

            <Section label={`Past Resumes · ${context.company}`}>
              {loading && <LoadingRow />}
              {!loading && resumes.length === 0 && (
                <EmptyState message="No past resumes for this company yet." hint="Generate one to get started." />
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

                    {!drafts ? (
                      <button
                        onClick={() => handleGenerateAnswers(q.questionId, q.questionText, q.category)}
                        disabled={isGenerating}
                        style={btnStyle("generate", isGenerating)}
                      >
                        {isGenerating ? "Generating…" : "✦ Generate 3 Drafts"}
                      </button>
                    ) : (
                      <>
                        <div style={{ display: "flex", gap: 4 }}>
                          {drafts.map((_, i) => (
                            <button
                              key={i}
                              onClick={() => setSelectedAnswers((p) => ({ ...p, [q.questionId]: i }))}
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
                              {i + 1}
                            </button>
                          ))}
                        </div>
                        <div style={{
                          fontSize: 12,
                          color: "#d1d5db",
                          lineHeight: 1.6,
                          background: "#0a0a14",
                          borderRadius: 8,
                          padding: "8px 10px",
                          border: "1px solid #1f1f38",
                          maxHeight: 140,
                          overflowY: "auto",
                        }}>
                          {drafts[selectedIdx]}
                        </div>
                        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                          <button
                            onClick={() => handleGenerateAnswers(q.questionId, q.questionText, q.category)}
                            disabled={isGenerating}
                            style={btnStyle("ghost", isGenerating)}
                          >
                            Regenerate
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
