import React, { useEffect, useState } from "react";
import type { JobCard, Message, PageContext } from "../../shared/types";
import { vaultApi } from "../../shared/api";
import ATSScoreBar from "../components/ATSScoreBar";

interface Props { context: PageContext }

interface JobEntry extends JobCard {
  score: number | null;
  loading: boolean;
  pastCount: number;
}

function scoreJob(entry: JobEntry, setJobs: React.Dispatch<React.SetStateAction<JobEntry[]>>) {
  vaultApi.retrieve(entry.company).then((res) => {
    const ats = res.ats_result as { overall_score?: number } | null;
    const history = (res.company_history || []) as unknown[];
    setJobs((prev) =>
      prev.map((j) =>
        j.company === entry.company && j.role === entry.role
          ? { ...j, score: ats?.overall_score ?? null, loading: false, pastCount: history.length }
          : j
      )
    );
  }).catch(() => {
    setJobs((prev) =>
      prev.map((j) =>
        j.company === entry.company && j.role === entry.role ? { ...j, loading: false } : j
      )
    );
  });
}

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
      width: 36,
      height: 36,
      borderRadius: 9,
      background: `hsl(${hue}, 40%, 18%)`,
      border: `1px solid hsl(${hue}, 40%, 28%)`,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontWeight: 700,
      fontSize: 14,
      color: `hsl(${hue}, 65%, 75%)`,
      flexShrink: 0,
    }}>
      {initial}
    </div>
  );
}

export default function JobScout({ context }: Props) {
  const [jobs, setJobs] = useState<JobEntry[]>([]);

  useEffect(() => {
    if (context.company) {
      const seed: JobEntry = {
        company: context.company,
        role: context.roleTitle,
        url: context.jobUrl,
        score: null,
        loading: true,
        pastCount: 0,
      };
      setJobs([seed]);
      scoreJob(seed, setJobs);
    }
  }, [context.company, context.roleTitle, context.jobUrl]);

  useEffect(() => {
    const listener = (message: Message) => {
      if (message.type !== "JOB_CARDS_UPDATE") return;
      const incoming = message.payload as JobCard[];
      const newEntries: JobEntry[] = incoming.map((c) => ({
        ...c,
        score: null,
        loading: true,
        pastCount: 0,
      }));
      setJobs(newEntries);
      newEntries.forEach((e) => scoreJob(e, setJobs));
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Header bar */}
      <div style={{
        padding: "10px 14px",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        background: "#0a0b0d",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexShrink: 0,
      }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, color: "#e0e4ef" }}>Job Scout</div>
          <div style={{ fontSize: 11, color: "#5a6278", marginTop: 1 }}>
            {jobs.length} job{jobs.length !== 1 ? "s" : ""} detected
          </div>
        </div>
        <div style={{
          background: "rgba(139,92,246,0.1)",
          border: "1px solid rgba(139,92,246,0.2)",
          borderRadius: 99,
          padding: "3px 10px",
          fontSize: 10,
          color: "#8b5cf6",
          fontWeight: 600,
        }}>
          Scout Mode
        </div>
      </div>

      {/* Job list */}
      <div style={{ flex: 1, overflowY: "auto", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 7 }}>
        {jobs.length === 0 ? (
          <div style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            padding: "40px 24px",
            textAlign: "center",
          }}>
            <div style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              background: "rgba(0,196,180,0.06)",
              border: "1px solid rgba(0,196,180,0.15)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 20,
            }}>🔍</div>
            <div style={{ fontSize: 12, color: "#5a6278" }}>Scanning for job listings…</div>
          </div>
        ) : (
          jobs.map((job, i) => (
            <JobCardItem key={i} job={job} index={i} />
          ))
        )}
      </div>
    </div>
  );
}

function JobCardItem({ job, index }: { job: JobEntry; index: number }) {
  return (
    <div style={{
      background: "#111318",
      border: "1px solid rgba(255,255,255,0.07)",
      borderRadius: 10,
      padding: "11px 13px",
      display: "flex",
      flexDirection: "column",
      gap: 8,
      animation: `fadeUp 180ms ${index * 40}ms both`,
    }}>
      {/* Top row */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <CompanyAvatar name={job.company} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontWeight: 700,
            fontSize: 13,
            color: "#e0e4ef",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}>
            {job.company}
          </div>
          <div style={{
            fontSize: 11,
            color: "#8b92a8",
            marginTop: 2,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}>
            {job.role}
          </div>
        </div>
        {job.loading ? (
          <div style={{
            width: 40,
            height: 40,
            borderRadius: 8,
            background: "#1a1d25",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}>
            <div style={{
              width: 14,
              height: 14,
              borderRadius: "50%",
              border: "2px solid rgba(0,196,180,0.2)",
              borderTopColor: "#00c4b4",
              animation: "spin 0.8s linear infinite",
            }} />
          </div>
        ) : job.score != null ? (
          <div style={{
            flexShrink: 0,
            background: "#1a1d25",
            border: `1px solid ${scoreColor(job.score)}33`,
            borderRadius: 8,
            padding: "5px 9px",
            textAlign: "center",
            minWidth: 42,
          }}>
            <div style={{ fontSize: 15, fontWeight: 800, color: scoreColor(job.score) }}>
              {job.score.toFixed(0)}
            </div>
            <div style={{ fontSize: 9, color: "#5a6278", fontWeight: 600, letterSpacing: "0.05em" }}>FIT</div>
          </div>
        ) : null}
      </div>

      {/* Score bar */}
      {!job.loading && job.score != null && (
        <ATSScoreBar score={job.score} label="Resume fit" size="sm" />
      )}

      {/* Bottom row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        {job.pastCount > 0 ? (
          <span style={{
            fontSize: 10,
            background: "rgba(0,196,180,0.08)",
            color: "#00c4b4",
            borderRadius: 99,
            padding: "2px 8px",
            border: "1px solid rgba(0,196,180,0.2)",
          }}>
            {job.pastCount} past application{job.pastCount !== 1 ? "s" : ""}
          </span>
        ) : (
          <span style={{ fontSize: 10, color: "#5a6278" }}>No past applications</span>
        )}
        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            style={{
              fontSize: 10,
              color: "#00c4b4",
              textDecoration: "none",
              fontWeight: 600,
              padding: "3px 10px",
              background: "rgba(0,196,180,0.08)",
              borderRadius: 6,
              border: "1px solid rgba(0,196,180,0.2)",
              transition: "all 0.15s",
            }}
          >
            Open →
          </a>
        )}
      </div>
    </div>
  );
}
