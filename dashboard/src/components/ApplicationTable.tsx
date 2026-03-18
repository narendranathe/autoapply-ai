import { useState, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { motion } from "framer-motion";
import { colors } from "../lib/tokens";
import { useApplications, useUpdateStatus } from "../hooks/useApplications";
import { ApplicationFilterBar } from "./ApplicationFilterBar";
import { ApplicationDetailDrawer } from "./ApplicationDetailDrawer";
import { skeletonPulse } from "../lib/animations";
import type { ApplicationRecord, AppStatus } from "../api/applications";

type SortKey = keyof Pick<
  ApplicationRecord,
  "company_name" | "role_title" | "platform" | "status" | "similarity_score" | "created_at"
>;
type SortDir = "asc" | "desc" | null;

function relativeDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

const ALL_STATUSES: AppStatus[] = [
  "discovered", "draft", "tailored", "applied",
  "phone_screen", "interview", "offer", "rejected",
];

interface ColDef {
  key: SortKey;
  label: string;
  width?: number | string;
  render: (app: ApplicationRecord) => React.ReactNode;
}

const COLUMNS: ColDef[] = [
  { key: "company_name", label: "Company", render: (a) => a.company_name },
  { key: "role_title", label: "Role", width: "20%", render: (a) => (
    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block", maxWidth: 200 }}>
      {a.role_title}
    </span>
  )},
  { key: "platform", label: "Platform", width: 90, render: (a) => a.platform ?? "—" },
  { key: "status", label: "Status", width: 110, render: (a) => a.status.replace("_", " ") },
  { key: "similarity_score", label: "ATS", width: 60, render: (a) =>
    a.similarity_score !== null ? `${Math.round(a.similarity_score * 100)}%` : "—"
  },
  { key: "created_at", label: "Applied", width: 90, render: (a) => relativeDate(a.created_at) },
];

function applyFilters(
  items: ApplicationRecord[],
  statuses: string[],
  company: string,
  from: string,
  to: string,
): ApplicationRecord[] {
  return items.filter((a) => {
    if (statuses.length > 0 && !statuses.includes(a.status)) return false;
    if (company && !a.company_name.toLowerCase().includes(company.toLowerCase())) return false;
    if (from && new Date(a.created_at) < new Date(from)) return false;
    if (to && new Date(a.created_at) > new Date(to + "T23:59:59")) return false;
    return true;
  });
}

function applySort(items: ApplicationRecord[], key: SortKey | null, dir: SortDir): ApplicationRecord[] {
  if (!key || !dir) return items;
  return [...items].sort((a, b) => {
    const av = a[key] ?? "";
    const bv = b[key] ?? "";
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
    return dir === "asc" ? cmp : -cmp;
  });
}

export function ApplicationTable() {
  const { data, isLoading } = useApplications();
  const { mutate: updateStatus } = useUpdateStatus();
  const [searchParams] = useSearchParams();

  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeApp, setActiveApp] = useState<ApplicationRecord | null>(null);
  const [bulkStatus, setBulkStatus] = useState<AppStatus>("applied");

  const statuses = searchParams.getAll("status");
  const company = searchParams.get("company") ?? "";
  const from = searchParams.get("from") ?? "";
  const to = searchParams.get("to") ?? "";

  const filtered = useMemo(() => {
    if (!data) return [];
    return applyFilters(data.items, statuses, company, from, to);
  }, [data, statuses, company, from, to]);

  const sorted = useMemo(() => applySort(filtered, sortKey, sortDir), [filtered, sortKey, sortDir]);

  const handleSort = useCallback((key: SortKey) => {
    setSortKey((prev) => {
      if (prev !== key) { setSortDir("asc"); return key; }
      setSortDir((d) => {
        if (d === "asc") return "desc";
        if (d === "desc") { setSortKey(null); return null; }
        return "asc";
      });
      return key;
    });
  }, []);

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelected((prev) =>
      prev.size === sorted.length ? new Set() : new Set(sorted.map((a) => a.id))
    );
  }, [sorted]);

  const applyBulkStatus = useCallback(() => {
    for (const id of selected) {
      updateStatus({ id, status: bulkStatus });
    }
    setSelected(new Set());
  }, [selected, bulkStatus, updateStatus]);

  if (isLoading) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <motion.div
            key={i}
            {...skeletonPulse}
            style={{ height: 40, background: colors.surface, borderRadius: 6 }}
          />
        ))}
      </div>
    );
  }

  const thStyle: React.CSSProperties = {
    textAlign: "left",
    fontSize: 10,
    fontWeight: 600,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    padding: "8px 12px",
    cursor: "pointer",
    userSelect: "none",
    whiteSpace: "nowrap",
    borderBottom: `1px solid ${colors.border}`,
  };

  const tdStyle: React.CSSProperties = {
    padding: "10px 12px",
    fontSize: 12,
    color: colors.mercury,
    borderBottom: `1px solid ${colors.border}`,
  };

  return (
    <>
      <ApplicationFilterBar totalShown={sorted.length} totalAll={data?.items.length ?? 0} />

      {/* Bulk action bar */}
      {selected.size >= 2 && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "8px 12px",
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            marginBottom: 10,
          }}
        >
          <span style={{ fontSize: 12, color: colors.mercury }}>{selected.size} selected</span>
          <select
            value={bulkStatus}
            onChange={(e) => setBulkStatus(e.target.value as AppStatus)}
            style={{
              background: colors.border,
              border: "none",
              color: colors.mercury,
              fontSize: 12,
              borderRadius: 4,
              padding: "4px 8px",
              fontFamily: "inherit",
              cursor: "pointer",
            }}
          >
            {ALL_STATUSES.map((s) => (
              <option key={s} value={s}>{s.replace("_", " ")}</option>
            ))}
          </select>
          <button
            onClick={applyBulkStatus}
            style={{
              background: colors.teal,
              border: "none",
              color: "#000",
              fontSize: 11,
              fontWeight: 600,
              padding: "4px 12px",
              borderRadius: 4,
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            Update Status
          </button>
        </div>
      )}

      {sorted.length === 0 ? (
        <div style={{ textAlign: "center", padding: "48px 0", color: colors.muted, fontSize: 13 }}>
          No applications match your filters.{" "}
          <span
            style={{ color: colors.teal, cursor: "pointer", textDecoration: "underline" }}
            onClick={() => { window.history.pushState({}, "", window.location.pathname); window.dispatchEvent(new PopStateEvent("popstate")); }}
          >
            Clear filters to see all.
          </span>
        </div>
      ) : (
        <div style={{ overflowX: "auto", flex: 1 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...thStyle, width: 36 }}>
                  <input
                    type="checkbox"
                    checked={selected.size === sorted.length && sorted.length > 0}
                    onChange={toggleAll}
                    style={{ accentColor: colors.teal }}
                  />
                </th>
                {COLUMNS.map((col) => (
                  <th
                    key={col.key}
                    style={{ ...thStyle, width: col.width }}
                    onClick={() => handleSort(col.key)}
                  >
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                      {col.label}
                      {sortKey === col.key && sortDir === "asc" && <ChevronUp size={11} />}
                      {sortKey === col.key && sortDir === "desc" && <ChevronDown size={11} />}
                      {sortKey !== col.key && <ChevronsUpDown size={11} style={{ opacity: 0.3 }} />}
                    </span>
                  </th>
                ))}
                <th style={{ ...thStyle }}>Notes</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((app) => (
                <motion.tr
                  key={app.id}
                  whileHover={{ backgroundColor: `${colors.surface}` }}
                  style={{ cursor: "pointer" }}
                  onClick={() => setActiveApp(app)}
                >
                  <td style={tdStyle} onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(app.id)}
                      onChange={() => toggleSelect(app.id)}
                      style={{ accentColor: colors.teal }}
                    />
                  </td>
                  {COLUMNS.map((col) => (
                    <td key={col.key} style={tdStyle}>
                      {col.render(app)}
                    </td>
                  ))}
                  <td style={{ ...tdStyle, color: colors.muted, maxWidth: 200 }}>
                    {app.notes ? app.notes.slice(0, 60) + (app.notes.length > 60 ? "…" : "") : "—"}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ApplicationDetailDrawer app={activeApp} onClose={() => setActiveApp(null)} />
    </>
  );
}
