import { useState } from "react";
import { vaultApi, type InterviewQuestion } from "../../shared/api";
import { getFreshProviders } from "./useProviders";
import type { PageContext } from "../../shared/types";

export interface UseInterviewPrepResult {
  interviewQuestions: InterviewQuestion[];
  interviewLoading: boolean;
  interviewError: string;
  expandedPrepIdx: number | null;
  setExpandedPrepIdx: (idx: number | null) => void;
  prepCategoryFilter: "all" | "behavioral" | "motivation" | "technical" | "general";
  setPrepCategoryFilter: (f: "all" | "behavioral" | "motivation" | "technical" | "general") => void;
  savingAllPrep: boolean;
  setSavingAllPrep: (v: boolean) => void;
  savedAllPrep: boolean;
  setSavedAllPrep: (v: boolean) => void;
  handleInterviewPrep: () => Promise<void>;
  setInterviewQuestions: React.Dispatch<React.SetStateAction<InterviewQuestion[]>>;
}

import React from "react";

function loadDraftSession<T>(jobUrl: string | undefined, suffix: string, fallback: T): T {
  try {
    const base = jobUrl ? btoa(jobUrl).slice(0, 32) : "nojob";
    const raw = sessionStorage.getItem(`aap_drafts_${base}_${suffix}`);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch { return fallback; }
}

export function useInterviewPrep(context: PageContext): UseInterviewPrepResult {
  const jobUrl = context.jobUrl;
  const [interviewQuestions, setInterviewQuestions] = useState<InterviewQuestion[]>(
    () => loadDraftSession(jobUrl, "interviewQuestions", [])
  );
  const [interviewLoading, setInterviewLoading] = useState(false);
  const [interviewError, setInterviewError] = useState<string>("");
  const [expandedPrepIdx, setExpandedPrepIdx] = useState<number | null>(null);
  const [prepCategoryFilter, setPrepCategoryFilter] = useState<"all" | "behavioral" | "motivation" | "technical" | "general">("all");
  const [savingAllPrep, setSavingAllPrep] = useState(false);
  const [savedAllPrep, setSavedAllPrep] = useState(false);

  const handleInterviewPrep = async () => {
    if (!context.company) return;
    setInterviewLoading(true);
    setInterviewError("");
    setInterviewQuestions([]);
    setPrepCategoryFilter("all");
    try {
      const providers = await getFreshProviders();
      const result = await vaultApi.interviewPrep({
        companyName: context.company,
        roleTitle: context.roleTitle,
        jdText: context.jdText ?? "",
        providers,
      });
      setInterviewQuestions(result.questions);
    } catch (e) {
      setInterviewError(e instanceof Error ? e.message : "Failed to generate interview prep");
    } finally {
      setInterviewLoading(false);
    }
  };

  return {
    interviewQuestions,
    interviewLoading,
    interviewError,
    expandedPrepIdx,
    setExpandedPrepIdx,
    prepCategoryFilter,
    setPrepCategoryFilter,
    savingAllPrep,
    setSavingAllPrep: (v: boolean) => setSavingAllPrep(v),
    savedAllPrep,
    setSavedAllPrep,
    handleInterviewPrep,
    setInterviewQuestions,
  };
}
