import React from "react";

interface Props {
  score: number;       // 0–100
  label?: string;
  size?: "sm" | "md";
}

function scoreColor(s: number): string {
  if (s >= 80) return "#34d399"; // green
  if (s >= 65) return "#fbbf24"; // amber
  if (s >= 50) return "#f97316"; // orange
  return "#f87171";              // red
}

export default function ATSScoreBar({ score, label, size = "md" }: Props) {
  const color = scoreColor(score);
  const barH = size === "sm" ? 4 : 6;
  const fontSize = size === "sm" ? 11 : 13;

  return (
    <div style={{ width: "100%" }}>
      {label && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize,
            marginBottom: 4,
            color: "#9ca3af",
          }}
        >
          <span>{label}</span>
          <span style={{ color, fontWeight: 600 }}>{score.toFixed(0)}%</span>
        </div>
      )}
      <div
        style={{
          height: barH,
          background: "#1e1e3a",
          borderRadius: barH,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${Math.min(score, 100)}%`,
            background: color,
            borderRadius: barH,
            transition: "width 0.4s ease",
          }}
        />
      </div>
    </div>
  );
}
