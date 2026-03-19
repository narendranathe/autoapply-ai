import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Upload, Download, Star, X, FileText, ChevronLeft, Plus } from "lucide-react";
import Editor from "@monaco-editor/react";
import { Worker, Viewer } from "@react-pdf-viewer/core";
import { defaultLayoutPlugin } from "@react-pdf-viewer/default-layout";
import "@react-pdf-viewer/core/lib/styles/index.css";
import "@react-pdf-viewer/default-layout/lib/styles/index.css";
import { useApiClient } from "../hooks/useApiClient";
import { fetchResumes, downloadResume, uploadResume, type ResumeRecord } from "../api/resumes";
import { colors } from "../lib/tokens";
import { fadeUp } from "../lib/animations";

function groupByCompany(resumes: ResumeRecord[]): Record<string, ResumeRecord[]> {
  return resumes.reduce((acc, r) => {
    const key = r.target_company ?? "General";
    if (!acc[key]) acc[key] = [];
    acc[key].push(r);
    return acc;
  }, {} as Record<string, ResumeRecord[]>);
}

const EXT_COLORS: Record<string, string> = { pdf: "#EF4444", docx: "#3B82F6", tex: "#8B5CF6", txt: "#6B7280" };

function extColor(filename: string) { return EXT_COLORS[filename.split(".").pop()?.toLowerCase() ?? ""] ?? "#6B7280"; }
function extLabel(filename: string) { return (filename.split(".").pop() ?? "FILE").toUpperCase(); }
function isTex(filename: string) { return filename.toLowerCase().endsWith(".tex"); }
function isPdf(filename: string) { return filename.toLowerCase().endsWith(".pdf"); }

function ResumeCard({ resume, onSelect, onDownload }: { resume: ResumeRecord; onSelect: (r: ResumeRecord) => void; onDownload: (r: ResumeRecord) => void }) {
  const color = extColor(resume.filename);
  return (
    <div
      onClick={() => onSelect(resume)}
      style={{
        background: "#0D0D0D", border: `1px solid ${colors.border}`,
        borderRadius: 10, padding: 16, cursor: "pointer",
        transition: "border-color 0.15s", position: "relative",
      }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = `${colors.teal}60`)}
      onMouseLeave={e => (e.currentTarget.style.borderColor = colors.border)}
    >
      {resume.is_base_template && (
        <div style={{
          position: "absolute", top: 10, right: 10,
          display: "flex", alignItems: "center", gap: 4,
          fontSize: 10, fontWeight: 600, color: colors.teal,
          background: `${colors.teal}15`, padding: "2px 7px", borderRadius: 4,
        }}>
          <Star size={9} fill={colors.teal} /> Base Template
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <div style={{
          width: 34, height: 34, borderRadius: 7, flexShrink: 0,
          background: `${color}18`, display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 9, fontWeight: 700, color, letterSpacing: "0.04em",
        }}>
          {extLabel(resume.filename)}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: colors.mercury, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {resume.version_tag ?? resume.filename}
          </div>
          {resume.target_role && <div style={{ fontSize: 11, color: colors.muted }}>{resume.target_role}</div>}
        </div>
      </div>
      <div style={{ fontSize: 11, color: colors.muted }}>
        {new Date(resume.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
      </div>
      <button
        onClick={e => { e.stopPropagation(); onDownload(resume); }}
        style={{
          marginTop: 10, width: "100%", padding: "6px 0", borderRadius: 6,
          background: "transparent", border: `1px solid ${colors.border}`,
          color: colors.muted, fontSize: 11, cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center", gap: 5,
        }}
      >
        <Download size={11} /> Download
      </button>
    </div>
  );
}

function SplitPane({ resume, onClose, apiClient }: { resume: ResumeRecord; onClose: () => void; apiClient: ReturnType<typeof useApiClient> }) {
  const defaultLayoutPluginInstance = defaultLayoutPlugin();
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [texContent, setTexContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadedRef = useRef(false);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    (async () => {
      try {
        const blob = await downloadResume(apiClient, resume.id);
        if (isTex(resume.filename)) {
          setTexContent(await blob.text());
        } else if (isPdf(resume.filename)) {
          setPdfUrl(URL.createObjectURL(blob));
        }
      } catch { /* ignore */ }
      finally { setLoading(false); }
    })();
    return () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div style={{ position: "fixed", inset: 0, background: "#000000CC", zIndex: 100, display: "flex", flexDirection: "column" }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 12, padding: "12px 20px",
        background: colors.sidebar, borderBottom: `1px solid ${colors.border}`, flexShrink: 0,
      }}>
        <button onClick={onClose} style={{
          background: "none", border: "none", cursor: "pointer", color: colors.muted,
          display: "flex", alignItems: "center", gap: 6, fontSize: 13, padding: 0,
        }}>
          <ChevronLeft size={16} /> Back
        </button>
        <div style={{ flex: 1, fontSize: 14, fontWeight: 500, color: colors.mercury }}>
          {resume.version_tag ?? resume.filename}
          {resume.is_base_template && <span style={{ marginLeft: 8, fontSize: 11, color: colors.teal }}>(Base Template)</span>}
        </div>
      </div>
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", overflow: "hidden" }}>
        {/* Editor pane */}
        <div style={{ borderRight: `1px solid ${colors.border}`, overflow: "hidden" }}>
          {isTex(resume.filename) ? (
            texContent !== null ? (
              <Editor
                height="100%"
                language="latex"
                theme="vs-dark"
                value={texContent}
                onChange={val => setTexContent(val ?? "")}
                options={{ fontSize: 13, minimap: { enabled: false }, wordWrap: "on", scrollBeyondLastLine: false, padding: { top: 16 } }}
              />
            ) : (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: colors.muted, fontSize: 13 }}>
                {loading ? "Loading..." : "Failed to load file"}
              </div>
            )
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 12, color: colors.muted }}>
              <FileText size={40} style={{ opacity: 0.4 }} />
              <div style={{ fontSize: 13 }}>LaTeX editor only available for .tex files</div>
            </div>
          )}
        </div>
        {/* Preview pane */}
        <div style={{ overflow: "auto", background: "#1a1a1a" }}>
          {loading && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: colors.muted, fontSize: 13 }}>
              Loading preview...
            </div>
          )}
          {!loading && pdfUrl && (
            <Worker workerUrl="https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js">
              <Viewer fileUrl={pdfUrl} plugins={[defaultLayoutPluginInstance]} />
            </Worker>
          )}
          {!loading && !pdfUrl && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 12, color: colors.muted }}>
              <FileText size={40} style={{ opacity: 0.4 }} />
              <div style={{ fontSize: 13, textAlign: "center" }}>PDF preview not available for {extLabel(resume.filename)} files</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const inp: React.CSSProperties = {
  width: "100%", padding: "8px 12px", background: "#0D0D0D",
  border: "1px solid #2A2A2A", borderRadius: 7, color: "#E8E8E8",
  fontSize: 13, outline: "none", fontFamily: "'Plus Jakarta Sans', sans-serif", boxSizing: "border-box",
};

export default function Resumes() {
  const apiClient = useApiClient();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<ResumeRecord | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [form, setForm] = useState({ versionTag: "", targetCompany: "", targetRole: "", isBase: false });
  const [file, setFile] = useState<File | null>(null);

  const { data: resumes = [], isLoading } = useQuery({
    queryKey: ["vault-resumes"],
    queryFn: () => fetchResumes(apiClient),
    refetchInterval: 60_000,
  });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      if (form.versionTag) fd.append("version_tag", form.versionTag);
      if (form.targetCompany) fd.append("target_company", form.targetCompany);
      if (form.targetRole) fd.append("target_role", form.targetRole);
      fd.append("is_base_template", String(form.isBase));
      await uploadResume(apiClient, fd);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["vault-resumes"] });
      setShowUpload(false);
      setFile(null);
      setForm({ versionTag: "", targetCompany: "", targetRole: "", isBase: false });
    },
  });

  const handleDownload = useCallback(async (resume: ResumeRecord) => {
    const blob = await downloadResume(apiClient, resume.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = resume.filename; a.click();
    URL.revokeObjectURL(url);
  }, [apiClient]);

  const grouped = groupByCompany(resumes);
  const companies = Object.keys(grouped).sort((a, b) => a === "General" ? 1 : b === "General" ? -1 : a.localeCompare(b));

  return (
    <>
      {selected && <SplitPane resume={selected} onClose={() => setSelected(null)} apiClient={apiClient} />}

      <motion.div variants={fadeUp} initial="hidden" animate="visible" style={{
        minHeight: "100svh", background: colors.obsidian,
        padding: "40px 40px 60px", fontFamily: "'Plus Jakarta Sans', sans-serif", boxSizing: "border-box",
      }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 32 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 500, color: colors.teal, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
              Resumes
            </div>
            <div style={{ fontSize: 22, fontWeight: 600, color: colors.mercury }}>Resume Vault</div>
          </div>
          <button onClick={() => setShowUpload(true)} style={{
            display: "flex", alignItems: "center", gap: 6, padding: "9px 16px",
            borderRadius: 8, fontSize: 13, fontWeight: 600,
            background: colors.teal, color: "#0D0D0D", border: "none", cursor: "pointer",
          }}>
            <Plus size={14} /> Upload Resume
          </button>
        </div>

        {isLoading && <div style={{ color: colors.muted, fontSize: 13 }}>Loading resumes...</div>}

        {!isLoading && resumes.length === 0 && (
          <div style={{ textAlign: "center", padding: 80, color: colors.muted }}>
            <Upload size={40} style={{ opacity: 0.4, margin: "0 auto 16px" }} />
            <div style={{ fontSize: 16, fontWeight: 600, color: colors.mercury, marginBottom: 8 }}>No resumes yet</div>
            <div style={{ fontSize: 13 }}>Upload your first resume to get started.</div>
          </div>
        )}

        {companies.map(company => (
          <div key={company} style={{ marginBottom: 32 }}>
            <div style={{
              fontSize: 11, fontWeight: 600, color: colors.teal, textTransform: "uppercase",
              letterSpacing: "0.08em", marginBottom: 14, paddingBottom: 8, borderBottom: `1px solid ${colors.border}`,
            }}>
              {company} <span style={{ color: colors.muted, fontWeight: 400 }}>({grouped[company].length})</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
              {grouped[company].map(r => (
                <ResumeCard key={r.id} resume={r} onSelect={setSelected} onDownload={handleDownload} />
              ))}
            </div>
          </div>
        ))}
      </motion.div>

      {showUpload && (
        <div style={{ position: "fixed", inset: 0, background: "#000000BB", zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{
            background: colors.surface, border: `1px solid ${colors.border}`,
            borderRadius: 16, padding: 32, width: 440, display: "flex", flexDirection: "column", gap: 16,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: 15, fontWeight: 600, color: colors.mercury }}>Upload Resume</div>
              <button onClick={() => setShowUpload(false)} style={{ background: "none", border: "none", cursor: "pointer", color: colors.muted }}>
                <X size={16} />
              </button>
            </div>
            <label style={{
              display: "flex", flexDirection: "column", alignItems: "center", gap: 8,
              padding: "24px 0", border: `2px dashed ${colors.border}`, borderRadius: 10, cursor: "pointer", color: colors.muted,
            }}>
              <Upload size={24} />
              <div style={{ fontSize: 13 }}>{file ? file.name : "Click or drag PDF, DOCX, or .tex"}</div>
              <input type="file" accept=".pdf,.docx,.tex,.txt" style={{ display: "none" }} onChange={e => setFile(e.target.files?.[0] ?? null)} />
            </label>
            {[
              { label: "Version Tag", key: "versionTag", ph: "e.g. v2-google-2025" },
              { label: "Target Company", key: "targetCompany", ph: "e.g. Google" },
              { label: "Target Role", key: "targetRole", ph: "e.g. Senior SWE" },
            ].map(({ label, key, ph }) => (
              <div key={key}>
                <label style={{ fontSize: 11, color: colors.muted, display: "block", marginBottom: 5 }}>{label}</label>
                <input
                  value={form[key as keyof typeof form] as string}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  placeholder={ph} style={inp}
                />
              </div>
            ))}
            <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
              <input type="checkbox" checked={form.isBase} onChange={e => setForm(f => ({ ...f, isBase: e.target.checked }))} />
              <span style={{ fontSize: 13, color: colors.mercury }}>Set as Base Template</span>
            </label>
            <button
              onClick={() => uploadMutation.mutate()}
              disabled={!file || uploadMutation.isPending}
              style={{
                padding: "10px 0", borderRadius: 8, fontSize: 13, fontWeight: 600,
                background: file ? colors.teal : colors.surface,
                color: file ? "#0D0D0D" : colors.muted,
                border: `1px solid ${file ? colors.teal : colors.border}`,
                cursor: file ? "pointer" : "not-allowed",
              }}
            >
              {uploadMutation.isPending ? "Uploading..." : "Upload"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
