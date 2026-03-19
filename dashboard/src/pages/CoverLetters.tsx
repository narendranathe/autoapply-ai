import { useState, useCallback, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Plus, Save, Copy, Download, ChevronRight } from "lucide-react";
import { useApiClient } from "../hooks/useApiClient";
import { useSafeAuth } from "../components/ProtectedRoute";
import { colors, font } from "../lib/tokens";
import { fadeUp } from "../lib/animations";

interface CoverLetter {
  id: string;
  company: string;
  role: string;
  content: string;
  created_at: string;
}

interface CoverLettersResponse {
  items: CoverLetter[];
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const BASE_URL = import.meta.env.VITE_API_URL ?? "https://autoapply-ai-api.fly.dev/api/v1";

export default function CoverLetters() {
  const api = useApiClient();
  const { getToken } = useSafeAuth();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [showGenerator, setShowGenerator] = useState(false);

  // Generator state
  const [genCompany, setGenCompany] = useState("");
  const [genRole, setGenRole] = useState("");
  const [genJD, setGenJD] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamTokens, setStreamTokens] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["cover-letters"],
    queryFn: async () => {
      const res = await api.get<CoverLettersResponse>("/vault/cover-letters");
      return res.data;
    },
  });

  const items = data?.items ?? [];

  // Group by company
  const grouped = items.reduce<Record<string, CoverLetter[]>>((acc, cl) => {
    const key = cl.company || "Other";
    if (!acc[key]) acc[key] = [];
    acc[key].push(cl);
    return acc;
  }, {});

  const selected = items.find((cl) => cl.id === selectedId);

  const handleSelect = useCallback((cl: CoverLetter) => {
    setSelectedId(cl.id);
    setEditContent(cl.content);
    setShowGenerator(false);
    setStreamTokens([]);
  }, []);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setEditContent("");
    setShowGenerator(true);
    setStreamTokens([]);
    setGenCompany("");
    setGenRole("");
    setGenJD("");
  }, []);

  // SSE Generate
  const handleGenerate = useCallback(async () => {
    setStreamTokens([]);
    setStreaming(true);
    abortRef.current = new AbortController();

    try {
      const token = await getToken?.();
      const response = await fetch(`${BASE_URL}/vault/cover-letters/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          company: genCompany,
          role: genRole,
          job_description: genJD,
        }),
        signal: abortRef.current.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`API error: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const text = line.slice(6);
            if (text === "[DONE]") break;
            if (text) setStreamTokens((prev) => [...prev, text]);
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        setStreamTokens((prev) => [...prev, "\n[Generation failed - check API connection]"]);
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [getToken, genCompany, genRole, genJD]);

  const generatedText = streamTokens.join("");

  const handleCopy = useCallback(async (text: string) => {
    await navigator.clipboard.writeText(text);
  }, []);

  const handleDownload = useCallback((text: string, company: string) => {
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cover-letter-${company.toLowerCase().replace(/\s+/g, "-")}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (selectedId) {
        await api.patch(`/vault/cover-letters/${selectedId}`, { content: editContent });
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["cover-letters"] });
    },
  });

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      className="flex h-[calc(100vh-0px)]"
      style={{ fontFamily: font.family }}
    >
      {/* Left: Repository Panel */}
      <div
        className="w-[300px] shrink-0 flex flex-col overflow-y-auto"
        style={{
          background: colors.surface,
          borderRight: `1px solid ${colors.border}`,
        }}
      >
        <div className="px-4 pt-5 pb-3 flex items-center justify-between">
          <h1 style={{ fontSize: 15, fontWeight: 600, color: colors.mercury }}>
            Cover Letters
          </h1>
          <button
            onClick={handleNew}
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold border-0 cursor-pointer"
            style={{ background: colors.teal, color: colors.obsidian }}
          >
            <Plus size={12} /> New
          </button>
        </div>

        {isLoading ? (
          <div className="p-3 space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="rounded mercury-shimmer" style={{ height: 48, background: colors.surface2 }} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <span style={{ fontSize: 12, color: colors.muted }}>
              No cover letters yet - generate your first one.
            </span>
          </div>
        ) : (
          <div className="flex-1">
            {Object.entries(grouped).map(([company, letters]) => (
              <div key={company}>
                <div className="px-4 py-2" style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: colors.muted, letterSpacing: "0.04em" }}>
                    {company.toUpperCase()}
                  </span>
                </div>
                {letters.map((cl) => (
                  <button
                    key={cl.id}
                    onClick={() => handleSelect(cl)}
                    className="w-full text-left px-4 py-2.5 border-0 cursor-pointer flex items-center gap-2"
                    style={{
                      background: selectedId === cl.id ? colors.tealSubtle : "transparent",
                      borderBottom: `1px solid ${colors.border}22`,
                      fontFamily: font.family,
                    }}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="truncate" style={{ fontSize: 12, color: colors.mercury, fontWeight: 500 }}>
                        {cl.role}
                      </div>
                      <div className="truncate" style={{ fontSize: 11, color: colors.muted }}>
                        {formatDate(cl.created_at)} - {cl.content.slice(0, 40)}...
                      </div>
                    </div>
                    <ChevronRight size={14} style={{ color: colors.muted }} />
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Right: Editor/Generator Panel */}
      <div className="flex-1 flex flex-col p-6 overflow-y-auto" style={{ background: colors.obsidian }}>
        {showGenerator || (!selectedId && !streaming) ? (
          // Generator form
          <div className="max-w-xl">
            <h2 style={{ fontSize: 15, fontWeight: 600, color: colors.mercury, marginBottom: 16 }}>
              Generate Cover Letter
            </h2>
            <div className="space-y-3">
              <div>
                <label style={{ fontSize: 11, fontWeight: 600, color: colors.muted, letterSpacing: "0.04em" }}>COMPANY</label>
                <input
                  value={genCompany}
                  onChange={(e) => setGenCompany(e.target.value)}
                  className="w-full mt-1 px-3 py-2 rounded text-sm outline-none"
                  style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.mercury, fontFamily: font.family }}
                />
              </div>
              <div>
                <label style={{ fontSize: 11, fontWeight: 600, color: colors.muted, letterSpacing: "0.04em" }}>ROLE</label>
                <input
                  value={genRole}
                  onChange={(e) => setGenRole(e.target.value)}
                  className="w-full mt-1 px-3 py-2 rounded text-sm outline-none"
                  style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.mercury, fontFamily: font.family }}
                />
              </div>
              <div>
                <label style={{ fontSize: 11, fontWeight: 600, color: colors.muted, letterSpacing: "0.04em" }}>JOB DESCRIPTION</label>
                <textarea
                  value={genJD}
                  onChange={(e) => setGenJD(e.target.value)}
                  rows={6}
                  className="w-full mt-1 px-3 py-2 rounded text-sm outline-none resize-y"
                  style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.mercury, fontFamily: font.family }}
                />
              </div>
              <button
                onClick={handleGenerate}
                disabled={streaming || !genCompany || !genRole}
                className="px-4 py-2 rounded text-sm font-semibold border-0 cursor-pointer"
                style={{
                  background: colors.teal,
                  color: colors.obsidian,
                  opacity: streaming || !genCompany || !genRole ? 0.5 : 1,
                }}
              >
                {streaming ? "Generating..." : "Generate"}
              </button>
            </div>

            {/* Streaming output */}
            {streamTokens.length > 0 && (
              <pre
                className="mt-4 p-4 rounded-lg text-sm leading-relaxed whitespace-pre-wrap"
                style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.mercury, fontFamily: font.family }}
              >
                {generatedText}
              </pre>
            )}

            {generatedText && !streaming && (
              <div className="flex gap-2 mt-3">
                <button onClick={() => handleCopy(generatedText)} className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium border-0 cursor-pointer" style={{ background: colors.surface, color: colors.mercury, border: `1px solid ${colors.border}` }}>
                  <Copy size={12} /> Copy
                </button>
                <button onClick={() => handleDownload(generatedText, genCompany)} className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium border-0 cursor-pointer" style={{ background: colors.surface, color: colors.mercury, border: `1px solid ${colors.border}` }}>
                  <Download size={12} /> Download .txt
                </button>
              </div>
            )}
          </div>
        ) : selected ? (
          // Inline editor
          <div className="flex-1 flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 style={{ fontSize: 15, fontWeight: 600, color: colors.mercury }}>
                  {selected.company} - {selected.role}
                </h2>
                <span style={{ fontSize: 11, color: colors.muted }}>{formatDate(selected.created_at)}</span>
              </div>
            </div>

            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="flex-1 w-full p-4 rounded-lg text-sm outline-none resize-none"
              style={{
                background: colors.surface,
                border: `1px solid ${colors.border}`,
                color: colors.mercury,
                fontFamily: font.family,
                minHeight: 300,
              }}
            />

            <div className="flex gap-2 mt-3">
              <button
                onClick={() => saveMutation.mutate()}
                className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-semibold border-0 cursor-pointer"
                style={{ background: colors.teal, color: colors.obsidian }}
              >
                <Save size={12} /> {saveMutation.isPending ? "Saving..." : "Save"}
              </button>
              <button onClick={() => handleCopy(editContent)} className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium border-0 cursor-pointer" style={{ background: colors.surface, color: colors.mercury, border: `1px solid ${colors.border}` }}>
                <Copy size={12} /> Copy
              </button>
              <button onClick={() => handleDownload(editContent, selected.company)} className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium border-0 cursor-pointer" style={{ background: colors.surface, color: colors.mercury, border: `1px solid ${colors.border}` }}>
                <Download size={12} /> Download .txt
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </motion.div>
  );
}
