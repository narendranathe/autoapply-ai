import { useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  LayoutDashboard,
  Briefcase,
  Telescope,
  FileText,
  ScrollText,
  BookOpen,
  Settings,
  LogOut,
  Wifi,
} from "lucide-react";
import { useUser, useAuth } from "@clerk/clerk-react";
import { useSyncTime } from "../providers/SyncContext";
import { colors } from "../lib/tokens";

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/applications", icon: Briefcase, label: "Applications" },
  { to: "/job-scout", icon: Telescope, label: "Job Scout" },
  { to: "/cover-letters", icon: FileText, label: "Cover Letters" },
  { to: "/resumes", icon: ScrollText, label: "Resumes" },
  { to: "/vault", icon: BookOpen, label: "Vault" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

function formatSyncAge(date: Date | null): string {
  if (!date) return "Not synced yet";
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return `Synced ${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Synced ${minutes}m ago`;
  return `Synced ${Math.floor(minutes / 60)}h ago`;
}

export function DashboardSidebar() {
  const { user } = useUser();
  const { signOut } = useAuth();
  const { lastSynced } = useSyncTime();
  const location = useLocation();
  const navigate = useNavigate();

  const initials = user
    ? (user.firstName?.[0] ?? "") + (user.lastName?.[0] ?? "")
    : "AA";
  const displayName = user
    ? `${user.firstName ?? ""} ${user.lastName ?? ""}`.trim()
    : "User";

  return (
    <aside
      className="hidden md:flex flex-col fixed left-0 top-0 h-screen z-40"
      style={{
        width: 220,
        background: colors.sidebar,
        borderRight: `1px solid ${colors.border}`,
      }}
    >
      {/* Logo */}
      <div className="px-5 pt-6 pb-4 flex items-center gap-2">
        <div
          className="w-2 h-2 rounded-full"
          style={{ background: colors.teal }}
        />
        <span
          className="text-sm tracking-tight font-semibold"
          style={{ color: colors.mercury, fontFamily: "'Plus Jakarta Sans', sans-serif" }}
        >
          AutoApply AI
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 flex flex-col gap-0.5 px-3 mt-2">
        {NAV.map((item) => {
          const isActive =
            item.to === "/"
              ? location.pathname === "/"
              : location.pathname.startsWith(item.to);

          return (
            <button
              key={item.to}
              onClick={() => navigate(item.to)}
              className="group relative flex items-center gap-3 rounded-md px-3 py-2.5 text-sm w-full text-left border-0 cursor-pointer"
              style={{
                color: isActive ? colors.mercury : colors.muted,
                background: isActive ? colors.hoverSurface : "transparent",
                fontWeight: isActive ? 600 : 400,
                borderLeft: isActive
                  ? `2px solid ${colors.teal}`
                  : "2px solid transparent",
                transition: "background 150ms, color 150ms",
                fontFamily: "'Plus Jakarta Sans', sans-serif",
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  (e.currentTarget as HTMLElement).style.background = colors.hoverSurface;
                  (e.currentTarget as HTMLElement).style.color = colors.mercury;
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  (e.currentTarget as HTMLElement).style.background = "transparent";
                  (e.currentTarget as HTMLElement).style.color = colors.muted;
                }
              }}
            >
              <item.icon size={16} strokeWidth={isActive ? 2.2 : 1.8} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Sync status */}
      <div className="px-4 py-2 flex items-center gap-2">
        <Wifi size={11} style={{ color: lastSynced ? colors.teal : colors.muted }} />
        <span style={{ fontSize: 11, color: colors.muted }}>
          {formatSyncAge(lastSynced)}
        </span>
      </div>

      {/* User section */}
      <div
        className="px-4 py-4 flex items-center gap-3"
        style={{ borderTop: `1px solid ${colors.border}` }}
      >
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0"
          style={{ background: `${colors.teal}20`, color: colors.teal }}
        >
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm truncate" style={{ color: colors.mercury, fontWeight: 500 }}>
            {displayName}
          </div>
          <button
            onClick={() => signOut?.()}
            className="text-xs mt-0.5 hover:underline border-0 bg-transparent cursor-pointer p-0 flex items-center gap-1"
            style={{ color: colors.muted }}
          >
            <LogOut size={10} /> Sign out
          </button>
        </div>
      </div>
    </aside>
  );
}

export function MobileBottomNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const MOBILE_NAV = NAV.slice(0, 5); // first 5 for mobile

  return (
    <motion.nav
      initial={{ y: 100 }}
      animate={{ y: 0 }}
      className="fixed bottom-0 left-0 right-0 z-50 flex md:hidden"
      style={{
        background: colors.sidebar,
        borderTop: `1px solid ${colors.border}`,
        padding: "6px 0 env(safe-area-inset-bottom, 6px)",
      }}
    >
      {MOBILE_NAV.map((item) => {
        const isActive =
          item.to === "/"
            ? location.pathname === "/"
            : location.pathname.startsWith(item.to);

        return (
          <button
            key={item.to}
            onClick={() => navigate(item.to)}
            className="flex-1 flex flex-col items-center gap-1 py-2 border-0 bg-transparent cursor-pointer"
            style={{
              color: isActive ? colors.teal : colors.muted,
              fontSize: 10,
              fontWeight: isActive ? 600 : 400,
            }}
          >
            <item.icon size={18} />
            <span>{item.label}</span>
          </button>
        );
      })}
    </motion.nav>
  );
}
