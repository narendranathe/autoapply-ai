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

// ── Career page URL patterns ───────────────────────────────────────────────

const CAREER_URL_PATTERNS = [
  /greenhouse\.io\/jobs\//,
  /lever\.co\//,
  /myworkday\.com/,
  /workday\.com\/[^/]+\/d\/jobs/,
  /taleo\.net/,
  /smartrecruiters\.com\/jobs/,
  /icims\.com/,
  /jobvite\.com/,
  /ashbyhq\.com/,
  /jobs\.ashbyhq\.com/,
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

// ── Message relay ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener(
  (message: Message, sender, sendResponse) => {
    switch (message.type) {
      case "PAGE_CONTEXT_UPDATE": {
        // Content script sends enriched context (detected fields, questions)
        if (sender.tab?.id) {
          tabContexts.set(sender.tab.id, message.payload);
        }
        // Relay to sidepanel
        chrome.runtime.sendMessage(message).catch(() => {});
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
