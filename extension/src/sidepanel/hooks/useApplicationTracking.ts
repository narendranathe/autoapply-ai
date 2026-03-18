import { useEffect, useState } from "react";
import { applicationsApi, type TrackedApplication } from "../../shared/api";
import type { PageContext } from "../../shared/types";

export interface UseApplicationTrackingResult {
  trackedAppId: string | null;
  pastApplications: TrackedApplication[];
  markingApplied: boolean;
  appliedMarked: boolean;
  updatingStatus: string | null;
  handleMarkApplied: () => Promise<void>;
  handleStatusUpdate: (appId: string, newStatus: string) => Promise<void>;
}

export function useApplicationTracking(context: PageContext): UseApplicationTrackingResult {
  const [trackedAppId, setTrackedAppId] = useState<string | null>(null);
  const [pastApplications, setPastApplications] = useState<TrackedApplication[]>([]);
  const [markingApplied, setMarkingApplied] = useState(false);
  const [appliedMarked, setAppliedMarked] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState<string | null>(null);

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

  const handleMarkApplied = async () => {
    if (!context.company) return;
    setMarkingApplied(true);
    try {
      const result = await applicationsApi.track({
        companyName: context.company,
        roleTitle: context.roleTitle,
        jobUrl: context.jobUrl,
        platform: context.platform,
      });
      await applicationsApi.updateStatus(result.application_id, "applied");
      setAppliedMarked(true);
      setTrackedAppId(result.application_id);
      setTimeout(() => setAppliedMarked(false), 3000);
    } catch {
      // ignore
    } finally {
      setMarkingApplied(false);
    }
  };

  // T1: Update application status from History tab
  const handleStatusUpdate = async (appId: string, newStatus: string) => {
    setUpdatingStatus(appId);
    try {
      await applicationsApi.updateStatus(appId, newStatus);
    } catch {
      // silently fail — status badge will show stale value
    } finally {
      setUpdatingStatus(null);
    }
  };

  return {
    trackedAppId,
    pastApplications,
    markingApplied,
    appliedMarked,
    updatingStatus,
    handleMarkApplied,
    handleStatusUpdate,
  };
}
