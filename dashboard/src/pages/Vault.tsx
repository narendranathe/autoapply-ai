import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { X, ChevronRight, Search } from "lucide-react";
import { useApiClient } from "../hooks/useApiClient";
import { colors, font } from "../lib/tokens";
import { fadeUp } from "../lib/animations";

// Types
interface VaultAnswer {
  id: string;
  question: string;
  answer: string;
  category: string | null;
  similarity_score: number | null;
  reward_score: number | null;
  created_at: string;
}

interface VaultResponse {
  items: VaultAnswer[];
}

const CATEGORIES = ["All", "Cover Letter", "Experience", "Skills", "Behavioral", "Other"] as const;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// Highlight match
function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark style={{ background: `${colors.teal}30`, color: colors.mercury, borderRadius: 2 }}>
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  );
}

// Answer Card
function AnswerCard({ item, search, onClick }: { item: VaultAnswer; search: string; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className="cursor-pointer group"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        borderRadius: 8,
        padding: "14px 16px",
        transition: "border-color 0.2s",
      }}
      onMouseEnter={(e) => { (e.currentTarget).style.borderColor = `${colors.teal}40`; }}
      onMouseLeave={(e) => { (e.currentTarget).style.borderColor = colors.border; }}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="text-sm font-medium" style={{ color: colors.mercury, lineHeight: 1.4 }}>
          <Highlight text={item.question.length > 100 ? item.question.slice(0, 100) + "..." : item.question} query={search} />
        </p>
        <ChevronRight size={14} className="opacity-0 group-hover:opacity-60 transition-opacity shrink-0 mt-0.5" style={{ color: colors.muted }} />
      </div>

      <p className="text-xs mb-3" style={{ color: colors.muted, lineHeight: 1.5 }}>
        <Highlight text={item.answer.length > 120 ? item.answer.slice(0, 120) + "..." : item.answer} query={search} />
      </p>

      <div className="flex items-center gap-2 flex-wrap">
        {item.category && (
          <span
            style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.04em", padding: "2px 6px", borderRadius: 4, background: colors.border, color: colors.mercury }}
          >
            {item.category}
          </span>
        )}
        {item.similarity_score !== null && (
          <span
            style={{ fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 4, background: `${colors.teal}18`, color: colors.teal }}
          >
            {Math.round(item.similarity_score * 100)}%
          </span>
        )}
        {item.reward_score !== null && (
          <span
            style={{ fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 4, background: `${colors.amber}18`, color: colors.amber }}
          >
            {item.reward_score >= 0.8 ? "Top" : item.reward_score.toFixed(2)}
          </span>
        )}
        <span className="ml-auto" style={{ fontSize: 10, color: colors.muted }}>
          {formatDate(item.created_at)}
        </span>
      </div>
    </div>
  );
}

export default function Vault() {
  const api = useApiClient();
  const [activeCategory, setActiveCategory] = useState("All");
  const [search, setSearch] = useState("");
  const [selectedAnswer, setSelectedAnswer] = useState<VaultAnswer | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["vault-answers"],
    queryFn: async () => {
      const res = await api.get<VaultResponse>("/vault/answers");
      return res.data;
    },
  });

  const items = data?.items ?? [];

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (!search && activeCategory !== "All") {
        const cat = (item.category ?? "Other").toLowerCase();
        if (cat !== activeCategory.toLowerCase()) return false;
      }
      if (search) {
        const q = search.toLowerCase();
        if (!item.question.toLowerCase().includes(q) && !item.answer.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [items, activeCategory, search]);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { All: items.length };
    items.forEach((item) => {
      const cat = item.category ?? "Other";
      counts[cat] = (counts[cat] ?? 0) + 1;
    });
    return counts;
  }, [items]);

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      className="p-6 w-full max-w-5xl mx-auto"
      style={{ fontFamily: font.family }}
    >
      <h1 style={{ fontSize: 20, fontWeight: 600, color: colors.mercury, marginBottom: 6 }}>
        Vault
      </h1>
      <p style={{ fontSize: 12, color: colors.muted, marginBottom: 20 }}>
        {isLoading ? "Loading..." : `${items.length} answer${items.length !== 1 ? "s" : ""} in your library`}
      </p>

      {/* Category tabs */}
      <div className="flex items-center gap-1 mb-4 flex-wrap">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => { setActiveCategory(cat); setSearch(""); }}
            className="px-3 py-1.5 rounded text-xs font-medium border-0 cursor-pointer"
            style={{
              background: activeCategory === cat ? colors.tealSubtle : colors.surface,
              color: activeCategory === cat ? colors.teal : colors.muted,
              border: `1px solid ${activeCategory === cat ? `${colors.teal}30` : colors.border}`,
              fontFamily: font.family,
              transition: "all 150ms",
            }}
          >
            {cat}
            {categoryCounts[cat] != null && (
              <span className="ml-1 opacity-60">{categoryCounts[cat]}</span>
            )}
          </button>
        ))}

        {/* Search */}
        <div className="relative ml-auto">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: colors.muted }} />
          <input
            type="text"
            placeholder="Search answers"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-7 pr-3 py-1.5 rounded text-xs outline-none"
            style={{
              background: colors.obsidian,
              border: `1px solid ${colors.border}`,
              color: colors.mercury,
              width: 180,
              fontFamily: font.family,
            }}
          />
        </div>
      </div>

      {/* Error */}
      {isError && (
        <div className="rounded-lg p-4 mb-4" style={{ background: `${colors.ember}10`, border: `1px solid ${colors.ember}30` }}>
          <p style={{ fontSize: 12, color: colors.ember }}>Failed to load vault answers.</p>
        </div>
      )}

      {/* Skeleton */}
      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="rounded-lg mercury-shimmer" style={{ background: colors.surface, border: `1px solid ${colors.border}`, height: 120 }} />
          ))}
        </div>
      )}

      {/* Empty */}
      {!isLoading && !isError && filtered.length === 0 && (
        <div className="text-center py-12">
          <p style={{ fontSize: 13, color: colors.muted }}>
            {search ? "No answers match your search." : "No answers in this category yet."}
          </p>
        </div>
      )}

      {/* Answer grid */}
      {!isLoading && filtered.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {filtered.map((item) => (
            <AnswerCard key={item.id} item={item} search={search} onClick={() => setSelectedAnswer(item)} />
          ))}
        </div>
      )}

      {/* Detail Drawer */}
      <AnimatePresence>
        {selectedAnswer && (
          <>
            <motion.div
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ duration: 0.25, ease: "easeOut" }}
              className="fixed right-0 top-0 h-full w-[420px] z-50 overflow-y-auto p-6"
              style={{ background: colors.surface2, borderLeft: `1px solid ${colors.border}` }}
            >
              <button
                onClick={() => setSelectedAnswer(null)}
                className="absolute top-4 right-4 p-1 border-0 bg-transparent cursor-pointer"
                style={{ color: colors.muted }}
              >
                <X size={18} />
              </button>

              <h3 style={{ fontSize: 14, fontWeight: 600, color: colors.mercury, marginBottom: 8, paddingRight: 24 }}>
                {selectedAnswer.question}
              </h3>

              <div className="flex items-center gap-2 mb-4">
                {selectedAnswer.category && (
                  <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 4, background: colors.border, color: colors.mercury }}>
                    {selectedAnswer.category}
                  </span>
                )}
                {selectedAnswer.similarity_score !== null && (
                  <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 4, background: `${colors.teal}18`, color: colors.teal }}>
                    {Math.round(selectedAnswer.similarity_score * 100)}%
                  </span>
                )}
                {selectedAnswer.reward_score !== null && (
                  <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 4, background: `${colors.amber}18`, color: colors.amber }}>
                    {selectedAnswer.reward_score >= 0.8 ? "Top" : selectedAnswer.reward_score.toFixed(2)}
                  </span>
                )}
              </div>

              <p style={{ fontSize: 13, color: colors.mercury, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                {selectedAnswer.answer}
              </p>

              <div className="mt-4 pt-3" style={{ borderTop: `1px solid ${colors.border}` }}>
                <span style={{ fontSize: 11, color: colors.muted }}>Added {formatDate(selectedAnswer.created_at)}</span>
              </div>
            </motion.div>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-40"
              style={{ background: "rgba(0,0,0,0.5)" }}
              onClick={() => setSelectedAnswer(null)}
            />
          </>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
