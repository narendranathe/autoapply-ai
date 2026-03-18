import { useState, useCallback, useRef, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  KanbanSquare,
  Table2,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  X,
  ExternalLink,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { FunnelBar } from "../components/FunnelBar";
import { KanbanBoard } from "../components/KanbanBoard";
import { useApplications } from "../hooks/useApplications";
import { patchApplicationStatus } from "../api/applications";
import { useApiClient } from "../hooks/useApiClient";
import { colors } from "../lib/tokens";
import type { AppStatus, ApplicationRecord } from "../api/applications";

// ─── Design tokens (extras not in tokens.ts) ─────────────────────────────────
const aurora = "#00CED1";
const amber = "#F59E0B";

// ─── Constants ────────────────────────────────────────────────────────────────
const VIEW_KEY = "mirror_apps_view";

const ALL_STATUSES: AppStatus[] = [
  "discovered",
  "draft",
  "tailored",
  "applied",
  "phone_screen",
  "interview",
  "offer",
  "rejected",
];

const STATUS_LABELS: Record<AppStatus, string> = {
  discovered: "Discovered",
  draft: "Draft",
  tailored: "Tailored",
  applied: "Applied",
  phone_screen: "Phone Screen",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
};

const PLATFORM_COLORS: Record<string, string> = {
  linkedin: "#0077B5",
  greenhouse: "#24A148",
  workday: "#8B5CF6",
  lever: "#EF4444",
  manual: colors.muted,
};

type SortDir = "asc" | "desc" | null;
type SortKey =
  | "company_name"
  | "role_title"
  | "platform"
  | "status"
  | "similarity_score"
  | "created_at";

// ─── Helpers ──────────────────────────────────────────────────────────────────
function relativeDate(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function atsColor(score: number | null): string {
  if (score === null) return colors.muted;
  // similarity_score is 0-1: >=0.80 aurora, >=0.65 amber, <0.65 ember
  if (score >= 0.8) return aurora;
  if (score >= 0.65) return amber;
  return colors.ember;
}

// ─── Platform Badge ───────────────────────────────────────────────────────────
function PlatformBadge({ platform }: { platform: string | null }) {
  if (!platform) return null;
  const color = PLATFORM_COLORS[platform] ?? colors.muted;
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        color,
        background: `${color}22`,
        border: `1px solid ${color}44`,
        borderRadius: 4,
        padding: "1px 6px",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
      }}
    >
      {platform}
    </span>
  );
}

// ─── Row Drawer ───────────────────────────────────────────────────────────────
function RowDrawer({
  app,
  onClose,
}: {
  app: ApplicationRecord;
  onClose: () => void;
}) {
  return (
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 1000,
        }}
      />
      <motion.div
        initial={{ x: 320 }}
        animate={{ x: 0 }}
        exit={{ x: 320 }}
        transition={{ duration: 0.32, ease: [0.32, 0.72, 0, 1] }}
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 320,
          background: colors.sidebar,
          borderLeft: `1px solid ${colors.border}`,
          zIndex: 1001,
          padding: 24,
          overflowY: "auto",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: 20,
          }}
        >
          <div>
            <div
              style={{ fontWeight: 700, fontSize: 16, color: colors.mercury }}
            >
              {app.company_name}
            </div>
            <div style={{ fontSize: 13, color: colors.muted, marginTop: 2 }}>
              {app.role_title}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: colors.muted,
              padding: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <DrawerRow label="Status">
            <span
              style={{
                textTransform: "capitalize",
                color: colors.mercury,
                fontSize: 13,
              }}
            >
              {STATUS_LABELS[app.status]}
            </span>
          </DrawerRow>
          <DrawerRow label="Platform">
            {app.platform ? (
              <PlatformBadge platform={app.platform} />
            ) : (
              <span style={{ fontSize: 13, color: colors.muted }}>—</span>
            )}
          </DrawerRow>
          <DrawerRow label="ATS Score">
            <span
              style={{
                color: atsColor(app.similarity_score),
                fontWeight: 600,
                fontSize: 13,
              }}
            >
              {app.similarity_score !== null
                ? `${Math.round(app.similarity_score * 100)}%`
                : "—"}
            </span>
          </DrawerRow>
          <DrawerRow label="Created">
            <span style={{ fontSize: 13, color: colors.mercury }}>
              {relativeDate(app.created_at)}
            </span>
          </DrawerRow>
          {app.job_url && (
            <DrawerRow label="Job URL">
              <a
                href={app.job_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  color: aurora,
                  fontSize: 13,
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  textDecoration: "none",
                }}
              >
                Open link <ExternalLink size={12} />
              </a>
            </DrawerRow>
          )}
          {app.notes && (
            <div>
              <div
                style={{
                  fontSize: 11,
                  color: colors.muted,
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  marginBottom: 6,
                }}
              >
                Notes
              </div>
              <div
                style={{
                  fontSize: 13,
                  color: colors.mercury,
                  lineHeight: 1.6,
                  whiteSpace: "pre-wrap",
                }}
              >
                {app.notes}
              </div>
            </div>
          )}
        </div>
      </motion.div>
    </>
  );
}

function DrawerRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}
    >
      <span
        style={{
          fontSize: 11,
          color: colors.muted,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </span>
      {children}
    </div>
  );
}

// ─── Table View ───────────────────────────────────────────────────────────────
function TableView({ apps }: { apps: ApplicationRecord[] }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const api = useApiClient();

  const urlStatuses =
    searchParams.get("status")?.split(",").filter(Boolean) ?? [];
  const urlCompany = searchParams.get("company") ?? "";
  const urlDateFrom = searchParams.get("date_from") ?? "";
  const urlDateTo = searchParams.get("date_to") ?? "";

  const [selectedStatuses, setSelectedStatuses] = useState<AppStatus[]>(
    urlStatuses.filter((s): s is AppStatus =>
      ALL_STATUSES.includes(s as AppStatus),
    ),
  );
  const [companySearch, setCompanySearch] = useState(urlCompany);
  const [dateFrom, setDateFrom] = useState(urlDateFrom);
  const [dateTo, setDateTo] = useState(urlDateTo);
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);

  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [drawerApp, setDrawerApp] = useState<ApplicationRecord | null>(null);

  const companyDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [debouncedCompany, setDebouncedCompany] = useState(urlCompany);

  const handleCompanyChange = useCallback((value: string) => {
    setCompanySearch(value);
    if (companyDebounceRef.current) clearTimeout(companyDebounceRef.current);
    companyDebounceRef.current = setTimeout(() => {
      setDebouncedCompany(value);
    }, 300);
  }, []);

  useEffect(() => {
    const params: Record<string, string> = {};
    if (selectedStatuses.length > 0) params.status = selectedStatuses.join(",");
    if (debouncedCompany) params.company = debouncedCompany;
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    setSearchParams(params, { replace: true });
  }, [selectedStatuses, debouncedCompany, dateFrom, dateTo, setSearchParams]);

  const filtered = apps.filter((a) => {
    if (
      selectedStatuses.length > 0 &&
      !selectedStatuses.includes(a.status)
    )
      return false;
    if (
      debouncedCompany &&
      !a.company_name
        .toLowerCase()
        .includes(debouncedCompany.toLowerCase())
    )
      return false;
    if (dateFrom && new Date(a.created_at) < new Date(dateFrom)) return false;
    if (
      dateTo &&
      new Date(a.created_at) > new Date(dateTo + "T23:59:59")
    )
      return false;
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    if (!sortKey || !sortDir) return 0;
    const av = a[sortKey] ?? "";
    const bv = b[sortKey] ?? "";
    const cmp = String(av).localeCompare(String(bv), undefined, {
      numeric: true,
    });
    return sortDir === "asc" ? cmp : -cmp;
  });

  function handleSort(key: SortKey) {
    if (sortKey !== key) {
      setSortKey(key);
      setSortDir("asc");
    } else if (sortDir === "asc") {
      setSortDir("desc");
    } else {
      setSortKey(null);
      setSortDir(null);
    }
  }

  function SortIcon({ colKey }: { colKey: SortKey }) {
    if (sortKey !== colKey)
      return <ChevronsUpDown size={12} style={{ opacity: 0.4 }} />;
    return sortDir === "asc" ? (
      <ChevronUp size={12} />
    ) : (
      <ChevronDown size={12} />
    );
  }

  const bulkMutation = useMutation({
    mutationFn: async (newStatus: AppStatus) => {
      await Promise.all(
        [...selectedIds].map((id) =>
          patchApplicationStatus(api, id, newStatus),
        ),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["applications"] });
      void queryClient.invalidateQueries({
        queryKey: ["applications-funnel"],
      });
      setSelectedIds(new Set());
    },
  });

  const allFilteredSelected =
    sorted.length > 0 && sorted.every((a) => selectedIds.has(a.id));

  function toggleSelectAll() {
    if (allFilteredSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(sorted.map((a) => a.id)));
    }
  }

  function toggleRow(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const thStyle: React.CSSProperties = {
    padding: "8px 12px",
    textAlign: "left",
    fontSize: 11,
    fontWeight: 600,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    cursor: "pointer",
    userSelect: "none",
    whiteSpace: "nowrap",
    borderBottom: `1px solid ${colors.border}`,
  };

  const tdStyle: React.CSSProperties = {
    padding: "10px 12px",
    fontSize: 13,
    color: colors.mercury,
    borderBottom: `1px solid ${colors.border}22`,
    verticalAlign: "middle",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Filter bar */}
      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "center",
          flexWrap: "wrap",
          background: colors.surface,
          border: `1px solid ${colors.border}`,
          borderRadius: 8,
          padding: "10px 14px",
        }}
      >
        {/* Status multi-select */}
        <div style={{ position: "relative" }}>
          <button
            onClick={() => setStatusDropdownOpen((v) => !v)}
            style={{
              background: colors.obsidian,
              border: `1px solid ${colors.border}`,
              borderRadius: 6,
              color: colors.mercury,
              fontSize: 12,
              padding: "5px 10px",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            Status
            {selectedStatuses.length > 0 && (
              <span
                style={{
                  background: aurora,
                  color: colors.obsidian,
                  borderRadius: 10,
                  fontSize: 10,
                  fontWeight: 700,
                  padding: "0 5px",
                  minWidth: 16,
                  textAlign: "center",
                }}
              >
                {selectedStatuses.length}
              </span>
            )}
            <ChevronDown size={12} />
          </button>
          {statusDropdownOpen && (
            <div
              style={{
                position: "absolute",
                top: "calc(100% + 4px)",
                left: 0,
                background: colors.sidebar,
                border: `1px solid ${colors.border}`,
                borderRadius: 8,
                padding: 6,
                zIndex: 100,
                minWidth: 160,
                boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
              }}
            >
              {ALL_STATUSES.map((s) => (
                <label
                  key={s}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "5px 8px",
                    cursor: "pointer",
                    borderRadius: 4,
                    fontSize: 12,
                    color: colors.mercury,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selectedStatuses.includes(s)}
                    onChange={() => {
                      setSelectedStatuses((prev) =>
                        prev.includes(s)
                          ? prev.filter((x) => x !== s)
                          : [...prev, s],
                      );
                    }}
                    style={{ accentColor: aurora }}
                  />
                  {STATUS_LABELS[s]}
                </label>
              ))}
              {selectedStatuses.length > 0 && (
                <button
                  onClick={() => setSelectedStatuses([])}
                  style={{
                    width: "100%",
                    marginTop: 4,
                    background: "none",
                    border: "none",
                    color: colors.muted,
                    fontSize: 11,
                    cursor: "pointer",
                    padding: "4px 8px",
                    textAlign: "left",
                  }}
                >
                  Clear
                </button>
              )}
            </div>
          )}
        </div>

        {/* Company text search */}
        <input
          type="text"
          placeholder="Company..."
          value={companySearch}
          onChange={(e) => handleCompanyChange(e.target.value)}
          style={{
            background: colors.obsidian,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            color: colors.mercury,
            fontSize: 12,
            padding: "5px 10px",
            outline: "none",
            width: 160,
          }}
        />

        {/* Date range */}
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          style={{
            background: colors.obsidian,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            color: dateFrom ? colors.mercury : colors.muted,
            fontSize: 12,
            padding: "5px 8px",
            outline: "none",
            colorScheme: "dark",
          }}
        />
        <span style={{ fontSize: 12, color: colors.muted }}>—</span>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          style={{
            background: colors.obsidian,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            color: dateTo ? colors.mercury : colors.muted,
            fontSize: 12,
            padding: "5px 8px",
            outline: "none",
            colorScheme: "dark",
          }}
        />

        <span
          style={{ fontSize: 12, color: colors.muted, marginLeft: "auto" }}
        >
          Showing {sorted.length} of {apps.length} applications
        </span>
      </div>

      {/* Bulk action bar */}
      <AnimatePresence>
        {selectedIds.size >= 2 && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18 }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              background: `${aurora}12`,
              border: `1px solid ${aurora}33`,
              borderRadius: 8,
              padding: "8px 14px",
            }}
          >
            <span style={{ fontSize: 12, color: aurora, fontWeight: 500 }}>
              {selectedIds.size} selected
            </span>
            <select
              onChange={(e) => {
                const val = e.target.value as AppStatus;
                if (val) bulkMutation.mutate(val);
                e.target.value = "";
              }}
              defaultValue=""
              style={{
                background: colors.obsidian,
                border: `1px solid ${colors.border}`,
                borderRadius: 6,
                color: colors.mercury,
                fontSize: 12,
                padding: "4px 8px",
                cursor: "pointer",
              }}
            >
              <option value="" disabled>
                Update Status…
              </option>
              {ALL_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
            <button
              onClick={() => setSelectedIds(new Set())}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: colors.muted,
                padding: 2,
              }}
            >
              <X size={14} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Table */}
      <div
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
          borderRadius: 8,
          overflow: "auto",
        }}
      >
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ ...thStyle, width: 36, cursor: "default" }}>
                <input
                  type="checkbox"
                  checked={allFilteredSelected}
                  onChange={toggleSelectAll}
                  style={{ accentColor: aurora, cursor: "pointer" }}
                />
              </th>
              {(
                [
                  ["company_name", "Company"],
                  ["role_title", "Role"],
                  ["platform", "Platform"],
                  ["status", "Status"],
                  ["similarity_score", "ATS Score"],
                  ["created_at", "Created"],
                ] as [SortKey, string][]
              ).map(([key, label]) => (
                <th
                  key={key}
                  style={thStyle}
                  onClick={() => handleSort(key)}
                >
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
                    {label}
                    <SortIcon colKey={key} />
                  </span>
                </th>
              ))}
              <th style={{ ...thStyle, cursor: "default" }}>Notes</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td
                  colSpan={8}
                  style={{
                    ...tdStyle,
                    textAlign: "center",
                    color: colors.muted,
                    padding: 32,
                  }}
                >
                  No applications match the current filters.
                </td>
              </tr>
            ) : (
              sorted.map((app) => (
                <tr
                  key={app.id}
                  onClick={() => setDrawerApp(app)}
                  style={{
                    cursor: "pointer",
                    background: selectedIds.has(app.id)
                      ? `${aurora}08`
                      : "transparent",
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={(e) => {
                    if (!selectedIds.has(app.id))
                      (
                        e.currentTarget as HTMLTableRowElement
                      ).style.background = `${colors.border}44`;
                  }}
                  onMouseLeave={(e) => {
                    (
                      e.currentTarget as HTMLTableRowElement
                    ).style.background = selectedIds.has(app.id)
                      ? `${aurora}08`
                      : "transparent";
                  }}
                >
                  <td
                    style={tdStyle}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={selectedIds.has(app.id)}
                      onChange={() => toggleRow(app.id)}
                      style={{ accentColor: aurora, cursor: "pointer" }}
                    />
                  </td>
                  <td style={{ ...tdStyle, fontWeight: 600 }}>
                    {app.company_name}
                  </td>
                  <td style={{ ...tdStyle, color: colors.muted }}>
                    {app.role_title}
                  </td>
                  <td style={tdStyle}>
                    {app.platform ? (
                      <PlatformBadge platform={app.platform} />
                    ) : (
                      <span style={{ color: colors.muted }}>—</span>
                    )}
                  </td>
                  <td style={tdStyle}>
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: colors.mercury,
                        background: `${colors.border}88`,
                        borderRadius: 4,
                        padding: "2px 7px",
                        textTransform: "capitalize",
                      }}
                    >
                      {STATUS_LABELS[app.status]}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    <span
                      style={{
                        color: atsColor(app.similarity_score),
                        fontWeight: 600,
                      }}
                    >
                      {app.similarity_score !== null
                        ? `${Math.round(app.similarity_score * 100)}%`
                        : "—"}
                    </span>
                  </td>
                  <td style={{ ...tdStyle, color: colors.muted }}>
                    {relativeDate(app.created_at)}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      color: colors.muted,
                      maxWidth: 200,
                    }}
                  >
                    <span
                      style={{
                        display: "block",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={app.notes ?? ""}
                    >
                      {app.notes
                        ? app.notes.slice(0, 60) +
                          (app.notes.length > 60 ? "…" : "")
                        : "—"}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Row drawer */}
      <AnimatePresence>
        {drawerApp && (
          <RowDrawer
            app={drawerApp}
            onClose={() => setDrawerApp(null)}
          />
        )}
      </AnimatePresence>

      {/* Dismiss status dropdown on outside click */}
      {statusDropdownOpen && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 99 }}
          onClick={() => setStatusDropdownOpen(false)}
        />
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function Applications() {
  const [view, setView] = useState<"board" | "table">(() => {
    const stored = localStorage.getItem(VIEW_KEY);
    return stored === "table" ? "table" : "board";
  });

  const { data } = useApplications();

  function switchView(v: "board" | "table") {
    setView(v);
    localStorage.setItem(VIEW_KEY, v);
  }

  return (
    <div
      style={{
        padding: "28px 32px",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: view === "board" ? "hidden" : "auto",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 0,
        }}
      >
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: colors.mercury,
            margin: 0,
            letterSpacing: "-0.3px",
          }}
        >
          Applications
        </h1>

        {/* View toggle */}
        <div
          style={{
            display: "flex",
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          {(
            [
              ["board", KanbanSquare, "Board"],
              ["table", Table2, "Table"],
            ] as const
          ).map(([v, Icon, label]) => (
            <button
              key={v}
              onClick={() => switchView(v)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 14px",
                background: view === v ? `${aurora}18` : "transparent",
                border: "none",
                borderRight:
                  v === "board" ? `1px solid ${colors.border}` : "none",
                color: view === v ? aurora : colors.muted,
                fontSize: 13,
                fontWeight: view === v ? 600 : 400,
                cursor: "pointer",
                transition: "background 0.15s, color 0.15s",
              }}
            >
              <Icon size={15} />
              {label}
            </button>
          ))}
        </div>
      </div>

      <FunnelBar />

      {view === "board" ? (
        <div style={{ flex: 1, overflow: "hidden" }}>
          <KanbanBoard />
        </div>
      ) : (
        <TableView apps={data?.items ?? []} />
      )}
    </div>
  );
}
