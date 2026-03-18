import { useState } from "react";
import { vaultApi } from "../../shared/api";
import { getFreshProviders } from "./useProviders";
import type { PageContext } from "../../shared/types";

function loadDraftSession<T>(jobUrl: string | undefined, suffix: string, fallback: T): T {
  try {
    const base = jobUrl ? btoa(jobUrl).slice(0, 32) : "nojob";
    const raw = sessionStorage.getItem(`aap_drafts_${base}_${suffix}`);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch { return fallback; }
}

export interface UseCoverLetterResult {
  coverDrafts: string[];
  setCoverDrafts: React.Dispatch<React.SetStateAction<string[]>>;
  coverDraftProviders: string[];
  setCoverDraftProviders: React.Dispatch<React.SetStateAction<string[]>>;
  coverSelectedDraft: number;
  setCoverSelectedDraft: (v: number) => void;
  coverLetter: string;
  setCoverLetter: React.Dispatch<React.SetStateAction<string>>;
  coverLoading: boolean;
  coverError: string;
  coverTone: "professional" | "enthusiastic" | "concise";
  setCoverTone: (t: "professional" | "enthusiastic" | "concise") => void;
  coverWordLimit: 300 | 400 | 500;
  setCoverWordLimit: (n: 300 | 400 | 500) => void;
  coverCopied: boolean;
  savingCoverLetter: boolean;
  savedCoverLetters: Array<{ id: string; company_name: string; role_title: string | null; answer_text: string; created_at: string }>;
  setSavedCoverLetters: React.Dispatch<React.SetStateAction<Array<{ id: string; company_name: string; role_title: string | null; answer_text: string; created_at: string }>>>;
  coverLettersSectionOpen: boolean;
  setCoverLettersSectionOpen: React.Dispatch<React.SetStateAction<boolean>>;
  handleGenerateCoverLetter: () => Promise<void>;
  handleSaveCoverLetter: () => Promise<void>;
  handleCopyLetter: () => Promise<void>;
}

import React from "react";

export function useCoverLetter(context: PageContext): UseCoverLetterResult {
  const jobUrl = context.jobUrl;
  const [coverDrafts, setCoverDrafts] = useState<string[]>(
    () => loadDraftSession(jobUrl, "coverDrafts", [])
  );
  const [coverDraftProviders, setCoverDraftProviders] = useState<string[]>(
    () => loadDraftSession(jobUrl, "coverDraftProviders", [])
  );
  const [coverSelectedDraft, setCoverSelectedDraft] = useState(0);
  const [coverLetter, setCoverLetter] = useState<string>(
    () => loadDraftSession(jobUrl, "coverLetter", "")
  );
  const [coverLoading, setCoverLoading] = useState(false);
  const [coverError, setCoverError] = useState<string>("");
  const [coverTone, setCoverTone] = useState<"professional" | "enthusiastic" | "concise">("professional");
  const [coverWordLimit, setCoverWordLimit] = useState<300 | 400 | 500>(400);
  const [coverCopied, setCoverCopied] = useState(false);
  const [savingCoverLetter, setSavingCoverLetter] = useState(false);
  const [savedCoverLetters, setSavedCoverLetters] = useState<Array<{ id: string; company_name: string; role_title: string | null; answer_text: string; created_at: string }>>([]);
  const [coverLettersSectionOpen, setCoverLettersSectionOpen] = useState(false);

  const handleGenerateCoverLetter = async () => {
    if (!context.company) return;
    setCoverLoading(true);
    setCoverError("");
    setCoverLetter("");
    try {
      const providers = await getFreshProviders();
      // Get candidate name from stored profile
      const profileData = await new Promise<{ firstName?: string; lastName?: string }>((resolve) => {
        chrome.storage.local.get("profile", (d) => resolve(d.profile ?? {}));
      });
      const candidateName = [profileData.firstName, profileData.lastName].filter(Boolean).join(" ");
      const result = await vaultApi.generateCoverLetter({
        companyName: context.company,
        roleTitle: context.roleTitle,
        jdText: context.jdText ?? "",
        tone: coverTone,
        wordLimit: coverWordLimit,
        candidateName,
        providers,
      });
      const drafts = result.drafts ?? [];
      const draftProvidersResult = result.draft_providers ?? [];
      setCoverDrafts(drafts);
      setCoverDraftProviders(draftProvidersResult);
      setCoverSelectedDraft(0);
      setCoverLetter(drafts[0] ?? "");
    } catch (err) {
      setCoverError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setCoverLoading(false);
    }
  };

  const handleSaveCoverLetter = async () => {
    if (!coverLetter.trim() || !context.company) return;
    setSavingCoverLetter(true);
    try {
      await vaultApi.saveAnswer({
        questionText: `Cover letter for ${context.roleTitle || "position"} at ${context.company}`,
        questionCategory: "cover_letter",
        answerText: coverLetter.trim(),
        companyName: context.company,
        roleTitle: context.roleTitle,
        llmProviderUsed: coverDraftProviders[coverSelectedDraft],
      });
    } catch { /* ignore */ } finally {
      setSavingCoverLetter(false);
    }
  };

  const handleCopyLetter = async () => {
    if (!coverLetter) return;
    try {
      await navigator.clipboard.writeText(coverLetter);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = coverLetter;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCoverCopied(true);
    setTimeout(() => setCoverCopied(false), 2000);
  };

  return {
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
  };
}
