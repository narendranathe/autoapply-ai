// Options page script — module scripts run after DOM is parsed, no DOMContentLoaded needed

import { workHistoryApi, type WorkHistoryEntry } from "../shared/api";

const API_DEFAULT = "http://localhost:8000/api/v1";

function get(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement;
}

function getInput(id: string): HTMLInputElement {
  return document.getElementById(id) as HTMLInputElement;
}

function getSelect(id: string): HTMLSelectElement {
  return document.getElementById(id) as HTMLSelectElement;
}

function showStatus(elId: string, msg: string, type: "ok" | "err" | "info") {
  const el = get(elId);
  if (!el) return;
  el.textContent = msg;
  el.className = `status ${type}`;
}

async function loadSettings() {
  const data = await chrome.storage.local.get([
    "clerkUserId",
    "apiBaseUrl",
    "llmApiKey",
    "llmProvider",
    "profile",
  ]);
  if (data.clerkUserId) getInput("clerk-user-id").value = data.clerkUserId as string;
  if (data.apiBaseUrl) getInput("api-base").value = data.apiBaseUrl as string;
  if (data.llmApiKey) getInput("llm-key").value = data.llmApiKey as string;
  if (data.llmProvider) getSelect("llm-provider").value = data.llmProvider as string;

  if (data.profile) {
    const p = data.profile as Record<string, string>;
    const setVal = (id: string, val: string | undefined) => {
      const el = document.getElementById(id);
      if (el && val) (el as HTMLInputElement | HTMLSelectElement).value = val;
    };
    setVal("profile-first", p.firstName);
    setVal("profile-last", p.lastName);
    setVal("profile-email", p.email);
    setVal("profile-phone", p.phone);
    setVal("profile-city", p.city);
    setVal("profile-state", p.state);
    setVal("profile-zip", p.zip);
    setVal("profile-linkedin", p.linkedinUrl);
    setVal("profile-portfolio", p.portfolioUrl);
    setVal("profile-yoe", p.yearsExperience);
    setVal("profile-salary", p.salary);
    setVal("profile-sponsorship", p.sponsorship);
  }

  const apiBase = (data.apiBaseUrl as string | undefined) || API_DEFAULT;
  const hasUser = !!data.clerkUserId;
  showStatus(
    "status-info",
    hasUser
      ? `Signed in as ${data.clerkUserId as string} · API: ${apiBase}`
      : "Not authenticated. Enter your Clerk User ID above.",
    hasUser ? "ok" : "info"
  );
}

async function saveAuth() {
  const userId = getInput("clerk-user-id").value.trim();
  if (!userId) {
    showStatus("auth-status", "User ID cannot be empty.", "err");
    return;
  }

  const apiBase =
    ((await chrome.storage.local.get("apiBaseUrl")).apiBaseUrl as string | undefined) ||
    API_DEFAULT;

  showStatus("auth-status", "Connecting…", "info");

  try {
    // Step 1: check if user already exists
    const meResp = await fetch(`${apiBase}/auth/me`, {
      headers: { "X-Clerk-User-Id": userId },
    });

    if (meResp.ok) {
      await chrome.storage.local.set({ clerkUserId: userId });
      showStatus("auth-status", "Verified and saved ✓", "ok");
      loadSettings();
      loadWorkHistory();
      return;
    }

    // Step 2: user not found — auto-register (first time setup)
    if (meResp.status === 401) {
      const profileData = await chrome.storage.local.get("profile");
      const profile = (profileData.profile as Record<string, string> | undefined) || {};
      const email = profile.email || `${userId}@autoapply.local`;
      // Simple deterministic hash for email_hash (not sensitive — just a DB key)
      const emailHash = btoa(email).replace(/[^a-zA-Z0-9]/g, "").slice(0, 32);

      const registerResp = await fetch(
        `${apiBase}/auth/register?clerk_id=${encodeURIComponent(userId)}&email_hash=${encodeURIComponent(emailHash)}`,
        { method: "POST" }
      );

      if (registerResp.ok) {
        await chrome.storage.local.set({ clerkUserId: userId });
        showStatus("auth-status", "Account created and saved ✓", "ok");
        loadSettings();
        loadWorkHistory();
      } else {
        const errText = await registerResp.text();
        showStatus("auth-status", `Registration failed (${registerResp.status}): ${errText}`, "err");
      }
      return;
    }

    showStatus("auth-status", `Backend returned ${meResp.status}.`, "err");
  } catch {
    await chrome.storage.local.set({ clerkUserId: userId });
    showStatus("auth-status", "Saved locally (backend unreachable — will sync later).", "info");
  }
}

async function testApi() {
  const apiBase = getInput("api-base").value.trim() || API_DEFAULT;
  try {
    const resp = await fetch(`${apiBase.replace(/\/api\/v1$/, "")}/health`);
    if (resp.ok) {
      showStatus("api-status", "Backend reachable.", "ok");
    } else {
      showStatus("api-status", `Backend returned ${resp.status}.`, "err");
    }
  } catch {
    showStatus("api-status", "Cannot reach backend. Is it running?", "err");
  }
}

async function saveApi() {
  const url = getInput("api-base").value.trim();
  await chrome.storage.local.set({ apiBaseUrl: url || "" });
  showStatus("api-status", "Saved.", "ok");
  loadSettings();
}

async function saveLlm() {
  const key = getInput("llm-key").value.trim();
  const provider = getSelect("llm-provider").value;
  await chrome.storage.local.set({ llmApiKey: key, llmProvider: provider });
  showStatus("llm-status", "Saved.", "ok");
}

async function saveProfile() {
  const profile = {
    firstName: getInput("profile-first").value.trim(),
    lastName: getInput("profile-last").value.trim(),
    email: getInput("profile-email").value.trim(),
    phone: getInput("profile-phone").value.trim(),
    city: getInput("profile-city").value.trim(),
    state: getInput("profile-state").value.trim(),
    zip: getInput("profile-zip").value.trim(),
    linkedinUrl: getInput("profile-linkedin").value.trim(),
    portfolioUrl: getInput("profile-portfolio").value.trim(),
    yearsExperience: getInput("profile-yoe").value.trim(),
    salary: getInput("profile-salary").value.trim(),
    sponsorship: (document.getElementById("profile-sponsorship") as HTMLSelectElement).value,
  };
  await chrome.storage.local.set({ profile });
  showStatus("profile-status", "Profile saved.", "ok");
}

// ── Work History ────────────────────────────────────────────────────────────

function renderWorkHistoryList(entries: WorkHistoryEntry[]) {
  const container = document.getElementById("wh-list")!;
  const empty = document.getElementById("wh-empty")!;
  if (entries.length === 0) {
    empty.textContent = "No entries yet. Add your first role above.";
    empty.style.display = "block";
    // Remove any previously rendered entry divs
    container.querySelectorAll(".wh-entry").forEach((el) => el.remove());
    return;
  }
  empty.style.display = "none";
  container.querySelectorAll(".wh-entry").forEach((el) => el.remove());
  for (const e of entries) {
    const div = document.createElement("div");
    div.className = "wh-entry";
    div.dataset.id = e.id;
    const dateRange = e.end_date ? `${e.start_date} – ${e.end_date}` : `${e.start_date} – Present`;
    const tech = e.technologies.length > 0 ? ` · ${e.technologies.slice(0, 4).join(", ")}` : "";
    div.innerHTML = `
      <div class="wh-entry-info">
        <div class="wh-entry-title">${e.role_title} @ ${e.company_name}</div>
        <div class="wh-entry-meta">${dateRange}${e.location ? " · " + e.location : ""}${tech}</div>
      </div>
      <button class="wh-del-btn" title="Delete entry">✕</button>
    `;
    div.querySelector(".wh-del-btn")!.addEventListener("click", () => deleteWorkHistoryEntry(e.id, div));
    container.appendChild(div);
  }
}

async function loadWorkHistory() {
  const { clerkUserId } = await chrome.storage.local.get("clerkUserId");
  if (!clerkUserId) {
    const empty = document.getElementById("wh-empty");
    if (empty) empty.textContent = "Save your User ID above first, then work history will load.";
    return;
  }
  try {
    const res = await workHistoryApi.list();
    renderWorkHistoryList(res.entries);
  } catch {
    const empty = document.getElementById("wh-empty");
    if (empty) empty.textContent = "Could not load (check API URL and User ID above).";
  }
}

async function addWorkHistoryEntry() {
  const { clerkUserId } = await chrome.storage.local.get("clerkUserId");
  if (!clerkUserId) {
    showStatus("wh-add-status", "Save your User ID in the Authentication section first.", "err");
    return;
  }

  const company = (document.getElementById("wh-company") as HTMLInputElement).value.trim();
  const role = (document.getElementById("wh-role") as HTMLInputElement).value.trim();
  const start = (document.getElementById("wh-start") as HTMLInputElement).value.trim();
  const end = (document.getElementById("wh-end") as HTMLInputElement).value.trim();
  const location = (document.getElementById("wh-location") as HTMLInputElement).value.trim();
  const bulletsRaw = (document.getElementById("wh-bullets") as HTMLTextAreaElement).value.trim();
  const techRaw = (document.getElementById("wh-tech") as HTMLInputElement).value.trim();

  if (!company || !role || !start) {
    showStatus("wh-add-status", "Company, Role, and Start Date are required.", "err");
    return;
  }

  const bullets = bulletsRaw ? bulletsRaw.split("\n").map((s) => s.trim()).filter(Boolean) : [];
  const technologies = techRaw ? techRaw.split(",").map((s) => s.trim()).filter(Boolean) : [];
  const isCurrent = !end || end.toLowerCase() === "present";

  try {
    await workHistoryApi.create({
      company_name: company,
      role_title: role,
      start_date: start,
      end_date: isCurrent ? undefined : end,
      is_current: isCurrent,
      location: location || undefined,
      bullets,
      technologies,
    });

    showStatus("wh-add-status", "Entry added.", "ok");

    // Clear form
    (["wh-company", "wh-role", "wh-start", "wh-end", "wh-location", "wh-tech"] as const).forEach((id) => {
      (document.getElementById(id) as HTMLInputElement).value = "";
    });
    (document.getElementById("wh-bullets") as HTMLTextAreaElement).value = "";

    loadWorkHistory();
  } catch (e) {
    showStatus("wh-add-status", `Failed: ${e instanceof Error ? e.message : "unknown error"}`, "err");
  }
}

async function deleteWorkHistoryEntry(entryId: string, el: HTMLElement) {
  try {
    await workHistoryApi.delete(entryId);
    el.remove();
    // Check if list is now empty
    const container = document.getElementById("wh-list")!;
    if (!container.querySelector(".wh-entry")) {
      const empty = document.getElementById("wh-empty")!;
      empty.textContent = "No entries yet. Add your first role above.";
      empty.style.display = "block";
    }
  } catch {
    // Silently fail — entry still shows
  }
}

// Module scripts are deferred — DOM is fully parsed when this runs.
loadSettings();
loadWorkHistory();
get("save-auth").addEventListener("click", saveAuth);
get("test-api").addEventListener("click", testApi);
get("save-api").addEventListener("click", saveApi);
get("save-llm").addEventListener("click", saveLlm);
get("save-profile").addEventListener("click", saveProfile);
get("wh-add-btn").addEventListener("click", addWorkHistoryEntry);
