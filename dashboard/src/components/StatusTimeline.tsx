import { colors } from "../lib/tokens";
import type { AppStatus } from "../api/applications";

const STEPS: { status: string; label: string }[] = [
  { status: "discovered", label: "Discovered" },
  { status: "applied", label: "Applied" },
  { status: "phone_screen", label: "Screen" },
  { status: "interview", label: "Interview" },
  { status: "offer", label: "Offer" },
];

const STATUS_ORDER = ["discovered", "draft", "tailored", "applied", "phone_screen", "interview", "offer", "rejected"];

export function StatusTimeline({ status }: { status: AppStatus }) {
  const isRejected = status === "rejected";
  const currentIdx = STATUS_ORDER.indexOf(status);

  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 0, marginTop: 10 }}>
      {STEPS.map((step, i) => {
        const stepIdx = STATUS_ORDER.indexOf(step.status);
        const isCompleted = !isRejected && currentIdx >= stepIdx;
        const isCurrent = !isRejected && status === step.status;

        return (
          <div key={step.status} style={{ display: "flex", alignItems: "center", flex: i < STEPS.length - 1 ? 1 : undefined }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
              <div
                style={{
                  width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                  background: isRejected
                    ? (i === 0 ? colors.ember : colors.border)
                    : isCompleted
                    ? (isCurrent ? colors.teal : `${colors.teal}60`)
                    : colors.border,
                  boxShadow: isCurrent ? `0 0 6px ${colors.teal}` : "none",
                }}
              />
              <div style={{ fontSize: 9, color: isCurrent ? colors.teal : colors.muted, whiteSpace: "nowrap" }}>
                {isRejected && i === 0 ? "Rejected" : step.label}
              </div>
            </div>
            {i < STEPS.length - 1 && (
              <div
                style={{
                  flex: 1, height: 1, marginBottom: 14,
                  background: !isRejected && currentIdx > stepIdx ? `${colors.teal}50` : colors.border,
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
