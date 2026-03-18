import { motion, AnimatePresence } from "framer-motion";
import { X, ExternalLink } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "../hooks/useApiClient";
import { fetchSimilarApplications } from "../api/applications";
import { colors } from "../lib/tokens";
import type { ApplicationRecord } from "../api/applications";

const STATUS_LABELS: Record<string, string> = {
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
  app: ApplicationRecord | null;
  onClose: () => void;
}

export function ApplicationDetailDrawer({ app, onClose }: Props) {
  const client = useApiClient();
  const { data: similar } = useQuery({
    queryKey: ["applications-similar", app?.id],
    queryFn: () => fetchSimilarApplications(client, app!.id),
    enabled: !!app,
    staleTime: 60_000,
  });

  return (
    <AnimatePresence>
      {app && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.5)",
              zIndex: 200,
            }}
          />

          {/* Drawer */}
          <motion.div
            key="drawer"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            style={{
              position: "fixed",
              top: 0,
              right: 0,
              bottom: 0,
              width: 400,
              background: colors.sidebar,
              borderLeft: `1px solid ${colors.border}`,
              zIndex: 201,
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
            }}
          >
            {/* Header */}
            <div
              style={{
                padding: "20px 24px",
                borderBottom: `1px solid ${colors.border}`,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: 12,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 16, fontWeight: 600, color: colors.mercury, marginBottom: 4 }}>
                  {app.company_name}
                </div>
                <div style={{ fontSize: 12, color: colors.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {app.role_title}
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close drawer"
                style={{
                  background: "transparent",
                  border: "none",
                  color: colors.muted,
                  cursor: "pointer",
                  padding: 4,
                  flexShrink: 0,
                }}
              >
                <X size={18} />
              </button>
            </div>

            {/* Body */}
            <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
              {/* Status + platform */}
              <Row label="Status" value={STATUS_LABELS[app.status] ?? app.status} />
              {app.platform && <Row label="Platform" value={app.platform} />}
              {app.similarity_score !== null && (
                <Row label="Match Score" value={`${Math.round(app.similarity_score * 100)}%`} />
              )}

              {/* Job URL */}
              {app.job_url && (
                <div>
                  <Label>Job URL</Label>
                  <a
                    href={app.job_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontSize: 12,
                      color: colors.teal,
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                      textDecoration: "none",
                      wordBreak: "break-all",
                    }}
                  >
                    <ExternalLink size={12} />
                    {app.job_url}
                  </a>
                </div>
              )}

              {/* Notes */}
              {app.notes && (
                <div>
                  <Label>Notes</Label>
                  <p style={{ fontSize: 12, color: colors.mercury, margin: 0, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                    {app.notes}
                  </p>
                </div>
              )}

              {/* Similar applications */}
              {similar && similar.length > 0 && (
                <div>
                  <Label>Similar Applications</Label>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {similar.slice(0, 5).map((s) => (
                      <div
                        key={s.id}
                        style={{
                          padding: "8px 10px",
                          background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          borderRadius: 6,
                        }}
                      >
                        <div style={{ fontSize: 12, fontWeight: 600, color: colors.mercury }}>
                          {s.company_name}
                        </div>
                        <div style={{ fontSize: 11, color: colors.muted }}>{s.role_title}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 600,
        color: colors.muted,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        marginBottom: 6,
      }}
    >
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <Label>{label}</Label>
      <span style={{ fontSize: 12, color: colors.mercury }}>{value}</span>
    </div>
  );
}
