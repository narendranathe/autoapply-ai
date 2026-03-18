import { useState, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, X, Download, ChevronRight, FileText } from "lucide-react";
import { useApiClient } from "../hooks/useApiClient";

// ── Design tokens ──────────────────────────────────────────────────────────────
const OBSIDIAN = "#0D0D0D";
const MERCURY = "#E8E8E8";
const AURORA = "#00CED1";
const EMBER = "#FF6B35";
const AMBER = "#F59E0B";

// ── Types ──────────────────────────────────────────────────────────────────────
interface Resume {
  id: string;
  filename: string;
  version_tag: string | null;
  is_base_template: boolean;
  target_company: string | null;
  ats_score: number | null;
  ats_breakdown: Record<string, number> | null;
  raw_text: string | null;
  created_at: string;
}

interface ResumesResponse {
  resumes: Resume[];
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function atsColor(score: number): string {
  if (score >= 80) return AURORA;
  if (score >= 65) return AMBER;
  return EMBER;
}

// ── Skeleton card ──────────────────────────────────────────────────────────────
function SkeletonCard() {
  return (
    <div
      style={{
        background: "#1A1A1A",
        borderRadius: 10,
        padding: "20px",
        border: "1px solid #2A2A2A",
        height: 160,
      }}
    >
      {[70, 40, 55, 30].map((w, i) => (
        <div
          key={i}
          style={{
            width: `${w}%`,
            height: 12,
            borderRadius: 6,
            background: "linear-gradient(90deg,#222 25%,#333 50%,#222 75%)",
            backgroundSize: "200% 100%",
            animation: "pulse 1.5s ease-in-out infinite",
            marginBottom: i < 3 ? 12 : 0,
          }}
        />
      ))}
    </div>
  );
}

// ── Resume card ────────────────────────────────────────────────────────────────
function ResumeCard({
  resume,
  onClick,
}: {
  resume: Resume;
  onClick: () => void;
}) {
  const score = resume.ats_score;
  return (
    <motion.div
      whileHover={{ scale: 1.02, borderColor: AURORA }}
      onClick={onClick}
      style={{
        background: "#1A1A1A",
        borderRadius: 10,
        padding: "20px",
        border: "1px solid #2A2A2A",
        cursor: "pointer",
        transition: "border-color 0.2s",
        height: 160,
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        overflow: "hidden",
      }}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <FileText size={16} color={AURORA} style={{ flexShrink: 0, marginTop: 2 }} />
        <span
          style={{
            fontFamily: "monospace",
            fontSize: 13,
            color: MERCURY,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flex: 1,
          }}
        >
          {resume.filename}
        </span>
      </div>

      {/* Badges */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <span
          style={{
            fontSize: 11,
            padding: "2px 8px",
            borderRadius: 99,
            background: resume.is_base_template ? `${AURORA}22` : "#2A2A2A",
            color: resume.is_base_template ? AURORA : "#999",
            border: `1px solid ${resume.is_base_template ? AURORA : "#333"}`,
          }}
        >
          {resume.is_base_template ? "base" : (resume.version_tag ?? "v1")}
        </span>
        <span
          style={{
            fontSize: 11,
            padding: "2px 8px",
            borderRadius: 99,
            background: "#2A2A2A",
            color: "#bbb",
          }}
        >
          {resume.target_company ?? "General"}
        </span>
      </div>

      {/* ATS score + date */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        {score !== null ? (
          <span
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: atsColor(score),
            }}
          >
            ATS {score}
          </span>
        ) : (
          <span style={{ fontSize: 12, color: "#555" }}>No ATS score</span>
        )}
        <span style={{ fontSize: 11, color: "#666" }}>
          {formatDate(resume.created_at)}
        </span>
      </div>
    </motion.div>
  );
}

// ── Drawer ─────────────────────────────────────────────────────────────────────
function ResumeDrawer({
  resume,
  onClose,
  onDownload,
}: {
  resume: Resume;
  onClose: () => void;
  onDownload: (id: string, filename: string) => void;
}) {
  const score = resume.ats_score;
  return (
    <motion.div
      initial={{ x: "100%" }}
      animate={{ x: 0 }}
      exit={{ x: "100%" }}
      transition={{ duration: 0.32, ease: [0.25, 0.1, 0.25, 1] }}
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        width: 400,
        height: "100vh",
        background: "#111",
        borderLeft: "1px solid #2A2A2A",
        zIndex: 200,
        display: "flex",
        flexDirection: "column",
        overflowY: "hidden",
      }}
    >
      {/* Drawer header */}
      <div
        style={{
          padding: "20px 24px",
          borderBottom: "1px solid #2A2A2A",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontFamily: "monospace",
            fontSize: 13,
            color: MERCURY,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            maxWidth: 280,
          }}
        >
          {resume.filename}
        </span>
        <button
          onClick={onClose}
          aria-label="Close resume preview"
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "#666",
            padding: 4,
          }}
        >
          <X size={18} />
        </button>
      </div>

      {/* Meta */}
      <div
        style={{
          padding: "16px 24px",
          borderBottom: "1px solid #1E1E1E",
          flexShrink: 0,
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            fontSize: 12,
            padding: "3px 10px",
            borderRadius: 99,
            background: resume.is_base_template ? `${AURORA}22` : "#2A2A2A",
            color: resume.is_base_template ? AURORA : "#999",
          }}
        >
          {resume.is_base_template ? "base" : (resume.version_tag ?? "v1")}
        </span>
        <span
          style={{ fontSize: 12, padding: "3px 10px", borderRadius: 99, background: "#2A2A2A", color: "#bbb" }}
        >
          {resume.target_company ?? "General"}
        </span>
        {score !== null && (
          <span style={{ fontSize: 12, fontWeight: 700, color: atsColor(score), padding: "3px 0" }}>
            ATS {score}
          </span>
        )}
      </div>

      {/* ATS breakdown */}
      {resume.ats_breakdown && Object.keys(resume.ats_breakdown).length > 0 && (
        <div
          style={{
            padding: "12px 24px",
            borderBottom: "1px solid #1E1E1E",
            flexShrink: 0,
          }}
        >
          <div style={{ fontSize: 11, color: "#666", marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
            ATS Breakdown
          </div>
          {Object.entries(resume.ats_breakdown).map(([key, val]) => (
            <div key={key} style={{ marginBottom: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                <span style={{ fontSize: 12, color: "#aaa" }}>{key}</span>
                <span style={{ fontSize: 12, color: atsColor(val), fontWeight: 600 }}>{val}</span>
              </div>
              <div style={{ height: 4, background: "#2A2A2A", borderRadius: 2, overflow: "hidden" }}>
                <div style={{ width: `${val}%`, height: "100%", background: atsColor(val), borderRadius: 2 }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Raw text */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "16px 24px",
        }}
      >
        <div style={{ fontSize: 11, color: "#666", marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
          Content
        </div>
        <pre
          style={{
            fontFamily: "monospace",
            fontSize: 12,
            color: "#ccc",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            margin: 0,
          }}
        >
          {resume.raw_text ?? "(No text extracted)"}
        </pre>
      </div>

      {/* Download button */}
      <div
        style={{
          padding: "16px 24px",
          borderTop: "1px solid #2A2A2A",
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => onDownload(resume.id, resume.filename)}
          style={{
            width: "100%",
            padding: "10px 0",
            background: AURORA,
            color: OBSIDIAN,
            border: "none",
            borderRadius: 8,
            fontWeight: 700,
            fontSize: 14,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
          }}
        >
          <Download size={16} />
          Download
        </button>
      </div>
    </motion.div>
  );
}

// ── Virtualised grid (>50 items) ───────────────────────────────────────────────
const COLS = 3;
const GAP = 16;
const CARD_HEIGHT = 160;

function VirtualGrid({
  resumes,
  onSelect,
}: {
  resumes: Resume[];
  onSelect: (r: Resume) => void;
}) {
  const parentRef = useRef<HTMLDivElement>(null);

  const rows = Math.ceil(resumes.length / COLS);

  const virtualizer = useVirtualizer({
    count: rows,
    getScrollElement: () => parentRef.current,
    estimateSize: () => CARD_HEIGHT + GAP,
    overscan: 3,
  });

  return (
    <div ref={parentRef} style={{ overflowY: "auto", height: "calc(100vh - 180px)" }}>
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((vItem) => {
          const startIdx = vItem.index * COLS;
          const rowResumes = resumes.slice(startIdx, startIdx + COLS);
          return (
            <div
              key={vItem.key}
              style={{
                position: "absolute",
                top: vItem.start,
                left: 0,
                right: 0,
                display: "grid",
                gridTemplateColumns: `repeat(${COLS}, 1fr)`,
                gap: GAP,
                paddingBottom: GAP,
              }}
            >
              {rowResumes.map((r) => (
                <ResumeCard key={r.id} resume={r} onClick={() => onSelect(r)} />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Flat grid (≤50 items) ──────────────────────────────────────────────────────
function FlatGrid({
  resumes,
  onSelect,
}: {
  resumes: Resume[];
  onSelect: (r: Resume) => void;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gap: GAP,
      }}
    >
      {resumes.map((r) => (
        <ResumeCard key={r.id} resume={r} onClick={() => onSelect(r)} />
      ))}
    </div>
  );
}

// ── Upload progress bar ────────────────────────────────────────────────────────
function UploadProgress({ progress }: { progress: number }) {
  return (
    <div
      style={{
        position: "fixed",
        bottom: 90,
        right: 24,
        width: 240,
        background: "#1A1A1A",
        border: "1px solid #2A2A2A",
        borderRadius: 8,
        padding: "10px 14px",
        zIndex: 150,
      }}
    >
      <div style={{ fontSize: 12, color: "#aaa", marginBottom: 6 }}>Uploading… {progress}%</div>
      <div style={{ height: 4, background: "#2A2A2A", borderRadius: 2, overflow: "hidden" }}>
        <motion.div
          animate={{ width: `${progress}%` }}
          transition={{ ease: "easeOut" }}
          style={{ height: "100%", background: AURORA, borderRadius: 2 }}
        />
      </div>
    </div>
  );
}

// ── Main Vault page ────────────────────────────────────────────────────────────
export default function Vault() {
  const api = useApiClient();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selected, setSelected] = useState<Resume | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  // Fetch resumes
  const { data, isLoading, isError } = useQuery<ResumesResponse>({
    queryKey: ["vault-resumes"],
    queryFn: async () => {
      const res = await api.get<ResumesResponse>("/vault/resumes");
      return res.data;
    },
  });

  const resumes: Resume[] = data?.resumes ?? [];

  // Upload mutation
  const uploadMutation = useMutation<void, Error, File>({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      await api.post("/vault/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (evt) => {
          if (evt.total) {
            setUploadProgress(Math.round((evt.loaded / evt.total) * 100));
          }
        },
      });
    },
    onSuccess: () => {
      setUploadProgress(null);
      void queryClient.invalidateQueries({ queryKey: ["vault-resumes"] });
    },
    onError: () => {
      setUploadProgress(null);
    },
  });

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        setUploadProgress(0);
        uploadMutation.mutate(file);
      }
      // reset input so same file can be re-uploaded
      e.target.value = "";
    },
    [uploadMutation]
  );

  const handleDownload = useCallback(
    async (id: string, filename: string) => {
      const res = await api.get(`/vault/download/${id}`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    },
    [api]
  );

  // Overlay backdrop when drawer open
  const handleBackdropClick = () => setSelected(null);

  return (
    <div style={{ padding: 32, position: "relative" }}>
      <style>{`
        @keyframes pulse {
          0%,100% { background-position: 200% 0; }
          50%      { background-position: -200% 0; }
        }
      `}</style>

      {/* Page header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 28,
        }}
      >
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: MERCURY, margin: 0 }}>
            Resume Vault
          </h1>
          <p style={{ color: "#666", fontSize: 13, marginTop: 4 }}>
            {isLoading ? "Loading…" : `${resumes.length} resume${resumes.length !== 1 ? "s" : ""}`}
          </p>
        </div>

        {/* Upload button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadMutation.isPending}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 18px",
            background: AURORA,
            color: OBSIDIAN,
            border: "none",
            borderRadius: 8,
            fontWeight: 700,
            fontSize: 14,
            cursor: uploadMutation.isPending ? "not-allowed" : "pointer",
            opacity: uploadMutation.isPending ? 0.6 : 1,
          }}
        >
          <Upload size={16} />
          Upload Resume
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.txt"
          style={{ display: "none" }}
          onChange={handleFileChange}
        />
      </div>

      {/* Error state */}
      {isError && (
        <div
          style={{
            padding: "16px 20px",
            background: `${EMBER}15`,
            border: `1px solid ${EMBER}44`,
            borderRadius: 8,
            color: EMBER,
            fontSize: 14,
            marginBottom: 24,
          }}
        >
          Failed to load resumes. Please try again.
        </div>
      )}

      {/* Skeleton grid */}
      {isLoading && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: GAP }}>
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !isError && resumes.length === 0 && (
        <div
          style={{
            textAlign: "center",
            padding: "80px 0",
            color: "#555",
          }}
        >
          <FileText size={48} color="#333" style={{ marginBottom: 16 }} />
          <p style={{ fontSize: 16, margin: 0 }}>No resumes yet.</p>
          <p style={{ fontSize: 13, marginTop: 8 }}>
            Click{" "}
            <span style={{ color: AURORA }}>Upload Resume</span> to get started.
          </p>
        </div>
      )}

      {/* Resume grid */}
      {!isLoading && resumes.length > 0 && (
        resumes.length > 50 ? (
          <VirtualGrid resumes={resumes} onSelect={setSelected} />
        ) : (
          <FlatGrid resumes={resumes} onSelect={setSelected} />
        )
      )}

      {/* Upload progress */}
      {uploadProgress !== null && <UploadProgress progress={uploadProgress} />}

      {/* Drawer backdrop */}
      <AnimatePresence>
        {selected && (
          <>
            <motion.div
              key="backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={handleBackdropClick}
              style={{
                position: "fixed",
                inset: 0,
                background: "rgba(0,0,0,0.5)",
                zIndex: 199,
              }}
            />
            <ResumeDrawer
              key="drawer"
              resume={selected}
              onClose={() => setSelected(null)}
              onDownload={handleDownload}
            />
          </>
        )}
      </AnimatePresence>

      {/* Chevron hint on cards when drawer closed */}
      {!selected && resumes.length > 0 && (
        <div
          style={{
            position: "fixed",
            bottom: 24,
            right: 24,
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
            color: "#444",
          }}
        >
          <ChevronRight size={14} />
          Click a card to preview
        </div>
      )}
    </div>
  );
}
