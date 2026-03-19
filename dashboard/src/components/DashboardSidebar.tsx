import { useState, useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Briefcase,
  Search,
  FileEdit,
  FileText,
  Archive,
  Settings,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useSafeAuth } from "./ProtectedRoute";
import { useSync } from "../providers/SyncContext";
import { colors, font } from "../lib/tokens";

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/applications", icon: Briefcase, label: "Applications" },
  { to: "/job-scout", icon: Search, label: "Job Scout" },
  { to: "/cover-letters", icon: FileEdit, label: "Cover Letters" },
  { to: "/resumes", icon: FileText, label: "Resumes" },
  { to: "/vault", icon: Archive, label: "Vault" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

const LS_KEY = "sidebar_collapsed";

function formatSyncAgo(date: Date | null): string {
  if (!date) return "Not synced yet";
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "Last synced just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Last synced ${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `Last synced ${hours}h ago`;
}

export function Sidebar() {
  const { signOut } = useSafeAuth();
  const location = useLocation();
  const { lastSynced } = useSync();
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(LS_KEY) === "true"; } catch { return false; }
  });

  useEffect(() => {
    try { localStorage.setItem(LS_KEY, String(collapsed)); } catch {}
    // Dispatch custom event so App.tsx can react to sidebar toggle
    window.dispatchEvent(new CustomEvent("sidebar-toggle", { detail: { collapsed } }));
  }, [collapsed]);

  const width = collapsed ? 52 : 220;

  return (
    <aside
      className="hidden md:flex flex-col fixed left-0 top-0 h-screen z-40"
      style={{
        width,
        background: colors.surface,
        borderRight: `1px solid ${colors.border}`,
        fontFamily: font.family,
        transition: "width 200ms ease",
      }}
    >
      {/* Header */}
      <div className="px-3 pt-5 pb-3 flex items-center justify-between">
        {!collapsed && (
          <div className="flex items-center gap-2">
            <span
              className="w-[6px] h-[6px] rounded-full inline-block"
              style={{ background: colors.teal }}
            />
            <span
              style={{
                color: colors.mercury,
                fontWeight: 700,
                fontSize: 15,
                fontFamily: font.family,
                letterSpacing: "-0.01em",
              }}
            >
              AutoApply AI
            </span>
          </div>
        )}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="border-0 bg-transparent cursor-pointer p-1 rounded"
          style={{ color: colors.muted }}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 flex flex-col gap-0.5 px-2 mt-1">
        {NAV.map((item) => {
          const isActive =
            item.to === "/"
              ? location.pathname === "/"
              : location.pathname.startsWith(item.to);

          return (
            <NavLink
              key={item.to}
              to={item.to}
              title={collapsed ? item.label : undefined}
              className="group relative flex items-center gap-2.5 rounded no-underline"
              style={{
                padding: collapsed ? "8px 0" : "7px 10px",
                justifyContent: collapsed ? "center" : "flex-start",
                color: isActive ? colors.mercury : colors.muted,
                background: isActive ? colors.tealSubtle : "transparent",
                fontWeight: isActive ? 600 : 500,
                fontSize: 13,
                borderLeft: isActive
                  ? `2px solid ${colors.teal}`
                  : "2px solid transparent",
                transition: "background 150ms, color 150ms",
                fontFamily: font.family,
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  (e.currentTarget).style.background = colors.hoverSurface;
                  (e.currentTarget).style.color = colors.mercury;
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  (e.currentTarget).style.background = "transparent";
                  (e.currentTarget).style.color = colors.muted;
                }
              }}
            >
              <item.icon size={18} strokeWidth={isActive ? 2 : 1.5} />
              {!collapsed && <span>{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      {/* Sync timestamp */}
      {!collapsed && (
        <div className="px-3 py-2">
          <span
            style={{
              color: colors.muted,
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.04em",
              fontFamily: font.family,
            }}
          >
            {formatSyncAgo(lastSynced)}
          </span>
        </div>
      )}

      {/* User section */}
      <div
        className="px-3 py-3 flex items-center gap-2.5"
        style={{ borderTop: `1px solid ${colors.border}` }}
      >
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0"
          style={{ background: `${colors.teal}20`, color: colors.teal }}
        >
          U
        </div>
        {!collapsed && (
          <div className="flex-1 min-w-0">
            <button
              onClick={() => signOut?.()}
              className="text-[11px] hover:underline border-0 bg-transparent cursor-pointer p-0"
              style={{ color: colors.muted, fontFamily: font.family }}
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}

// Mobile bottom nav
export function MobileBottomNav() {
  const location = useLocation();

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 flex md:hidden"
      style={{
        background: colors.surface,
        borderTop: `1px solid ${colors.border}`,
        padding: "6px 0 env(safe-area-inset-bottom, 6px)",
      }}
    >
      {NAV.slice(0, 5).map((item) => {
        const isActive =
          item.to === "/"
            ? location.pathname === "/"
            : location.pathname.startsWith(item.to);

        return (
          <NavLink
            key={item.to}
            to={item.to}
            className="flex-1 flex flex-col items-center gap-1 py-2 no-underline"
            style={{
              color: isActive ? colors.teal : colors.muted,
              fontSize: 10,
              fontWeight: isActive ? 600 : 400,
              fontFamily: font.family,
            }}
          >
            <item.icon size={20} />
            <span>{item.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}

// Legacy export alias
export { Sidebar as DashboardSidebar };
