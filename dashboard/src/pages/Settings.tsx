import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Key, Briefcase, User, Puzzle, Edit2, Trash2,
  Plus, Save, X, CheckCircle, Eye, EyeOff,
} from "lucide-react";
import { useApiClient } from "../hooks/useApiClient";
import { colors } from "../lib/tokens";
import { fadeUp } from "../lib/animations";

type TabId = "profile" | "providers" | "work-history" | "extension";

interface Tab {
  id: TabId;
  label: string;
  Icon: React.ComponentType<{ size?: number | string }>;
}

const TABS: Tab[] = [
  { id: "profile", label: "Profile", Icon: User },
  { id: "providers", label: "AI Providers", Icon: Key },
  { id: "work-history", label: "Work History", Icon: Briefcase },
  { id: "extension", label: "Extension", Icon: Puzzle },
];

const SUPPORTED_PROVIDERS = [
  "anthropic", "openai", "groq", "kimi", "gemini", "perplexity", "ollama",
] as const;

type ProviderName = (typeof SUPPORTED_PROVIDERS)[number];

// Types
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

// Utility
function maskKey(last4: string | null): string {
  return last4 ? `••••${last4}` : "-";
}

function SectionCard({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-5"
      style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
    >
      {children}
    </div>
  );
}

// Profile Tab
function ProfileTab() {
  const api = useApiClient();
  const queryClient = useQueryClient();

  const { data: profile, isLoading } = useQuery({
    queryKey: ["auth-me"],
    queryFn: async () => {
      const res = await api.get("/auth/me");
      return res.data;
    },
  });

  const [form, setForm] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);

  const fields = [
    { key: "first_name", label: "First Name" },
    { key: "last_name", label: "Last Name" },
    { key: "email", label: "Email" },
    { key: "phone", label: "Phone" },
    { key: "location", label: "Location" },
    { key: "linkedin_url", label: "LinkedIn URL" },
    { key: "github_url", label: "GitHub URL" },
  ];

  const getValue = (key: string) => form[key] ?? (profile as Record<string, unknown>)?.[key] ?? "";

  const handleChange = (key: string, val: string) => {
    setForm((prev) => ({ ...prev, [key]: val }));
    setDirty(true);
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      await api.patch("/auth/me", form);
    },
    onSuccess: () => {
      setDirty(false);
      void queryClient.invalidateQueries({ queryKey: ["auth-me"] });
    },
  });

  if (isLoading) {
    return <SectionCard><p className="text-xs" style={{ color: colors.muted }}>Loading profile...</p></SectionCard>;
  }

  return (
    <div className="space-y-5">
      <SectionCard>
        <div className="space-y-4">
          {fields.map(({ key, label }) => (
            <div key={key} className="grid grid-cols-[160px_1fr] gap-4 items-center">
              <label className="text-sm font-medium" style={{ color: colors.muted }}>{label}</label>
              <input
                type="text"
                value={getValue(key) as string}
                onChange={(e) => handleChange(key, e.target.value)}
                className="px-3 py-2 rounded-md text-sm outline-none w-full"
                style={{
                  background: colors.obsidian,
                  border: `1px solid ${colors.border}`,
                  color: colors.mercury,
                }}
              />
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Sticky save button */}
      <AnimatePresence>
        {dirty && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="sticky bottom-4"
          >
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="w-full py-3 rounded-lg text-sm font-semibold border-0 cursor-pointer flex items-center justify-center gap-2"
              style={{ background: colors.teal, color: colors.obsidian }}
            >
              <Save size={16} />
              {saveMutation.isPending ? "Saving..." : "Save Changes"}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// Providers Tab
function ProvidersTab() {
  const api = useApiClient();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Partial<Record<ProviderName, { api_key: string; model: string }>>>({});
  const [revealed, setRevealed] = useState<Set<string>>(new Set());

  const { data: configs, isLoading } = useQuery({
    queryKey: ["provider-config"],
    queryFn: async () => {
      const res = await api.get<ProviderConfig[]>("/users/provider-config");
      return res.data;
    },
  });

  const saveMutation = useMutation({
    mutationFn: async ({ name, api_key, model }: { name: string; api_key: string; model: string }) => {
      await api.put("/users/provider-config", { name, api_key, model: model || null });
    },
    onSuccess: (_data, vars) => {
      setEditing((prev) => { const next = { ...prev }; delete next[vars.name as ProviderName]; return next; });
      void queryClient.invalidateQueries({ queryKey: ["provider-config"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (name: string) => {
      await api.delete(`/users/provider-config/${name}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["provider-config"] });
    },
  });

  const configMap = new Map<ProviderName, ProviderConfig>();
  (configs ?? []).forEach((c) => configMap.set(c.name, c));

  if (isLoading) {
    return <SectionCard><p className="text-xs" style={{ color: colors.muted }}>Loading provider config...</p></SectionCard>;
  }

  return (
    <div className="space-y-3">
      {SUPPORTED_PROVIDERS.map((name) => {
        const cfg = configMap.get(name);
        const editState = editing[name];
        const isRevealed = revealed.has(name);

        return (
          <SectionCard key={name}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium capitalize" style={{ color: colors.mercury }}>{name}</span>
                {cfg?.enabled && (
                  <span className="text-[10px] px-2 py-0.5 rounded font-medium" style={{ background: `${colors.teal}18`, color: colors.teal }}>
                    enabled
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {cfg && (
                  <span className="text-xs font-mono" style={{ color: colors.muted }}>
                    {isRevealed ? cfg.api_key_last4 : maskKey(cfg.api_key_last4)}
                  </span>
                )}
                {cfg && (
                  <button
                    onClick={() => setRevealed((prev) => { const next = new Set(prev); if (next.has(name)) next.delete(name); else next.add(name); return next; })}
                    className="border-0 bg-transparent cursor-pointer p-1"
                    style={{ color: colors.muted }}
                  >
                    {isRevealed ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                )}
                <button
                  onClick={() => setEditing((prev) => ({ ...prev, [name]: { api_key: "", model: cfg?.model ?? "" } }))}
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded border-0 cursor-pointer"
                  style={{ background: colors.hoverSurface, color: colors.mercury }}
                >
                  <Edit2 size={12} /> Edit
                </button>
                {cfg && (
                  <button
                    onClick={() => deleteMutation.mutate(name)}
                    className="border-0 bg-transparent cursor-pointer p-1"
                    style={{ color: colors.ember }}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>

            {cfg?.model && (
              <span className="text-[11px] block" style={{ color: colors.muted }}>Model: {cfg.model}</span>
            )}

            <AnimatePresence>
              {editState && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="overflow-hidden mt-3 pt-3"
                  style={{ borderTop: `1px solid ${colors.border}` }}
                >
                  <div className="grid grid-cols-[120px_1fr] gap-3 items-center mb-3">
                    <label className="text-xs" style={{ color: colors.muted }}>API Key</label>
                    <input
                      type="password"
                      placeholder="Enter API key"
                      value={editState.api_key}
                      onChange={(e) => setEditing((prev) => ({ ...prev, [name]: { ...prev[name]!, api_key: e.target.value } }))}
                      className="px-3 py-2 rounded-md text-sm outline-none w-full"
                      style={{ background: colors.obsidian, border: `1px solid ${colors.border}`, color: colors.mercury }}
                    />
                  </div>
                  <div className="grid grid-cols-[120px_1fr] gap-3 items-center mb-3">
                    <label className="text-xs" style={{ color: colors.muted }}>Model override</label>
                    <input
                      type="text"
                      placeholder="e.g. gpt-4"
                      value={editState.model}
                      onChange={(e) => setEditing((prev) => ({ ...prev, [name]: { ...prev[name]!, model: e.target.value } }))}
                      className="px-3 py-2 rounded-md text-sm outline-none w-full"
                      style={{ background: colors.obsidian, border: `1px solid ${colors.border}`, color: colors.mercury }}
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => saveMutation.mutate({ name, api_key: editState.api_key, model: editState.model })}
                      disabled={saveMutation.isPending}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold border-0 cursor-pointer"
                      style={{ background: colors.teal, color: colors.obsidian }}
                    >
                      <Save size={12} /> Save
                    </button>
                    <button
                      onClick={() => setEditing((prev) => { const next = { ...prev }; delete next[name]; return next; })}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs border-0 cursor-pointer"
                      style={{ background: colors.hoverSurface, color: colors.muted }}
                    >
                      <X size={12} /> Cancel
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

// Work History Tab
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
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<WorkFormState>(emptyWorkForm());

  const { data: entries, isLoading } = useQuery({
    queryKey: ["work-history"],
    queryFn: async () => {
      const res = await api.get<WorkEntry[]>("/work-history");
      return res.data;
    },
  });

  const saveMutation = useMutation({
    mutationFn: async ({ id, data }: { id: string | null; data: WorkFormState }) => {
      const payload = {
        company: data.company,
        role: data.role,
        start_date: data.start_date || null,
        end_date: data.end_date || null,
        bullets: data.bullets.split("\n").filter(Boolean),
      };
      if (id && id !== "new") await api.patch(`/work-history/${id}`, payload);
      else await api.post("/work-history", payload);
    },
    onSuccess: () => {
      setEditing(null);
      setForm(emptyWorkForm());
      void queryClient.invalidateQueries({ queryKey: ["work-history"] });
    },
  });

  if (isLoading) {
    return <SectionCard><p className="text-xs" style={{ color: colors.muted }}>Loading...</p></SectionCard>;
  }

  return (
    <div className="space-y-3">
      {(entries ?? []).map((entry) => (
        <SectionCard key={entry.id}>
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm font-medium" style={{ color: colors.mercury }}>{entry.role}</p>
              <p className="text-xs" style={{ color: colors.muted }}>{entry.company}</p>
              {(entry.start_date || entry.end_date) && (
                <p className="text-[11px] mt-1" style={{ color: colors.muted }}>
                  {entry.start_date ?? "?"} - {entry.end_date ?? "present"}
                </p>
              )}
            </div>
            <button
              onClick={() => { setEditing(entry.id); setForm(entryToForm(entry)); }}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded border-0 cursor-pointer"
              style={{ background: colors.hoverSurface, color: colors.mercury }}
            >
              <Edit2 size={12} /> Edit
            </button>
          </div>

          {entry.bullets.length > 0 && (
            <ul className="mt-2 space-y-1 pl-4" style={{ listStyleType: "disc" }}>
              {entry.bullets.slice(0, 3).map((b, i) => (
                <li key={i} className="text-xs" style={{ color: colors.muted }}>
                  {b.length > 80 ? `${b.slice(0, 80)}...` : b}
                </li>
              ))}
              {entry.bullets.length > 3 && (
                <li className="text-[11px]" style={{ color: colors.muted }}>+{entry.bullets.length - 3} more</li>
              )}
            </ul>
          )}

          {editing === entry.id && (
            <WorkForm
              form={form}
              onChange={setForm}
              onSave={() => saveMutation.mutate({ id: entry.id, data: form })}
              onCancel={() => { setEditing(null); setForm(emptyWorkForm()); }}
              saving={saveMutation.isPending}
            />
          )}
        </SectionCard>
      ))}

      {editing === "new" ? (
        <SectionCard>
          <p className="text-sm font-medium mb-3" style={{ color: colors.mercury }}>New Entry</p>
          <WorkForm
            form={form}
            onChange={setForm}
            onSave={() => saveMutation.mutate({ id: null, data: form })}
            onCancel={() => { setEditing(null); setForm(emptyWorkForm()); }}
            saving={saveMutation.isPending}
          />
        </SectionCard>
      ) : (
        <button
          onClick={() => { setEditing("new"); setForm(emptyWorkForm()); }}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium border-0 cursor-pointer w-full justify-center"
          style={{ background: colors.hoverSurface, color: colors.mercury, border: `1px dashed ${colors.border}` }}
        >
          <Plus size={16} /> Add Entry
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
  const fields: [keyof WorkFormState, string][] = [
    ["company", "Company"],
    ["role", "Role"],
    ["start_date", "Start date (YYYY-MM-DD)"],
    ["end_date", "End date (leave blank for present)"],
  ];

  return (
    <div className="mt-3 pt-3 space-y-3" style={{ borderTop: `1px solid ${colors.border}` }}>
      {fields.map(([field, label]) => (
        <div key={field} className="grid grid-cols-[160px_1fr] gap-3 items-center">
          <label className="text-xs" style={{ color: colors.muted }}>{label}</label>
          <input
            type="text"
            value={form[field]}
            onChange={(e) => onChange({ ...form, [field]: e.target.value })}
            className="px-3 py-2 rounded-md text-sm outline-none w-full"
            style={{ background: colors.obsidian, border: `1px solid ${colors.border}`, color: colors.mercury }}
          />
        </div>
      ))}
      <div className="grid grid-cols-[160px_1fr] gap-3 items-start">
        <label className="text-xs pt-2" style={{ color: colors.muted }}>Bullets (one per line)</label>
        <textarea
          value={form.bullets}
          onChange={(e) => onChange({ ...form, bullets: e.target.value })}
          rows={4}
          className="px-3 py-2 rounded-md text-sm outline-none w-full resize-y"
          style={{ background: colors.obsidian, border: `1px solid ${colors.border}`, color: colors.mercury }}
        />
      </div>
      <div className="flex gap-2 justify-end">
        <button
          onClick={onSave}
          disabled={saving}
          className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold border-0 cursor-pointer"
          style={{ background: colors.teal, color: colors.obsidian }}
        >
          <Save size={12} /> {saving ? "Saving..." : "Save"}
        </button>
        <button
          onClick={onCancel}
          className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs border-0 cursor-pointer"
          style={{ background: colors.hoverSurface, color: colors.muted }}
        >
          <X size={12} /> Cancel
        </button>
      </div>
    </div>
  );
}

// Extension Tab
function ExtensionTab() {
  const api = useApiClient();

  const { data, isLoading } = useQuery({
    queryKey: ["app-stats"],
    queryFn: async () => {
      const res = await api.get("/applications/stats");
      return res.data;
    },
  });

  return (
    <SectionCard>
      <h3 className="text-sm font-semibold mb-3" style={{ color: colors.mercury }}>Extension Status</h3>
      {isLoading ? (
        <p className="text-xs" style={{ color: colors.muted }}>Loading...</p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle size={16} style={{ color: colors.teal }} />
            <span className="text-sm" style={{ color: colors.mercury }}>Extension connected</span>
          </div>
          {data?.most_recent_application && (
            <p className="text-xs" style={{ color: colors.muted }}>
              Last application: {new Date(data.most_recent_application).toLocaleDateString()}
            </p>
          )}
        </div>
      )}
    </SectionCard>
  );
}

// Main Settings page
export default function Settings() {
  const [activeTab, setActiveTab] = useState<TabId>("profile");

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      className="p-6 w-full max-w-4xl mx-auto"
    >
      <h1 className="text-xl font-bold mb-6" style={{ color: colors.mercury }}>
        Settings
      </h1>

      {/* Tab navigation */}
      <div className="flex gap-1 mb-6 rounded-lg p-1" style={{ background: colors.surface }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="flex items-center gap-2 px-4 py-2 rounded-md text-sm cursor-pointer border-0"
            style={{
              background: activeTab === tab.id ? colors.hoverSurface : "transparent",
              color: activeTab === tab.id ? colors.mercury : colors.muted,
              fontWeight: activeTab === tab.id ? 600 : 400,
              transition: "background 0.15s, color 0.15s",
            }}
          >
            <tab.Icon size={16} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "profile" && <ProfileTab />}
      {activeTab === "providers" && <ProvidersTab />}
      {activeTab === "work-history" && <WorkHistoryTab />}
      {activeTab === "extension" && <ExtensionTab />}
    </motion.div>
  );
}
