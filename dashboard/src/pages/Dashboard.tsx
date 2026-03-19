import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useApiClient } from "../hooks/useApiClient";
import { useSyncTime } from "../providers/SyncContext";
import { colors, font } from "../lib/tokens";
import { fadeUp } from "../lib/animations";
import { fetchApplications, type ApplicationRecord } from "../api/applications";
import { ActivityFeed } from "../components/ActivityFeed";
import { WatchlistPanel } from "../components/WatchlistPanel";

// ─── Types ────────────────────────────────────────────────────────────────────

interface AppStats {
  total_count: number;
  offer_count: number;
  interview_count: number;
  applied_count: number;
}

interface VaultAnalytics {
  total_resumes: number;
  avg_ats_score: number | null;
  avg_reward_score: number | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const MS_PER_DAY = 86_400_000;

function appsInRange(items: ApplicationRecord[], daysStart: number, daysEnd: number): number {
  const now = Date.now();
  return items.filter((a) => {
    const age = (now - new Date(a.created_at).getTime()) / MS_PER_DAY;
    return age >= daysStart && age < daysEnd;
  }).length;
}

function countByStatus(items: ApplicationRecord[], status: string): number {
  return items.filter((a) => a.status === status).length;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 600,
        color: colors.muted,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        marginBottom: 12,
      }}
    >
      {children}
    </div>
  );
}

function Card({
  children,
  onClick,
  style,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  style?: React.CSSProperties;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        padding: "16px 20px",
        cursor: onClick ? "pointer" : "default",
        transition: "border-color 0.15s",
        ...style,
      }}
      onMouseEnter={(e) => {
        if (onClick) (e.currentTarget as HTMLDivElement).style.borderColor = `${colors.teal}44`;
      }}
      onMouseLeave={(e) => {
        if (onClick) (e.currentTarget as HTMLDivElement).style.borderColor = colors.border;
      }}
    >
      {children}
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
  onClick,
}: {
  label: string;
  value: string | number;
  accent?: string;
  onClick?: () => void;
}) {
  return (
    <Card onClick={onClick} style={{ flex: 1 }}>
      <div style={{ fontSize: 11, color: colors.muted, fontWeight: 500, marginBottom: 6 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 24,
          fontWeight: 700,
          color: accent ?? colors.mercury,
          letterSpacing: "-0.5px",
        }}
      >
        {value}
      </div>
    </Card>
  );
}

const KANBAN_COLUMNS: { status: string; label: string }[] = [
  { status: "discovered", label: "Discovered" },
  { status: "applied", label: "Applied" },
  { status: "phone_screen", label: "Phone Screen" },
  { status: "interview", label: "Interview" },
  { status: "offer", label: "Offer" },
];

const KANBAN_STATUS_COLORS: Record<string, string> = {
  discovered: colors.muted,
  applied: colors.teal,
  phone_screen: colors.amber,
  interview: colors.amber,
  offer: "#22C55E",
};

function MiniKanban({
  items,
  onNavigate,
}: {
  items: ApplicationRecord[];
  onNavigate: () => void;
}) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {KANBAN_COLUMNS.map(({ status, label }) => {
        const count = countByStatus(items, status);
        const accent = KANBAN_STATUS_COLORS[status] ?? colors.muted;
        return (
          <div
            key={status}
            onClick={onNavigate}
            style={{
              flex: 1,
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              borderRadius: 8,
              padding: "12px 10px",
              textAlign: "center",
              cursor: "pointer",
              transition: "border-color 0.15s",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLDivElement).style.borderColor = `${accent}44`;
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLDivElement).style.borderColor = colors.border;
            }}
          >
            <div
              style={{
                fontSize: 18,
                fontWeight: 700,
                color: count > 0 ? accent : colors.muted,
                letterSpacing: "-0.3px",
              }}
            >
              {count}
            </div>
            <div
              style={{
                fontSize: 10,
                color: colors.muted,
                fontWeight: 500,
                marginTop: 4,
                lineHeight: 1.3,
              }}
            >
              {label}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Skeleton block ───────────────────────────────────────────────────────────

function SkeletonBlock({ w, h }: { w?: string | number; h?: string | number }) {
  return (
    <div
      style={{
        width: w ?? "100%",
        height: h ?? 16,
        background: colors.border,
        borderRadius: 4,
        opacity: 0.5,
      }}
    />
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const navigate = useNavigate();
  const client = useApiClient();
  const { markSynced } = useSyncTime();

  const onSuccess = useCallback(() => markSynced(), [markSynced]);

  const appsQuery = useQuery({
    queryKey: ["applications"],
    queryFn: async () => {
      const result = await fetchApplications(client);
      onSuccess();
      return result;
    },
    refetchInterval: 30_000,
  });

  const statsQuery = useQuery<AppStats>({
    queryKey: ["applications-stats"],
    queryFn: async () => {
      const { data } = await client.get<AppStats>("/applications/stats");
      return data;
    },
    refetchInterval: 30_000,
  });

  const vaultQuery = useQuery<VaultAnalytics>({
    queryKey: ["vault-analytics"],
    queryFn: async () => {
      const { data } = await client.get<VaultAnalytics>("/vault/analytics");
      return data;
    },
    refetchInterval: 60_000,
  });

  const items: ApplicationRecord[] = appsQuery.data?.items ?? [];
  const stats = statsQuery.data;
  const vault = vaultQuery.data;

  // Hero metric computations
  const thisWeek = appsInRange(items, 0, 7);
  const lastWeek = appsInRange(items, 7, 14);
  const trend = thisWeek - lastWeek;
  const trendColor =
    trend > 0 ? "#22C55E" : trend === 0 ? colors.amber : colors.muted;
  const trendLabel =
    trend > 0
      ? `+${trend} vs last week`
      : trend === 0
        ? "same as last week"
        : `${trend} vs last week`;

  const totalAllTime = appsQuery.data?.total ?? 0;

  const avgAts = vault?.avg_ats_score ?? null;
  const avgAtsDisplay = avgAts !== null ? `${(avgAts * 100).toFixed(1)}%` : "—";

  const goToApplications = () => navigate("/applications");

  const isLoading = appsQuery.isLoading;

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      style={{
        padding: "28px 32px",
        fontFamily: font.family,
        minHeight: "100%",
        overflowY: "auto",
      }}
    >
      {/* Page header */}
      <div style={{ marginBottom: 28 }}>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 700,
            color: colors.mercury,
            margin: 0,
            letterSpacing: "-0.4px",
          }}
        >
          Dashboard
        </h1>
        <div style={{ fontSize: 13, color: colors.muted, marginTop: 4 }}>
          Your job search at a glance
        </div>
      </div>

      {/* 2-column layout */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 340px",
          gap: 24,
          alignItems: "start",
        }}
      >
        {/* ── Left column ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>

          {/* Hero metric */}
          <Card>
            {isLoading ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <SkeletonBlock w="40%" h={40} />
                <SkeletonBlock w="25%" h={14} />
                <SkeletonBlock w="30%" h={12} />
              </div>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
                  <span
                    style={{
                      fontSize: 42,
                      fontWeight: 700,
                      color: colors.mercury,
                      letterSpacing: "-1px",
                      lineHeight: 1,
                    }}
                  >
                    {thisWeek}
                  </span>
                  <span style={{ fontSize: 16, color: colors.muted, fontWeight: 500 }}>
                    applications this week
                  </span>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: trendColor,
                      background: `${trendColor}18`,
                      border: `1px solid ${trendColor}30`,
                      borderRadius: 20,
                      padding: "2px 10px",
                    }}
                  >
                    {trendLabel}
                  </span>
                </div>

                <div style={{ marginTop: 8, fontSize: 12, color: colors.muted }}>
                  Total:{" "}
                  <span style={{ color: colors.mercury, fontWeight: 600 }}>
                    {totalAllTime} all time
                  </span>
                </div>
              </>
            )}
          </Card>

          {/* Quick stats row */}
          <div>
            <SectionLabel>Quick Stats</SectionLabel>
            <div style={{ display: "flex", gap: 12 }}>
              {isLoading || !stats ? (
                <>
                  {[0, 1, 2, 3].map((i) => (
                    <div
                      key={i}
                      style={{
                        flex: 1,
                        background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        borderRadius: 10,
                        padding: "16px 20px",
                      }}
                    >
                      <SkeletonBlock w="60%" h={12} />
                      <div style={{ marginTop: 10 }}>
                        <SkeletonBlock w="40%" h={28} />
                      </div>
                    </div>
                  ))}
                </>
              ) : (
                <>
                  <StatCard
                    label="Applied"
                    value={stats.applied_count}
                    accent={colors.teal}
                    onClick={goToApplications}
                  />
                  <StatCard
                    label="Interviews"
                    value={stats.interview_count}
                    accent={colors.amber}
                    onClick={goToApplications}
                  />
                  <StatCard
                    label="Offers"
                    value={stats.offer_count}
                    accent="#22C55E"
                    onClick={goToApplications}
                  />
                  <StatCard
                    label="Avg ATS"
                    value={avgAtsDisplay}
                    onClick={goToApplications}
                  />
                </>
              )}
            </div>
          </div>

          {/* Mini kanban snapshot */}
          <div>
            <SectionLabel>Pipeline Snapshot</SectionLabel>
            {isLoading ? (
              <div style={{ display: "flex", gap: 8 }}>
                {[0, 1, 2, 3, 4].map((i) => (
                  <div
                    key={i}
                    style={{
                      flex: 1,
                      background: colors.surface,
                      border: `1px solid ${colors.border}`,
                      borderRadius: 8,
                      padding: "12px 10px",
                      textAlign: "center",
                    }}
                  >
                    <SkeletonBlock w="50%" h={22} />
                    <div style={{ marginTop: 8 }}>
                      <SkeletonBlock w="80%" h={10} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <MiniKanban items={items} onNavigate={goToApplications} />
            )}
          </div>
        </div>

        {/* ── Right column ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>

          {/* Watchlist */}
          <Card>
            <SectionLabel>Priority Watchlist</SectionLabel>
            <WatchlistPanel applications={items} />
          </Card>

          {/* Activity feed */}
          <Card>
            <SectionLabel>Recent Activity</SectionLabel>
            {isLoading ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {[0, 1, 2, 3, 4].map((i) => (
                  <div key={i} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <SkeletonBlock w={6} h={6} />
                    <div style={{ flex: 1 }}>
                      <SkeletonBlock w="60%" h={12} />
                      <div style={{ marginTop: 4 }}>
                        <SkeletonBlock w="40%" h={10} />
                      </div>
                    </div>
                    <SkeletonBlock w={40} h={10} />
                  </div>
                ))}
              </div>
            ) : (
              <ActivityFeed items={items} />
            )}
          </Card>
        </div>
      </div>
    </motion.div>
  );
}
