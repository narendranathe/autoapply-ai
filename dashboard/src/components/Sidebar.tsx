import { NavLink } from "react-router-dom";
import { useUser } from "@clerk/clerk-react";
import {
  Sparkles,
  Briefcase,
  FileText,
  BrainCircuit,
  Settings,
} from "lucide-react";

const NAV = [
  { to: "/", icon: Sparkles, label: "Mirror" },
  { to: "/applications", icon: Briefcase, label: "Applications" },
  { to: "/vault", icon: FileText, label: "Vault" },
  { to: "/reflection", icon: BrainCircuit, label: "Reflection" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export function Sidebar() {
  const { user } = useUser();
  const initials = user ? (user.firstName?.[0] ?? "") + (user.lastName?.[0] ?? "") : "?";

  return (
    <aside
      className="flex flex-col justify-between shrink-0 border-r"
      style={{
        width: 220,
        minHeight: "100svh",
        background: "#111111",
        borderColor: "#2A2A2A",
      }}
    >
      {/* Logo */}
      <div>
        <div className="px-5 py-6">
          <span style={{ fontWeight: 600, fontSize: 15, color: "#00CED1", letterSpacing: "0.06em" }}>
            MIRROR
          </span>
        </div>

        {/* Nav */}
        <nav className="flex flex-col gap-1 px-2">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              style={({ isActive }) => ({
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "8px 12px",
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 500,
                color: isActive ? "#00CED1" : "#666666",
                background: isActive ? "rgba(0,206,209,0.08)" : "transparent",
                textDecoration: "none",
                transition: "color 0.15s, background 0.15s",
              })}
            >
              <Icon size={16} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {/* User slot */}
      <div
        className="flex items-center gap-3 px-4 py-5 border-t"
        style={{ borderColor: "#2A2A2A" }}
      >
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: "50%",
            background: "#2A2A2A",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 11,
            fontWeight: 600,
            color: "#E8E8E8",
            flexShrink: 0,
          }}
        >
          {user?.imageUrl ? (
            <img src={user.imageUrl} alt="" style={{ width: 30, height: 30, borderRadius: "50%" }} />
          ) : (
            initials.toUpperCase()
          )}
        </div>
        <div style={{ overflow: "hidden" }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "#E8E8E8", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {user?.firstName} {user?.lastName}
          </div>
          <div style={{ fontSize: 11, color: "#666666", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {user?.primaryEmailAddress?.emailAddress}
          </div>
        </div>
      </div>
    </aside>
  );
}
