/**
 * gmailTracker.ts — T2: Email status parsing for Gmail
 *
 * When the user has Gmail open, scans visible email subjects + senders for
 * job-application status signals (interview invite, rejection, offer).
 *
 * Strategy:
 *  - MutationObserver watches Gmail's conversation list for new rows
 *  - Each row subject is matched against keyword patterns
 *  - Matched emails are batched and sent to the background worker via
 *    chrome.runtime.sendMessage({ type: "EMAIL_STATUS_DETECTED", payload: [...] })
 *  - background worker calls PATCH /applications/:id to update status
 *
 * This module only READS email subject lines visible in the DOM.
 * It does NOT open emails, access email body, or use the Gmail API.
 */

// ── Email signal patterns ──────────────────────────────────────────────────

export type EmailSignal = "interview" | "offer" | "rejected" | "applied" | "phone_screen";

interface EmailMatch {
  subject: string;
  sender: string;
  signal: EmailSignal;
  confidence: number; // 0–1
}

const SIGNAL_PATTERNS: Array<{ signal: EmailSignal; patterns: RegExp[]; confidence: number }> = [
  {
    signal: "interview",
    confidence: 0.9,
    patterns: [
      /interview\s+(invitation|invite|request|scheduled|confirmation)/i,
      /we.*like to\s+interview/i,
      /interview\s+with\s+us/i,
      /schedule.*interview/i,
      /interview.*next\s+step/i,
      /technical\s+interview/i,
      /onsite\s+interview/i,
      /virtual\s+interview/i,
      /hiring\s+manager\s+interview/i,
      /panel\s+interview/i,
    ],
  },
  {
    signal: "phone_screen",
    confidence: 0.85,
    patterns: [
      /phone\s+(screen|interview|call)/i,
      /recruiter\s+(screen|call|reach out)/i,
      /intro\s+call/i,
      /screening\s+call/i,
      /initial\s+(call|conversation)/i,
      /chat\s+with.*recruiter/i,
    ],
  },
  {
    signal: "offer",
    confidence: 0.95,
    patterns: [
      /offer\s+letter/i,
      /job\s+offer/i,
      /we.*pleased to\s+offer/i,
      /congratulations.*offer/i,
      /offer.*congratulations/i,
      /extend.*offer/i,
      /formal\s+offer/i,
    ],
  },
  {
    signal: "rejected",
    confidence: 0.88,
    patterns: [
      /unfortunately.*not.*moving forward/i,
      /not.*moving.*forward.*application/i,
      /application.*not.*selected/i,
      /not.*selected.*position/i,
      /decided.*pursue.*other\s+candidates/i,
      /other\s+candidates.*better\s+fit/i,
      /filled\s+the\s+position/i,
      /position.*been\s+filled/i,
      /we.*regret.*inform/i,
      /not.*match.*requirements/i,
      /application.*rejected/i,
      /rejected.*application/i,
    ],
  },
  {
    signal: "applied",
    confidence: 0.7,
    patterns: [
      /application\s+(received|submitted|confirmed)/i,
      /we\s+received\s+your\s+application/i,
      /thank\s+you\s+for\s+(applying|your application)/i,
      /application\s+confirmation/i,
    ],
  },
];

// Map email signal → application status (for PATCH /applications/:id)
const SIGNAL_TO_STATUS: Record<EmailSignal, string> = {
  interview: "interview",
  phone_screen: "interview",
  offer: "offer",
  rejected: "rejected",
  applied: "applied",
};

// ── Company name extraction from subject/sender ────────────────────────────

function extractCompanyFromEmail(subject: string, sender: string): string {
  // "Interview with Google" → "Google"
  const withMatch = subject.match(/(?:interview|offer|from|at|with)\s+([A-Z][a-zA-Z0-9\s&.,]+?)(?:\s*[-–|,!]|$)/i);
  if (withMatch) return withMatch[1].trim().replace(/\s+/g, " ").slice(0, 40);

  // Extract domain from sender email: "careers@google.com" → "Google"
  const emailDomain = sender.match(/@([a-z0-9-]+)\./i);
  if (emailDomain) {
    const domain = emailDomain[1];
    // Skip generic domains
    if (!["gmail", "yahoo", "outlook", "hotmail", "noreply", "no-reply", "donotreply", "notifications", "careers", "jobs", "greenhouse", "lever", "workday"].includes(domain.toLowerCase())) {
      return domain.charAt(0).toUpperCase() + domain.slice(1);
    }
  }

  return "";
}

// ── Gmail DOM parsing ──────────────────────────────────────────────────────

function getEmailRows(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(
      // Gmail uses tr[jscontroller] for email rows
      "tr[jscontroller][id], tr[data-legacy-thread-id], div[data-thread-id]"
    )
  );
}

function getSubjectFromRow(row: HTMLElement): string {
  // Subject is usually in a <span> with a specific class, or an element with role="link"
  const subjectEl =
    row.querySelector<HTMLElement>(".bog") ?? // Gmail subject class
    row.querySelector<HTMLElement>("[data-thread-id] span[id]") ??
    row.querySelector<HTMLElement>("span.y6") ??  // subject+snippet container
    row.querySelector<HTMLElement>("span[class]");
  return subjectEl?.textContent?.trim() ?? row.textContent?.trim().slice(0, 100) ?? "";
}

function getSenderFromRow(row: HTMLElement): string {
  const senderEl =
    row.querySelector<HTMLElement>(".yW span, .zF") ?? // Gmail sender element
    row.querySelector<HTMLElement>("[email]");
  return senderEl?.getAttribute("email") ?? senderEl?.textContent?.trim() ?? "";
}

// ── Match detection ────────────────────────────────────────────────────────

function matchEmail(subject: string, sender: string): EmailMatch | null {
  for (const { signal, patterns, confidence } of SIGNAL_PATTERNS) {
    for (const pattern of patterns) {
      if (pattern.test(subject)) {
        return { subject, sender, signal, confidence };
      }
    }
  }
  return null;
}

// ── Send matches to background for API update ─────────────────────────────

function reportMatches(matches: EmailMatch[]): void {
  if (matches.length === 0) return;
  const payload = matches.map((m) => ({
    subject: m.subject,
    sender: m.sender,
    status: SIGNAL_TO_STATUS[m.signal],
    company: extractCompanyFromEmail(m.subject, m.sender),
    confidence: m.confidence,
  }));
  chrome.runtime.sendMessage({ type: "EMAIL_STATUS_DETECTED", payload }).catch(() => {});
}

// ── Scan visible email rows ────────────────────────────────────────────────

let _scannedRows = new Set<string>();

function scanGmailRows(): void {
  const rows = getEmailRows();
  const newMatches: EmailMatch[] = [];

  for (const row of rows) {
    const rowId = row.getAttribute("id") ?? row.getAttribute("data-legacy-thread-id") ?? "";
    if (rowId && _scannedRows.has(rowId)) continue; // already processed
    if (rowId) _scannedRows.add(rowId);

    const subject = getSubjectFromRow(row);
    const sender = getSenderFromRow(row);
    if (!subject) continue;

    const match = matchEmail(subject, sender);
    if (match) newMatches.push(match);
  }

  if (newMatches.length > 0) {
    reportMatches(newMatches);
  }
}

// ── Notification banner ────────────────────────────────────────────────────

export function showGmailBanner(count: number, company: string, status: string): void {
  const existing = document.getElementById("__aap_gmail_banner__");
  if (existing) existing.remove();

  const banner = document.createElement("div");
  banner.id = "__aap_gmail_banner__";
  Object.assign(banner.style, {
    position: "fixed",
    top: "16px",
    right: "16px",
    zIndex: "2147483647",
    background: "#0f0f1e",
    border: "1px solid #4f46e5",
    borderRadius: "10px",
    padding: "12px 16px",
    color: "#e2e8f0",
    fontSize: "12px",
    fontFamily: "system-ui,sans-serif",
    boxShadow: "0 4px 20px rgba(0,0,0,0.5)",
    maxWidth: "280px",
    lineHeight: "1.5",
  });
  banner.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
      <span style="font-size:16px">⚡</span>
      <span style="font-weight:700;color:#a78bfa">AutoApply AI</span>
      <button id="__aap_banner_close__" style="margin-left:auto;background:none;border:none;color:#475569;cursor:pointer;font-size:14px;">✕</button>
    </div>
    <div>Detected <strong>${count}</strong> job email${count > 1 ? "s" : ""}${company ? ` from <strong>${company}</strong>` : ""}.</div>
    <div style="margin-top:4px;color:#94a3b8;">Application status updated to <strong style="color:#a78bfa;">${status}</strong>.</div>
  `;
  document.body.appendChild(banner);

  banner.querySelector("#__aap_banner_close__")?.addEventListener("click", () => banner.remove());
  setTimeout(() => banner.remove(), 6000);
}

// ── Init ────────────────────────────────────────────────────────────────────

export function initGmailTracker(): void {
  if (!/mail\.google\.com/i.test(window.location.href)) return;

  // Initial scan after Gmail loads
  setTimeout(scanGmailRows, 2000);

  // Watch for new email rows (inbox, search results, navigation)
  const observer = new MutationObserver(() => {
    scanGmailRows();
  });

  // Gmail's main content area
  const gmailRoot = document.querySelector<HTMLElement>('[role="main"]') ?? document.body;
  observer.observe(gmailRoot, { childList: true, subtree: true });

  // Re-scan on Gmail SPA navigation (hash changes)
  window.addEventListener("hashchange", () => {
    _scannedRows.clear(); // Reset on navigation so new inbox view is fully scanned
    setTimeout(scanGmailRows, 800);
  });
}
