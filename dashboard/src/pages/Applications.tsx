import { useState, useCallback, useRef, useEffect, useMemo } from "react";
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
  Copy,
  Clock,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { FunnelBar } from "../components/FunnelBar";
import { KanbanBoard } from "../components/KanbanBoard";
import { useApplications } from "../hooks/useApplications";
import { patchApplicationStatus } from "../api/applications";
import { useApiClient } from "../hooks/useApiClient";
import { colors, font } from "../lib/tokens";
import { fadeUp } from "../lib/animations";
import type { AppStatus, ApplicationRecord } from "../api/applications";

const VIEW_KEY = "mirror_apps_view";

const ALL_STATUSES: AppStatus[] = [
  "discovered", "draft", "tailored", "applied",
  "phone_screen", "interview", "offer", "rejected",
];

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

const PLATFORM_COLORS: Record<string, string> = {
  linkedin: "#0077B5",
  indeed: "#FF6B35",
  greenhouse: "#24A148",
  lever: "#EF4444",
  workday: "#8B5CF6",
  manual: colors.muted,
};

const PLATFORMS = ["linkedin", "indeed", "greenhouse", "lever", "workday", "other"];

type SortDir = "asc" | "desc" | null;
type SortKey = "company_name" | "role_title" | "platform" | "status" | "similarity_score" | "created_at";

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
  if (score >= 0.8) return colors.teal;
  if (score >= 0.65) return colors.amber;
  return colors.ember;
}

function PlatformBadge({ platform }: { platform: string | null }) {
  if (!platform) return null;
  const color = PLATFORM_COLORS[platform] ?? colors.muted;
  return (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded font-medium capitalize"
      style={{ background: `${color}20`, color }}
    >
      {platform}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const c = status === "offer" ? "#22C55E" : status === "interview" || status === "phone_screen" ? "#3B82F6" : status === "rejected" ? colors.ember : status === "applied" ? colors.teal : colors.muted;
  return (
    <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 4, background: `${c}18`, color: c }}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

// Company Deep-Dive Drawer
function CompanyDrawer({ companyName, apps, onClose }: { companyName: string; apps: ApplicationRecord[]; onClose: () => void }) {
  return (
    <>
      <motion.div
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        className="fixed right-0 top-0 h-full z-50 overflow-y-auto p-6"
        style={{
          width: 520,
          background: colors.surface2,
          borderLeft: `1px solid ${colors.border}`,
          fontFamily: font.family,
        }}
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 border-0 bg-transparent cursor-pointer"
          style={{ color: colors.muted }}
        >
          <X size={18} />
        </button>

        <div className="flex items-center gap-3 mb-5">
          <img
            src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(companyName.toLowerCase().replace(/\s+/g, ""))}.com&sz=24`}
            alt=""
            width={24}
            height={24}
            className="rounded"
            style={{ background: colors.border }}
          />
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 600, color: colors.mercury }}>{companyName}</h3>
            <span style={{ fontSize: 11, color: colors.muted }}>{apps.length} application{apps.length !== 1 ? "s" : ""}</span>
          </div>
        </div>

        <div className="space-y-3">
          {apps.map((app) => (
            <div
              key={app.id}
              className="rounded-lg p-3"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
            >
              <div className="flex items-start justify-between mb-2">
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: colors.mercury }}>{app.role_title}</div>
                  <div className="flex items-center gap-2 mt-1">
                    <span style={{ fontSize: 11, color: colors.muted }}>{relativeDate(app.created_at)}</span>
                    <PlatformBadge platform={app.platform} />
                  </div>
                </div>
                <StatusBadge status={app.status} />
              </div>

              {app.job_id && (
                <div className="flex items-center gap-1.5 mb-1.5">
                  <span style={{ fontSize: 11, fontFamily: "monospace", color: colors.muted }}>
                    {app.job_id}
                  </span>
                </div>
              )}

              {app.job_description && (
                <p style={{ fontSize: 11, color: colors.muted, lineHeight: 1.4, marginBottom: 6 }}>
                  {app.job_description.slice(0, 120)}{app.job_description.length > 120 ? "..." : ""}
                </p>
              )}

              {/* Status timeline */}
              <div className="flex items-center gap-2 mt-2">
                <Clock size={11} style={{ color: colors.muted }} />
                <span style={{ fontSize: 10, color: colors.muted }}>
                  {STATUS_LABELS[app.status]} since {new Date(app.updated_at ?? app.created_at).toLocaleDateString()}
                </span>
              </div>

              {app.job_url && (
                <a
                  href={app.job_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 mt-2 text-xs no-underline"
                  style={{ color: colors.teal }}
                >
                  View job <ExternalLink size={11} />
                </a>
              )}
            </div>
          ))}
        </div>
      </motion.div>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="fixed inset-0 z-40"
        style={{ background: "rgba(0,0,0,0.5)" }}
      />
    </>
  );
}

// Row Drawer
function RowDrawer({ app, onClose }: { app: ApplicationRecord; onClose: () => void }) {
  return (
    <>
      <motion.div
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        className="fixed right-0 top-0 h-full w-[360px] z-50 overflow-y-auto p-6"
        style={{ background: colors.surface2, borderLeft: `1px solid ${colors.border}`, fontFamily: font.family }}
      >
        <button onClick={onClose} className="absolute top-4 right-4 p-1 border-0 bg-transparent cursor-pointer" style={{ color: colors.muted }}>
          <X size={18} />
        </button>
        <h3 style={{ fontSize: 16, fontWeight: 600, color: colors.mercury, marginBottom: 4 }}>{app.company_name}</h3>
        <p style={{ fontSize: 13, color: colors.muted, marginBottom: 16 }}>{app.role_title}</p>

        <DrawerRow label="Status"><StatusBadge status={app.status} /></DrawerRow>
        <DrawerRow label="Platform">{app.platform ? <PlatformBadge platform={app.platform} /> : <span style={{ color: colors.muted }}>-</span>}</DrawerRow>
        <DrawerRow label="ATS Score">
          <span style={{ color: app.similarity_score !== null ? atsColor(app.similarity_score) : colors.muted }}>
            {app.similarity_score !== null ? `${Math.round(app.similarity_score * 100)}%` : "-"}
          </span>
        </DrawerRow>
        <DrawerRow label="Applied"><span style={{ color: colors.mercury }}>{relativeDate(app.created_at)}</span></DrawerRow>
        {app.job_url && (
          <DrawerRow label="Link">
            <a href={app.job_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs no-underline" style={{ color: colors.teal }}>
              Open link <ExternalLink size={12} />
            </a>
          </DrawerRow>
        )}
        {app.notes && (
          <div className="mt-4 pt-4" style={{ borderTop: `1px solid ${colors.border}` }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: colors.muted, marginBottom: 6, display: "block" }}>Notes</span>
            <p style={{ fontSize: 13, color: colors.mercury, lineHeight: 1.5 }}>{app.notes}</p>
          </div>
        )}
      </motion.div>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="fixed inset-0 z-40" style={{ background: "rgba(0,0,0,0.5)" }} />
    </>
  );
}

function DrawerRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center py-2.5" style={{ borderBottom: `1px solid ${colors.border}22` }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: colors.muted }}>{label}</span>
      <div>{children}</div>
    </div>
  );
}

// Table View
function TableView({ apps }: { apps: ApplicationRecord[] }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const api = useApiClient();

  const urlStatuses = searchParams.get("status")?.split(",").filter(Boolean) ?? [];
  const urlCompany = searchParams.get("company") ?? "";

  const [selectedStatuses, setSelectedStatuses] = useState<AppStatus[]>(
    urlStatuses.filter((s): s is AppStatus => ALL_STATUSES.includes(s as AppStatus))
  );
  const [companySearch, setCompanySearch] = useState(urlCompany);
  const [dateFrom, setDateFrom] = useState(searchParams.get("date_from") ?? "");
  const [dateTo, setDateTo] = useState(searchParams.get("date_to") ?? "");
  const [platformFilter, setPlatformFilter] = useState<string[]>([]);
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [drawerApp, setDrawerApp] = useState<ApplicationRecord | null>(null);
  const [companyDrawer, setCompanyDrawer] = useState<string | null>(null);

  // Company autocomplete
  const uniqueCompanies = useMemo(() => {
    const set = new Set(apps.map((a) => a.company_name));
    return Array.from(set).sort();
  }, [apps]);
  const [showCompanyDropdown, setShowCompanyDropdown] = useState(false);
  const companySuggestions = useMemo(() => {
    if (!companySearch) return [];
    return uniqueCompanies.filter((c) => c.toLowerCase().includes(companySearch.toLowerCase())).slice(0, 8);
  }, [uniqueCompanies, companySearch]);

  const companyDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [debouncedCompany, setDebouncedCompany] = useState(urlCompany);

  const handleCompanyChange = useCallback((value: string) => {
    setCompanySearch(value);
    setShowCompanyDropdown(value.length > 0);
    if (companyDebounceRef.current) clearTimeout(companyDebounceRef.current);
    companyDebounceRef.current = setTimeout(() => setDebouncedCompany(value), 300);
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
    if (selectedStatuses.length > 0 && !selectedStatuses.includes(a.status)) return false;
    if (debouncedCompany && !a.company_name.toLowerCase().includes(debouncedCompany.toLowerCase())) return false;
    if (dateFrom && new Date(a.created_at) < new Date(dateFrom)) return false;
    if (dateTo && new Date(a.created_at) > new Date(dateTo + "T23:59:59")) return false;
    if (platformFilter.length > 0 && !platformFilter.includes(a.platform ?? "other")) return false;
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    if (!sortKey || !sortDir) return 0;
    const av = a[sortKey] ?? "";
    const bv = b[sortKey] ?? "";
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
    return sortDir === "asc" ? cmp : -cmp;
  });

  function handleSort(key: SortKey) {
    if (sortKey !== key) { setSortKey(key); setSortDir("asc"); }
    else if (sortDir === "asc") setSortDir("desc");
    else { setSortKey(null); setSortDir(null); }
  }

  function SortIcon({ colKey }: { colKey: SortKey }) {
    if (sortKey !== colKey) return <ChevronsUpDown size={12} />;
    return sortDir === "asc" ? <ChevronUp size={12} /> : <ChevronDown size={12} />;
  }

  const bulkMutation = useMutation({
    mutationFn: async (newStatus: AppStatus) => {
      await Promise.all([...selectedIds].map((id) => patchApplicationStatus(api, id, newStatus)));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["applications"] });
      void queryClient.invalidateQueries({ queryKey: ["applications-funnel"] });
      setSelectedIds(new Set());
    },
  });

  const allFilteredSelected = sorted.length > 0 && sorted.every((a) => selectedIds.has(a.id));

  function toggleSelectAll() {
    if (allFilteredSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(sorted.map((a) => a.id)));
  }

  function toggleRow(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function copyToClipboard(text: string) {
    void navigator.clipboard.writeText(text);
  }

  // Company apps for deep-dive
  const companyApps = companyDrawer
    ? apps.filter((a) => a.company_name === companyDrawer)
    : [];

  const thStyle = {
    padding: "8px 10px",
    fontSize: 11,
    fontWeight: 600 as const,
    color: colors.muted,
    textTransform: "uppercase" as const,
    letterSpacing: "0.04em",
    borderBottom: `1px solid ${colors.border}`,
    textAlign: "left" as const,
    fontFamily: font.family,
  };

  return (
    <div className="relative" style={{ fontFamily: font.family }}>
      {/* Filter bar */}
      <div className="flex items-center gap-2.5 flex-wrap mb-4">
        {/* Status multi-select */}
        <div className="relative">
          <button
            onClick={() => setStatusDropdownOpen((v) => !v)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs cursor-pointer border-0"
            style={{ background: colors.obsidian, border: `1px solid ${colors.border}`, color: colors.mercury, fontFamily: font.family }}
          >
            Status
            {selectedStatuses.length > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ background: `${colors.teal}20`, color: colors.teal }}>
                {selectedStatuses.length}
              </span>
            )}
          </button>
          {statusDropdownOpen && (
            <div className="absolute top-full left-0 mt-1 rounded-lg p-2 z-30 min-w-[160px]" style={{ background: colors.surface2, border: `1px solid ${colors.border}` }}>
              {ALL_STATUSES.map((s) => (
                <label key={s} className="flex items-center gap-2 px-2 py-1.5 text-xs cursor-pointer" style={{ color: colors.mercury }}>
                  <input type="checkbox" checked={selectedStatuses.includes(s)} onChange={() => setSelectedStatuses((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s])} style={{ accentColor: colors.teal }} />
                  {STATUS_LABELS[s]}
                </label>
              ))}
              {selectedStatuses.length > 0 && (
                <button onClick={() => setSelectedStatuses([])} className="w-full mt-1 text-left text-[11px] px-2 py-1 border-0 bg-transparent cursor-pointer" style={{ color: colors.muted }}>Clear</button>
              )}
            </div>
          )}
        </div>

        {/* Company autocomplete */}
        <div className="relative">
          <input
            type="text"
            placeholder="Search company"
            value={companySearch}
            onChange={(e) => handleCompanyChange(e.target.value)}
            onFocus={() => companySearch && setShowCompanyDropdown(true)}
            onBlur={() => setTimeout(() => setShowCompanyDropdown(false), 200)}
            className="px-2.5 py-1.5 rounded text-xs outline-none"
            style={{ background: colors.obsidian, border: `1px solid ${colors.border}`, color: colors.mercury, width: 150, fontFamily: font.family }}
          />
          {showCompanyDropdown && companySuggestions.length > 0 && (
            <div className="absolute top-full left-0 mt-1 rounded-lg p-1 z-30 w-full" style={{ background: colors.surface2, border: `1px solid ${colors.border}` }}>
              {companySuggestions.map((c) => (
                <button
                  key={c}
                  onMouseDown={() => { handleCompanyChange(c); setShowCompanyDropdown(false); }}
                  className="w-full text-left px-2 py-1.5 text-xs border-0 bg-transparent cursor-pointer rounded"
                  style={{ color: colors.mercury, fontFamily: font.family }}
                  onMouseEnter={(e) => { (e.currentTarget).style.background = colors.hoverSurface; }}
                  onMouseLeave={(e) => { (e.currentTarget).style.background = "transparent"; }}
                >
                  {c}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Date range */}
        <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
          className="px-2 py-1.5 rounded text-xs outline-none"
          style={{ background: colors.obsidian, border: `1px solid ${colors.border}`, color: dateFrom ? colors.mercury : colors.muted, colorScheme: "dark", fontFamily: font.family }}
        />
        <span style={{ fontSize: 11, color: colors.muted }}>to</span>
        <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
          className="px-2 py-1.5 rounded text-xs outline-none"
          style={{ background: colors.obsidian, border: `1px solid ${colors.border}`, color: dateTo ? colors.mercury : colors.muted, colorScheme: "dark", fontFamily: font.family }}
        />

        {/* Platform chips */}
        <div className="flex items-center gap-1">
          {PLATFORMS.map((p) => (
            <button
              key={p}
              onClick={() => setPlatformFilter((prev) => prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p])}
              className="px-2 py-1 rounded text-[10px] font-medium border-0 cursor-pointer capitalize"
              style={{
                background: platformFilter.includes(p) ? `${PLATFORM_COLORS[p] ?? colors.muted}20` : "transparent",
                color: platformFilter.includes(p) ? (PLATFORM_COLORS[p] ?? colors.mercury) : colors.muted,
                border: `1px solid ${colors.border}`,
                fontFamily: font.family,
              }}
            >
              {p}
            </button>
          ))}
        </div>

        <span className="text-xs ml-auto" style={{ color: colors.muted }}>
          {sorted.length} of {apps.length}
        </span>
      </div>

      {/* Bulk action bar */}
      <AnimatePresence>
        {selectedIds.size >= 2 && (
          <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
            className="flex items-center gap-3 mb-3 px-3 py-2 rounded-lg"
            style={{ background: `${colors.teal}08`, border: `1px solid ${colors.teal}30` }}
          >
            <span style={{ fontSize: 12, fontWeight: 500, color: colors.mercury }}>{selectedIds.size} selected</span>
            <select
              onChange={(e) => { const val = e.target.value as AppStatus; if (val) bulkMutation.mutate(val); e.target.value = ""; }}
              defaultValue=""
              className="text-xs px-2 py-1 rounded cursor-pointer"
              style={{ background: colors.obsidian, border: `1px solid ${colors.border}`, color: colors.mercury, fontFamily: font.family }}
            >
              <option value="" disabled>Update Status...</option>
              {ALL_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
            </select>
            <button onClick={() => setSelectedIds(new Set())} className="border-0 bg-transparent cursor-pointer p-1" style={{ color: colors.muted }}>
              <X size={14} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg" style={{ border: `1px solid ${colors.border}` }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ ...thStyle, width: 32, padding: "8px 10px" }}>
                <input type="checkbox" checked={allFilteredSelected} onChange={toggleSelectAll} style={{ accentColor: colors.teal }} />
              </th>
              {([
                ["company_name", "Company"],
                ["role_title", "Role"],
                ["platform", "Platform"],
                ["status", "Status"],
                ["similarity_score", "ATS"],
                ["created_at", "Applied"],
              ] as [SortKey, string][]).map(([key, label]) => (
                <th key={key} onClick={() => handleSort(key)} className="cursor-pointer select-none whitespace-nowrap" style={thStyle}>
                  <span className="flex items-center gap-1">{label} <SortIcon colKey={key} /></span>
                </th>
              ))}
              <th style={thStyle}>Job ID</th>
              <th style={thStyle}>JD</th>
              <th style={thStyle}>Notes</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr><td colSpan={10} className="text-center py-8" style={{ fontSize: 12, color: colors.muted }}>No applications match the current filters.</td></tr>
            ) : (
              sorted.map((app) => {
                const tdStyle = { padding: "8px 10px", fontSize: 12, borderBottom: `1px solid ${colors.border}22`, color: colors.mercury };
                return (
                  <tr
                    key={app.id}
                    onClick={() => setDrawerApp(app)}
                    className="cursor-pointer"
                    style={{ transition: "background 0.1s" }}
                    onMouseEnter={(e) => { (e.currentTarget).style.background = `${colors.border}44`; }}
                    onMouseLeave={(e) => { (e.currentTarget).style.background = selectedIds.has(app.id) ? `${colors.teal}08` : "transparent"; }}
                  >
                    <td style={{ ...tdStyle, verticalAlign: "middle" }} onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={selectedIds.has(app.id)} onChange={() => toggleRow(app.id)} style={{ accentColor: colors.teal, cursor: "pointer" }} />
                    </td>
                    <td style={{ ...tdStyle, fontWeight: 500 }} onClick={(e) => { e.stopPropagation(); setCompanyDrawer(app.company_name); }}>
                      <span className="hover:underline cursor-pointer" style={{ color: colors.teal }}>{app.company_name}</span>
                    </td>
                    <td style={tdStyle}>{app.role_title}</td>
                    <td style={tdStyle}>{app.platform ? <PlatformBadge platform={app.platform} /> : <span style={{ color: colors.muted }}>-</span>}</td>
                    <td style={tdStyle}><StatusBadge status={app.status} /></td>
                    <td style={{ ...tdStyle, color: app.similarity_score !== null ? atsColor(app.similarity_score) : colors.muted }}>
                      {app.similarity_score !== null ? `${Math.round(app.similarity_score * 100)}%` : "-"}
                    </td>
                    <td style={tdStyle}>{relativeDate(app.created_at)}</td>
                    <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: 11, color: colors.muted }} onClick={(e) => { e.stopPropagation(); if (app.job_id) copyToClipboard(app.job_id); }}>
                      {app.job_id ? (
                        <span className="flex items-center gap-1 cursor-pointer hover:opacity-80">
                          {app.job_id.slice(0, 12)}{app.job_id.length > 12 ? "..." : ""}
                          <Copy size={10} />
                        </span>
                      ) : "-"}
                    </td>
                    <td style={{ ...tdStyle, color: colors.muted, maxWidth: 120 }}>
                      {app.job_description ? (app.job_description.slice(0, 80) + (app.job_description.length > 80 ? "..." : "")) : "-"}
                    </td>
                    <td style={{ ...tdStyle, color: colors.muted, maxWidth: 160 }}>
                      {app.notes ? (app.notes.length > 60 ? app.notes.slice(0, 60) + "..." : app.notes) : "-"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Row drawer */}
      <AnimatePresence>
        {drawerApp && <RowDrawer app={drawerApp} onClose={() => setDrawerApp(null)} />}
      </AnimatePresence>

      {/* Company deep-dive drawer */}
      <AnimatePresence>
        {companyDrawer && <CompanyDrawer companyName={companyDrawer} apps={companyApps} onClose={() => setCompanyDrawer(null)} />}
      </AnimatePresence>

      {/* Dismiss dropdowns */}
      {statusDropdownOpen && <div className="fixed inset-0 z-20" onClick={() => setStatusDropdownOpen(false)} />}
    </div>
  );
}

// Main Applications page
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
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      className="p-6 w-full"
      style={{ fontFamily: font.family }}
    >
      <div className="flex items-center justify-between mb-6">
        <h1 style={{ fontSize: 20, fontWeight: 600, color: colors.mercury }}>Applications</h1>
        <div className="flex rounded-lg overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
          {([["board", KanbanSquare, "Board"], ["table", Table2, "Table"]] as const).map(([v, Icon, label]) => (
            <button
              key={v}
              onClick={() => switchView(v)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs cursor-pointer border-0"
              style={{
                background: view === v ? `${colors.teal}18` : "transparent",
                borderRight: v === "board" ? `1px solid ${colors.border}` : "none",
                color: view === v ? colors.teal : colors.muted,
                fontWeight: view === v ? 600 : 400,
                transition: "background 0.15s, color 0.15s",
                fontFamily: font.family,
              }}
            >
              <Icon size={14} />{label}
            </button>
          ))}
        </div>
      </div>

      <FunnelBar />

      {view === "board" ? <KanbanBoard /> : <TableView apps={data?.items ?? []} />}
    </motion.div>
  );
}
