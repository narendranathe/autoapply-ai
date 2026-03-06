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
      borderRadius: 8,
      background: `hsl(${hue}, 45%, 22%)`,
      border: `1px solid hsl(${hue}, 45%, 32%)`,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontWeight: 700,
      fontSize: 14,
      color: `hsl(${hue}, 70%, 80%)`,
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
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 45px)" }}>
      {/* Header bar */}
      <div style={{
        padding: "10px 14px",
        borderBottom: "1px solid #1f1f38",
        background: "#0f0f1e",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexShrink: 0,
      }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, color: "#f1f5f9" }}>Job Scout</div>
          <div style={{ fontSize: 11, color: "#475569", marginTop: 1 }}>
            {jobs.length} job{jobs.length !== 1 ? "s" : ""} detected
          </div>
        </div>
        <div style={{
          background: "#1c1a2e",
          border: "1px solid #2d2b4e",
          borderRadius: 99,
          padding: "3px 10px",
          fontSize: 10,
          color: "#f59e0b",
          fontWeight: 600,
        }}>
          Scout Mode
        </div>
      </div>

      {/* Job list */}
      <div style={{ flex: 1, overflowY: "auto", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
        {jobs.length === 0 ? (
          <div style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 10,
            padding: "32px 24px",
            textAlign: "center",
          }}>
            <div style={{ fontSize: 28 }}>🔍</div>
            <div style={{ fontSize: 13, color: "#475569" }}>Scanning for job listings…</div>
          </div>
        ) : (
          jobs.map((job, i) => (
            <JobCard key={i} job={job} />
          ))
        )}
      </div>
    </div>
  );
}

function JobCard({ job }: { job: JobEntry }) {
  return (
    <div style={{
      background: "#12121e",
      border: "1px solid #1f1f38",
      borderRadius: 10,
      padding: "10px 12px",
      display: "flex",
      flexDirection: "column",
      gap: 8,
    }}>
      {/* Top row: avatar + company + role + score chip */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <CompanyAvatar name={job.company} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 13, color: "#f1f5f9", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {job.company}
          </div>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {job.role}
          </div>
        </div>
        {/* Score chip or past count */}
        {job.loading ? (
          <div style={{ fontSize: 11, color: "#334155", fontStyle: "italic" }}>Scoring…</div>
        ) : job.score != null ? (
          <div style={{
            flexShrink: 0,
            background: "#12121e",
            border: `1px solid ${scoreColor(job.score)}44`,
            borderRadius: 8,
            padding: "4px 8px",
            textAlign: "center",
          }}>
            <div style={{ fontSize: 14, fontWeight: 800, color: scoreColor(job.score) }}>{job.score.toFixed(0)}</div>
            <div style={{ fontSize: 9, color: "#475569", fontWeight: 600 }}>FIT</div>
          </div>
        ) : null}
      </div>

      {/* Score bar */}
      {!job.loading && job.score != null && (
        <ATSScoreBar score={job.score} label="Resume fit" size="sm" />
      )}

      {/* Bottom: past applications badge + open link */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        {job.pastCount > 0 ? (
          <span style={{
            fontSize: 10,
            background: "#1e1335",
            color: "#a78bfa",
            borderRadius: 99,
            padding: "2px 8px",
            border: "1px solid #2d1b69",
          }}>
            {job.pastCount} past application{job.pastCount !== 1 ? "s" : ""}
          </span>
        ) : (
          <span style={{ fontSize: 10, color: "#334155" }}>No past applications</span>
        )}
        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            style={{
              fontSize: 10,
              color: "#8b5cf6",
              textDecoration: "none",
              fontWeight: 600,
              padding: "3px 8px",
              background: "#1e1335",
              borderRadius: 6,
              border: "1px solid #2d1b69",
            }}
          >
            Open →
          </a>
        )}
      </div>
    </div>
  );
}
