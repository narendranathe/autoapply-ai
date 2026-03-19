import { useCallback, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Copy, Download, ChevronDown, ChevronUp, Send, Square, Check } from "lucide-react";
import { useApiClient } from "../hooks/useApiClient";
import { useAuth } from "@clerk/clerk-react";
import { fetchCoverLetters, type CoverLetter } from "../api/coverLetters";
import { colors } from "../lib/tokens";
import { fadeUp } from "../lib/animations";

const BASE_URL = import.meta.env.VITE_API_URL ?? "https://autoapply-ai-api.fly.dev/api/v1";

function relativeDate(dateStr: string): string {
  const d = new Date(dateStr);
  const diff = Date.now() - d.getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days === 0) return "today";
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function groupByCompany(letters: CoverLetter[]): Record<string, CoverLetter[]> {
  return letters.reduce((acc, cl) => {
    const key = cl.company_name ?? "General";
    if (!acc[key]) acc[key] = [];
    acc[key].push(cl);
    return acc;
  }, {} as Record<string, CoverLetter[]>);
}

function CoverLetterItem({ cl }: { cl: CoverLetter }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(cl.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const download = () => {
    const blob = new Blob([cl.content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cover-letter-${cl.company_name ?? "general"}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ borderBottom: `1px solid ${colors.border}`, padding: "12px 0" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {cl.role_title && (
            <div style={{ fontSize: 13, fontWeight: 500, color: colors.mercury }}>{cl.role_title}</div>
          )}
          <div style={{ fontSize: 11, color: colors.muted }}>{relativeDate(cl.created_at)}</div>
          {!expanded && (
            <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>
              {cl.content.slice(0, 120)}...
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button onClick={copy} style={{
            background: "none", border: `1px solid ${colors.border}`, borderRadius: 6,
            padding: "4px 8px", cursor: "pointer", color: copied ? colors.teal : colors.muted,
            display: "flex", alignItems: "center",
          }}>
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
          <button onClick={download} style={{
            background: "none", border: `1px solid ${colors.border}`, borderRadius: 6,
            padding: "4px 8px", cursor: "pointer", color: colors.muted, display: "flex", alignItems: "center",
          }}>
            <Download size={12} />
          </button>
          <button onClick={() => setExpanded(!expanded)} style={{
            background: "none", border: `1px solid ${colors.border}`, borderRadius: 6,
            padding: "4px 8px", cursor: "pointer", color: colors.muted, display: "flex", alignItems: "center",
          }}>
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        </div>
      </div>
      {expanded && (
        <pre style={{
          marginTop: 12, padding: 14, background: "#0D0D0D",
          border: `1px solid ${colors.border}`, borderRadius: 8,
          fontSize: 12, color: colors.mercury, lineHeight: 1.7,
          whiteSpace: "pre-wrap", fontFamily: "'Plus Jakarta Sans', sans-serif",
          maxHeight: 300, overflow: "auto",
        }}>
          {cl.content}
        </pre>
      )}
    </div>
  );
}

const inp: React.CSSProperties = {
  width: "100%", padding: "8px 12px", background: "#0D0D0D",
  border: "1px solid #2A2A2A", borderRadius: 7,
  color: "#E8E8E8", fontSize: 13, outline: "none",
  fontFamily: "'Plus Jakarta Sans', sans-serif", boxSizing: "border-box",
};
const lbl: React.CSSProperties = {
  fontSize: 11, color: "#6B7280", fontWeight: 500,
  textTransform: "uppercase", letterSpacing: "0.06em",
  marginBottom: 6, display: "block",
};

export default function CoverLetters() {
  const apiClient = useApiClient();
  const { getToken } = useAuth();
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [jd, setJd] = useState("");
  const [streamTokens, setStreamTokens] = useState<string[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [copied, setCopied] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const { data: letters = [], isLoading } = useQuery({
    queryKey: ["cover-letters"],
    queryFn: () => fetchCoverLetters(apiClient),
    refetchInterval: 60_000,
  });

  const grouped = groupByCompany(letters);
  const companies = Object.keys(grouped).sort();

  const generate = useCallback(async () => {
    if (!company || !role) return;
    setStreamTokens([]);
    setStreaming(true);
    abortRef.current = new AbortController();
    try {
      const token = await getToken();
      const authHeader: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
      const response = await fetch(`${BASE_URL}/vault/cover-letters/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader },
        body: JSON.stringify({ company_name: company, role_title: role, job_description: jd }),
        signal: abortRef.current.signal,
      });
      if (!response.ok || !response.body) throw new Error(`API ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const collected: string[] = [];
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const line of decoder.decode(value, { stream: true }).split("\n")) {
          if (line.startsWith("data: ")) {
            const text = line.slice(6);
            if (text && text !== "[DONE]") { collected.push(text); setStreamTokens([...collected]); }
          } else if (line.trim() && !line.startsWith(":")) {
            collected.push(line); setStreamTokens([...collected]);
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError")
        setStreamTokens(["[Generation failed — check API connection]"]);
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [company, role, jd, getToken]);

  const stop = () => { abortRef.current?.abort(); setStreaming(false); };

  const copyOutput = () => {
    navigator.clipboard.writeText(streamTokens.join(""));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadOutput = () => {
    const blob = new Blob([streamTokens.join("")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cover-letter-${company}-${role}.txt`.replace(/\s+/g, "-").toLowerCase();
    a.click();
    URL.revokeObjectURL(url);
  };

  const canGenerate = !!company && !!role;

  return (
    <motion.div variants={fadeUp} initial="hidden" animate="visible" style={{
      minHeight: "100svh", background: colors.obsidian,
      padding: "40px 40px 60px", fontFamily: "'Plus Jakarta Sans', sans-serif", boxSizing: "border-box",
    }}>
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: colors.teal, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
          Cover Letters
        </div>
        <div style={{ fontSize: 22, fontWeight: 600, color: colors.mercury }}>Cover Letter Studio</div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 400px", gap: 32, alignItems: "start" }}>
        {/* Repository */}
        <div style={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: 12, padding: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: colors.mercury, marginBottom: 20 }}>
            My Cover Letters {letters.length > 0 && <span style={{ color: colors.muted, fontWeight: 400 }}>({letters.length})</span>}
          </div>
          {isLoading && <div style={{ color: colors.muted, fontSize: 13 }}>Loading...</div>}
          {!isLoading && letters.length === 0 && (
            <div style={{ color: colors.muted, fontSize: 13, padding: "24px 0", textAlign: "center" }}>
              No cover letters yet. Generate your first one →
            </div>
          )}
          {companies.map((co) => (
            <div key={co} style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: colors.teal, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
                {co}
              </div>
              {grouped[co].map((cl) => <CoverLetterItem key={cl.id} cl={cl} />)}
            </div>
          ))}
        </div>

        {/* Generator */}
        <div style={{
          background: colors.surface, border: `1px solid ${colors.border}`,
          borderRadius: 12, padding: 24, display: "flex", flexDirection: "column", gap: 16,
          position: "sticky", top: 24,
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: colors.mercury }}>Generate New</div>
          <div>
            <label style={lbl}>Company</label>
            <input value={company} onChange={e => setCompany(e.target.value)} placeholder="e.g. Google" style={inp} />
          </div>
          <div>
            <label style={lbl}>Role Title</label>
            <input value={role} onChange={e => setRole(e.target.value)} placeholder="e.g. Senior Engineer" style={inp} />
          </div>
          <div>
            <label style={lbl}>Job Description (optional)</label>
            <textarea value={jd} onChange={e => setJd(e.target.value)} rows={5} placeholder="Paste the job description..." style={{ ...inp, resize: "vertical" }} />
          </div>
          {!streaming ? (
            <button onClick={generate} disabled={!canGenerate} style={{
              padding: "9px 16px", borderRadius: 7, fontSize: 13, fontWeight: 600,
              background: canGenerate ? colors.teal : colors.surface,
              color: canGenerate ? "#0D0D0D" : colors.muted,
              border: `1px solid ${canGenerate ? colors.teal : colors.border}`,
              cursor: canGenerate ? "pointer" : "not-allowed",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            }}>
              <Send size={13} /> Generate
            </button>
          ) : (
            <button onClick={stop} style={{
              padding: "9px 16px", borderRadius: 7, fontSize: 13, fontWeight: 600,
              background: "transparent", border: `1px solid ${colors.ember}`, color: colors.ember,
              cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            }}>
              <Square size={13} /> Stop
            </button>
          )}
          {streamTokens.length > 0 && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <label style={lbl}>Output</label>
                <div style={{ display: "flex", gap: 6 }}>
                  <button onClick={copyOutput} style={{
                    background: "none", border: `1px solid ${colors.border}`, borderRadius: 6,
                    padding: "3px 8px", cursor: "pointer", color: copied ? colors.teal : colors.muted,
                    fontSize: 11, display: "flex", alignItems: "center", gap: 4,
                  }}>
                    {copied ? <Check size={10} /> : <Copy size={10} />} Copy
                  </button>
                  <button onClick={downloadOutput} style={{
                    background: "none", border: `1px solid ${colors.border}`, borderRadius: 6,
                    padding: "3px 8px", cursor: "pointer", color: colors.muted,
                    fontSize: 11, display: "flex", alignItems: "center", gap: 4,
                  }}>
                    <Download size={10} /> .txt
                  </button>
                </div>
              </div>
              <textarea value={streamTokens.join("")} onChange={() => {}} rows={12}
                style={{ ...inp, resize: "vertical", lineHeight: 1.7, color: streaming ? colors.teal : colors.mercury }} />
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
