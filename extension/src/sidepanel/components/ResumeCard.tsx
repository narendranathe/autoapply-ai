import React from "react";
import type { ResumeCard as ResumeCardType } from "../../shared/types";
import ATSScoreBar from "./ATSScoreBar";

interface Props {
  resume: ResumeCardType;
  onAttach?: () => void;
}

const OUTCOME_BADGE: Record<string, { icon: string; color: string; bg: string }> = {
  offer:        { icon: "🎉", color: "#10b981", bg: "#052e16" },
  interview:    { icon: "✅", color: "#34d399", bg: "#052e16" },
  phone_screen: { icon: "📞", color: "#60a5fa", bg: "#0c1a33" },
  applied:      { icon: "📤", color: "#94a3b8", bg: "#1a1a2e" },
  rejected:     { icon: "✕",  color: "#f87171", bg: "#2d0a0a" },
};

export default function ResumeCard({ resume, onAttach }: Props) {
  const lastDate = resume.lastUsed
    ? new Date(resume.lastUsed).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : null;

  const topOutcome = resume.outcomes[0];
  const badge = topOutcome ? OUTCOME_BADGE[topOutcome] : null;
  const score = resume.atsScore ?? (resume.similarityScore > 0 ? resume.similarityScore * 100 : null);

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
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontWeight: 600,
            fontSize: 12,
            color: "#c4b5fd",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}>
            {resume.versionTag || resume.filename}
          </div>
          {resume.targetRole && (
            <div style={{ fontSize: 11, color: "#475569", marginTop: 2 }}>
              {resume.targetRole}
            </div>
          )}
        </div>
        {badge && (
          <div style={{
            flexShrink: 0,
            background: badge.bg,
            borderRadius: 6,
            padding: "2px 7px",
            fontSize: 11,
            color: badge.color,
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: 3,
          }}>
            <span>{badge.icon}</span>
            <span>{topOutcome.replace("_", " ")}</span>
          </div>
        )}
      </div>

      {/* Score bar */}
      {score != null && (
        <ATSScoreBar
          score={score}
          label={resume.atsScore != null ? "ATS match" : "Similarity"}
          size="sm"
        />
      )}

      {/* Footer row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 10, color: "#334155" }}>
          {lastDate ? `Used ${lastDate}` : "Not yet submitted"}
        </span>
        {onAttach && (
          <button
            onClick={onAttach}
            style={{
              background: "#4f46e5",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              padding: "4px 12px",
              fontSize: 11,
              cursor: "pointer",
              fontWeight: 700,
              letterSpacing: "0.01em",
            }}
          >
            Attach PDF
          </button>
        )}
      </div>
    </div>
  );
}
