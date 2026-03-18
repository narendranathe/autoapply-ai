import { useState, useCallback } from "react";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { motion, AnimatePresence } from "framer-motion";
import { KanbanColumn } from "./KanbanColumn";
import { ApplicationCard } from "./ApplicationCard";
import { useApplications, useUpdateStatus } from "../hooks/useApplications";
import { skeletonPulse } from "../lib/animations";
import { colors } from "../lib/tokens";
import type { AppStatus, ApplicationRecord } from "../api/applications";

const COLUMNS: AppStatus[] = [
  "discovered",
  "draft",
  "tailored",
  "applied",
  "phone_screen",
  "interview",
  "offer",
  "rejected",
];

function groupByStatus(items: ApplicationRecord[]): Record<string, ApplicationRecord[]> {
  const groups: Record<string, ApplicationRecord[]> = {};
  for (const col of COLUMNS) groups[col] = [];
  for (const item of items) {
    const col = item.status in groups ? item.status : "discovered";
    groups[col].push(item);
  }
  return groups;
}

export function KanbanBoard() {
  const { data, isLoading } = useApplications();
  const { mutate: updateStatus, isPending } = useUpdateStatus();

  const [activeId, setActiveId] = useState<string | null>(null);
  const [errorIds, setErrorIds] = useState<Set<string>>(new Set());

  // Toast state
  const [toast, setToast] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const groups = data ? groupByStatus(data.items) : {};
  const activeApp = data?.items.find((a) => a.id === activeId) ?? null;

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  }, []);

  const handleDragStart = useCallback(({ active }: DragStartEvent) => {
    setActiveId(active.id as string);
  }, []);

  const handleDragEnd = useCallback(
    ({ active, over }: DragEndEvent) => {
      setActiveId(null);
      if (!over || !data) return;

      const draggedId = active.id as string;
      const targetStatus = over.id as AppStatus;

      const app = data.items.find((a) => a.id === draggedId);
      if (!app || app.status === targetStatus) return;
      if (!COLUMNS.includes(targetStatus)) return;

      updateStatus(
        { id: draggedId, status: targetStatus },
        {
          onError: () => {
            setErrorIds((prev) => new Set([...prev, draggedId]));
            setTimeout(() => {
              setErrorIds((prev) => {
                const next = new Set(prev);
                next.delete(draggedId);
                return next;
              });
            }, 800);
            showToast("Failed to update status. Card restored.");
          },
        },
      );
    },
    [data, updateStatus, showToast],
  );

  if (isLoading) {
    return (
      <div style={{ display: "flex", gap: 16, overflowX: "auto", paddingBottom: 16 }}>
        {COLUMNS.map((col) => (
          <motion.div
            key={col}
            {...skeletonPulse}
            style={{
              minWidth: 200,
              height: 240,
              background: colors.surface,
              borderRadius: 8,
              flexShrink: 0,
            }}
          />
        ))}
      </div>
    );
  }

  return (
    <>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div
          style={{
            display: "flex",
            gap: 16,
            overflowX: "auto",
            paddingBottom: 16,
            cursor: isPending ? "wait" : undefined,
          }}
        >
          {COLUMNS.map((col) => (
            <KanbanColumn
              key={col}
              status={col}
              items={groups[col] ?? []}
              errorIds={errorIds}
            />
          ))}
        </div>

        <DragOverlay>
          {activeApp && (
            <div style={{ width: 200, pointerEvents: "none" }}>
              <ApplicationCard app={activeApp} />
            </div>
          )}
        </DragOverlay>
      </DndContext>

      {/* Framer Motion toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            key="toast"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 16 }}
            transition={{ duration: 0.2 }}
            style={{
              position: "fixed",
              bottom: 24,
              left: "50%",
              transform: "translateX(-50%)",
              background: colors.surface,
              border: `1px solid ${colors.ember}`,
              color: colors.mercury,
              padding: "10px 20px",
              borderRadius: 8,
              fontSize: 13,
              zIndex: 9999,
              boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
            }}
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
