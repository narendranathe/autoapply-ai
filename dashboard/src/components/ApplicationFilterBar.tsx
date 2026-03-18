import { useSearchParams } from "react-router-dom";
import { useCallback, useEffect, useRef } from "react";
import { colors } from "../lib/tokens";
import type { AppStatus } from "../api/applications";

const ALL_STATUSES: AppStatus[] = [
  "discovered",
  "draft",
  "tailored",
  "applied",
  "phone_screen",
  "interview",
  "offer",
  "rejected",
];

const STATUS_LABEL: Record<string, string> = {
  discovered: "Discovered",
  draft: "Draft",
  tailored: "Tailored",
  applied: "Applied",
  phone_screen: "Phone Screen",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
};

interface Props {
  totalShown: number;
  totalAll: number;
}

export function ApplicationFilterBar({ totalShown, totalAll }: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const companyParam = searchParams.get("company") ?? "";
  const statusParams = searchParams.getAll("status");
  const dateFrom = searchParams.get("from") ?? "";
  const dateTo = searchParams.get("to") ?? "";

  // Debounce company search
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onCompanyChange = useCallback(
    (val: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          if (val) next.set("company", val);
          else next.delete("company");
          return next;
        });
      }, 300);
    },
    [setSearchParams],
  );

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const toggleStatus = useCallback(
    (status: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        const current = next.getAll("status");
        if (current.includes(status)) {
          next.delete("status");
          current.filter((s) => s !== status).forEach((s) => next.append("status", s));
        } else {
          next.append("status", status);
        }
        return next;
      });
    },
    [setSearchParams],
  );

  const onDateChange = useCallback(
    (key: "from" | "to", val: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (val) next.set(key, val);
        else next.delete(key);
        return next;
      });
    },
    [setSearchParams],
  );

  const clearFilters = useCallback(() => {
    setSearchParams({});
  }, [setSearchParams]);

  const hasFilters = statusParams.length > 0 || companyParam || dateFrom || dateTo;

  const inputStyle: React.CSSProperties = {
    background: colors.surface,
    border: `1px solid ${colors.border}`,
    borderRadius: 6,
    color: colors.mercury,
    fontSize: 12,
    padding: "5px 10px",
    outline: "none",
    fontFamily: "inherit",
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        flexWrap: "wrap",
        marginBottom: 12,
      }}
    >
      {/* Company search */}
      <input
        type="text"
        placeholder="Search company…"
        defaultValue={companyParam}
        onChange={(e) => onCompanyChange(e.target.value)}
        style={{ ...inputStyle, width: 160 }}
      />

      {/* Status multi-select chips */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {ALL_STATUSES.map((s) => {
          const active = statusParams.includes(s);
          return (
            <button
              key={s}
              onClick={() => toggleStatus(s)}
              style={{
                fontSize: 10,
                fontWeight: 600,
                padding: "3px 8px",
                borderRadius: 20,
                border: `1px solid ${active ? colors.teal : colors.border}`,
                background: active ? `${colors.teal}22` : "transparent",
                color: active ? colors.teal : colors.muted,
                cursor: "pointer",
                fontFamily: "inherit",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                transition: "all 0.15s",
              }}
            >
              {STATUS_LABEL[s]}
            </button>
          );
        })}
      </div>

      {/* Date range */}
      <input
        type="date"
        value={dateFrom}
        onChange={(e) => onDateChange("from", e.target.value)}
        style={{ ...inputStyle, colorScheme: "dark" }}
        aria-label="From date"
      />
      <span style={{ color: colors.muted, fontSize: 11 }}>–</span>
      <input
        type="date"
        value={dateTo}
        onChange={(e) => onDateChange("to", e.target.value)}
        style={{ ...inputStyle, colorScheme: "dark" }}
        aria-label="To date"
      />

      {/* Result count */}
      <span style={{ fontSize: 11, color: colors.muted, marginLeft: "auto" }}>
        Showing {totalShown} of {totalAll} applications
      </span>

      {hasFilters && (
        <button
          onClick={clearFilters}
          style={{
            fontSize: 11,
            color: colors.ember,
            background: "transparent",
            border: "none",
            cursor: "pointer",
            fontFamily: "inherit",
            textDecoration: "underline",
          }}
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
