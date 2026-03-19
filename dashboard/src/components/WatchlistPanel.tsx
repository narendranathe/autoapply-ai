import { useState, useEffect } from "react";
import { X, Plus } from "lucide-react";
import { colors } from "../lib/tokens";
import type { ApplicationRecord } from "../api/applications";

interface WatchlistItem {
  company: string;
  note: string;
}

const STORAGE_KEY = "aap_watchlist";

function getLastApplied(company: string, applications: ApplicationRecord[]): string | null {
  const matches = applications.filter(
    (a) =>
      a.company_name.toLowerCase() === company.toLowerCase() &&
      ["applied", "phone_screen", "interview", "offer"].includes(a.status),
  );
  if (matches.length === 0) return null;
  matches.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  const date = new Date(matches[0].created_at);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function getStatus(company: string, applications: ApplicationRecord[]): string | null {
  const match = applications.find(
    (a) => a.company_name.toLowerCase() === company.toLowerCase(),
  );
  return match?.status ?? null;
}

const STATUS_COLORS: Record<string, string> = {
  interview: colors.amber,
  offer: "#22C55E",
  applied: colors.teal,
  phone_screen: colors.amber,
  rejected: colors.ember,
};

export function WatchlistPanel({ applications }: { applications: ApplicationRecord[] }) {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [input, setInput] = useState("");

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) setItems(JSON.parse(stored) as WatchlistItem[]);
    } catch {
      // ignore malformed storage
    }
  }, []);

  const save = (newItems: WatchlistItem[]) => {
    setItems(newItems);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(newItems));
  };

  const add = () => {
    const company = input.trim();
    if (!company || items.find((i) => i.company.toLowerCase() === company.toLowerCase())) {
      setInput("");
      return;
    }
    save([...items, { company, note: "" }]);
    setInput("");
  };

  const remove = (company: string) => save(items.filter((i) => i.company !== company));

  return (
    <div>
      {items.length === 0 && (
        <div style={{ fontSize: 12, color: colors.muted, padding: "8px 0" }}>
          Add target companies to track them here.
        </div>
      )}
      {items.map((item) => {
        const lastApplied = getLastApplied(item.company, applications);
        const status = getStatus(item.company, applications);
        return (
          <div
            key={item.company}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 0",
              borderBottom: `1px solid ${colors.border}`,
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, color: colors.mercury, fontWeight: 500 }}>
                {item.company}
              </div>
              <div style={{ fontSize: 11, color: colors.muted }}>
                {lastApplied ? `Last applied ${lastApplied}` : "Not applied yet"}
              </div>
            </div>
            {status && (
              <span
                style={{
                  fontSize: 10,
                  padding: "2px 6px",
                  borderRadius: 4,
                  background: `${STATUS_COLORS[status] ?? colors.muted}20`,
                  color: STATUS_COLORS[status] ?? colors.muted,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  flexShrink: 0,
                }}
              >
                {status.replace("_", " ")}
              </span>
            )}
            <button
              onClick={() => remove(item.company)}
              aria-label={`Remove ${item.company} from watchlist`}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: colors.muted,
                padding: 2,
                display: "flex",
                alignItems: "center",
                flexShrink: 0,
              }}
            >
              <X size={12} />
            </button>
          </div>
        );
      })}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder="Add company..."
          style={{
            flex: 1,
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            padding: "6px 10px",
            color: colors.mercury,
            fontSize: 12,
            outline: "none",
            fontFamily: "'Plus Jakarta Sans', sans-serif",
          }}
        />
        <button
          onClick={add}
          aria-label="Add company to watchlist"
          style={{
            background: `${colors.teal}15`,
            border: `1px solid ${colors.teal}30`,
            borderRadius: 6,
            padding: "6px 10px",
            color: colors.teal,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
          }}
        >
          <Plus size={14} />
        </button>
      </div>
    </div>
  );
}
