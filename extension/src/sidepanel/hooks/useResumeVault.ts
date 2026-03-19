import { useCallback, useEffect, useRef, useState } from "react";
import type { ATSScoreResult, PageContext, ResumeCard } from "../../shared/types";
import { vaultApi, type GenerateTailoredResponse } from "../../shared/api";
import { getFreshProviders } from "./useProviders";

export interface UseResumeVaultResult {
  resumes: ResumeCard[];
  setResumes: React.Dispatch<React.SetStateAction<ResumeCard[]>>;
  ats: ATSScoreResult | null;
  loading: boolean;
  // Resume content viewer
  viewingResumeId: string | null;
  setViewingResumeId: React.Dispatch<React.SetStateAction<string | null>>;
  resumeContent: string;
  // Resume rename
  renamingResumeId: string | null;
  setRenamingResumeId: React.Dispatch<React.SetStateAction<string | null>>;
  renameTag: string;
  setRenameTag: React.Dispatch<React.SetStateAction<string>>;
  // Resume tailoring
  tailoringResumeId: string | null;
  tailorResults: Record<string, GenerateTailoredResponse>;
  tailorErrors: Record<string, string>;
  // Upload
  uploadError: string;
  uploadSuccess: string;
  uploading: boolean;
  fileInputRef: React.RefObject<HTMLInputElement>;
  // Handlers
  handleResumeUpload: (e: React.ChangeEvent<HTMLInputElement>) => Promise<void>;
  handleResumeDelete: (resumeId: string) => Promise<void>;
  handleTailorResume: (resumeId: string) => Promise<void>;
  handleViewResume: (resumeId: string) => Promise<void>;
  handleRenameResume: (resumeId: string, newTag: string) => Promise<void>;
  clearUploadFeedback: () => void;
}

export function useResumeVault(context: PageContext): UseResumeVaultResult {
  const [resumes, setResumes] = useState<ResumeCard[]>([]);
  const [ats, setAts] = useState<ATSScoreResult | null>(null);
  const [loading, setLoading] = useState(false);

  // Resume content viewer
  const [viewingResumeId, setViewingResumeId] = useState<string | null>(null);
  const [resumeContent, setResumeContent] = useState<string>("");

  // Resume rename
  const [renamingResumeId, setRenamingResumeId] = useState<string | null>(null);
  const [renameTag, setRenameTag] = useState("");

  // Resume tailoring
  const [tailoringResumeId, setTailoringResumeId] = useState<string | null>(null);
  const [tailorResults, setTailorResults] = useState<Record<string, GenerateTailoredResponse>>({});
  const [tailorErrors, setTailorErrors] = useState<Record<string, string>>({});

  // Upload state
  const [uploadError, setUploadError] = useState<string>("");
  const [uploadSuccess, setUploadSuccess] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!context.company) return;
    setLoading(true);
    vaultApi
      .retrieve(context.company, context.jdText)
      .then((res) => {
        setResumes(res.company_history ?? []);
        if (res.ats_result) setAts(res.ats_result);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [context.company]);

  const handleResumeUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!e.target.files) return;
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
      const updated = await vaultApi.retrieve(context.company);
      setResumes(updated.company_history ?? []);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed. Try again.");
    } finally {
      setUploading(false);
    }
  }, [context.company, context.roleTitle]);

  const handleResumeDelete = useCallback(async (resumeId: string) => {
    try {
      await vaultApi.deleteResume(resumeId);
      setResumes((prev) => prev.filter((r) => r.resumeId !== resumeId));
    } catch {
      // Silently fail
    }
  }, []);

  const handleTailorResume = useCallback(async (resumeId: string) => {
    if (!context.jdText) {
      setTailorErrors((prev) => ({ ...prev, [resumeId]: "No job description detected. Navigate to the job posting page first." }));
      return;
    }
    const freshProviders = await getFreshProviders();
    if (freshProviders.length === 0) {
      setTailorErrors((prev) => ({ ...prev, [resumeId]: "No API key found. Open Settings and add a Groq or Gemini key." }));
      return;
    }
    setTailoringResumeId(resumeId);
    setTailorErrors((prev) => { const n = { ...prev }; delete n[resumeId]; return n; });
    try {
      const result = await vaultApi.generateTailored({
        baseResumeId: resumeId,
        jdText: context.jdText,
        companyName: context.company,
        roleTitle: context.roleTitle,
        providers: freshProviders,
      });
      setTailorResults((prev) => ({ ...prev, [resumeId]: result }));
      vaultApi.retrieve(context.company, context.jdText).then((res) => {
        setResumes(res.company_history ?? []);
        if (res.ats_result) setAts(res.ats_result);
      }).catch(() => {});
    } catch (err) {
      setTailorErrors((prev) => ({ ...prev, [resumeId]: err instanceof Error ? err.message : "Tailoring failed" }));
    } finally {
      setTailoringResumeId(null);
    }
  }, [context.jdText, context.company, context.roleTitle]);

  const handleViewResume = useCallback(async (resumeId: string) => {
    if (viewingResumeId === resumeId) {
      setViewingResumeId(null);
      return;
    }
    const res = await vaultApi.getResume(resumeId).catch(() => null);
    if (res) {
      setResumeContent(res.markdown_content || res.raw_text || res.latex_content || "No content available.");
      setViewingResumeId(resumeId);
    }
  }, [viewingResumeId]);

  const handleRenameResume = useCallback(async (resumeId: string, newTag: string) => {
    await vaultApi.patchResume(resumeId, { versionTag: newTag.trim() || undefined });
    setResumes((prev) => prev.map((r) => r.resumeId === resumeId ? { ...r, versionTag: newTag.trim() || null } : r));
    setRenamingResumeId(null);
  }, []);

  const clearUploadFeedback = useCallback(() => {
    setUploadError("");
    setUploadSuccess("");
  }, []);

  return {
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
  };
}
