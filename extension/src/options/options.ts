// Options page script — module scripts run after DOM is parsed, no DOMContentLoaded needed

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

  try {
    const resp = await fetch(`${apiBase}/auth/me`, {
      headers: { "X-Clerk-User-Id": userId },
    });
    if (resp.ok) {
      await chrome.storage.local.set({ clerkUserId: userId });
      showStatus("auth-status", "Verified and saved.", "ok");
      loadSettings();
    } else {
      showStatus("auth-status", `Backend returned ${resp.status}. Check your User ID.`, "err");
    }
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

// Module scripts are deferred — DOM is fully parsed when this runs.
loadSettings();
get("save-auth").addEventListener("click", saveAuth);
get("test-api").addEventListener("click", testApi);
get("save-api").addEventListener("click", saveApi);
get("save-llm").addEventListener("click", saveLlm);
get("save-profile").addEventListener("click", saveProfile);
