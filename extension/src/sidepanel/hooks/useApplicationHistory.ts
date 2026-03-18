import { useEffect, useState } from "react";
import { applicationsApi, vaultApi, type TrackedApplication } from "../../shared/api";
import type { Tab } from "./useTabNavigation";

export interface UseApplicationHistoryResult {
  allApplications: TrackedApplication[];
  historyLoading: boolean;
  appStats: { total: number; by_status: Record<string, number>; unique_companies: number } | null;
  appFunnel: Awaited<ReturnType<typeof applicationsApi.getFunnel>> | null;
  vaultAnalytics: Awaited<ReturnType<typeof vaultApi.getAnalytics>> | null;
  historySearch: string;
  setHistorySearch: (v: string) => void;
  historyStatusFilter: string;
  setHistoryStatusFilter: (v: string) => void;
  answerBankSearch: string;
  setAnswerBankSearch: (v: string) => void;
  answerBankResults: Array<{
    answer_id: string;
    question_text: string;
    answer_text: string;
    company_name: string;
    question_category: string;
    reward_score: number | null;
    feedback: string;
  }>;
  setAnswerBankResults: React.Dispatch<React.SetStateAction<Array<{
    answer_id: string;
    question_text: string;
    answer_text: string;
    company_name: string;
    question_category: string;
    reward_score: number | null;
    feedback: string;
  }>>>;
  answerBankSearching: boolean;
  setAnswerBankSearching: (v: boolean) => void;
  setAllApplications: React.Dispatch<React.SetStateAction<TrackedApplication[]>>;
}

import React from "react";

export function useApplicationHistory(tab: Tab): UseApplicationHistoryResult {
  const [allApplications, setAllApplications] = useState<TrackedApplication[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [appStats, setAppStats] = useState<{ total: number; by_status: Record<string, number>; unique_companies: number } | null>(null);
  const [appFunnel, setAppFunnel] = useState<Awaited<ReturnType<typeof applicationsApi.getFunnel>> | null>(null);
  const [vaultAnalytics, setVaultAnalytics] = useState<Awaited<ReturnType<typeof vaultApi.getAnalytics>> | null>(null);
  const [historySearch, setHistorySearch] = useState("");
  const [historyStatusFilter, setHistoryStatusFilter] = useState<string>("all");
  const [answerBankSearch, setAnswerBankSearch] = useState("");
  const [answerBankResults, setAnswerBankResults] = useState<Array<{
    answer_id: string;
    question_text: string;
    answer_text: string;
    company_name: string;
    question_category: string;
    reward_score: number | null;
    feedback: string;
  }>>([]);
  const [answerBankSearching, setAnswerBankSearching] = useState(false);

  // T1: Fetch all applications when History tab is activated
  useEffect(() => {
    if (tab !== "history") return;
    setHistoryLoading(true);
    Promise.all([
      applicationsApi.list(),
      applicationsApi.getStats(),
      applicationsApi.getFunnel().catch(() => null),
      vaultApi.getAnalytics().catch(() => null),
    ]).then(([listRes, statsRes, funnelRes, analyticsRes]) => {
      setAllApplications(listRes.items);
      setAppStats(statsRes);
      if (funnelRes) setAppFunnel(funnelRes);
      if (analyticsRes) setVaultAnalytics(analyticsRes);
    }).catch(() => {}).finally(() => setHistoryLoading(false));
  }, [tab]);

  return {
    allApplications,
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
    setAllApplications,
  };
}
