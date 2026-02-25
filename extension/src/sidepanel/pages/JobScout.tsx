import React, { useEffect, useState } from "react";
import type { PageContext } from "../../shared/types";
import { vaultApi } from "../../shared/api";
import ATSScoreBar from "../components/ATSScoreBar";

interface Props { context: PageContext }

interface JobEntry {
  company: string;
  role: string;
  url: string;
  score: number | null;
  loading: boolean;
  pastCount: number;
}

export default function JobScout({ context }: Props) {
  const [jobs, setJobs] = useState<JobEntry[]>([]);

  // On LinkedIn/Indeed, the content script may send job cards via context
  // For now seed from context metadata; real job cards come via DOM scraping.
  useEffect(() => {
    // Placeholder: show the current page's company as one entry
    if (context.company) {
      const entry: JobEntry = {
        company: context.company,
        role: context.roleTitle,
        url: context.jobUrl,
        score: null,
        loading: true,
        pastCount: 0,
      };
      setJobs([entry]);

      // Score against vault
      vaultApi.retrieve(context.company).then((res) => {
        const ats = res.ats_result as { overall_score?: number } | null;
        const history = (res.company_history || []) as unknown[];
        setJobs((prev) =>
          prev.map((j) =>
            j.company === context.company
              ? { ...j, score: ats?.overall_score ?? null, loading: false, pastCount: history.length }
              : j
          )
        );
      }).catch(() => {
        setJobs((prev) => prev.map((j) => ({ ...j, loading: false })));
      });
    }
  }, [context.company]);

  const S = {
    container: { display: "flex", flexDirection: "column" as const, height: "calc(100vh - 53px)" },
    header: { padding: "12px 16px", borderBottom: "1px solid #1e1e3a", fontSize: 13, color: "#9ca3af" },
    list: { flex: 1, overflowY: "auto" as const, padding: 12, display: "flex", flexDirection: "column" as const, gap: 8 },
    card: { background: "#13131f", border: "1px solid #1e1e3a", borderRadius: 10, padding: "12px 14px", display: "flex", flexDirection: "column" as const, gap: 6 },
    topRow: { display: "flex", justifyContent: "space-between", alignItems: "flex-start" },
    company: { fontWeight: 700, fontSize: 13, color: "#f1f5f9" },
    role: { fontSize: 11, color: "#6b7280", marginTop: 2 },
    pastBadge: { fontSize: 10, background: "#1e1e3a", color: "#a78bfa", borderRadius: 99, padding: "2px 8px" },
    noScore: { fontSize: 12, color: "#4b5563" },
  };

  return (
    <div style={S.container}>
      <div style={S.header}>
        Job Scout Mode · {jobs.length} job{jobs.length !== 1 ? "s" : ""} detected
      </div>
      <div style={S.list}>
        {jobs.map((job, i) => (
          <div key={i} style={S.card}>
            <div style={S.topRow}>
              <div>
                <div style={S.company}>{job.company}</div>
                <div style={S.role}>{job.role}</div>
              </div>
              {job.pastCount > 0 && (
                <span style={S.pastBadge}>{job.pastCount} past</span>
              )}
            </div>
            {job.loading ? (
              <div style={S.noScore}>Scoring…</div>
            ) : job.score != null ? (
              <ATSScoreBar score={job.score} label="Resume fit" size="sm" />
            ) : (
              <div style={S.noScore}>No resume in vault yet</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
