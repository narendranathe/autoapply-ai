import { useFunnel } from "../hooks/useApplications";
import { colors } from "../lib/tokens";

export function FunnelBar() {
  const { data } = useFunnel();

  if (!data) return null;

  const appliedStage = data.funnel.find((s) => s.status === "applied");
  const interviewStage = data.funnel.find((s) => s.status === "interview");
  const appliedCount = appliedStage?.count ?? 0;
  const interviewCount = interviewStage?.count ?? 0;
  const interviewRate =
    appliedCount > 0 ? Math.round((interviewCount / appliedCount) * 100) : 0;

  const stats = [
    { label: "Total", value: data.total },
    { label: "Applied", value: appliedCount },
    { label: "Interview Rate", value: `${interviewRate}%` },
  ];

  return (
    <div
      style={{
        display: "flex",
        gap: 24,
        padding: "12px 0 20px",
      }}
    >
      {stats.map((s) => (
        <div key={s.label} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: colors.mercury,
              letterSpacing: "-0.5px",
            }}
          >
            {s.value}
          </span>
          <span style={{ fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            {s.label}
          </span>
        </div>
      ))}
    </div>
  );
}
