import { useCallback, useState } from "react";
import type { PageContext } from "../../shared/types";
import { vaultApi } from "../../shared/api";
import { getFreshProviders, type UserProfile } from "./useProviders";

export interface UseWritingToolsResult {
  generatingSummary: boolean;
  generatedSummary: string;
  summaryError: string;
  summaryCopied: boolean;
  setSummaryCopied: React.Dispatch<React.SetStateAction<boolean>>;
  generatingBullets: boolean;
  generatedBullets: string[];
  bulletsError: string;
  bulletsCopied: boolean;
  setBulletsCopied: React.Dispatch<React.SetStateAction<boolean>>;
  handleGenerateSummary: () => Promise<void>;
  handleGenerateBullets: () => Promise<void>;
}

export function useWritingTools(context: PageContext, profile: UserProfile | null): UseWritingToolsResult {
  const [generatingSummary, setGeneratingSummary] = useState(false);
  const [generatedSummary, setGeneratedSummary] = useState<string>("");
  const [summaryError, setSummaryError] = useState<string>("");
  const [summaryCopied, setSummaryCopied] = useState(false);

  const [generatingBullets, setGeneratingBullets] = useState(false);
  const [generatedBullets, setGeneratedBullets] = useState<string[]>([]);
  const [bulletsError, setBulletsError] = useState<string>("");
  const [bulletsCopied, setBulletsCopied] = useState(false);

  const handleGenerateSummary = useCallback(async () => {
    if (!context.company || !context.roleTitle) {
      setSummaryError("Company and role title are required. Navigate to a job posting first.");
      return;
    }
    setGeneratingSummary(true);
    setSummaryError("");
    setGeneratedSummary("");
    try {
      const freshProviders = await getFreshProviders();
      const candidateName = profile ? `${profile.firstName ?? ""} ${profile.lastName ?? ""}`.trim() : "";
      const res = await vaultApi.generateSummary({
        companyName: context.company,
        roleTitle: context.roleTitle,
        jdText: context.jdText ?? "",
        wordLimit: 80,
        candidateName,
        providers: freshProviders,
      });
      setGeneratedSummary(res.summary);
    } catch (err) {
      setSummaryError(err instanceof Error ? err.message : "Summary generation failed.");
    } finally {
      setGeneratingSummary(false);
    }
  }, [context.company, context.roleTitle, context.jdText, profile]);

  const handleGenerateBullets = useCallback(async () => {
    if (!context.company || !context.roleTitle) {
      setBulletsError("Company and role title are required. Navigate to a job posting first.");
      return;
    }
    setGeneratingBullets(true);
    setBulletsError("");
    setGeneratedBullets([]);
    try {
      const freshProviders = await getFreshProviders();
      const res = await vaultApi.generateBullets({
        companyName: context.company,
        roleTitle: context.roleTitle,
        jdText: context.jdText ?? "",
        numBullets: 5,
        targetCompany: context.company,
        providers: freshProviders,
      });
      setGeneratedBullets(res.bullets);
    } catch (err) {
      setBulletsError(err instanceof Error ? err.message : "Bullets generation failed.");
    } finally {
      setGeneratingBullets(false);
    }
  }, [context.company, context.roleTitle, context.jdText]);

  return {
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
  };
}
