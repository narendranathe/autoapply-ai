import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { colors } from "../lib/tokens";
import { ApplicationCard } from "./ApplicationCard";
import type { ApplicationRecord } from "../api/applications";

const COLUMN_LABELS: Record<string, string> = {
  discovered: "Discovered",
  draft: "Draft",
  tailored: "Tailored",
  applied: "Applied",
  phone_screen: "Phone Screen",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
};

interface Props {
  status: string;
  items: ApplicationRecord[];
  errorIds: Set<string>;
}

export function KanbanColumn({ status, items, errorIds }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: status });

  const label = COLUMN_LABELS[status] ?? status;
  const isEmpty = items.length === 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        minWidth: 200,
        maxWidth: 220,
        flexShrink: 0,
      }}
    >
      {/* Column header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 10,
        }}
      >
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: colors.muted,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          {label}
        </span>
        {items.length > 0 && (
          <span
            style={{
              fontSize: 10,
              color: colors.muted,
              background: colors.border,
              borderRadius: 10,
              padding: "1px 6px",
            }}
          >
            {items.length}
          </span>
        )}
      </div>

      {/* Drop zone */}
      <div
        ref={setNodeRef}
        style={{
          flex: 1,
          minHeight: 120,
          borderRadius: 8,
          border: isEmpty
            ? `1px dashed ${isOver ? colors.teal : colors.border}`
            : "none",
          display: "flex",
          flexDirection: "column",
          gap: 8,
          padding: isEmpty ? "16px 8px" : 0,
          transition: "border-color 0.15s ease",
          alignItems: isEmpty ? "center" : "stretch",
          justifyContent: isEmpty ? "center" : "flex-start",
          background: isOver && !isEmpty ? `${colors.surface}80` : "transparent",
        }}
      >
        {isEmpty ? (
          <span
            style={{
              fontSize: 11,
              color: colors.border,
              textAlign: "center",
            }}
          >
            {label}
          </span>
        ) : (
          <SortableContext items={items.map((a) => a.id)} strategy={verticalListSortingStrategy}>
            {items.map((app) => (
              <ApplicationCard
                key={app.id}
                app={app}
                isError={errorIds.has(app.id)}
              />
            ))}
          </SortableContext>
        )}
      </div>
    </div>
  );
}
