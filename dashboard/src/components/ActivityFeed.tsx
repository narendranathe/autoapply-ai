import { colors } from "../lib/tokens";
import type { ApplicationRecord } from "../api/applications";

const STATUS_COLORS: Record<string, string> = {
  discovered: colors.muted,
  draft: "#6366F1",
  tailored: "#8B5CF6",
  applied: colors.teal,
  phone_screen: colors.amber,
  interview: colors.amber,
  offer: "#22C55E",
  rejected: colors.ember,
};

function relativeDate(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

export function ActivityFeed({ items }: { items: ApplicationRecord[] }) {
  const sorted = [...items]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  if (sorted.length === 0) {
    return (
      <div style={{ padding: "24px 0", textAlign: "center", color: colors.muted, fontSize: 13 }}>
        No activity yet. Start applying with the Chrome extension.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
      {sorted.map((app) => (
        <div
          key={app.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "10px 0",
            borderBottom: `1px solid ${colors.border}`,
          }}
        >
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              flexShrink: 0,
              background: STATUS_COLORS[app.status] ?? colors.muted,
            }}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: 13,
                color: colors.mercury,
                fontWeight: 500,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {app.company_name}
            </div>
            <div style={{ fontSize: 11, color: colors.muted }}>{app.role_title}</div>
          </div>
          <div style={{ fontSize: 11, color: colors.muted, flexShrink: 0 }}>
            {relativeDate(app.created_at)}
          </div>
        </div>
      ))}
    </div>
  );
}
