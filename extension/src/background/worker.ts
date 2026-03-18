/**
 * Background Service Worker (Chrome MV3)
 *
 * Responsibilities:
 * 1. Detect career pages and job scout pages via URL/title patterns
 * 2. Open the side panel automatically when a career page is detected
 * 3. Relay PageContext messages between content script ↔ sidepanel
 * 4. Drain the offline sync queue when connectivity is restored
 */

import type { Message, PageContext } from "../shared/types";

// Open sidepanel when user clicks the toolbar icon (required for MV3)
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

// Fallback: also handle action click directly
chrome.action.onClicked.addListener((tab) => {
  if (tab.id) {
    chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
  }
});

// ── Career page URL patterns ───────────────────────────────────────────────

const CAREER_URL_PATTERNS = [
  /greenhouse\.io/,
  /lever\.co\//,
  /myworkday\.com/,
  /workday\.com\/[^/]+\/d\/jobs/,
  /taleo\.net/,
  /smartrecruiters\.com\/jobs/,
  /icims\.com/,
  /jobvite\.com/,
  /ashbyhq\.com/,
  /jobs\.ashbyhq\.com/,
  /bamboohr\.com/,
  /ziprecruiter\.com\/jobs/,
  /dice\.com\/jobs/,
  /wellfound\.com\/jobs/,
  /otta\.com/,
  /gh_jid=/,
  /careers\.[a-z]+\.[a-z]+/,
  /[a-z]+\.com\/careers\//,
  /[a-z]+\.com\/jobs\//,
];

const JOB_SCOUT_PATTERNS = [
  /linkedin\.com\/jobs/,
  /indeed\.com\/(viewjob|jobs)/,
  /glassdoor\.com\/job-listing/,
  /glassdoor\.com\/Jobs/,
  /builtin[a-z]*\.com\/job/,
  /levels\.fyi\/jobs/,
];

// ── Auth helpers ───────────────────────────────────────────────────────────

/**
 * Build auth headers for fetch() calls made from the service worker.
 *
 * Priority:
 *   1. If a Clerk RS256 JWT exists in storage AND is not expired (with 30-second
 *      buffer) → `Authorization: Bearer <token>`
 *   2. Otherwise fall back to the legacy `X-Clerk-User-Id` header.
 *
 * All values are read fresh from chrome.storage.local on every call so the
 * worker always picks up a newly-refreshed token without needing an explicit
 * invalidation signal.
 */
async function workerBuildAuthHeaders(): Promise<Record<string, string>> {
  const data = await chrome.storage.local.get([
    "clerkUserId",
    "clerkToken",
    "clerkTokenExp",
  ]);

  const token = data.clerkToken as string | undefined;
  const exp = (data.clerkTokenExp as number | undefined) ?? 0;
  const userId = data.clerkUserId as string | undefined;

  // Use JWT Bearer if present and not within 30 s of expiry.
  // exp === 0 means expiry is unknown — treat token as valid.
  if (token && (exp === 0 || Date.now() / 1000 < exp - 30)) {
    return { Authorization: `Bearer ${token}` };
  }

  // Fall back to X-Clerk-User-Id (dev / legacy path)
  if (userId) {
    return { "X-Clerk-User-Id": userId };
  }

  return {};
}

// ── State ──────────────────────────────────────────────────────────────────

// tab id → most recent PageContext detected by content script
const tabContexts = new Map<number, PageContext>();

// ── URL classification ──────────────────────────────────────────────────────

function classifyUrl(url: string): "apply" | "scout" | null {
  if (JOB_SCOUT_PATTERNS.some((p) => p.test(url))) return "scout";
  if (CAREER_URL_PATTERNS.some((p) => p.test(url))) return "apply";
  return null;
}

function extractCompanyFromUrl(url: string, title: string): string {
  // Try hostname first: "careers.google.com" → "Google"
  try {
    const hostname = new URL(url).hostname.replace(/^www\./, "");
    const parts = hostname.split(".");
    // "careers.google.com" → "google"
    if (parts[0] === "careers" || parts[0] === "jobs") {
      return parts[1] ? parts[1].charAt(0).toUpperCase() + parts[1].slice(1) : "";
    }
    // "google.greenhouse.io" → "Google"
    if (parts.length >= 3 && (parts[1] === "greenhouse" || parts[1] === "lever")) {
      return parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
    }
  } catch {
    // ignore
  }

  // Fall back to page title: "Software Engineer at Google" → "Google"
  const atMatch = title.match(/\bat\s+([A-Z][a-zA-Z\s]+?)(?:\s*[\-–|]|$)/);
  if (atMatch) return atMatch[1].trim();

  return "";
}

// ── Tab event listeners ────────────────────────────────────────────────────

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url) return;

  const mode = classifyUrl(tab.url);
  if (!mode) return;

  const company = extractCompanyFromUrl(tab.url, tab.title || "");

  // Inject a preliminary context so the sidepanel has something to show
  // immediately — the content script will send a richer update shortly.
  const prelimContext: PageContext = {
    mode,
    company,
    roleTitle: tab.title || "",
    jobUrl: tab.url,
    platform: detectPlatform(tab.url),
    detectedFields: [],
    openQuestions: [],
  };

  tabContexts.set(tabId, prelimContext);

  // Open the side panel for this tab
  chrome.sidePanel.open({ tabId }).catch(() => {
    // Side panel may already be open — ignore
  });

  // Notify sidepanel
  chrome.runtime.sendMessage<Message>({
    type: "PAGE_CONTEXT_UPDATE",
    payload: prelimContext,
  }).catch(() => {
    // Sidepanel not yet open — it will request context on mount
  });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  tabContexts.delete(tabId);
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const ctx = tabContexts.get(tabId);
  if (ctx) {
    chrome.sidePanel.open({ tabId }).catch(() => {});
    chrome.tabs.sendMessage(tabId, { type: "JOB_PAGE_DETECTED", context: ctx }).catch(() => {});
  }
});

// ── Message relay ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener(
  (message: Message, sender, sendResponse) => {
    switch (message.type) {
      case "OPEN_SIDEPANEL": {
        // Badge click in content script → open sidepanel for that tab
        const tabId = sender.tab?.id;
        if (tabId) {
          chrome.sidePanel.open({ tabId }).catch(() => {});
        }
        break;
      }

      case "JOB_PAGE_DETECTED": {
        // Heuristic fired in content script for unknown ATS domain → store context + open sidepanel
        const tabId = sender.tab?.id;
        if (tabId) {
          // Store heuristically-detected context if not already known (URL didn't match patterns)
          if (!tabContexts.has(tabId) && message.context) {
            tabContexts.set(tabId, message.context);
          }
          chrome.sidePanel.open({ tabId }).catch(() => {});
        }
        break;
      }

      case "PAGE_CONTEXT_UPDATE": {
        // Content script sends enriched context (detected fields, questions).
        // If the message comes from a sub-frame (frameId != 0), MERGE its fields
        // and questions into the existing top-level context so Workday iframes
        // contribute their form inputs without overwriting the company/role detected
        // from the main frame.
        if (sender.tab?.id) {
          const tabId = sender.tab.id;
          const isSubFrame = (sender.frameId ?? 0) !== 0;
          const incoming: PageContext = message.payload;

          if (isSubFrame) {
            const existing = tabContexts.get(tabId);
            if (existing) {
              // Merge: deduplicate by fieldId / questionId
              const existingFieldIds = new Set(existing.detectedFields.map((f) => f.fieldId));
              const existingQIds = new Set(existing.openQuestions.map((q) => q.questionId));
              const newFields = incoming.detectedFields.filter((f) => !existingFieldIds.has(f.fieldId));
              const newQuestions = incoming.openQuestions.filter((q) => !existingQIds.has(q.questionId));
              const merged: PageContext = {
                ...existing,
                detectedFields: [...existing.detectedFields, ...newFields],
                openQuestions: [...existing.openQuestions, ...newQuestions],
              };
              tabContexts.set(tabId, merged);
              chrome.runtime.sendMessage<Message>({ type: "PAGE_CONTEXT_UPDATE", payload: merged }).catch(() => {});
            } else {
              // No existing context yet — treat sub-frame as primary
              tabContexts.set(tabId, incoming);
              chrome.runtime.sendMessage(message).catch(() => {});
            }
          } else {
            // Main frame: replace wholesale (authoritative company/role/mode)
            tabContexts.set(tabId, incoming);
            chrome.runtime.sendMessage(message).catch(() => {});
          }
        }
        break;
      }

      case "GET_CONTEXT": {
        // Sidepanel asks: what's the current context?
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          const tabId = tabs[0]?.id;
          const ctx = tabId ? (tabContexts.get(tabId) ?? null) : null;
          sendResponse({ type: "CONTEXT_RESPONSE", payload: ctx });
        });
        return true; // Keep channel open for async sendResponse
      }

      case "FILL_FIELD":
      case "FILL_ANSWER": {
        // Sidepanel asks content script to fill a specific field / textarea
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          if (tabs[0]?.id) {
            chrome.tabs.sendMessage(tabs[0].id, message).catch(() => {});
          }
        });
        break;
      }

      case "ATTACH_RESUME": {
        // Sidepanel asks content script to attach a PDF to a file input
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
          if (tabs[0]?.id) {
            chrome.tabs.sendMessage(tabs[0].id, message).catch(() => {});
          }
        });
        break;
      }

      case "JOB_CARDS_UPDATE": {
        // Content script sends scraped job cards; relay to sidepanel
        chrome.runtime.sendMessage(message).catch(() => {});
        break;
      }

      case "EMAIL_STATUS_DETECTED": {
        // Gmail tracker found job-related emails — update application status for each match.
        // Uses company name to find the most recent matching application, then PATCHes status.
        const emailMatches = message.payload;
        if (!emailMatches?.length) break;

        chrome.storage.local.get(["clerkUserId", "apiBaseUrl"]).then(async (data) => {
          const userId = data.clerkUserId as string | undefined;
          const apiBase = (data.apiBaseUrl as string | undefined) || "https://autoapply-ai-api.fly.dev/api/v1";
          if (!userId) return;

          const authHdrs = await workerBuildAuthHeaders();

          for (const match of emailMatches) {
            if (!match.company) continue;
            // Step 1: list applications for this company
            fetch(`${apiBase}/applications?company=${encodeURIComponent(match.company)}&limit=1`, {
              headers: authHdrs,
            }).then((r) => r.json()).then((res: { items?: Array<{ id: string; status: string }> }) => {
              const app = res.items?.[0];
              if (!app) return;
              // Only upgrade status (don't downgrade e.g. interview → applied)
              const STATUS_RANK: Record<string, number> = {
                discovered: 0, applied: 1, tailored: 1, phone_screen: 2,
                interview: 3, offer: 4, rejected: 4,
              };
              const currentRank = STATUS_RANK[app.status] ?? 0;
              const newRank = STATUS_RANK[match.status] ?? 0;
              if (newRank <= currentRank) return;
              return fetch(`${apiBase}/applications/${app.id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json", ...authHdrs },
                body: JSON.stringify({ status: match.status }),
              });
            }).catch(() => {});
          }
        }).catch(() => {});
        break;
      }

      case "APPLICATION_SUBMITTED": {
        // Content script detected a form submission — update tracked application to "applied".
        // We look up the tracked context for this tab, find the application_id via the URL
        // and call PATCH /applications/:id with status=applied.
        const tabId = sender.tab?.id;
        if (!tabId) break;
        const ctx = tabContexts.get(tabId);
        if (!ctx) break;

        // Notify sidepanel so it can update its History tab state
        chrome.runtime.sendMessage<Message>({ type: "PAGE_CONTEXT_UPDATE", payload: ctx }).catch(() => {});

        // Fire-and-forget: update via API using stored credentials
        chrome.storage.local.get(["clerkUserId", "apiBaseUrl"]).then(async (data) => {
          const userId = data.clerkUserId as string | undefined;
          const apiBase = (data.apiBaseUrl as string | undefined) || "https://autoapply-ai-api.fly.dev/api/v1";
          if (!userId || !ctx.jobUrl) return;

          const authHdrs = await workerBuildAuthHeaders();

          // Use the track endpoint to get/create the application record first, then patch status
          fetch(`${apiBase}/applications/track`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHdrs },
            body: JSON.stringify({
              company_name: ctx.company,
              role_title: ctx.roleTitle,
              job_url: ctx.jobUrl,
              platform: ctx.platform ?? "generic",
            }),
          }).then((r) => r.json()).then((res: { application_id: string }) => {
            if (!res.application_id) return;
            return fetch(`${apiBase}/applications/${res.application_id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json", ...authHdrs },
              body: JSON.stringify({ status: "applied" }),
            });
          }).catch(() => {});
        }).catch(() => {});
        break;
      }
    }
  }
);

// ── Offline sync queue drain ───────────────────────────────────────────────

// When we come back online, push any pending markdown edits to GitHub via the API
self.addEventListener("online", () => {
  drainOfflineQueue().catch(console.error);
});

async function drainOfflineQueue(): Promise<void> {
  const result = await chrome.storage.local.get("offline_queue");
  const queue: Array<{
    id: string;
    versionTag: string;
    markdownContent: string;
    timestamp: number;
    synced: boolean;
  }> = result.offline_queue || [];

  const pending = queue.filter((e) => !e.synced);
  if (pending.length === 0) return;

  console.log(`[AutoApply] Draining ${pending.length} offline edits...`);

  for (const entry of pending) {
    try {
      const fd = new FormData();
      fd.append("version_tag", entry.versionTag);
      fd.append("markdown_content", entry.markdownContent);
      fd.append("timestamp", String(entry.timestamp));

      const resp = await fetch("http://localhost:8000/api/v1/vault/sync-markdown", {
        method: "POST",
        body: fd,
      });

      if (resp.ok) {
        entry.synced = true;
        console.log(`[AutoApply] Synced edit for ${entry.versionTag}`);
      }
    } catch {
      // Stay pending — will retry on next online event
    }
  }

  await chrome.storage.local.set({ offline_queue: queue });
}

// ── Helpers ────────────────────────────────────────────────────────────────

function detectPlatform(url: string): string {
  if (/linkedin\.com/.test(url)) return "linkedin";
  if (/greenhouse\.io/.test(url)) return "greenhouse";
  if (/lever\.co/.test(url)) return "lever";
  if (/workday\.com|myworkday\.com/.test(url)) return "workday";
  if (/indeed\.com/.test(url)) return "indeed";
  if (/glassdoor\.com/.test(url)) return "glassdoor";
  if (/taleo\.net/.test(url)) return "taleo";
  return "generic";
}

export {};
