import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { motion } from "framer-motion";
import { colors } from "../lib/tokens";
import type { ApplicationRecord } from "../api/applications";

const PLATFORM_LABELS: Record<string, string> = {
  linkedin: "LI",
  greenhouse: "GH",
  workday: "WD",
  lever: "LV",
  ashby: "AS",
  indeed: "IN",
  glassdoor: "GD",
};

function atsDot(score: number | null) {
  if (score === null) return colors.muted;
  if (score >= 0.8) return colors.teal;
  if (score >= 0.65) return "#F59E0B";
  return colors.ember;
}

function relativeDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

interface Props {
  app: ApplicationRecord;
  isError?: boolean;
}

export function ApplicationCard({ app, isError = false }: Props) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: app.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    cursor: isDragging ? "grabbing" : "grab",
  };

  const platformLabel = app.platform ? (PLATFORM_LABELS[app.platform] ?? app.platform.slice(0, 2).toUpperCase()) : null;

  return (
    <motion.div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      animate={isError ? { x: [0, -6, 6, -4, 4, 0] } : {}}
      transition={{ duration: 0.35 }}
      whileHover={{ scale: 1.01 }}
      tabIndex={0}
      role="button"
      aria-label={`${app.company_name}, ${app.role_title}. Drag to move.`}
    >
      <div
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
          borderRadius: 8,
          padding: "10px 12px",
          display: "flex",
          flexDirection: "column",
          gap: 6,
          userSelect: "none",
        }}
      >
        {/* Top row: company + platform badge */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: colors.mercury,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              maxWidth: "75%",
            }}
          >
            {app.company_name}
          </span>
          {platformLabel && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 600,
                color: colors.muted,
                background: colors.border,
                borderRadius: 4,
                padding: "2px 5px",
                letterSpacing: "0.05em",
              }}
            >
              {platformLabel}
            </span>
          )}
        </div>

        {/* Role title */}
        <span
          style={{
            fontSize: 11,
            color: colors.muted,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {app.role_title}
        </span>

        {/* Bottom row: ATS dot + date */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <div
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: atsDot(app.similarity_score),
                flexShrink: 0,
              }}
            />
            {app.similarity_score !== null && (
              <span style={{ fontSize: 10, color: colors.muted }}>
                {Math.round(app.similarity_score * 100)}%
              </span>
            )}
          </div>
          <span style={{ fontSize: 10, color: colors.muted }}>
            {relativeDate(app.created_at)}
          </span>
        </div>
      </div>
    </motion.div>
  );
}
