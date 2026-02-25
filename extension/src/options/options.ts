// Options page script

const API_DEFAULT = "http://localhost:8000/api/v1";

function $(id: string): HTMLElement {
  return document.getElementById(id)!;
}

function showStatus(elId: string, msg: string, type: "ok" | "err" | "info") {
  const el = $(elId) as HTMLElement;
  el.textContent = msg;
  el.className = `status ${type}`;
}

async function loadSettings() {
  const data = await chrome.storage.local.get([
    "clerkUserId",
    "apiBaseUrl",
    "llmApiKey",
    "llmProvider",
  ]);
  if (data.clerkUserId) ($("#clerk-user-id") as HTMLInputElement).value = data.clerkUserId;
  if (data.apiBaseUrl) ($("#api-base") as HTMLInputElement).value = data.apiBaseUrl;
  if (data.llmApiKey) ($("#llm-key") as HTMLInputElement).value = data.llmApiKey;
  if (data.llmProvider) ($("#llm-provider") as HTMLSelectElement).value = data.llmProvider;

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
  const userId = ($("#clerk-user-id") as HTMLInputElement).value.trim();
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
    // Backend not reachable — save anyway, will retry on next use
    await chrome.storage.local.set({ clerkUserId: userId });
    showStatus("auth-status", "Saved locally (backend unreachable — will sync later).", "info");
  }
}

async function testApi() {
  const apiBase =
    (($("api-base") as HTMLInputElement).value.trim()) ||
    API_DEFAULT;
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
  const url = ($("#api-base") as HTMLInputElement).value.trim();
  await chrome.storage.local.set({ apiBaseUrl: url || "" });
  showStatus("api-status", "Saved.", "ok");
  loadSettings();
}

async function saveLlm() {
  const key = ($("#llm-key") as HTMLInputElement).value.trim();
  const provider = ($("#llm-provider") as HTMLSelectElement).value;
  await chrome.storage.local.set({ llmApiKey: key, llmProvider: provider });
  showStatus("llm-status", "Saved.", "ok");
}

document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  $("#save-auth").addEventListener("click", saveAuth);
  $("#test-api").addEventListener("click", testApi);
  $("#save-api").addEventListener("click", saveApi);
  $("#save-llm").addEventListener("click", saveLlm);
});
