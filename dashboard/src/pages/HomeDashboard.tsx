import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowUp, ArrowDown } from "lucide-react";
import { useApiClient } from "../hooks/useApiClient";
import { useSync } from "../providers/SyncContext";
import { colors, font } from "../lib/tokens";
import { fadeUp } from "../lib/animations";

// Types
interface ApplicationStatsResponse {
  total_applied?: number;
  total_interviews?: number;
  total_offers?: number;
  avg_ats_score?: number | null;
  week_count?: number;
  month_count?: number;
  week_prev?: number;
  month_prev?: number;
}

interface FunnelStage {
  status: string;
  count: number;
}

interface FunnelResponse {
  total: number;
  funnel: FunnelStage[];
}

interface ApplicationRecord {
  id: string;
  company_name: string;
  role_title: string;
  status: string;
  platform: string | null;
  job_url: string | null;
  similarity_score: number | null;
  is_priority?: boolean;
  created_at: string;
  updated_at?: string;
}

interface ApplicationListResponse {
  items: ApplicationRecord[];
  total: number;
}

const PIPELINE_STAGES = ["discovered", "applied", "interview", "offer"] as const;

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

function relativeTime(dateStr: string): string {
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const diff = Date.now() - new Date(dateStr).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return rtf.format(-seconds, "second");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return rtf.format(-minutes, "minute");
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return rtf.format(-hours, "hour");
  const days = Math.floor(hours / 24);
  return rtf.format(-days, "day");
}

function statusBadgeColor(status: string): string {
  switch (status) {
    case "applied": return colors.teal;
    case "interview": case "phone_screen": return "#3B82F6";
    case "offer": return "#22C55E";
    case "rejected": return colors.ember;
    default: return colors.muted;
  }
}

// Skeleton rows
function SkeletonRows({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="rounded mercury-shimmer"
          style={{ background: colors.surface2, height: 40, marginBottom: 6 }}
        />
      ))}
    </>
  );
}

// Trend Arrow
function TrendArrow({ current, previous }: { current: number; previous: number }) {
  if (previous === 0 && current === 0) return <span style={{ color: colors.muted, fontSize: 11 }}>--</span>;
  const diff = current - previous;
  if (diff === 0) return <span style={{ color: colors.muted, fontSize: 11 }}>0</span>;
  const isUp = diff > 0;
  return (
    <span className="flex items-center gap-0.5" style={{ color: isUp ? colors.teal : colors.ember, fontSize: 11, fontWeight: 600 }}>
      {isUp ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
      {Math.abs(diff)}
    </span>
  );
}

// StatusBadge
function StatusBadge({ status }: { status: string }) {
  const c = statusBadgeColor(status);
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: "0.04em",
        padding: "2px 8px",
        borderRadius: 4,
        background: `${c}18`,
        color: c,
      }}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

export default function HomeDashboard() {
  const api = useApiClient();
  const navigate = useNavigate();
  const { setLastSynced } = useSync();

  const statsQuery = useQuery({
    queryKey: ["application-stats"],
    queryFn: async () => {
      const res = await api.get<ApplicationStatsResponse>("/applications/stats");
      return res.data;
    },
    refetchInterval: 30000,
  });

  const funnelQuery = useQuery({
    queryKey: ["applications-funnel"],
    queryFn: async () => {
      const res = await api.get<FunnelResponse>("/applications/funnel");
      return res.data;
    },
    refetchInterval: 30000,
  });

  const recentQuery = useQuery({
    queryKey: ["applications-recent"],
    queryFn: async () => {
      const res = await api.get<ApplicationListResponse>("/applications", {
        params: { ordering: "-updated_at", limit: 5 },
      });
      return res.data;
    },
    refetchInterval: 30000,
  });

  const priorityQuery = useQuery({
    queryKey: ["applications-priority"],
    queryFn: async () => {
      const res = await api.get<ApplicationListResponse>("/applications", {
        params: { is_priority: true },
      });
      return res.data;
    },
    refetchInterval: 30000,
  });

  // Update sync timestamp on successful refetch
  const onRefetchSuccess = useCallback(() => {
    setLastSynced(new Date());
  }, [setLastSynced]);

  if (statsQuery.isSuccess && statsQuery.dataUpdatedAt) {
    onRefetchSuccess();
  }

  const stats = statsQuery.data;
  const funnel = funnelQuery.data;
  const recentItems = recentQuery.data?.items ?? [];
  const priorityItems = priorityQuery.data?.items ?? [];
  const loading = statsQuery.isLoading;

  const funnelMap = new Map<string, number>();
  funnel?.funnel.forEach((s) => funnelMap.set(s.status, s.count));

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      className="p-6 max-w-5xl mx-auto w-full"
      style={{ fontFamily: font.family }}
    >
      <h1 style={{ fontSize: 20, fontWeight: 600, color: colors.mercury, marginBottom: 24 }}>
        Dashboard
      </h1>

      {/* 2a. Hero Metric Row */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div
          className="rounded-lg p-4"
          style={{ background: colors.surface2, border: `1px solid ${colors.border}` }}
        >
          <span style={{ fontSize: 11, fontWeight: 600, color: colors.muted, letterSpacing: "0.04em" }}>
            THIS WEEK
          </span>
          <div className="flex items-center gap-3 mt-2">
            <span style={{ fontSize: 28, fontWeight: 700, color: colors.mercury }}>
              {loading ? "--" : (stats?.week_count ?? 0)}
            </span>
            {!loading && stats && (
              <TrendArrow current={stats.week_count ?? 0} previous={stats.week_prev ?? 0} />
            )}
          </div>
        </div>
        <div
          className="rounded-lg p-4"
          style={{ background: colors.surface2, border: `1px solid ${colors.border}` }}
        >
          <span style={{ fontSize: 11, fontWeight: 600, color: colors.muted, letterSpacing: "0.04em" }}>
            THIS MONTH
          </span>
          <div className="flex items-center gap-3 mt-2">
            <span style={{ fontSize: 28, fontWeight: 700, color: colors.mercury }}>
              {loading ? "--" : (stats?.month_count ?? 0)}
            </span>
            {!loading && stats && (
              <TrendArrow current={stats.month_count ?? 0} previous={stats.month_prev ?? 0} />
            )}
          </div>
        </div>
      </div>

      {/* 2b. Quick Stats Row */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {[
          { label: "Total Applied", value: stats?.total_applied ?? 0 },
          { label: "Interviews", value: stats?.total_interviews ?? 0 },
          { label: "Offers", value: stats?.total_offers ?? 0 },
          { label: "Avg ATS Score", value: stats?.avg_ats_score != null ? `${Math.round(stats.avg_ats_score)}%` : "--" },
        ].map((s) => (
          <div
            key={s.label}
            className="rounded-lg p-3"
            style={{ background: colors.surface2, border: `1px solid ${colors.border}` }}
          >
            <span style={{ fontSize: 11, fontWeight: 600, color: colors.muted, letterSpacing: "0.04em" }}>
              {s.label.toUpperCase()}
            </span>
            <div style={{ fontSize: 20, fontWeight: 700, color: colors.mercury, marginTop: 4 }}>
              {loading ? "--" : s.value}
            </div>
          </div>
        ))}
      </div>

      {/* 2c. Mini Kanban Pipeline Snapshot */}
      <div className="mb-6">
        <h2 style={{ fontSize: 13, fontWeight: 600, color: colors.mercury, marginBottom: 10 }}>
          Pipeline
        </h2>
        <div className="grid grid-cols-4 gap-3">
          {PIPELINE_STAGES.map((stage) => {
            const count = funnelMap.get(stage) ?? 0;
            const stageApps = recentItems.filter((a) => a.status === stage).slice(0, 3);
            return (
              <div
                key={stage}
                className="rounded-lg overflow-hidden"
                style={{ background: colors.surface2, border: `1px solid ${colors.border}` }}
              >
                <div className="px-3 py-2 flex items-center justify-between"
                  style={{ borderBottom: `1px solid ${colors.border}` }}
                >
                  <span style={{ fontSize: 11, fontWeight: 600, color: colors.muted, letterSpacing: "0.04em" }}>
                    {STATUS_LABELS[stage]?.toUpperCase()}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      padding: "1px 6px",
                      borderRadius: 4,
                      background: `${colors.teal}18`,
                      color: colors.teal,
                    }}
                  >
                    {count}
                  </span>
                </div>
                <div className="p-2 space-y-1.5" style={{ minHeight: 80 }}>
                  {funnelQuery.isLoading ? (
                    <SkeletonRows count={2} />
                  ) : stageApps.length === 0 ? (
                    <span style={{ fontSize: 11, color: `${colors.muted}80` }}>No items</span>
                  ) : (
                    stageApps.map((app) => (
                      <div
                        key={app.id}
                        className="rounded px-2 py-1.5"
                        style={{ background: colors.hoverSurface, fontSize: 12 }}
                      >
                        <div className="truncate" style={{ color: colors.mercury, fontWeight: 500 }}>
                          {app.company_name}
                        </div>
                        <div className="truncate" style={{ color: colors.muted, fontSize: 11 }}>
                          {app.role_title}
                        </div>
                      </div>
                    ))
                  )}
                </div>
                <button
                  onClick={() => navigate(`/applications?stage=${stage}`)}
                  className="w-full text-left px-3 py-1.5 border-0 bg-transparent cursor-pointer"
                  style={{
                    fontSize: 11,
                    color: colors.teal,
                    fontWeight: 500,
                    borderTop: `1px solid ${colors.border}`,
                    fontFamily: font.family,
                  }}
                >
                  See all →
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Two column: Priority Watchlist + Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 2d. Priority Watchlist */}
        <div
          className="rounded-lg overflow-hidden"
          style={{ background: colors.surface2, border: `1px solid ${colors.border}` }}
        >
          <div className="px-4 py-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
            <h2 style={{ fontSize: 13, fontWeight: 600, color: colors.mercury }}>
              Priority Watchlist
            </h2>
          </div>
          <div style={{ maxHeight: 280, overflowY: "auto" }}>
            {priorityQuery.isLoading ? (
              <div className="p-3"><SkeletonRows count={3} /></div>
            ) : priorityItems.length === 0 ? (
              <div className="px-4 py-6 text-center">
                <span style={{ fontSize: 12, color: colors.muted }}>
                  No priority companies yet — star an application to add it here.
                </span>
              </div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <tbody>
                  {priorityItems.slice(0, 6).map((app) => (
                    <tr key={app.id}>
                      <td style={{ padding: "8px 12px", fontSize: 12, color: colors.mercury, fontWeight: 500, borderBottom: `1px solid ${colors.border}22` }}>
                        {app.company_name}
                      </td>
                      <td style={{ padding: "8px 12px", fontSize: 12, color: colors.muted, borderBottom: `1px solid ${colors.border}22` }}>
                        {app.role_title}
                      </td>
                      <td style={{ padding: "8px 12px", borderBottom: `1px solid ${colors.border}22` }}>
                        <StatusBadge status={app.status} />
                      </td>
                      <td style={{ padding: "8px 12px", fontSize: 11, color: colors.muted, borderBottom: `1px solid ${colors.border}22` }}>
                        {new Date(app.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* 2e. Recent Activity Feed */}
        <div
          className="rounded-lg overflow-hidden"
          style={{ background: colors.surface2, border: `1px solid ${colors.border}` }}
        >
          <div className="px-4 py-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
            <h2 style={{ fontSize: 13, fontWeight: 600, color: colors.mercury }}>
              Recent Activity
            </h2>
          </div>
          <div>
            {recentQuery.isLoading ? (
              <div className="p-3"><SkeletonRows count={3} /></div>
            ) : recentItems.length === 0 ? (
              <div className="px-4 py-6 text-center">
                <span style={{ fontSize: 12, color: colors.muted }}>No recent activity.</span>
              </div>
            ) : (
              recentItems.map((app) => (
                <div
                  key={app.id}
                  className="flex items-center gap-3 px-4 py-2.5"
                  style={{ borderBottom: `1px solid ${colors.border}22` }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate" style={{ fontSize: 12, color: colors.mercury, fontWeight: 500 }}>
                        {app.company_name}
                      </span>
                      <span className="truncate" style={{ fontSize: 11, color: colors.muted }}>
                        {app.role_title}
                      </span>
                    </div>
                  </div>
                  <StatusBadge status={app.status} />
                  <span style={{ fontSize: 11, color: colors.muted, whiteSpace: "nowrap" }}>
                    {relativeTime(app.updated_at ?? app.created_at)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
