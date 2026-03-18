import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Key,
  Briefcase,
  User,
  Puzzle,
  Edit2,
  Trash2,
  Plus,
  Save,
  X,
  CheckCircle,
  ExternalLink,
} from "lucide-react";
import { useApiClient } from "../hooks/useApiClient";

// ── Design tokens ──────────────────────────────────────────────────────────────
const OBSIDIAN = "#0D0D0D";
const MERCURY = "#E8E8E8";
const AURORA = "#00CED1";
const EMBER = "#FF6B35";

// ── Tab definition ─────────────────────────────────────────────────────────────
type TabId = "providers" | "work-history" | "profile" | "extension";

interface Tab {
  id: TabId;
  label: string;
  Icon: React.FC<{ size?: number; color?: string }>;
}

const TABS: Tab[] = [
  { id: "providers", label: "Provider Config", Icon: Key },
  { id: "work-history", label: "Work History", Icon: Briefcase },
  { id: "profile", label: "Profile", Icon: User },
  { id: "extension", label: "Extension Status", Icon: Puzzle },
];

const SUPPORTED_PROVIDERS = [
  "anthropic",
  "openai",
  "groq",
  "kimi",
  "gemini",
  "perplexity",
  "ollama",
] as const;

type ProviderName = (typeof SUPPORTED_PROVIDERS)[number];

// ── Types ──────────────────────────────────────────────────────────────────────
interface ProviderConfig {
  name: ProviderName;
  model: string | null;
  enabled: boolean;
  api_key_last4: string | null;
}

interface WorkEntry {
  id: string;
  company: string;
  role: string;
  start_date: string | null;
  end_date: string | null;
  bullets: string[];
}

interface UserProfile {
  email: string;
  first_name: string | null;
  last_name: string | null;
  github_username: string | null;
}

interface AppStats {
  most_recent_application: string | null;
  [key: string]: unknown;
}

// ── Utility ────────────────────────────────────────────────────────────────────
function maskKey(last4: string | null): string {
  return last4 ? `••••${last4}` : "—";
}

function inputStyle(extra?: React.CSSProperties): React.CSSProperties {
  return {
    background: "#1A1A1A",
    border: "1px solid #333",
    borderRadius: 6,
    color: MERCURY,
    fontSize: 13,
    padding: "8px 12px",
    outline: "none",
    width: "100%",
    boxSizing: "border-box" as const,
    ...extra,
  };
}

function btnPrimary(extra?: React.CSSProperties): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "8px 14px",
    background: AURORA,
    color: OBSIDIAN,
    border: "none",
    borderRadius: 6,
    fontWeight: 700,
    fontSize: 13,
    cursor: "pointer",
    ...extra,
  };
}

function btnGhost(extra?: React.CSSProperties): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 12px",
    background: "none",
    color: "#aaa",
    border: "1px solid #333",
    borderRadius: 6,
    fontSize: 13,
    cursor: "pointer",
    ...extra,
  };
}

function SectionCard({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        background: "#111",
        border: "1px solid #222",
        borderRadius: 10,
        padding: "20px 24px",
        marginBottom: 16,
      }}
    >
      {children}
    </div>
  );
}

// ── Provider Config tab ────────────────────────────────────────────────────────
interface ProviderEditState {
  api_key: string;
  model: string;
}

function ProvidersTab() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  const [editing, setEditing] = useState<Partial<Record<ProviderName, ProviderEditState>>>({});

  const { data: configs, isLoading } = useQuery<ProviderConfig[]>({
    queryKey: ["provider-config"],
    queryFn: async () => {
      const res = await api.get<ProviderConfig[]>("/users/provider-config");
      return res.data;
    },
  });

  const saveMutation = useMutation<void, Error, { name: ProviderName; api_key: string; model: string }>({
    mutationFn: async ({ name, api_key, model }) => {
      await api.put("/users/provider-config", { name, api_key, model: model || null });
    },
    onSuccess: (_data, vars) => {
      setEditing((prev) => {
        const next = { ...prev };
        delete next[vars.name];
        return next;
      });
      void queryClient.invalidateQueries({ queryKey: ["provider-config"] });
    },
  });

  const deleteMutation = useMutation<void, Error, ProviderName>({
    mutationFn: async (name) => {
      await api.delete(`/users/provider-config/${name}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["provider-config"] });
    },
  });

  const configMap = new Map<ProviderName, ProviderConfig>();
  (configs ?? []).forEach((c) => configMap.set(c.name, c));

  const startEdit = (name: ProviderName) => {
    setEditing((prev) => ({
      ...prev,
      [name]: { api_key: "", model: configMap.get(name)?.model ?? "" },
    }));
  };

  const cancelEdit = (name: ProviderName) => {
    setEditing((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
  };

  if (isLoading) {
    return (
      <div style={{ color: "#555", fontSize: 13, padding: "24px 0" }}>
        Loading provider config…
      </div>
    );
  }

  return (
    <div>
      {SUPPORTED_PROVIDERS.map((name) => {
        const cfg = configMap.get(name);
        const editState = editing[name];
        return (
          <SectionCard key={name}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: editState ? 16 : 0,
              }}
            >
              {/* Name + status */}
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: cfg?.enabled ? MERCURY : "#555",
                    textTransform: "capitalize",
                  }}
                >
                  {name}
                </span>
                {cfg?.enabled && (
                  <span
                    style={{
                      fontSize: 11,
                      padding: "2px 8px",
                      borderRadius: 99,
                      background: `${AURORA}22`,
                      color: AURORA,
                    }}
                  >
                    enabled
                  </span>
                )}
                {cfg && (
                  <span style={{ fontSize: 12, color: "#555", fontFamily: "monospace" }}>
                    {maskKey(cfg.api_key_last4)}
                  </span>
                )}
                {cfg?.model && (
                  <span style={{ fontSize: 12, color: "#777" }}>{cfg.model}</span>
                )}
              </div>

              {/* Actions */}
              <div style={{ display: "flex", gap: 8 }}>
                <button style={btnGhost()} onClick={() => startEdit(name)}>
                  <Edit2 size={13} />
                  Edit
                </button>
                {cfg && (
                  <button
                    style={btnGhost({ color: EMBER, borderColor: `${EMBER}44` })}
                    onClick={() => deleteMutation.mutate(name)}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            </div>

            {/* Inline edit form */}
            <AnimatePresence>
              {editState && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  style={{ overflow: "hidden" }}
                >
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: 12,
                      marginBottom: 12,
                    }}
                  >
                    <div>
                      <label style={{ fontSize: 11, color: "#666", display: "block", marginBottom: 4 }}>
                        API Key
                      </label>
                      <input
                        type="password"
                        placeholder="sk-…"
                        value={editState.api_key}
                        onChange={(e) =>
                          setEditing((prev) => ({
                            ...prev,
                            [name]: { ...prev[name]!, api_key: e.target.value },
                          }))
                        }
                        style={inputStyle()}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: 11, color: "#666", display: "block", marginBottom: 4 }}>
                        Model override
                      </label>
                      <input
                        type="text"
                        placeholder="default"
                        value={editState.model}
                        onChange={(e) =>
                          setEditing((prev) => ({
                            ...prev,
                            [name]: { ...prev[name]!, model: e.target.value },
                          }))
                        }
                        style={inputStyle()}
                      />
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      style={btnPrimary()}
                      onClick={() =>
                        saveMutation.mutate({
                          name,
                          api_key: editState.api_key,
                          model: editState.model,
                        })
                      }
                      disabled={saveMutation.isPending}
                    >
                      <Save size={13} />
                      Save
                    </button>
                    <button style={btnGhost()} onClick={() => cancelEdit(name)}>
                      <X size={13} />
                      Cancel
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </SectionCard>
        );
      })}
    </div>
  );
}

// ── Work History tab ───────────────────────────────────────────────────────────
interface WorkFormState {
  company: string;
  role: string;
  start_date: string;
  end_date: string;
  bullets: string;
}

function emptyWorkForm(): WorkFormState {
  return { company: "", role: "", start_date: "", end_date: "", bullets: "" };
}

function entryToForm(e: WorkEntry): WorkFormState {
  return {
    company: e.company,
    role: e.role,
    start_date: e.start_date ?? "",
    end_date: e.end_date ?? "",
    bullets: e.bullets.join("\n"),
  };
}

function WorkHistoryTab() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  const [editing, setEditing] = useState<string | null>(null); // entry id or "new"
  const [form, setForm] = useState<WorkFormState>(emptyWorkForm());

  const { data: entries, isLoading } = useQuery<WorkEntry[]>({
    queryKey: ["work-history"],
    queryFn: async () => {
      const res = await api.get<WorkEntry[]>("/work-history");
      return res.data;
    },
  });

  const saveMutation = useMutation<void, Error, { id: string | null; data: WorkFormState }>({
    mutationFn: async ({ id, data }) => {
      const payload = {
        company: data.company,
        role: data.role,
        start_date: data.start_date || null,
        end_date: data.end_date || null,
        bullets: data.bullets.split("\n").filter(Boolean),
      };
      if (id && id !== "new") {
        await api.patch(`/work-history/${id}`, payload);
      } else {
        await api.post("/work-history", payload);
      }
    },
    onSuccess: () => {
      setEditing(null);
      setForm(emptyWorkForm());
      void queryClient.invalidateQueries({ queryKey: ["work-history"] });
    },
  });

  const startEdit = (entry: WorkEntry) => {
    setEditing(entry.id);
    setForm(entryToForm(entry));
  };

  const startNew = () => {
    setEditing("new");
    setForm(emptyWorkForm());
  };

  const cancel = () => {
    setEditing(null);
    setForm(emptyWorkForm());
  };

  if (isLoading) {
    return <div style={{ color: "#555", fontSize: 13, padding: "24px 0" }}>Loading…</div>;
  }

  return (
    <div>
      {/* Existing entries */}
      {(entries ?? []).map((entry) => (
        <SectionCard key={entry.id}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: MERCURY }}>{entry.role}</div>
              <div style={{ fontSize: 13, color: "#aaa", marginTop: 2 }}>{entry.company}</div>
              {(entry.start_date ?? entry.end_date) && (
                <div style={{ fontSize: 12, color: "#555", marginTop: 4 }}>
                  {entry.start_date ?? "?"} – {entry.end_date ?? "present"}
                </div>
              )}
              {entry.bullets.length > 0 && (
                <ul style={{ margin: "8px 0 0 16px", padding: 0 }}>
                  {entry.bullets.slice(0, 2).map((b, i) => (
                    <li key={i} style={{ fontSize: 12, color: "#777", marginBottom: 2 }}>
                      {b.length > 80 ? `${b.slice(0, 80)}…` : b}
                    </li>
                  ))}
                  {entry.bullets.length > 2 && (
                    <li style={{ fontSize: 12, color: "#444" }}>
                      +{entry.bullets.length - 2} more
                    </li>
                  )}
                </ul>
              )}
            </div>
            <button style={btnGhost()} onClick={() => startEdit(entry)}>
              <Edit2 size={13} />
              Edit
            </button>
          </div>

          <AnimatePresence>
            {editing === entry.id && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                style={{ overflow: "hidden", marginTop: 16 }}
              >
                <WorkForm
                  form={form}
                  onChange={setForm}
                  onSave={() => saveMutation.mutate({ id: entry.id, data: form })}
                  onCancel={cancel}
                  saving={saveMutation.isPending}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </SectionCard>
      ))}

      {/* Add new */}
      {editing === "new" ? (
        <SectionCard>
          <div style={{ fontSize: 14, fontWeight: 600, color: MERCURY, marginBottom: 16 }}>
            New Entry
          </div>
          <WorkForm
            form={form}
            onChange={setForm}
            onSave={() => saveMutation.mutate({ id: null, data: form })}
            onCancel={cancel}
            saving={saveMutation.isPending}
          />
        </SectionCard>
      ) : (
        <button style={btnGhost({ marginTop: 4 })} onClick={startNew}>
          <Plus size={14} />
          Add New
        </button>
      )}
    </div>
  );
}

function WorkForm({
  form,
  onChange,
  onSave,
  onCancel,
  saving,
}: {
  form: WorkFormState;
  onChange: (f: WorkFormState) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        {(
          [
            ["company", "Company"],
            ["role", "Role"],
            ["start_date", "Start date (YYYY-MM-DD)"],
            ["end_date", "End date (leave blank for present)"],
          ] as [keyof WorkFormState, string][]
        ).map(([field, label]) => (
          <div key={field}>
            <label style={{ fontSize: 11, color: "#666", display: "block", marginBottom: 4 }}>{label}</label>
            <input
              type="text"
              value={form[field]}
              onChange={(e) => onChange({ ...form, [field]: e.target.value })}
              style={inputStyle()}
            />
          </div>
        ))}
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 11, color: "#666", display: "block", marginBottom: 4 }}>
          Bullets (one per line)
        </label>
        <textarea
          value={form.bullets}
          onChange={(e) => onChange({ ...form, bullets: e.target.value })}
          rows={4}
          style={inputStyle({ resize: "vertical", fontFamily: "monospace" })}
        />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button style={btnPrimary()} onClick={onSave} disabled={saving}>
          <Save size={13} />
          Save
        </button>
        <button style={btnGhost()} onClick={onCancel}>
          <X size={13} />
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Profile tab ────────────────────────────────────────────────────────────────
interface ProfileFormState {
  first_name: string;
  last_name: string;
  github_username: string;
  github_pat: string;
}

function ProfileTab() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  const [editingProfile, setEditingProfile] = useState(false);
  const [editingPat, setEditingPat] = useState(false);
  const [saveOk, setSaveOk] = useState(false);

  const { data: profile, isLoading } = useQuery<UserProfile>({
    queryKey: ["me"],
    queryFn: async () => {
      const res = await api.get<UserProfile>("/auth/me");
      return res.data;
    },
  });

  const [form, setForm] = useState<ProfileFormState>({
    first_name: "",
    last_name: "",
    github_username: "",
    github_pat: "",
  });

  // populate form when profile loads
  const [initialized, setInitialized] = useState(false);
  if (profile && !initialized) {
    setForm({
      first_name: profile.first_name ?? "",
      last_name: profile.last_name ?? "",
      github_username: profile.github_username ?? "",
      github_pat: "",
    });
    setInitialized(true);
  }

  const profileMutation = useMutation<void, Error, Partial<UserProfile>>({
    mutationFn: async (data) => {
      await api.patch("/auth/me", data);
    },
    onSuccess: () => {
      setEditingProfile(false);
      setSaveOk(true);
      setTimeout(() => setSaveOk(false), 2500);
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  const patMutation = useMutation<void, Error, string>({
    mutationFn: async (pat) => {
      await api.put("/users/github-token", { token: pat });
    },
    onSuccess: () => {
      setEditingPat(false);
      setForm((f) => ({ ...f, github_pat: "" }));
    },
  });

  if (isLoading) {
    return <div style={{ color: "#555", fontSize: 13, padding: "24px 0" }}>Loading profile…</div>;
  }

  return (
    <div>
      <SectionCard>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: MERCURY }}>Account Info</div>
          {saveOk && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, color: AURORA, fontSize: 13 }}>
              <CheckCircle size={14} />
              Saved
            </div>
          )}
          <button style={btnGhost()} onClick={() => setEditingProfile((v) => !v)}>
            <Edit2 size={13} />
            {editingProfile ? "Cancel" : "Edit"}
          </button>
        </div>

        {!editingProfile ? (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {(
              [
                ["Email", profile?.email ?? "—"],
                ["First name", profile?.first_name ?? "—"],
                ["Last name", profile?.last_name ?? "—"],
                ["GitHub", profile?.github_username ?? "—"],
              ] as [string, string][]
            ).map(([label, value]) => (
              <div key={label}>
                <div style={{ fontSize: 11, color: "#555", marginBottom: 2 }}>{label}</div>
                <div style={{ fontSize: 13, color: MERCURY }}>{value}</div>
              </div>
            ))}
          </div>
        ) : (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
              {(
                [
                  ["first_name", "First name"],
                  ["last_name", "Last name"],
                  ["github_username", "GitHub username"],
                ] as [keyof ProfileFormState, string][]
              ).map(([field, label]) => (
                <div key={field}>
                  <label style={{ fontSize: 11, color: "#666", display: "block", marginBottom: 4 }}>{label}</label>
                  <input
                    type="text"
                    value={form[field]}
                    onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.value }))}
                    style={inputStyle()}
                  />
                </div>
              ))}
            </div>
            <button
              style={btnPrimary()}
              onClick={() =>
                profileMutation.mutate({
                  first_name: form.first_name || null,
                  last_name: form.last_name || null,
                  github_username: form.github_username || null,
                })
              }
              disabled={profileMutation.isPending}
            >
              <Save size={13} />
              Save
            </button>
          </div>
        )}
      </SectionCard>

      {/* GitHub PAT */}
      <SectionCard>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: MERCURY }}>GitHub PAT</div>
          <button style={btnGhost()} onClick={() => setEditingPat((v) => !v)}>
            <Key size={13} />
            {editingPat ? "Cancel" : "Update"}
          </button>
        </div>
        <p style={{ fontSize: 12, color: "#555", margin: "0 0 12px" }}>
          Personal access token used for GitHub integrations.
        </p>
        <AnimatePresence>
          {editingPat && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              style={{ overflow: "hidden" }}
            >
              <input
                type="password"
                placeholder="ghp_…"
                value={form.github_pat}
                onChange={(e) => setForm((f) => ({ ...f, github_pat: e.target.value }))}
                style={{ ...inputStyle(), marginBottom: 10 }}
              />
              <button
                style={btnPrimary()}
                onClick={() => patMutation.mutate(form.github_pat)}
                disabled={patMutation.isPending || !form.github_pat}
              >
                <Save size={13} />
                Save PAT
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </SectionCard>
    </div>
  );
}

// ── Extension Status tab ───────────────────────────────────────────────────────
function ExtensionTab() {
  const api = useApiClient();

  const { data: stats } = useQuery<AppStats>({
    queryKey: ["app-stats"],
    queryFn: async () => {
      const res = await api.get<AppStats>("/applications/stats");
      return res.data;
    },
  });

  const lastSync = stats?.most_recent_application
    ? new Date(stats.most_recent_application).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : null;

  return (
    <div>
      <SectionCard>
        <div style={{ fontSize: 14, fontWeight: 600, color: MERCURY, marginBottom: 12 }}>
          Chrome Extension
        </div>
        <p style={{ fontSize: 13, color: "#aaa", marginBottom: 16, lineHeight: 1.6 }}>
          Install the Chrome extension to enable form autofill and job scoring directly on job
          sites. The extension communicates with this dashboard via your Clerk session.
        </p>
        {lastSync ? (
          <div style={{ fontSize: 12, color: "#555", marginBottom: 16 }}>
            Last application synced:{" "}
            <span style={{ color: AURORA }}>{lastSync}</span>
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "#555", marginBottom: 16 }}>
            No applications synced yet.
          </div>
        )}
        <a
          href="#"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "10px 16px",
            background: AURORA,
            color: OBSIDIAN,
            border: "none",
            borderRadius: 8,
            fontWeight: 700,
            fontSize: 13,
            textDecoration: "none",
          }}
        >
          <ExternalLink size={14} />
          Download Extension
        </a>
      </SectionCard>

      <SectionCard>
        <div style={{ fontSize: 14, fontWeight: 600, color: MERCURY, marginBottom: 12 }}>
          How it works
        </div>
        <ol style={{ padding: "0 0 0 18px", margin: 0 }}>
          {[
            "Download and install the extension in Chrome (chrome://extensions, developer mode).",
            "Sign in — the extension reuses your Clerk session automatically.",
            "Navigate to any job application page; the floating panel will appear.",
            "Click \"Autofill\" to let the AI fill form fields using your profile and work history.",
            "Applications are tracked back to this dashboard in real-time.",
          ].map((step, i) => (
            <li key={i} style={{ fontSize: 13, color: "#aaa", marginBottom: 8, lineHeight: 1.6 }}>
              {step}
            </li>
          ))}
        </ol>
      </SectionCard>
    </div>
  );
}

// ── Main Settings page ─────────────────────────────────────────────────────────
export default function Settings() {
  const [activeTab, setActiveTab] = useState<TabId>("providers");

  return (
    <div style={{ padding: 32, maxWidth: 860 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, color: MERCURY, margin: "0 0 24px" }}>
        Settings
      </h1>

      {/* Tab bar */}
      <div
        style={{
          display: "flex",
          gap: 4,
          borderBottom: "1px solid #222",
          marginBottom: 24,
        }}
      >
        {TABS.map(({ id, label, Icon }) => {
          const active = id === activeTab;
          return (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                padding: "10px 16px",
                background: "none",
                border: "none",
                borderBottom: `2px solid ${active ? AURORA : "transparent"}`,
                color: active ? AURORA : "#666",
                fontWeight: active ? 600 : 400,
                fontSize: 13,
                cursor: "pointer",
                marginBottom: -1,
                transition: "color 0.15s, border-color 0.15s",
              }}
            >
              <Icon size={14} color={active ? AURORA : "#666"} />
              {label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.18 }}
        >
          {activeTab === "providers" && <ProvidersTab />}
          {activeTab === "work-history" && <WorkHistoryTab />}
          {activeTab === "profile" && <ProfileTab />}
          {activeTab === "extension" && <ExtensionTab />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
