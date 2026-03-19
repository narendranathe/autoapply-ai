import { useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, ExternalLink } from "lucide-react";
import { colors } from "../lib/tokens";
import { StatusTimeline } from "./StatusTimeline";
import type { ApplicationRecord } from "../api/applications";

interface CompanyDrawerProps {
  company: string | null;
  applications: ApplicationRecord[];
  onClose: () => void;
}

function relativeDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
}

const STATUS_COLORS: Record<string, string> = {
  discovered: "#6B7280", draft: "#6366F1", tailored: "#8B5CF6",
  applied: "#00CED1", phone_screen: "#F59E0B", interview: "#F59E0B",
  offer: "#22C55E", rejected: "#FF6B35",
};

export function CompanyDrawer({ company, applications, onClose }: CompanyDrawerProps) {
  const companyApps = company
    ? [...applications]
        .filter((a) => a.company_name.toLowerCase() === company.toLowerCase())
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    : [];

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <AnimatePresence>
      {company && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            style={{ position: "fixed", inset: 0, background: "#00000060", zIndex: 50 }}
          />
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            style={{
              position: "fixed", top: 0, right: 0, height: "100vh", width: 480,
              background: colors.surface, borderLeft: `1px solid ${colors.border}`,
              zIndex: 51, overflowY: "auto", fontFamily: "'Plus Jakarta Sans', sans-serif",
            }}
          >
            {/* Header */}
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "20px 24px", borderBottom: `1px solid ${colors.border}`,
              position: "sticky", top: 0, background: colors.surface, zIndex: 1,
            }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: colors.mercury }}>{company}</div>
                <div style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}>
                  {companyApps.length} application{companyApps.length !== 1 ? "s" : ""}
                </div>
              </div>
              <button onClick={onClose} style={{
                background: "none", border: "none", cursor: "pointer", color: colors.muted,
                padding: 6, borderRadius: 6, display: "flex", alignItems: "center",
              }}>
                <X size={16} />
              </button>
            </div>

            {/* List */}
            <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
              {companyApps.length === 0 && (
                <div style={{ color: colors.muted, fontSize: 13, textAlign: "center", padding: 40 }}>
                  No applications found.
                </div>
              )}
              {companyApps.map((app) => (
                <div key={app.id} style={{
                  background: "#0D0D0D", border: `1px solid ${colors.border}`,
                  borderRadius: 10, padding: 16,
                }}>
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: colors.mercury }}>{app.role_title}</div>
                      <div style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}>{relativeDate(app.created_at)}</div>
                    </div>
                    <span style={{
                      fontSize: 10, padding: "3px 7px", borderRadius: 5, flexShrink: 0,
                      background: `${STATUS_COLORS[app.status] ?? colors.muted}20`,
                      color: STATUS_COLORS[app.status] ?? colors.muted,
                      fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em",
                    }}>
                      {app.status.replace("_", " ")}
                    </span>
                  </div>

                  <StatusTimeline status={app.status} />

                  <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 5 }}>
                    {(app as ApplicationRecord & { job_id?: string }).job_id && (
                      <div style={{ fontSize: 11, color: colors.muted }}>
                        <span>Job ID: </span>
                        <span style={{ color: colors.mercury, fontFamily: "monospace" }}>
                          {(app as ApplicationRecord & { job_id?: string }).job_id}
                        </span>
                      </div>
                    )}
                    {app.platform && (
                      <div style={{ fontSize: 11, color: colors.muted }}>
                        Platform: <span style={{ color: colors.mercury, textTransform: "capitalize" }}>{app.platform}</span>
                      </div>
                    )}
                    {(app as ApplicationRecord & { job_description?: string }).job_description && (
                      <div style={{ fontSize: 11, color: colors.muted }}>
                        JD: <span style={{ color: colors.mercury }}>
                          {(app as ApplicationRecord & { job_description?: string }).job_description!.slice(0, 150)}...
                        </span>
                      </div>
                    )}
                    {app.job_url && (
                      <a href={app.job_url} target="_blank" rel="noopener noreferrer" style={{
                        display: "inline-flex", alignItems: "center", gap: 4,
                        fontSize: 11, color: colors.teal, textDecoration: "none", marginTop: 4,
                      }}>
                        <ExternalLink size={10} /> View Job Posting
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
