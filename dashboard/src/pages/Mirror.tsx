import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import type { Variants } from "framer-motion";
import { useUser, useAuth } from "@clerk/clerk-react";
import { useApiClient } from "../hooks/useApiClient";
import { colors } from "../lib/tokens";
import { fadeUp, mercuryRipple, streamToken } from "../lib/animations";

// Locally typed skeleton variant to avoid the string-ease inference issue in animations.ts
const skeletonVariants: Variants = {
  pulse: {
    opacity: [0.15, 0.3, 0.15],
    transition: { duration: 1.6, repeat: Infinity, ease: "easeInOut" },
  },
};

// ─── API response shape types ───────────────────────────────────────────────

interface MeResponse {
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
  phone?: string | null;
  location?: string | null;
  linkedin_url?: string | null;
  github_url?: string | null;
  summary?: string | null;
}

interface VaultAnalyticsResponse {
  total_resumes?: number;
  avg_ats_score?: number | null;
  avg_reward_score?: number | null;
}

interface ApplicationStatsResponse {
  total_count?: number;
  offer_count?: number;
  interview_count?: number;
  applied_count?: number;
}

// ─── Score helpers ───────────────────────────────────────────────────────────

function profileCompleteness(me: MeResponse): number {
  const fields: (keyof MeResponse)[] = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "location",
    "linkedin_url",
    "github_url",
    "summary",
  ];
  const filled = fields.filter((f) => {
    const v = me[f];
    return v !== null && v !== undefined && v !== "";
  }).length;
  return Math.round((filled / fields.length) * 100);
}

function calcScore(
  me: MeResponse | undefined,
  vault: VaultAnalyticsResponse | undefined,
  stats: ApplicationStatsResponse | undefined
): number {
  const profilePct = me ? profileCompleteness(me) : 0;
  const avgAts = vault?.avg_ats_score ?? 0;
  const avgReward = vault?.avg_reward_score ?? 0;
  const total = stats?.total_count ?? 0;
  const offers = stats?.offer_count ?? 0;
  const conversionRate = total > 0 ? (offers / total) * 100 : 0;

  return Math.round(
    profilePct * 0.25 + avgAts * 0.3 + avgReward * 0.25 + conversionRate * 0.2
  );
}

function scoreColor(score: number): string {
  if (score >= 80) return colors.teal;
  if (score >= 60) return "#F59E0B";
  return colors.ember;
}

// ─── Pulse ring animation ────────────────────────────────────────────────────

const pulseRing = {
  animate: {
    scale: [1, 1.18, 1],
    opacity: [0.35, 0, 0.35],
    transition: {
      duration: 4,
      repeat: Infinity,
      ease: "easeInOut" as const,
    },
  },
};

// ─── Quadrant card ───────────────────────────────────────────────────────────

interface QuadrantCardProps {
  label: string;
  value: string | number;
  subtitle: string;
  to: string;
  loading?: boolean;
}

function QuadrantCard({ label, value, subtitle, to, loading }: QuadrantCardProps) {
  const navigate = useNavigate();
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const rect = cardRef.current?.getBoundingClientRect();
    if (!rect) return;
    setMousePos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  }, []);

  const handleMouseLeave = useCallback(() => setMousePos(null), []);

  return (
    <motion.div
      ref={cardRef}
      variants={mercuryRipple}
      initial="rest"
      whileHover="hover"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      onClick={() => navigate(to)}
      style={{
        position: "relative",
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        borderRadius: 12,
        padding: "20px 24px",
        cursor: "pointer",
        overflow: "hidden",
        transition: "border-color 0.2s",
      }}
    >
      {/* cursor ripple */}
      {mousePos && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: `radial-gradient(circle 80px at ${mousePos.x}px ${mousePos.y}px, rgba(0,206,209,0.20) 0%, transparent 70%)`,
            pointerEvents: "none",
            transition: "opacity 0.3s ease-out",
          }}
        />
      )}

      <div style={{ fontSize: 11, fontWeight: 500, color: colors.muted, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
        {label}
      </div>

      {loading ? (
        <motion.div
          variants={skeletonVariants}
          animate="pulse"
          style={{ width: 64, height: 32, background: colors.border, borderRadius: 6 }}
        />
      ) : (
        <div style={{ fontSize: 28, fontWeight: 600, color: colors.mercury, lineHeight: 1.1 }}>
          {value}
        </div>
      )}

      <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>{subtitle}</div>
    </motion.div>
  );
}

// ─── Score ring display ──────────────────────────────────────────────────────

interface ScoreRingProps {
  score: number;
  loading: boolean;
}

function ScoreRing({ score, loading }: ScoreRingProps) {
  const color = scoreColor(score);

  if (loading) {
    return (
      <div style={{ position: "relative", width: 180, height: 180, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <motion.div
          variants={skeletonVariants}
          animate="pulse"
          style={{
            position: "absolute",
            width: 180,
            height: 180,
            borderRadius: "50%",
            border: `3px solid ${colors.teal}`,
            boxShadow: `0 0 24px ${colors.teal}`,
          }}
        />
        <motion.div
          variants={skeletonVariants}
          animate="pulse"
          style={{ width: 80, height: 40, background: colors.border, borderRadius: 8 }}
        />
      </div>
    );
  }

  return (
    <div style={{ position: "relative", width: 180, height: 180, display: "flex", alignItems: "center", justifyContent: "center" }}>
      {/* pulse ring */}
      <motion.div
        variants={pulseRing}
        animate="animate"
        style={{
          position: "absolute",
          width: 180,
          height: 180,
          borderRadius: "50%",
          border: `2px solid ${color}`,
          boxShadow: `0 0 16px ${color}`,
        }}
      />
      {/* static ring */}
      <div
        style={{
          position: "absolute",
          width: 150,
          height: 150,
          borderRadius: "50%",
          border: `2px solid ${color}`,
          opacity: 0.4,
        }}
      />
      {/* score */}
      <div style={{ textAlign: "center", zIndex: 1 }}>
        <div
          style={{
            fontSize: 64,
            fontWeight: 600,
            color,
            lineHeight: 1,
            fontFamily: "'Plus Jakarta Sans', sans-serif",
          }}
        >
          {score}
        </div>
        <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>/ 100</div>
      </div>
    </div>
  );
}

// ─── Reflection panel ────────────────────────────────────────────────────────

const BASE_URL = import.meta.env.VITE_API_URL ?? "https://autoapply-ai-api.fly.dev/api/v1";

interface ReflectionPanelProps {
  firstName: string;
  lastName: string;
}

function ReflectionPanel({ firstName, lastName }: ReflectionPanelProps) {
  const { getToken } = useAuth();
  const [tokens, setTokens] = useState<string[]>([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const startReflection = useCallback(async () => {
    setTokens([]);
    setStreaming(true);
    abortRef.current = new AbortController();

    try {
      // Get auth token for the fetch call
      let authHeader: HeadersInit = {};
      const token = await getToken();
      if (token) authHeader = { Authorization: `Bearer ${token}` };

      const response = await fetch(`${BASE_URL}/reflect`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeader,
        },
        body: JSON.stringify({
          context_type: "profile",
          profile_summary: `${firstName} ${lastName}`.trim(),
        }),
        signal: abortRef.current.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Reflect API error: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        // Handle SSE lines: "data: token\n\n"
        const lines = chunk.split("\n");
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const text = line.slice(6);
            if (text === "[DONE]") break;
            if (text) {
              setTokens((prev) => [...prev, text]);
            }
          } else if (line.trim() && !line.startsWith(":")) {
            // plain text stream
            setTokens((prev) => [...prev, line]);
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setTokens((prev) => [...prev, "\n\n[Reflection unavailable — check API connection]"]);
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [firstName, lastName, getToken]);

  const stopReflection = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  const hasContent = tokens.length > 0;

  return (
    <div
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        borderRadius: 16,
        padding: 28,
        display: "flex",
        flexDirection: "column",
        gap: 20,
        height: "100%",
        minHeight: 420,
      }}
    >
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: colors.mercury, marginBottom: 4 }}>
          AI Reflection
        </div>
        <div style={{ fontSize: 12, color: colors.muted }}>
          Ask Claude to reflect on your career profile
        </div>
      </div>

      {/* Stream content area */}
      <div
        style={{
          flex: 1,
          background: "#0D0D0D",
          borderRadius: 10,
          border: `1px solid ${colors.border}`,
          padding: 16,
          minHeight: 200,
          fontSize: 13,
          lineHeight: 1.7,
          color: colors.mercury,
          overflowY: "auto",
          fontFamily: "'Plus Jakarta Sans', sans-serif",
        }}
      >
        {!hasContent && !streaming && (
          <div style={{ color: colors.muted, fontSize: 12 }}>
            Your career reflection will appear here...
          </div>
        )}

        {streaming && !hasContent && (
          <motion.div
            variants={skeletonVariants}
            animate="pulse"
            style={{ display: "flex", alignItems: "center", gap: 8, color: colors.teal, fontSize: 12 }}
          >
            <span>Reflecting</span>
            <span>...</span>
          </motion.div>
        )}

        <AnimatePresence>
          {tokens.map((token, i) => (
            <motion.span
              key={i}
              variants={streamToken}
              initial="hidden"
              animate="visible"
              style={{ display: "inline" }}
            >
              {token}
            </motion.span>
          ))}
        </AnimatePresence>
      </div>

      {/* Action buttons */}
      <div style={{ display: "flex", gap: 10 }}>
        {!streaming ? (
          <button
            onClick={startReflection}
            style={{
              background: colors.teal,
              color: "#0D0D0D",
              border: "none",
              borderRadius: 8,
              padding: "10px 20px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              transition: "opacity 0.15s",
              fontFamily: "'Plus Jakarta Sans', sans-serif",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.85")}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
          >
            Ask Claude to Reflect
          </button>
        ) : (
          <button
            onClick={stopReflection}
            style={{
              background: "transparent",
              color: colors.ember,
              border: `1px solid ${colors.ember}`,
              borderRadius: 8,
              padding: "10px 20px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              transition: "opacity 0.15s",
              fontFamily: "'Plus Jakarta Sans', sans-serif",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.75")}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
          >
            Stop
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Main Mirror page ────────────────────────────────────────────────────────

export default function Mirror() {
  const apiClient = useApiClient();
  const { user } = useUser();

  const meQuery = useQuery<MeResponse>({
    queryKey: ["auth-me"],
    queryFn: async () => {
      const res = await apiClient.get<MeResponse>("/auth/me");
      return res.data;
    },
  });

  const vaultQuery = useQuery<VaultAnalyticsResponse>({
    queryKey: ["vault-analytics"],
    queryFn: async () => {
      const res = await apiClient.get<VaultAnalyticsResponse>("/vault/analytics");
      return res.data;
    },
  });

  const statsQuery = useQuery<ApplicationStatsResponse>({
    queryKey: ["application-stats"],
    queryFn: async () => {
      const res = await apiClient.get<ApplicationStatsResponse>("/applications/stats");
      return res.data;
    },
  });

  const anyLoading = meQuery.isLoading || vaultQuery.isLoading || statsQuery.isLoading;

  const score = calcScore(meQuery.data, vaultQuery.data, statsQuery.data);
  const profilePct = meQuery.data ? profileCompleteness(meQuery.data) : 0;
  const resumeCount = vaultQuery.data?.total_resumes ?? 0;
  const avgReward = vaultQuery.data?.avg_reward_score ?? 0;
  const appTotal = statsQuery.data?.total_count ?? 0;

  const firstName = user?.firstName ?? meQuery.data?.first_name ?? "";
  const lastName = user?.lastName ?? meQuery.data?.last_name ?? "";

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      style={{
        minHeight: "100svh",
        background: colors.obsidian,
        backgroundImage: `radial-gradient(ellipse 60% 50% at 50% 30%, rgba(0,206,209,0.08) 0%, transparent 70%)`,
        padding: "40px 40px 60px",
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        boxSizing: "border-box",
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 40 }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: colors.teal, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
          Career Reflection Score
        </div>
        <div style={{ fontSize: 22, fontWeight: 600, color: colors.mercury }}>
          {firstName ? `Welcome back, ${firstName}` : "Your Career Dashboard"}
        </div>
      </div>

      {/* Two-column layout */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 380px",
          gap: 32,
          alignItems: "start",
        }}
        className="mirror-grid"
      >
        {/* Left column */}
        <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
          {/* Score ring */}
          <div style={{ display: "flex", justifyContent: "flex-start" }}>
            <ScoreRing score={score} loading={anyLoading} />
          </div>

          {/* Quadrant cards grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
            }}
          >
            <QuadrantCard
              label="Applications"
              value={anyLoading ? "—" : appTotal}
              subtitle="Total tracked"
              to="/applications"
              loading={statsQuery.isLoading}
            />
            <QuadrantCard
              label="Resume Vault"
              value={anyLoading ? "—" : resumeCount}
              subtitle="Saved resumes"
              to="/vault"
              loading={vaultQuery.isLoading}
            />
            <QuadrantCard
              label="Answer Quality"
              value={anyLoading ? "—" : `${Math.round(avgReward * 100) / 100}`}
              subtitle="Avg reward score"
              to="/reflection"
              loading={vaultQuery.isLoading}
            />
            <QuadrantCard
              label="Profile"
              value={anyLoading ? "—" : `${profilePct}%`}
              subtitle="Completeness"
              to="/settings"
              loading={meQuery.isLoading}
            />
          </div>
        </div>

        {/* Right column — AI Reflection panel */}
        <ReflectionPanel firstName={firstName} lastName={lastName} />
      </div>

      {/* Responsive overrides via style tag */}
      <style>{`
        @media (max-width: 1024px) {
          .mirror-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </motion.div>
  );
}
