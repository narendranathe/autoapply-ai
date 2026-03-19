import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { Search, ExternalLink, Plus, X, Telescope } from "lucide-react";
import { useApiClient } from "../hooks/useApiClient";
import { colors } from "../lib/tokens";
import { fadeUp } from "../lib/animations";
import type { ApplicationRecord, AppStatus } from "../api/applications";

// djb2 hash for company color avatar (same algo as floatingPanel.ts)
function companyHue(name: string): number {
  let hash = 0;
  for (const c of name) hash = (Math.imul(31, hash) + c.charCodeAt(0)) | 0;
  return Math.abs(hash) % 360;
}

function fitScoreColor(score: number | null): string {
  if (score === null) return "#6B7280";
  if (score >= 0.75) return "#22C55E";
  if (score >= 0.5) return "#F59E0B";
  return "#FF6B35";
}

function relativeDate(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "1d ago";
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

const PLATFORM_COLORS: Record<string, string> = {
  linkedin: "#0077B5", greenhouse: "#24A148", workday: "#8B5CF6",
  lever: "#EF4444", indeed: "#2164F3", manual: "#6B7280",
};

interface DiscoveryCardProps {
  app: ApplicationRecord;
  onAction: (id: string, status: AppStatus, direction: "right" | "left") => void;
  isActing: boolean;
}

function DiscoveryCard({ app, onAction, isActing }: DiscoveryCardProps) {
  const hue = companyHue(app.company_name);
  const scoreColor = fitScoreColor(app.similarity_score);
  const platform = app.platform?.toLowerCase() ?? "manual";
  const platformColor = PLATFORM_COLORS[platform] ?? PLATFORM_COLORS.manual;

  return (
    <motion.div
      layout
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        borderRadius: 12,
        padding: 20,
        display: "flex",
        flexDirection: "column",
        gap: 14,
        opacity: isActing ? 0.5 : 1,
        transition: "opacity 0.2s",
      }}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        {/* Company avatar */}
        <div style={{
          width: 40, height: 40, borderRadius: 10, flexShrink: 0,
          background: `hsl(${hue}, 60%, 35%)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 16, fontWeight: 700, color: "#fff",
        }}>
          {app.company_name[0]?.toUpperCase()}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: colors.mercury, marginBottom: 2 }}>
            {app.company_name}
          </div>
          <div style={{ fontSize: 13, color: colors.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {app.role_title}
          </div>
        </div>

        {/* Fit score */}
        {app.similarity_score !== null && (
          <div style={{
            fontSize: 12, fontWeight: 700, padding: "3px 8px",
            borderRadius: 6, flexShrink: 0,
            background: `${scoreColor}18`,
            color: scoreColor,
          }}>
            {Math.round(app.similarity_score * 100)}% fit
          </div>
        )}
      </div>

      {/* Meta row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{
          fontSize: 11, padding: "2px 8px", borderRadius: 4,
          background: `${platformColor}18`, color: platformColor,
          fontWeight: 500, textTransform: "capitalize",
        }}>
          {platform}
        </span>
        <span style={{ fontSize: 11, color: colors.muted }}>
          Discovered {relativeDate(app.created_at)}
        </span>
      </div>

      {/* Action buttons */}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => app.job_url && window.open(app.job_url, "_blank")}
          disabled={!app.job_url}
          style={{
            flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            padding: "7px 12px", borderRadius: 7, fontSize: 12, fontWeight: 500,
            background: "transparent", border: `1px solid ${colors.border}`,
            color: app.job_url ? colors.mercury : colors.muted,
            cursor: app.job_url ? "pointer" : "not-allowed",
          }}
        >
          <ExternalLink size={12} />
          View Job
        </button>

        <button
          onClick={() => onAction(app.id, "applied", "right")}
          disabled={isActing}
          style={{
            flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            padding: "7px 12px", borderRadius: 7, fontSize: 12, fontWeight: 600,
            background: `${colors.teal}15`, border: `1px solid ${colors.teal}40`,
            color: colors.teal, cursor: isActing ? "not-allowed" : "pointer",
          }}
        >
          <Plus size={12} />
          Add to Pipeline
        </button>

        <button
          onClick={() => onAction(app.id, "rejected", "left")}
          disabled={isActing}
          style={{
            padding: "7px 12px", borderRadius: 7, fontSize: 12,
            background: "transparent", border: `1px solid ${colors.border}`,
            color: colors.muted, cursor: isActing ? "not-allowed" : "pointer",
            display: "flex", alignItems: "center",
          }}
        >
          <X size={12} />
        </button>
      </div>
    </motion.div>
  );
}

export default function JobScout() {
  const apiClient = useApiClient();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [actingIds, setActingIds] = useState<Set<string>>(new Set());
  const [exitingIds, setExitingIds] = useState<Map<string, "right" | "left">>(new Map());

  // Fetch discovered + draft applications
  const { data: discoveredData, isLoading: loadingDiscovered } = useQuery({
    queryKey: ["applications", "discovered"],
    queryFn: async () => {
      const res = await apiClient.get<{ items: ApplicationRecord[] }>("/applications", {
        params: { status: "discovered", per_page: 100 },
      });
      return res.data.items;
    },
    refetchInterval: 30_000,
  });

  const { data: draftData, isLoading: loadingDraft } = useQuery({
    queryKey: ["applications", "draft"],
    queryFn: async () => {
      const res = await apiClient.get<{ items: ApplicationRecord[] }>("/applications", {
        params: { status: "draft", per_page: 100 },
      });
      return res.data.items;
    },
    refetchInterval: 30_000,
  });

  const mutation = useMutation({
    mutationFn: async ({ id, status }: { id: string; status: AppStatus }) => {
      await apiClient.patch(`/applications/${id}`, { status });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  const allJobs = [
    ...(discoveredData ?? []),
    ...(draftData ?? []),
  ].sort((a, b) => (b.similarity_score ?? 0) - (a.similarity_score ?? 0));

  const filtered = allJobs.filter((app) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return app.company_name.toLowerCase().includes(q) || app.role_title.toLowerCase().includes(q);
  });

  // Remove exiting cards from visible list
  const visible = filtered.filter((app) => !exitingIds.has(app.id));

  const handleAction = (id: string, status: AppStatus, direction: "right" | "left") => {
    setActingIds((prev) => new Set(prev).add(id));
    setExitingIds((prev) => new Map(prev).set(id, direction));
    setTimeout(() => {
      mutation.mutate({ id, status });
      setActingIds((prev) => { const s = new Set(prev); s.delete(id); return s; });
    }, 300);
  };

  const isLoading = loadingDiscovered || loadingDraft;

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      style={{
        minHeight: "100svh",
        background: colors.obsidian,
        padding: "40px 40px 60px",
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        boxSizing: "border-box",
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: colors.teal, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
          Job Scout
        </div>
        <div style={{ fontSize: 22, fontWeight: 600, color: colors.mercury, marginBottom: 4 }}>
          Discovered Opportunities
        </div>
        <div style={{ fontSize: 13, color: colors.muted }}>
          Jobs the extension found while you browsed — sorted by fit score.
        </div>
      </div>

      {/* Search */}
      <div style={{ position: "relative", marginBottom: 28, maxWidth: 400 }}>
        <Search size={14} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: colors.muted }} />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by company or role..."
          style={{
            width: "100%", paddingLeft: 36, paddingRight: 12,
            paddingTop: 9, paddingBottom: 9,
            background: colors.surface, border: `1px solid ${colors.border}`,
            borderRadius: 8, color: colors.mercury, fontSize: 13,
            outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif",
            boxSizing: "border-box",
          }}
        />
      </div>

      {/* Loading */}
      {isLoading && (
        <div style={{ color: colors.muted, fontSize: 13 }}>Loading opportunities...</div>
      )}

      {/* Empty state */}
      {!isLoading && visible.length === 0 && (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          padding: 80, gap: 16, textAlign: "center",
        }}>
          <Telescope size={40} style={{ color: colors.muted, opacity: 0.5 }} />
          <div style={{ fontSize: 16, fontWeight: 600, color: colors.mercury }}>
            {search ? "No matching jobs found" : "No jobs discovered yet"}
          </div>
          <div style={{ fontSize: 13, color: colors.muted, maxWidth: 340 }}>
            {search
              ? "Try a different search term."
              : "Browse job boards with the AutoApply AI Chrome extension — jobs will appear here automatically."}
          </div>
        </div>
      )}

      {/* Cards grid */}
      {!isLoading && visible.length > 0 && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 16,
        }}>
          <AnimatePresence>
            {visible.map((app) => (
              <DiscoveryCard
                key={app.id}
                app={app}
                onAction={handleAction}
                isActing={actingIds.has(app.id)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  );
}
