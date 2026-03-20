import React, { useCallback, useEffect, useState } from "react";
import type { PageContext, ResumeCard } from "../../shared/types";
import { applicationsApi, vaultApi, type GenerateTailoredResponse, type InterviewQuestion, type TrackedApplication } from "../../shared/api";
import ATSScoreBar from "../components/ATSScoreBar";
import ResumeCardComponent from "../components/ResumeCard";
import { useTabNavigation, type Tab } from "../hooks/useTabNavigation";
import { useProviders, type UserProfile } from "../hooks/useProviders";
import { useApplicationTracking } from "../hooks/useApplicationTracking";
import { useApplicationHistory } from "../hooks/useApplicationHistory";
import { useInterviewPrep } from "../hooks/useInterviewPrep";
import { useCoverLetter } from "../hooks/useCoverLetter";
import { useResumeVault } from "../hooks/useResumeVault";
import { useQAGeneration } from "../hooks/useQAGeneration";
import { useWritingTools } from "../hooks/useWritingTools";
import { useRagDocs } from "../hooks/useRagDocs";

// ── Draft persistence helpers (sessionStorage, keyed by job URL) ────────────

function draftKey(jobUrl: string | undefined, suffix: string): string {
  const base = jobUrl ? btoa(jobUrl).slice(0, 32) : "nojob";
  return `aap_drafts_${base}_${suffix}`;
}

function loadDraftSession<T>(jobUrl: string | undefined, suffix: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(draftKey(jobUrl, suffix));
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch { return fallback; }
}

function saveDraftSession(jobUrl: string | undefined, suffix: string, value: unknown): void {
  try {
    sessionStorage.setItem(draftKey(jobUrl, suffix), JSON.stringify(value));
  } catch { /* storage full — ignore */ }
}

interface Props { context: PageContext }

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
  const { tab, setTab } = useTabNavigation("resumes");
  const { profile, providers, providersLoaded, promptTemplates } = useProviders();

  // C2/L6: resume vault — hook
  const {
    resumes,
    setResumes,
    ats,
    loading,
    viewingResumeId,
    setViewingResumeId,
    resumeContent,
    renamingResumeId,
    setRenamingResumeId,
    renameTag,
    setRenameTag,
    tailoringResumeId,
    tailorResults,
    tailorErrors,
    uploadError,
    uploadSuccess,
    uploading,
    fileInputRef,
    handleResumeUpload,
    handleResumeDelete,
    handleTailorResume,
    handleViewResume,
    handleRenameResume,
    clearUploadFeedback,
  } = useResumeVault(context);

  // Q&A generation — hook
  const {
    answerDrafts,
    setAnswerDrafts,
    selectedAnswers,
    setSelectedAnswers,
    savingAnswer,
    generatingAnswer,
    draftProviders,
    setDraftProviders,
    savedAnswerIds,
    generationErrors,
    memoryAnswers,
    setMemoryAnswers,
    editedTexts,
    setEditedTexts,
    trimmingAnswer,
    copiedAllAnswers,
    setCopiedAllAnswers,
    workHistoryText,
    handleGenerateAnswers,
    handleSaveAnswer,
    handleUseMemoryAnswer,
    handleTrimAnswer,
    persistDrafts: persistQADrafts,
  } = useQAGeneration(context, tab, promptTemplates);

  // AI Writing Tools — hook
  const {
    generatingSummary,
    generatedSummary,
    summaryError,
    summaryCopied,
    setSummaryCopied,
    generatingBullets,
    generatedBullets,
    bulletsError,
    bulletsCopied,
    setBulletsCopied,
    handleGenerateSummary,
    handleGenerateBullets,
  } = useWritingTools(context, profile);

  // RAG document management — hook
  const {
    ragDocContent,
    setRagDocContent,
    ragDocType,
    setRagDocType,
    ragDocFilename,
    setRagDocFilename,
    uploadingRagDoc,
    ragUploadResult,
    ragUploadError,
    ragDocList,
    ragDocsLoaded,
    loadRagDocs,
    handleUploadRagDoc,
    handleDeleteRagDoc,
  } = useRagDocs();

  // C5/C6: application tracking — hook
  const {
    trackedAppId,
    pastApplications,
    markingApplied,
    appliedMarked,
    updatingStatus,
    handleMarkApplied,
    handleStatusUpdate: _handleStatusUpdate,
  } = useApplicationTracking(context);

  // T1: application history — hook
  const {
    allApplications,
    setAllApplications,
    historyLoading,
    appStats,
    appFunnel,
    vaultAnalytics,
    historySearch,
    setHistorySearch,
    historyStatusFilter,
    setHistoryStatusFilter,
    answerBankSearch,
    setAnswerBankSearch,
    answerBankResults,
    setAnswerBankResults,
    answerBankSearching,
    setAnswerBankSearching,
  } = useApplicationHistory(tab);

  // T3: interview prep — hook
  const {
    interviewQuestions,
    setInterviewQuestions,
    interviewLoading,
    interviewError,
    expandedPrepIdx,
    setExpandedPrepIdx,
    prepCategoryFilter,
    setPrepCategoryFilter,
    savingAllPrep,
    setSavingAllPrep,
    savedAllPrep,
    setSavedAllPrep,
    handleInterviewPrep,
  } = useInterviewPrep(context);

  // Cover letter — hook
  const {
    coverDrafts,
    setCoverDrafts,
    coverDraftProviders,
    setCoverDraftProviders,
    coverSelectedDraft,
    setCoverSelectedDraft,
    coverLetter,
    setCoverLetter,
    coverLoading,
    coverError,
    coverTone,
    setCoverTone,
    coverWordLimit,
    setCoverWordLimit,
    coverCopied,
    savingCoverLetter,
    savedCoverLetters,
    setSavedCoverLetters,
    coverLettersSectionOpen,
    setCoverLettersSectionOpen,
    handleGenerateCoverLetter,
    handleSaveCoverLetter,
    handleCopyLetter,
  } = useCoverLetter(context);

  // Draft persistence — Q&A drafts are persisted by useQAGeneration; persist cover letter + interview here
  const persistDrafts = useCallback(() => {
    persistQADrafts();
    saveDraftSession(context.jobUrl, "coverLetter", coverLetter);
    saveDraftSession(context.jobUrl, "coverDrafts", coverDrafts);
    saveDraftSession(context.jobUrl, "coverDraftProviders", coverDraftProviders);
    saveDraftSession(context.jobUrl, "interviewQuestions", interviewQuestions);
  }, [persistQADrafts, context.jobUrl, coverLetter, coverDrafts, coverDraftProviders, interviewQuestions]);

  useEffect(() => { persistDrafts(); }, [persistDrafts]);

  // T1: Update application status from History tab — also updates local list
  const handleStatusUpdate = async (appId: string, newStatus: string) => {
    await _handleStatusUpdate(appId, newStatus);
    setAllApplications((prev) => prev.map((a) => a.id === appId ? { ...a, status: newStatus } : a));
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

  const tabs: Array<{ key: Tab; label: string; count: number }> = [
    { key: "resumes", label: "Resumes", count: resumes.length },
    { key: "fields", label: "Fields", count: context.detectedFields.length },
    { key: "questions", label: "Q&A", count: context.openQuestions.length },
    { key: "cover", label: "Cover", count: coverLetter ? 1 : 0 },
    { key: "history", label: "History", count: allApplications.length },
    { key: "prep", label: "Prep", count: interviewQuestions.length },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 45px)", overflow: "hidden" }}>

      {/* Company context bar */}
      <div style={{
        padding: "10px 14px",
        background: "#0a0b0d",
        borderBottom: "1px solid #rgba(255,255,255,0.07)",
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
        {/* Quick "Mark as Applied" button */}
        <button
          onClick={handleMarkApplied}
          disabled={markingApplied || appliedMarked}
          title="Mark this job as Applied in your tracker"
          style={{
            flexShrink: 0,
            background: appliedMarked ? "#166534" : "#0a1628",
            color: appliedMarked ? "#86efac" : "#60a5fa",
            border: `1px solid ${appliedMarked ? "#166534" : "#1e3a5f"}`,
            borderRadius: 8,
            padding: "4px 8px",
            fontSize: 10,
            fontWeight: 700,
            cursor: markingApplied ? "wait" : "pointer",
            transition: "all .2s",
            whiteSpace: "nowrap",
          }}
        >
          {appliedMarked ? "✓ Applied" : markingApplied ? "…" : "✓ Mark Applied"}
        </button>
        {ats && (
          <div style={{
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            background: "#111318",
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
        <div style={{ padding: "8px 14px", borderBottom: "1px solid rgba(255,255,255,0.07)", background: "#0a0b0d", flexShrink: 0 }}>
          <ATSScoreBar score={ats.overallScore} label={`Resume Match · ${ats.matchedKeywords}/${ats.totalJdKeywords} keywords`} />
        </div>
      )}

      {/* Tab navigation */}
      <div style={{
        display: "flex",
        borderBottom: "1px solid rgba(255,255,255,0.07)",
        background: "#0a0b0d",
        flexShrink: 0,
      }}>
        {tabs.map(({ key, label, count }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{
              flex: 1,
              padding: "10px 4px",
              border: "none",
              borderBottom: tab === key ? "2px solid #00c4b4" : "2px solid transparent",
              cursor: "pointer",
              fontSize: 11,
              fontWeight: tab === key ? 600 : 500,
              transition: "all 0.15s",
              background: "transparent",
              color: tab === key ? "#00c4b4" : "#5a6278",
              outline: "none",
              letterSpacing: "0.01em",
            }}
          >
            {label}
            {count > 0 && (
              <span style={{
                marginLeft: 4,
                background: tab === key ? "rgba(0,196,180,0.15)" : "rgba(255,255,255,0.06)",
                color: tab === key ? "#00c4b4" : "#5a6278",
                borderRadius: 99,
                padding: "1px 5px",
                fontSize: 9,
                fontWeight: 700,
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
                      background: "rgba(0,196,180,0.1)",
                      color: "#00c4b4",
                      borderRadius: 99,
                      fontSize: 10,
                      padding: "2px 8px",
                      border: "1px solid rgba(0,196,180,0.2)",
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
                    borderBottom: i < Math.min(ats.suggestions.length, 3) - 1 ? "1px solid rgba(255,255,255,0.07)" : "none",
                  }}>
                    <span style={{ color: "#00c4b4", flexShrink: 0 }}>›</span>
                    <span>{s}</span>
                  </div>
                ))}
              </Section>
            )}

            {/* AI Writing Tools: Summary + Bullets */}
            <Section label="AI Writing Tools">
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  onClick={handleGenerateSummary}
                  disabled={generatingSummary}
                  style={{ ...btnStyle("generate", generatingSummary), flex: 1, fontSize: 10, padding: "5px 8px" }}
                >
                  {generatingSummary ? "Generating…" : "✦ Generate Summary"}
                </button>
                <button
                  onClick={handleGenerateBullets}
                  disabled={generatingBullets}
                  style={{ ...btnStyle("generate", generatingBullets), flex: 1, fontSize: 10, padding: "5px 8px" }}
                >
                  {generatingBullets ? "Generating…" : "✦ Generate Bullets"}
                </button>
              </div>

              {summaryError && (
                <div style={{ fontSize: 10, color: "#f87171", padding: "4px 8px", background: "#1a0808", borderRadius: 5, border: "1px solid #7f1d1d", marginTop: 4 }}>
                  {summaryError}
                </div>
              )}
              {generatedSummary && (
                <div style={{ marginTop: 6, background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 8, padding: "8px 10px" }}>
                  <div style={{ fontSize: 10, color: "#00c4b4", fontWeight: 700, marginBottom: 4, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>Professional Summary</span>
                    <button
                      onClick={() => { navigator.clipboard.writeText(generatedSummary); setSummaryCopied(true); setTimeout(() => setSummaryCopied(false), 2000); }}
                      style={{ ...btnStyle("ghost"), fontSize: 9, padding: "2px 6px" }}
                    >
                      {summaryCopied ? "✓ Copied" : "Copy"}
                    </button>
                  </div>
                  <p style={{ margin: 0, fontSize: 11, color: "#cbd5e1", lineHeight: 1.6 }}>{generatedSummary}</p>
                </div>
              )}

              {bulletsError && (
                <div style={{ fontSize: 10, color: "#f87171", padding: "4px 8px", background: "#1a0808", borderRadius: 5, border: "1px solid #7f1d1d", marginTop: 4 }}>
                  {bulletsError}
                </div>
              )}
              {generatedBullets.length > 0 && (
                <div style={{ marginTop: 6, background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 8, padding: "8px 10px" }}>
                  <div style={{ fontSize: 10, color: "#00c4b4", fontWeight: 700, marginBottom: 6, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>Resume Bullets</span>
                    <button
                      onClick={() => { navigator.clipboard.writeText(generatedBullets.map((b) => `• ${b}`).join("\n")); setBulletsCopied(true); setTimeout(() => setBulletsCopied(false), 2000); }}
                      style={{ ...btnStyle("ghost"), fontSize: 9, padding: "2px 6px" }}
                    >
                      {bulletsCopied ? "✓ Copied" : "Copy All"}
                    </button>
                  </div>
                  {generatedBullets.map((bullet, i) => (
                    <div key={i} style={{ display: "flex", gap: 6, fontSize: 11, color: "#cbd5e1", lineHeight: 1.5, padding: "3px 0", borderBottom: i < generatedBullets.length - 1 ? "1px solid rgba(255,255,255,0.07)" : "none" }}>
                      <span style={{ color: "#00c4b4", flexShrink: 0 }}>•</span>
                      <span>{bullet}</span>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            {/* RAG Document Upload */}
            <Section label="RAG Context Docs">
              <div style={{ fontSize: 10, color: "#94a3b8", marginBottom: 6, lineHeight: 1.5 }}>
                Paste your <strong style={{ color: "#00c4b4" }}>resume.md</strong> or <strong style={{ color: "#00c4b4" }}>work history</strong> — used to ground cover letters &amp; answers with your real experience.
              </div>

              {/* Existing docs */}
              {!ragDocsLoaded && (
                <button onClick={loadRagDocs} style={{ ...btnStyle("ghost"), fontSize: 9, padding: "3px 8px", marginBottom: 6 }}>
                  Load uploaded docs
                </button>
              )}
              {ragDocsLoaded && ragDocList.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  {ragDocList.map((doc) => (
                    <div key={doc.source_filename} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 8px", background: "#111318", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 6, marginBottom: 3 }}>
                      <div>
                        <div style={{ fontSize: 10, color: "#00c4b4", fontWeight: 700 }}>{doc.source_filename}</div>
                        <div style={{ fontSize: 9, color: "#475569" }}>{doc.chunk_count} chunks · {doc.doc_type}{doc.has_dense_embeddings ? " · dense" : ""}</div>
                      </div>
                      <button
                        onClick={() => handleDeleteRagDoc(doc.source_filename)}
                        style={{ ...btnStyle("ghost"), fontSize: 9, padding: "2px 6px", color: "#f87171" }}
                        title="Delete"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Upload form */}
              <div style={{ display: "flex", gap: 6, marginBottom: 4 }}>
                <select
                  value={ragDocType}
                  onChange={(e) => {
                    const t = e.target.value as "resume" | "work_history";
                    setRagDocType(t);
                    setRagDocFilename(t === "resume" ? "resume.md" : "work_history.md");
                  }}
                  style={{ fontSize: 10, background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", color: "#00c4b4", borderRadius: 5, padding: "3px 6px", flex: 1 }}
                >
                  <option value="resume">resume.md</option>
                  <option value="work_history">work_history.md</option>
                </select>
                <input
                  value={ragDocFilename}
                  onChange={(e) => setRagDocFilename(e.target.value)}
                  style={{ fontSize: 10, background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", color: "#94a3b8", borderRadius: 5, padding: "3px 6px", flex: 1 }}
                  placeholder="filename.md"
                />
              </div>
              <textarea
                value={ragDocContent}
                onChange={(e) => setRagDocContent(e.target.value)}
                placeholder={"Paste your resume.md or work_history.md content here…"}
                rows={4}
                style={{ width: "100%", fontSize: 10, background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", color: "#94a3b8", borderRadius: 6, padding: "6px 8px", resize: "vertical", boxSizing: "border-box", lineHeight: 1.5 }}
              />
              <button
                onClick={handleUploadRagDoc}
                disabled={uploadingRagDoc || !ragDocContent.trim()}
                style={{ ...btnStyle("generate", uploadingRagDoc || !ragDocContent.trim()), marginTop: 4, width: "100%", fontSize: 10 }}
              >
                {uploadingRagDoc ? "Chunking & uploading…" : "⬆ Upload to RAG Pipeline"}
              </button>
              {ragUploadError && (
                <div style={{ fontSize: 10, color: "#f87171", padding: "4px 8px", background: "#1a0808", borderRadius: 5, border: "1px solid #7f1d1d", marginTop: 4 }}>
                  {ragUploadError}
                </div>
              )}
              {ragUploadResult && (
                <div style={{ fontSize: 10, color: "#6ee7b7", padding: "4px 8px", background: "#071a12", borderRadius: 5, border: "1px solid #064e3b", marginTop: 4 }}>
                  {ragUploadResult}
                </div>
              )}
            </Section>

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
                onClick={() => { clearUploadFeedback(); fileInputRef.current?.click(); }}
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
                <div key={r.resumeId}>
                  <ResumeCardComponent resume={r} onAttach={() => handleAttach(r)} />
                  {/* View content inline + Rename */}
                  <div style={{ display: "flex", gap: 6, marginTop: 4, marginBottom: context.jdText ? 0 : 8 }}>
                    <button
                      onClick={() => void handleViewResume(r.resumeId)}
                      style={{ ...btnStyle("ghost"), fontSize: 10, padding: "3px 8px" }}
                    >
                      {viewingResumeId === r.resumeId ? "Hide" : "View"}
                    </button>
                    <button
                      onClick={() => {
                        if (renamingResumeId === r.resumeId) { setRenamingResumeId(null); return; }
                        setRenameTag(r.versionTag ?? r.filename ?? "");
                        setRenamingResumeId(r.resumeId);
                      }}
                      style={{ ...btnStyle("ghost"), fontSize: 10, padding: "3px 8px" }}
                    >
                      {renamingResumeId === r.resumeId ? "Cancel" : "Rename"}
                    </button>
                  </div>
                  {renamingResumeId === r.resumeId && (
                    <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                      <input
                        type="text"
                        value={renameTag}
                        onChange={(e) => setRenameTag(e.target.value)}
                        placeholder="Version tag (e.g. v2, Q2-2025)"
                        style={{ flex: 1, background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 6, color: "#e2e8f0", fontSize: 11, padding: "4px 8px", outline: "none" }}
                      />
                      <button
                        onClick={() => void handleRenameResume(r.resumeId, renameTag).catch(() => {})}
                        style={{ ...btnStyle("primary"), fontSize: 10, padding: "4px 10px" }}
                      >
                        Save
                      </button>
                    </div>
                  )}
                  {viewingResumeId === r.resumeId && (
                    <div style={{ marginBottom: 6, background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 8, padding: "8px 10px", maxHeight: 300, overflowY: "auto" }}>
                      <pre style={{ margin: 0, fontSize: 10, color: "#94a3b8", whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "system-ui,sans-serif", lineHeight: 1.5 }}>
                        {resumeContent}
                      </pre>
                    </div>
                  )}
                  {/* L6: Tailor for this job button */}
                  {context.jdText && (
                    <div style={{ marginTop: 4, marginBottom: 8 }}>
                      <button
                        onClick={() => handleTailorResume(r.resumeId)}
                        disabled={tailoringResumeId === r.resumeId}
                        style={{ ...btnStyle("generate", tailoringResumeId === r.resumeId), fontSize: 10, padding: "4px 10px", width: "auto" }}
                      >
                        {tailoringResumeId === r.resumeId ? "Tailoring…" : "✦ Tailor for this Job"}
                      </button>
                      {tailorErrors[r.resumeId] && (
                        <div style={{ fontSize: 10, color: "#f87171", marginTop: 3, padding: "3px 6px", background: "#1a0808", borderRadius: 5, border: "1px solid #7f1d1d" }}>
                          {tailorErrors[r.resumeId]}
                        </div>
                      )}
                      {tailorResults[r.resumeId] && (
                        <TailoredResumeResult result={tailorResults[r.resumeId]} />
                      )}
                    </div>
                  )}
                </div>
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
                <EmptyState message="No fillable fields detected." hint="Navigate directly to the application form page. If fields still don't appear, try clicking a text field on the form to trigger detection." />
              ) : (
                context.detectedFields.map((f) => {
                  const profileVal = getProfileValue(f.fieldType, profile);
                  return (
                    <div key={f.fieldId} style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "7px 10px",
                      background: "#111318",
                      border: "1px solid #rgba(255,255,255,0.07)",
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
              <EmptyState message="No open questions detected." hint="Questions appear when text areas are found on the application form. Try scrolling to or clicking on a text field on the page." />
            ) : (
              context.openQuestions.map((q) => {
                const drafts = answerDrafts[q.questionId];
                const selectedIdx = selectedAnswers[q.questionId] ?? 0;
                const isGenerating = generatingAnswer === q.questionId;
                return (
                  <div key={q.questionId} style={{
                    background: "#111318",
                    border: "1px solid #rgba(255,255,255,0.07)",
                    borderRadius: 10,
                    padding: "10px 12px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}>
                    <div style={{ fontSize: 12, color: "#00c4b4", fontWeight: 600, lineHeight: 1.4 }}>
                      {q.questionText.slice(0, 130)}{q.questionText.length > 130 ? "…" : ""}
                    </div>
                    <div style={{ display: "flex", gap: 6, fontSize: 10, color: "#475569" }}>
                      <span style={{ background: "rgba(255,255,255,0.07)", borderRadius: 4, padding: "1px 6px" }}>{q.category.replace(/_/g, " ")}</span>
                      {q.maxLength && (
                        <span style={{ background: "rgba(255,255,255,0.07)", borderRadius: 4, padding: "1px 6px" }}>max {q.maxLength}</span>
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
                            <div style={{ display: "flex", gap: 6 }}>
                              <button
                                onClick={() => handleUseMemoryAnswer(q.questionId, q.questionText, q.category, mem)}
                                style={{ ...btnStyle("fill"), fontSize: 10, background: "#064e3b", color: "#6ee7b7" }}
                              >
                                Use This
                              </button>
                              <button
                                onClick={async () => {
                                  try {
                                    await vaultApi.deleteAnswer(mem.answer_id);
                                    setMemoryAnswers((prev) => ({
                                      ...prev,
                                      [q.questionId]: (prev[q.questionId] ?? []).filter((a) => a.answer_id !== mem.answer_id),
                                    }));
                                  } catch { /* silently ignore */ }
                                }}
                                style={{ ...btnStyle("ghost"), fontSize: 10, padding: "3px 8px", color: "#f87171", border: "1px solid #7f1d1d" }}
                                title="Remove from bank"
                              >
                                ✕
                              </button>
                            </div>
                          </div>
                        ))}
                        <div style={{ height: 1, background: "rgba(255,255,255,0.07)", margin: "2px 0" }} />
                      </div>
                    )}

                    {!drafts?.length ? (
                      <>
                        <button
                          onClick={() => handleGenerateAnswers(q.questionId, q.questionText, q.category, false, q.maxLength)}
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
                                background: selectedIdx === i ? "#4f46e5" : "rgba(255,255,255,0.07)",
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
                            background: "#0a0b0d",
                            borderRadius: 8,
                            padding: "8px 10px",
                            border: "1px solid #rgba(255,255,255,0.07)",
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
                        {/* Char counter + trim button when answer exceeds field limit */}
                        {(() => {
                          const currentText = editedTexts[q.questionId] ?? drafts[selectedIdx];
                          const charCount = currentText?.length ?? 0;
                          const overLimit = q.maxLength && charCount > q.maxLength;
                          return overLimit ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              <span style={{ fontSize: 10, color: "#f87171", fontWeight: 600 }}>
                                {charCount}/{q.maxLength} chars
                              </span>
                              <button
                                onClick={() => handleTrimAnswer(q.questionId, q.maxLength!)}
                                disabled={trimmingAnswer === q.questionId}
                                style={{ ...btnStyle("ghost", trimmingAnswer === q.questionId), fontSize: 10, padding: "2px 8px" }}
                              >
                                {trimmingAnswer === q.questionId ? "Trimming…" : "✂ Trim to limit"}
                              </button>
                            </div>
                          ) : q.maxLength ? (
                            <span style={{ fontSize: 10, color: "#4ade80" }}>{charCount}/{q.maxLength} chars</span>
                          ) : null;
                        })()}
                        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                          <button
                            onClick={() => handleGenerateAnswers(q.questionId, q.questionText, q.category, true, q.maxLength)}
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
            {/* Copy All Answers button */}
            {context.openQuestions.length > 0 && Object.keys(answerDrafts).length > 0 && (
              <div style={{ marginTop: 8, display: "flex", justifyContent: "flex-end" }}>
                <button
                  onClick={() => {
                    const lines = context.openQuestions.flatMap((q) => {
                      const drafts = answerDrafts[q.questionId];
                      const selectedIdx = selectedAnswers[q.questionId] ?? 0;
                      const text = editedTexts[q.questionId] ?? drafts?.[selectedIdx] ?? "";
                      if (!text) return [];
                      return [`Q: ${q.questionText}`, `A: ${text}`, ""];
                    });
                    navigator.clipboard.writeText(lines.join("\n"));
                    setCopiedAllAnswers(true);
                    setTimeout(() => setCopiedAllAnswers(false), 2000);
                  }}
                  style={{ ...btnStyle("ghost"), fontSize: 10, padding: "4px 12px" }}
                >
                  {copiedAllAnswers ? "✓ Copied All" : "Copy All Answers"}
                </button>
              </div>
            )}
          </Section>
        )}
        {/* HISTORY TAB */}
        {tab === "history" && (
          <>
            {/* Stats row */}
            {appStats && (
              <div style={{ display: "flex", gap: 8, marginBottom: 2 }}>
                {[
                  { label: "Total", value: appStats.total },
                  { label: "Companies", value: appStats.unique_companies },
                  { label: "Interviews", value: appStats.by_status?.interview ?? 0 },
                  { label: "Offers", value: appStats.by_status?.offer ?? 0 },
                ].map(({ label, value }) => (
                  <div key={label} style={{ flex: 1, textAlign: "center", background: "#111318", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 8, padding: "6px 4px" }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: "#00c4b4" }}>{value}</div>
                    <div style={{ fontSize: 9, color: "#475569", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Application funnel */}
            {appFunnel && appFunnel.total > 0 && (
              <Section label="Application Funnel">
                {/* Rate badges */}
                <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
                  {[
                    { label: "Response Rate", value: `${appFunnel.response_rate_pct}%`, color: "#10b981" },
                    { label: "Offer Rate", value: `${appFunnel.offer_rate_pct}%`, color: "#00c4b4" },
                  ].map(({ label, value, color }) => (
                    <div key={label} style={{ flex: 1, textAlign: "center", background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 8, padding: "5px 4px" }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color }}>{value}</div>
                      <div style={{ fontSize: 8, color: "#475569", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                    </div>
                  ))}
                </div>
                {/* Stage bars */}
                {appFunnel.funnel.filter(s => s.count > 0).map(({ stage, count, pct_of_total }) => {
                  const stageColor: Record<string, string> = {
                    discovered: "#475569", applied: "#3b82f6", tailored: "#00c4b4",
                    phone_screen: "#f59e0b", interview: "#f97316", offer: "#10b981", rejected: "#f87171",
                  };
                  const barColor = stageColor[stage] ?? "#64748b";
                  const barWidth = Math.max(pct_of_total, 3);
                  return (
                    <div key={stage} style={{ marginBottom: 4 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                        <span style={{ fontSize: 10, color: "#94a3b8", textTransform: "capitalize" }}>{stage.replace("_", " ")}</span>
                        <span style={{ fontSize: 10, color: "#64748b" }}>{count} ({pct_of_total}%)</span>
                      </div>
                      <div style={{ height: 6, background: "rgba(255,255,255,0.07)", borderRadius: 3, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${barWidth}%`, background: barColor, borderRadius: 3, transition: "width 0.4s ease" }} />
                      </div>
                    </div>
                  );
                })}
                {/* 30-day volume sparkline (simple text bars) */}
                {appFunnel.daily_volume_30d.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 9, color: "#475569", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>30-Day Activity</div>
                    <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 28 }}>
                      {(() => {
                        const maxCount = Math.max(...appFunnel.daily_volume_30d.map(d => d.count), 1);
                        // Fill all 30 days
                        const today = new Date();
                        const days: Record<string, number> = {};
                        appFunnel.daily_volume_30d.forEach(d => { days[d.date] = d.count; });
                        return Array.from({ length: 30 }, (_, i) => {
                          const d = new Date(today);
                          d.setDate(d.getDate() - (29 - i));
                          const key = d.toISOString().slice(0, 10);
                          const c = days[key] ?? 0;
                          const h = Math.round((c / maxCount) * 26) + 2;
                          return (
                            <div key={key} title={`${key}: ${c}`} style={{
                              flex: 1, height: h, background: c > 0 ? "#00c4b4" : "rgba(255,255,255,0.07)",
                              borderRadius: 2, minWidth: 2, cursor: "default",
                            }} />
                          );
                        });
                      })()}
                    </div>
                  </div>
                )}
              </Section>
            )}

            {/* Vault analytics mini-dashboard */}
            {vaultAnalytics && (
              <Section label="Answer Vault Stats">
                <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
                  {[
                    { label: "Answers Saved", value: vaultAnalytics.answers.total },
                    { label: "Resumes", value: vaultAnalytics.resumes.total },
                    { label: "Avg Reward", value: vaultAnalytics.answers.avg_reward_score != null ? vaultAnalytics.answers.avg_reward_score.toFixed(2) : "—" },
                    { label: "Accept Rate", value: (() => { const used = vaultAnalytics.answers.feedback_distribution["used_as_is"] ?? 0; const total = vaultAnalytics.answers.total; return total > 0 ? `${Math.round(used / total * 100)}%` : "—"; })() },
                  ].map(({ label, value }) => (
                    <div key={label} style={{ flex: 1, textAlign: "center", background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 8, padding: "5px 2px" }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: "#00c4b4" }}>{value}</div>
                      <div style={{ fontSize: 8, color: "#475569", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                    </div>
                  ))}
                </div>
                {vaultAnalytics.top_companies_by_answers.length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {vaultAnalytics.top_companies_by_answers.slice(0, 5).map(({ company, answer_count }) => (
                      <span key={company} style={{ background: "#111318", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 99, fontSize: 9, padding: "2px 7px", color: "#00c4b4" }}>
                        {company} <span style={{ color: "#475569" }}>({answer_count})</span>
                      </span>
                    ))}
                  </div>
                )}
              </Section>
            )}

            {/* Answer bank search */}
            <Section label="Search Answer Bank">
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  type="text"
                  placeholder="Search past answers…"
                  value={answerBankSearch}
                  onChange={(e) => setAnswerBankSearch(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key !== "Enter" || !answerBankSearch.trim()) return;
                    setAnswerBankSearching(true);
                    setAnswerBankResults([]);
                    try {
                      const res = await vaultApi.searchAnswers({ q: answerBankSearch.trim(), limit: 10 });
                      setAnswerBankResults(res.answers as typeof answerBankResults);
                    } catch { /* silently ignore */ } finally {
                      setAnswerBankSearching(false);
                    }
                  }}
                  style={{ flex: 1, background: "#111318", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 6, color: "#e2e8f0", fontSize: 11, padding: "5px 8px", outline: "none" }}
                />
                <button
                  onClick={async () => {
                    if (!answerBankSearch.trim()) return;
                    setAnswerBankSearching(true);
                    setAnswerBankResults([]);
                    try {
                      const res = await vaultApi.searchAnswers({ q: answerBankSearch.trim(), limit: 10 });
                      setAnswerBankResults(res.answers as typeof answerBankResults);
                    } catch { /* silently ignore */ } finally {
                      setAnswerBankSearching(false);
                    }
                  }}
                  disabled={answerBankSearching}
                  style={{ ...btnStyle("ghost", answerBankSearching), fontSize: 10, padding: "5px 10px" }}
                >
                  {answerBankSearching ? "…" : "Search"}
                </button>
              </div>
              {answerBankResults.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                  {answerBankResults.map((a) => (
                    <AnswerBankCard
                      key={a.answer_id}
                      answer={a}
                      onDelete={() => setAnswerBankResults((prev) => prev.filter((x) => x.answer_id !== a.answer_id))}
                      onEdit={(newText) => setAnswerBankResults((prev) => prev.map((x) => x.answer_id === a.answer_id ? { ...x, answer_text: newText } : x))}
                    />
                  ))}
                </div>
              )}
              {!answerBankSearching && answerBankResults.length === 0 && answerBankSearch.trim() && (
                <div style={{ fontSize: 10, color: "#475569", marginTop: 4, textAlign: "center" }}>No results — try a different term.</div>
              )}
            </Section>

            {/* Export + Search + Filter bar */}
            <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
              <input
                type="text"
                placeholder="Search company or role…"
                value={historySearch}
                onChange={(e) => setHistorySearch(e.target.value)}
                style={{
                  flex: 1,
                  background: "#111318",
                  border: "1px solid #rgba(255,255,255,0.07)",
                  borderRadius: 6,
                  color: "#e2e8f0",
                  fontSize: 11,
                  padding: "5px 8px",
                  outline: "none",
                }}
              />
              <select
                value={historyStatusFilter}
                onChange={(e) => setHistoryStatusFilter(e.target.value)}
                style={{
                  background: "#111318",
                  border: "1px solid #rgba(255,255,255,0.07)",
                  borderRadius: 6,
                  color: "#9ca3af",
                  fontSize: 11,
                  padding: "5px 6px",
                  outline: "none",
                }}
              >
                <option value="all">All</option>
                <option value="discovered">Discovered</option>
                <option value="applied">Applied</option>
                <option value="tailored">Tailored</option>
                <option value="interview">Interview</option>
                <option value="offer">Offer</option>
                <option value="rejected">Rejected</option>
              </select>
              <button
                onClick={() => applicationsApi.exportCsv().catch(() => {})}
                style={{ ...btnStyle("ghost"), fontSize: 10, padding: "5px 8px", whiteSpace: "nowrap" }}
                title="Export all applications as CSV"
              >
                ⬇ CSV
              </button>
            </div>

            <Section label="All Applications">
              {historyLoading && <LoadingRow />}
              {!historyLoading && allApplications.length === 0 && (
                <EmptyState message="No applications tracked yet." hint="Applications are recorded automatically when you visit job pages." />
              )}
              {(() => {
                const q = historySearch.toLowerCase();
                const filtered = allApplications.filter((app) => {
                  const matchesSearch = !q ||
                    app.company_name.toLowerCase().includes(q) ||
                    app.role_title.toLowerCase().includes(q);
                  const matchesStatus = historyStatusFilter === "all" || app.status === historyStatusFilter;
                  return matchesSearch && matchesStatus;
                });
                if (!historyLoading && filtered.length === 0 && allApplications.length > 0) {
                  return <EmptyState message="No matches." hint="Try adjusting the search or filter." />;
                }
                return filtered.map((app) => (
                  <ApplicationRow
                    key={app.id}
                    app={app}
                    updating={updatingStatus === app.id}
                    onStatusChange={(s) => handleStatusUpdate(app.id, s)}
                    onNotesChange={async (notes) => {
                      await applicationsApi.updateNotes(app.id, notes);
                      setAllApplications((prev) => prev.map((a) => a.id === app.id ? { ...a, notes } : a));
                    }}
                  />
                ));
              })()}
            </Section>
          </>
        )}

        {/* T3 — Interview Prep tab */}
        {tab === "prep" && (
          <>
            <div style={{ marginBottom: 10 }}>
              <button
                onClick={handleInterviewPrep}
                disabled={interviewLoading || !context.company}
                style={{
                  width: "100%",
                  padding: "10px",
                  background: "linear-gradient(135deg,#009688 0%,#4f46e5 100%)",
                  color: "#fff",
                  border: "none",
                  borderRadius: 8,
                  fontSize: 12,
                  fontWeight: 700,
                  cursor: interviewLoading ? "not-allowed" : "pointer",
                  opacity: interviewLoading ? 0.6 : 1,
                }}
              >
                {interviewLoading ? "Generating questions…" : `⚡ Generate Interview Prep for ${context.company || "this role"}`}
              </button>
              {interviewError && (
                <div style={{ marginTop: 6, fontSize: 11, color: "#f87171" }}>{interviewError}</div>
              )}
            </div>

            {interviewQuestions.length === 0 && !interviewLoading && (
              <EmptyState
                message="No questions generated yet."
                hint="Click the button above to generate 10 likely interview questions with suggested answers."
              />
            )}

            {interviewQuestions.length > 0 && (
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 4 }}>
                {(["all", "behavioral", "motivation", "technical", "general"] as const).map((cat) => {
                  const count = cat === "all" ? interviewQuestions.length : interviewQuestions.filter((q) => q.category === cat).length;
                  if (cat !== "all" && count === 0) return null;
                  const isActive = prepCategoryFilter === cat;
                  return (
                    <button
                      key={cat}
                      onClick={() => { setPrepCategoryFilter(cat); setExpandedPrepIdx(null); }}
                      style={{
                        background: isActive ? (CATEGORY_COLORS[cat] ?? "#475569") + "22" : "#111318",
                        border: `1px solid ${isActive ? (CATEGORY_COLORS[cat] ?? "#475569") : "#rgba(255,255,255,0.07)"}`,
                        borderRadius: 99,
                        padding: "2px 8px",
                        fontSize: 9,
                        fontWeight: 700,
                        color: CATEGORY_COLORS[cat] ?? "#475569",
                        cursor: "pointer",
                      }}
                    >
                      {cat === "all" ? `All (${count})` : `${cat} (${count})`}
                    </button>
                  );
                })}
              </div>
            )}

            {interviewQuestions.length > 0 && (
              <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
                <button
                  onClick={async () => {
                    if (!context.company || savingAllPrep) return;
                    setSavingAllPrep(true);
                    try {
                      await vaultApi.bulkSaveAnswers({
                        companyName: context.company,
                        roleTitle: context.roleTitle,
                        answers: interviewQuestions.map((q) => ({
                          questionText: q.question,
                          questionCategory: q.category === "behavioral" ? "challenge" : q.category === "motivation" ? "motivation" : "custom",
                          answerText: q.suggested_answer,
                          wasDefault: true,
                        })),
                      });
                      setSavedAllPrep(true);
                      setTimeout(() => setSavedAllPrep(false), 3000);
                    } catch { /* silently ignore */ } finally {
                      setSavingAllPrep(false);
                    }
                  }}
                  disabled={savingAllPrep || !context.company}
                  style={{ ...btnStyle("ghost", savingAllPrep), fontSize: 10, padding: "4px 12px" }}
                >
                  {savingAllPrep ? "Saving…" : savedAllPrep ? "✓ Saved All" : "Save All to Bank"}
                </button>
              </div>
            )}

            {interviewQuestions
              .filter((q) => prepCategoryFilter === "all" || q.category === prepCategoryFilter)
              .map((q, idx) => (
                <PrepQuestion
                  key={idx}
                  question={q}
                  index={idx}
                  expanded={expandedPrepIdx === idx}
                  onToggle={() => setExpandedPrepIdx(expandedPrepIdx === idx ? null : idx)}
                  onSaveToBank={async () => {
                    await vaultApi.saveAnswer({
                      questionText: q.question,
                      questionCategory: q.category === "behavioral" ? "challenge" : q.category === "motivation" ? "motivation" : "custom",
                      answerText: q.suggested_answer,
                      companyName: context.company,
                      roleTitle: context.roleTitle,
                      wasDefault: true,
                    });
                  }}
                />
              ))}
          </>
        )}

        {/* Cover Letter tab */}
        {tab === "cover" && (
          <>
            {/* Controls */}
            <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
              <select
                value={coverTone}
                onChange={(e) => setCoverTone(e.target.value as typeof coverTone)}
                style={{ background: "#111318", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 6, color: "#9ca3af", fontSize: 11, padding: "5px 6px", outline: "none" }}
              >
                <option value="professional">Professional</option>
                <option value="enthusiastic">Enthusiastic</option>
                <option value="concise">Concise</option>
              </select>
              <select
                value={coverWordLimit}
                onChange={(e) => setCoverWordLimit(Number(e.target.value) as typeof coverWordLimit)}
                style={{ background: "#111318", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 6, color: "#9ca3af", fontSize: 11, padding: "5px 6px", outline: "none" }}
              >
                <option value={300}>~300 words</option>
                <option value={400}>~400 words</option>
                <option value={500}>~500 words</option>
              </select>
              <button
                onClick={handleGenerateCoverLetter}
                disabled={coverLoading}
                style={{ ...btnStyle("generate", coverLoading), flex: 1, minWidth: 100 }}
              >
                {coverLoading ? "Generating…" : "⚡ Generate"}
              </button>
            </div>

            {coverError && (
              <div style={{ fontSize: 11, color: "#f87171", marginBottom: 8 }}>{coverError}</div>
            )}

            {!coverLetter && !coverLoading && (
              <EmptyState
                message="No cover letter yet."
                hint={`Select tone and word length above, then click Generate to create a cover letter for ${context.company || "this company"}.`}
              />
            )}

            {coverLetter && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {coverDrafts.length > 1 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {coverDrafts.map((_, i) => (
                      <button
                        key={i}
                        onClick={() => { setCoverSelectedDraft(i); setCoverLetter(coverDrafts[i]); }}
                        style={{
                          background: coverSelectedDraft === i ? "#3730a3" : "#111318",
                          color: coverSelectedDraft === i ? "#00c4b4" : "#64748b",
                          border: `1px solid ${coverSelectedDraft === i ? "#4f46e5" : "#rgba(255,255,255,0.07)"}`,
                          borderRadius: 6,
                          padding: "3px 10px",
                          fontSize: 10,
                          fontWeight: 600,
                          cursor: "pointer",
                        }}
                      >
                        Draft {i + 1}{coverDraftProviders[i] ? ` (${coverDraftProviders[i]})` : ""}
                      </button>
                    ))}
                  </div>
                )}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 10, color: "#475569" }}>
                    {coverLetter.split(/\s+/).filter(Boolean).length} words
                  </span>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      onClick={() => void handleSaveCoverLetter()}
                      disabled={savingCoverLetter}
                      style={{ background: "#111318", color: "#00c4b4", border: "1px solid rgba(0,196,180,0.15)", borderRadius: 6, padding: "3px 10px", fontSize: 10, fontWeight: 600, cursor: savingCoverLetter ? "wait" : "pointer", opacity: savingCoverLetter ? 0.6 : 1 }}
                    >
                      {savingCoverLetter ? "Saving…" : "Save"}
                    </button>
                    <button
                      onClick={handleCopyLetter}
                      style={{
                        background: coverCopied ? "#166534" : "#1e1e3a",
                        color: coverCopied ? "#86efac" : "#00c4b4",
                        border: `1px solid ${coverCopied ? "#166534" : "#3730a3"}`,
                        borderRadius: 6,
                        padding: "3px 10px",
                        fontSize: 10,
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      {coverCopied ? "✓ Copied" : "Copy"}
                    </button>
                  </div>
                </div>
                <textarea
                  value={coverLetter}
                  onChange={(e) => setCoverLetter(e.target.value)}
                  style={{
                    width: "100%",
                    minHeight: 320,
                    background: "#0a0b0d",
                    border: "1px solid #rgba(255,255,255,0.07)",
                    borderRadius: 8,
                    color: "#e2e8f0",
                    fontSize: 12,
                    lineHeight: 1.6,
                    padding: "10px 12px",
                    outline: "none",
                    resize: "vertical",
                    fontFamily: "system-ui, sans-serif",
                  }}
                />
              </div>
            )}

            {/* Past saved cover letters for this company */}
            <div style={{ marginTop: 8 }}>
              <button
                onClick={async () => {
                  if (!coverLettersSectionOpen) {
                    try {
                      const res = await vaultApi.listCoverLetters(context.company, 10);
                      setSavedCoverLetters(res.items);
                    } catch { /* ignore */ }
                  }
                  setCoverLettersSectionOpen((v) => !v);
                }}
                style={{ background: "transparent", border: "none", color: "#475569", cursor: "pointer", fontSize: 10, fontWeight: 700, padding: 0 }}
              >
                {coverLettersSectionOpen ? "▲ Hide past letters" : "▼ Past saved letters"}
              </button>
              {coverLettersSectionOpen && (
                <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
                  {savedCoverLetters.length === 0 && (
                    <div style={{ fontSize: 11, color: "#374151" }}>No saved cover letters yet.</div>
                  )}
                  {savedCoverLetters.map((cl) => (
                    <div key={cl.id} style={{ background: "#111318", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 8, padding: "8px 10px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                        <span style={{ fontSize: 11, color: "#00c4b4", fontWeight: 600 }}>{cl.company_name}{cl.role_title ? ` — ${cl.role_title}` : ""}</span>
                        <span style={{ fontSize: 9, color: "#374151" }}>{new Date(cl.created_at).toLocaleDateString()}</span>
                      </div>
                      <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 6, lineHeight: 1.5 }}>
                        {cl.answer_text.slice(0, 120)}…
                      </div>
                      <button
                        onClick={() => { setCoverLetter(cl.answer_text); setCoverLettersSectionOpen(false); }}
                        style={{ background: "rgba(255,255,255,0.07)", border: "1px solid rgba(0,196,180,0.15)", borderRadius: 5, color: "#00c4b4", cursor: "pointer", fontSize: 10, fontWeight: 700, padding: "3px 10px" }}
                      >
                        Load
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
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
      background: "#111318",
      border: "1px dashed #rgba(255,255,255,0.07)",
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
          background: "linear-gradient(90deg, #111318 25%, rgba(255,255,255,0.07) 50%, #111318 75%)",
          borderRadius: 10,
          border: "1px solid #rgba(255,255,255,0.07)",
          animation: "pulse 1.5s ease infinite",
        }} />
      ))}
    </div>
  );
}

function TailoredResumeResult({ result }: { result: GenerateTailoredResponse }) {
  const [expanded, setExpanded] = React.useState(false);
  const scoreBefore = result.ats_score_before;
  const scoreAfter = result.ats_score_estimate;
  const improved = scoreAfter != null && scoreBefore != null && scoreAfter > scoreBefore;

  return (
    <div style={{ background: "#071a12", border: "1px solid #064e3b", borderRadius: 8, padding: "8px 10px", marginTop: 4, display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 11, color: "#34d399", fontWeight: 700 }}>
          ✓ Tailored · {result.version_tag}
        </span>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {scoreBefore != null && scoreAfter != null && (
            <span style={{ fontSize: 10, color: improved ? "#6ee7b7" : "#94a3b8", fontWeight: 600 }}>
              ATS: {scoreBefore.toFixed(0)} → {scoreAfter.toFixed(0)} {improved ? "↑" : ""}
            </span>
          )}
          <button onClick={() => setExpanded((v) => !v)} style={{ ...btnStyle("ghost"), fontSize: 10, padding: "2px 8px" }}>
            {expanded ? "Hide" : "Preview"}
          </button>
        </div>
      </div>
      {result.changes_summary && (
        <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.5 }}>{result.changes_summary.slice(0, 150)}{result.changes_summary.length > 150 ? "…" : ""}</div>
      )}
      {result.skills_gap.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
          {result.skills_gap.slice(0, 5).map((s) => (
            <span key={s} style={{ fontSize: 9, background: "rgba(0,196,180,0.1)", color: "#00c4b4", borderRadius: 99, padding: "1px 7px", border: "1px solid rgba(0,196,180,0.2)" }}>{s}</span>
          ))}
        </div>
      )}
      {expanded && result.markdown_preview && (
        <div style={{ fontSize: 10, color: "#94a3b8", lineHeight: 1.6, maxHeight: 200, overflowY: "auto", whiteSpace: "pre-wrap", background: "#0a0b0d", borderRadius: 6, padding: "8px", fontFamily: "monospace", border: "1px solid rgba(255,255,255,0.07)" }}>
          {result.markdown_preview}
        </div>
      )}
      {result.warnings.length > 0 && (
        <div style={{ fontSize: 9, color: "#f59e0b", lineHeight: 1.4 }}>{result.warnings[0]}</div>
      )}
    </div>
  );
}

const STATUS_ORDER = ["discovered", "applied", "tailored", "interview", "offer", "rejected"];
const STATUS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  discovered: { bg: "#111318", text: "#475569", border: "#rgba(255,255,255,0.07)" },
  applied:    { bg: "#0a1628", text: "#60a5fa", border: "#1e3a5f" },
  tailored:   { bg: "#0d1a2e", text: "#818cf8", border: "#1e2d55" },
  interview:  { bg: "#071a12", text: "#34d399", border: "#064e3b" },
  offer:      { bg: "#0e1a04", text: "#86efac", border: "#166534" },
  rejected:   { bg: "#1a0808", text: "#f87171", border: "#7f1d1d" },
};

function ApplicationRow({
  app,
  updating,
  onStatusChange,
  onNotesChange,
}: {
  app: TrackedApplication;
  updating: boolean;
  onStatusChange: (s: string) => void;
  onNotesChange?: (notes: string | null) => Promise<void>;
}) {
  const [showMenu, setShowMenu] = React.useState(false);
  const [showNotes, setShowNotes] = React.useState(false);
  const [notesText, setNotesText] = React.useState(app.notes ?? "");
  const [savingNotes, setSavingNotes] = React.useState(false);
  const colors = STATUS_COLORS[app.status] ?? STATUS_COLORS.discovered;

  const handleSaveNotes = async () => {
    if (!onNotesChange) return;
    setSavingNotes(true);
    try { await onNotesChange(notesText.trim() || null); } catch { /* ignore */ } finally { setSavingNotes(false); setShowNotes(false); }
  };

  return (
    <div style={{ background: "#111318", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 8, padding: "8px 10px" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, color: "#e2e8f0", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {app.company_name}
        </div>
        <div style={{ fontSize: 10, color: "#64748b", marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {app.role_title}
        </div>
        <div style={{ fontSize: 9, color: "#374151", marginTop: 2, display: "flex", alignItems: "center", gap: 6 }}>
          <span>{new Date(app.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>
          {app.platform && app.platform !== "generic" && <span>· {app.platform}</span>}
          {app.job_url && (
            <a
              href={app.job_url}
              target="_blank"
              rel="noreferrer"
              title="Open job posting"
              style={{ color: "#4f46e5", textDecoration: "none", fontSize: 10, lineHeight: 1 }}
              onClick={(e) => { e.stopPropagation(); chrome.tabs.create({ url: app.job_url! }); e.preventDefault(); }}
            >↗</a>
          )}
          {/* Notes toggle */}
          <button
            onClick={() => { setNotesText(app.notes ?? ""); setShowNotes((v) => !v); }}
            style={{ background: "transparent", border: "none", cursor: "pointer", color: app.notes ? "#fbbf24" : "#374151", fontSize: 10, padding: 0, fontWeight: 700 }}
            title={app.notes ? "View/edit notes" : "Add notes"}
          >
            {app.notes ? "📝" : "＋note"}
          </button>
        </div>
      </div>
      <div style={{ position: "relative", flexShrink: 0 }}>
        <button
          onClick={() => setShowMenu((v) => !v)}
          disabled={updating}
          style={{
            fontSize: 10,
            fontWeight: 700,
            background: colors.bg,
            color: colors.text,
            border: `1px solid ${colors.border}`,
            borderRadius: 99,
            padding: "2px 8px",
            cursor: updating ? "wait" : "pointer",
            opacity: updating ? 0.6 : 1,
          }}
        >
          {updating ? "…" : app.status}
        </button>
        {showMenu && (
          <div style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 4px)",
            background: "#111318",
            border: "1px solid #rgba(255,255,255,0.07)",
            borderRadius: 8,
            zIndex: 100,
            display: "flex",
            flexDirection: "column",
            minWidth: 120,
            boxShadow: "0 4px 20px #000a",
          }}>
            {STATUS_ORDER.filter((s) => s !== app.status).map((s) => {
              const c = STATUS_COLORS[s] ?? STATUS_COLORS.discovered;
              return (
                <button
                  key={s}
                  onClick={() => { setShowMenu(false); onStatusChange(s); }}
                  style={{
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    padding: "6px 12px",
                    fontSize: 11,
                    color: c.text,
                    textAlign: "left",
                    fontWeight: 600,
                  }}
                >
                  {s}
                </button>
              );
            })}
          </div>
        )}
      </div>
      </div>
      {/* Inline notes editor */}
      {showNotes && (
        <div style={{ marginTop: 6, borderTop: "1px solid #rgba(255,255,255,0.07)", paddingTop: 6 }}>
          <textarea
            autoFocus
            rows={3}
            value={notesText}
            onChange={(e) => setNotesText(e.target.value)}
            placeholder="Interview notes, contacts, follow-up reminders…"
            style={{ width: "100%", boxSizing: "border-box", background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 6, color: "#d1d5db", fontSize: 11, padding: "5px 8px", resize: "vertical", fontFamily: "system-ui,sans-serif", outline: "none" }}
          />
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 4 }}>
            <button onClick={() => setShowNotes(false)} style={{ background: "transparent", border: "none", color: "#64748b", cursor: "pointer", fontSize: 10, fontWeight: 600 }}>Cancel</button>
            <button onClick={() => void handleSaveNotes()} disabled={savingNotes} style={{ background: "rgba(255,255,255,0.07)", border: "1px solid rgba(0,196,180,0.15)", borderRadius: 5, color: "#00c4b4", cursor: savingNotes ? "wait" : "pointer", fontSize: 10, fontWeight: 700, padding: "3px 10px" }}>
              {savingNotes ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}
      {/* Show saved notes as collapsed preview */}
      {!showNotes && app.notes && (
        <div style={{ marginTop: 4, fontSize: 10, color: "#94a3b8", borderTop: "1px solid #1f1f2a", paddingTop: 4, cursor: "pointer" }} onClick={() => { setNotesText(app.notes ?? ""); setShowNotes(true); }}>
          {app.notes.length > 80 ? app.notes.slice(0, 80) + "…" : app.notes}
        </div>
      )}
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
  if (variant === "primary") return { ...base, background: "#009688", color: "#fff", padding: "5px 14px" };
  if (variant === "ghost") return { ...base, background: "rgba(255,255,255,0.07)", color: "#00c4b4", padding: "5px 12px" };
  if (variant === "generate") return { ...base, background: "rgba(0,196,180,0.08)", color: "#00c4b4", padding: "6px 12px", width: "100%", outline: "1px solid rgba(0,196,180,0.15)" };
  return { ...base, background: "#1e1b4b", color: "#a5b4fc", padding: "3px 10px" };
}

const CATEGORY_COLORS: Record<string, string> = {
  behavioral: "#00c4b4",
  motivation: "#0891b2",
  technical: "#059669",
  general: "#d97706",
};

function AnswerBankCard({
  answer,
  onDelete,
  onEdit,
}: {
  answer: { answer_id: string; question_text: string; answer_text: string; company_name: string; question_category: string; reward_score: number | null; feedback: string };
  onDelete: () => void;
  onEdit: (newText: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(answer.answer_text);
  const [saving, setSaving] = useState(false);

  const handleSaveEdit = async () => {
    if (!editText.trim()) return;
    setSaving(true);
    try {
      await vaultApi.editAnswer(answer.answer_id, editText.trim());
      onEdit(editText.trim());
      setEditing(false);
    } catch { /* ignore */ } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ background: "#0a0b0d", border: "1px solid #rgba(255,255,255,0.07)", borderRadius: 8, padding: "8px 10px" }}>
      <div style={{ fontSize: 10, color: "#00c4b4", fontWeight: 700, marginBottom: 2, display: "flex", justifyContent: "space-between" }}>
        <span>{answer.company_name} · {answer.question_category}</span>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {answer.reward_score != null && <span style={{ color: "#475569" }}>{(answer.reward_score * 100).toFixed(0)}%</span>}
          <button onClick={() => { setEditing(!editing); setEditText(answer.answer_text); }} style={{ ...btnStyle("ghost"), fontSize: 9, padding: "1px 5px" }}>
            {editing ? "Cancel" : "✎ Edit"}
          </button>
          <button onClick={async () => { await vaultApi.deleteAnswer(answer.answer_id); onDelete(); }} style={{ ...btnStyle("ghost"), fontSize: 9, padding: "1px 5px", color: "#f87171" }}>
            ✕
          </button>
        </div>
      </div>
      <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4, fontStyle: "italic" }}>{answer.question_text.slice(0, 100)}{answer.question_text.length > 100 ? "…" : ""}</div>
      {editing ? (
        <>
          <textarea
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            rows={4}
            style={{ width: "100%", background: "#111318", border: "1px solid #2d2d52", borderRadius: 6, color: "#e2e8f0", fontSize: 11, padding: "6px 8px", outline: "none", resize: "vertical", boxSizing: "border-box" }}
          />
          <button
            onClick={() => void handleSaveEdit()}
            disabled={saving}
            style={{ ...btnStyle("generate", saving), fontSize: 9, padding: "3px 8px", marginTop: 4 }}
          >
            {saving ? "Saving…" : "Save Edit"}
          </button>
        </>
      ) : (
        <>
          <div style={{ fontSize: 11, color: "#94a3b8", lineHeight: 1.5, maxHeight: 60, overflowY: "auto" }}>{answer.answer_text.slice(0, 200)}{answer.answer_text.length > 200 ? "…" : ""}</div>
          <button
            onClick={() => navigator.clipboard.writeText(answer.answer_text)}
            style={{ ...btnStyle("ghost"), fontSize: 9, padding: "2px 6px", marginTop: 4 }}
          >
            Copy
          </button>
        </>
      )}
    </div>
  );
}

function PrepQuestion({
  question,
  index,
  expanded,
  onToggle,
  onSaveToBank,
}: {
  question: InterviewQuestion;
  index: number;
  expanded: boolean;
  onToggle: () => void;
  onSaveToBank?: () => Promise<void>;
}) {
  const catColor = CATEGORY_COLORS[question.category] ?? "#475569";
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const copyAnswer = () => {
    navigator.clipboard.writeText(question.suggested_answer).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };

  const saveToBank = async () => {
    if (!onSaveToBank || saving || saved) return;
    setSaving(true);
    try { await onSaveToBank(); setSaved(true); } catch { /* ignore */ } finally { setSaving(false); }
  };

  return (
    <div style={{
      background: "#111318",
      border: "1px solid #rgba(255,255,255,0.07)",
      borderRadius: 10,
      padding: "10px 12px",
      display: "flex",
      flexDirection: "column",
      gap: 6,
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8, cursor: "pointer" }} onClick={onToggle}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "#475569", minWidth: 18 }}>Q{index + 1}</span>
        <span style={{ flex: 1, fontSize: 12, color: "#e2e8f0", lineHeight: 1.5 }}>{question.question}</span>
        <span style={{
          fontSize: 9,
          fontWeight: 700,
          color: catColor,
          background: catColor + "22",
          border: `1px solid ${catColor}44`,
          borderRadius: 99,
          padding: "1px 7px",
          textTransform: "capitalize",
          whiteSpace: "nowrap",
        }}>{question.category}</span>
      </div>

      {expanded && (
        <div style={{ borderTop: "1px solid #rgba(255,255,255,0.07)", paddingTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 11, color: "#94a3b8", lineHeight: 1.6 }}>{question.suggested_answer}</div>
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
            {onSaveToBank && (
              <button
                onClick={() => void saveToBank()}
                disabled={saving || saved}
                style={{
                  background: saved ? "#14532d" : "none",
                  border: `1px solid ${saved ? "#166534" : "#334155"}`,
                  color: saved ? "#86efac" : "#64748b",
                  borderRadius: 6,
                  padding: "3px 10px",
                  fontSize: 11,
                  cursor: saving || saved ? "default" : "pointer",
                  fontFamily: "system-ui,sans-serif",
                }}
              >
                {saved ? "✓ Saved" : saving ? "Saving…" : "Save to bank"}
              </button>
            )}
            <button
              onClick={copyAnswer}
              style={{
                background: "none",
                border: "1px solid #334155",
                color: copied ? "#22c55e" : "#64748b",
                borderRadius: 6,
                padding: "3px 10px",
                fontSize: 11,
                cursor: "pointer",
                fontFamily: "system-ui,sans-serif",
              }}
            >
              {copied ? "Copied ✓" : "⎘ Copy Answer"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
