import React from "react";
import type { ResumeCard as ResumeCardType } from "../../shared/types";
import ATSScoreBar from "./ATSScoreBar";
import type { Message } from "../../shared/types";

interface Props {
  resume: ResumeCardType;
  onAttach?: () => void;
}

const outcomeIcon: Record<string, string> = {
  interview: "✅",
  offer: "🎉",
  rejected: "❌",
  applied: "📤",
  phone_screen: "📞",
};

export default function ResumeCard({ resume, onAttach }: Props) {
  const lastDate = resume.lastUsed
    ? new Date(resume.lastUsed).toLocaleDateString("en-US", { month: "short", year: "numeric" })
    : null;

  const topOutcome = resume.outcomes[0];

  return (
    <div
      style={{
        background: "#13131f",
        border: "1px solid #1e1e3a",
        borderRadius: 10,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {/* Title row */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, color: "#c4b5fd" }}>
            {resume.versionTag || resume.filename}
          </div>
          {resume.targetRole && (
            <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
              {resume.targetRole}
            </div>
          )}
        </div>
        {topOutcome && (
          <span style={{ fontSize: 14 }} title={topOutcome}>
            {outcomeIcon[topOutcome] || "🔵"}
          </span>
        )}
      </div>

      {/* ATS score */}
      {resume.atsScore != null && (
        <ATSScoreBar score={resume.atsScore} label="ATS match" size="sm" />
      )}

      {/* Similarity */}
      {resume.similarityScore > 0 && resume.atsScore == null && (
        <ATSScoreBar score={resume.similarityScore * 100} label="Similarity" size="sm" />
      )}

      {/* Meta row */}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#6b7280" }}>
        <span>{lastDate ? `Used: ${lastDate}` : "Never submitted"}</span>
        {onAttach && (
          <button
            onClick={onAttach}
            style={{
              background: "#4f46e5",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              padding: "3px 10px",
              fontSize: 11,
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            Attach
          </button>
        )}
      </div>
    </div>
  );
}
