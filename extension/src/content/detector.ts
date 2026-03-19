/**
 * Content Script — injected into every page.
 *
 * Responsibilities:
 * 1. Detect application form fields (name, email, resume upload, etc.)
 * 2. Detect open-ended questions (textarea prompts)
 * 3. Detect job scout job cards (LinkedIn, Indeed, etc.)
 * 4. Send PageContext to background worker
 * 5. Listen for FILL_FIELD / ATTACH_RESUME messages from sidepanel
 * 6. Inject the floating overlay badge on career pages
 */

import type { DetectedField, DetectedQuestion, FieldType, JobCard, Message, PageContext, QuestionCategory } from "../shared/types";
import { FIELD_PATTERNS, QUESTION_CATEGORY_PATTERNS } from "../shared/detection-patterns";

// ── Label hashing ──────────────────────────────────────────────────────────

function computeLabelHash(label: string): string {
  const normalized = label.toLowerCase().replace(/\s+/g, " ").replace(/[^\w\s]/g, "").trim();
  // djb2 hash — synchronous, no async needed
  let hash = 5381;
  for (let i = 0; i < normalized.length; i++) {
    hash = ((hash << 5) + hash) + normalized.charCodeAt(i);
    hash = hash & hash; // force 32-bit
  }
  return (hash >>> 0).toString(36);
}

// ── Field detection ────────────────────────────────────────────────────────

function getFieldLabel(el: HTMLElement): string {
  // Try: aria-label, placeholder, associated <label>, nearby text
  const ariaLabel = el.getAttribute("aria-label") || "";
  if (ariaLabel) return ariaLabel;

  const placeholder = el.getAttribute("placeholder") || "";
  if (placeholder) return placeholder;

  const id = el.getAttribute("id");
  if (id) {
    const label = document.querySelector(`label[for="${id}"]`);
    if (label) return label.textContent?.trim() || "";
  }

  // Walk up to find a label or legend
  let parent = el.parentElement;
  for (let i = 0; i < 5; i++) {
    if (!parent) break;
    const label = parent.querySelector("label, legend");
    if (label && label !== el) return label.textContent?.trim() || "";
    parent = parent.parentElement;
  }

  // Check field wrapper with class-based label
  const wrapper = el.closest("[class*='field'], [class*='Field'], [class*='form-group'], [class*='form-item'], [class*='FormItem'], [class*='FormField']");
  if (wrapper) {
    const wrapperLabel = wrapper.querySelector("label, legend, [class*='label'], [class*='Label']");
    if (wrapperLabel && wrapperLabel !== el) {
      const text = wrapperLabel.textContent?.trim() || "";
      if (text) return text;
    }
  }
  // Check previous sibling for label text
  const prev = el.previousElementSibling;
  if (prev && ["SPAN", "DIV", "LABEL", "P"].includes(prev.tagName)) {
    const text = prev.textContent?.trim() || "";
    if (text && text.length < 80) return text;
  }

  return el.getAttribute("name") || "";
}

function classifyField(el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement): FieldType {
  const label = getFieldLabel(el as HTMLElement).toLowerCase();
  const name = (el.getAttribute("name") || "").toLowerCase();
  const id = (el.getAttribute("id") || "").toLowerCase();
  const combined = `${label} ${name} ${id}`;

  if (el instanceof HTMLInputElement && el.type === "file") {
    const accept = (el.getAttribute("accept") || "").toLowerCase();
    const nearbyText = getFieldLabel(el as HTMLElement).toLowerCase();
    if (/cover/i.test(nearbyText)) return "cover_letter_upload" as FieldType;
    return "resume_upload";
  }

  for (const { type, patterns } of FIELD_PATTERNS) {
    if (patterns.some((p) => p.test(combined))) return type;
  }
  return "unknown";
}

function detectFields(): DetectedField[] {
  const inputs = Array.from(
    document.querySelectorAll<HTMLInputElement | HTMLSelectElement>(
      "input:not([type=hidden]):not([type=submit]):not([type=button]), select"
    )
  );
  const fields: DetectedField[] = [];

  for (const el of inputs) {
    const fieldType = classifyField(el as HTMLInputElement);
    if (fieldType === "unknown" && !getFieldLabel(el as HTMLElement)) continue;

    const label = getFieldLabel(el as HTMLElement);
    const labelHash = computeLabelHash(label);
    fields.push({
      fieldId: el.id || el.name || `field_${fields.length}`,
      fieldType,
      label,
      labelHash,
      currentValue: (el as HTMLInputElement).value || "",
      suggestedValue: "",
      confidence: 0.9,
    });
  }
  return fields;
}

function isEssayQuestion(label: string): boolean {
  // Any textarea with a non-trivial label is a Q&A question.
  // detectFields() only covers <input> and <select>, never <textarea>,
  // so every textarea is by definition not in the Fields list.
  return label.trim().length >= 3;
}

function detectQuestions(): DetectedQuestion[] {
  const questions: DetectedQuestion[] = [];
  const seen = new Set<string>(); // dedup by questionId

  // Scan standard <textarea> elements
  const textareas = Array.from(document.querySelectorAll<HTMLTextAreaElement>("textarea"));
  for (const ta of textareas) {
    const label = getFieldLabel(ta);
    if (!label) continue;
    if (!isEssayQuestion(label)) continue;

    const qId = ta.id || ta.name || `q_${questions.length}`;
    if (seen.has(qId)) continue;
    seen.add(qId);

    let category: QuestionCategory = "custom";
    for (const { category: cat, patterns } of QUESTION_CATEGORY_PATTERNS) {
      if (patterns.some((p) => p.test(label))) { category = cat; break; }
    }

    questions.push({
      questionId: qId,
      questionText: label,
      category,
      fieldType: "textarea",
      maxLength: ta.maxLength > 0 ? ta.maxLength : undefined,
    });
  }

  // Scan contenteditable divs — used by Ashby, newer Greenhouse, Notion-style ATSes
  const contenteditables = Array.from(
    document.querySelectorAll<HTMLElement>('[contenteditable="true"], [contenteditable=""]')
  );
  for (const ce of contenteditables) {
    // Skip tiny/invisible contenteditable elements (toolbars, etc.)
    const rect = ce.getBoundingClientRect();
    if (rect.height < 30 || rect.width < 100) continue;
    // Skip elements that look like rich text toolbars or navigation
    const role = (ce.getAttribute("role") || "").toLowerCase();
    if (["toolbar", "navigation", "menu", "menuitem", "combobox"].includes(role)) continue;

    const label = getFieldLabel(ce);
    if (!label) continue;
    if (!isEssayQuestion(label)) continue;

    const qId = ce.id || `ce_${questions.length}`;
    if (seen.has(qId)) continue;
    seen.add(qId);

    let category: QuestionCategory = "custom";
    for (const { category: cat, patterns } of QUESTION_CATEGORY_PATTERNS) {
      if (patterns.some((p) => p.test(label))) { category = cat; break; }
    }

    // Contenteditable elements rarely have maxLength — use aria-describedby hint if available
    const describedBy = ce.getAttribute("aria-describedby");
    let maxLength: number | undefined;
    if (describedBy) {
      const hint = document.getElementById(describedBy)?.textContent || "";
      const limitMatch = hint.match(/(\d+)\s*(char|character|word)/i);
      if (limitMatch) maxLength = parseInt(limitMatch[1], 10);
    }

    questions.push({
      questionId: qId,
      questionText: label,
      category,
      fieldType: "textarea",
      maxLength,
    });
  }

  return questions;
}

// ── Job scout detection (LinkedIn, Indeed) ─────────────────────────────────

function extractJobCards(): Array<{ company: string; role: string; url: string }> {
  const cards: Array<{ company: string; role: string; url: string }> = [];

  // LinkedIn
  document.querySelectorAll<HTMLElement>(".job-card-container").forEach((card) => {
    const role = card.querySelector(".job-card-list__title")?.textContent?.trim() || "";
    const company = card.querySelector(".job-card-container__company-name")?.textContent?.trim() || "";
    const link = card.querySelector<HTMLAnchorElement>("a.job-card-list__title");
    if (role && company) cards.push({ company, role, url: link?.href || "" });
  });

  // Indeed
  document.querySelectorAll<HTMLElement>("[data-testid='job-title']").forEach((el) => {
    const role = el.textContent?.trim() || "";
    const companyEl = el.closest("[data-testid='slider_container']")?.querySelector("[data-testid='company-name']");
    const company = companyEl?.textContent?.trim() || "";
    const link = el.closest("a") as HTMLAnchorElement | null;
    if (role && company) cards.push({ company, role, url: link?.href || "" });
  });

  return cards.slice(0, 20);
}

// ── Overlay badge injection ────────────────────────────────────────────────

function injectOverlayBadge(company: string, atsHint: string) {
  const existing = document.getElementById("autoapply-badge");
  if (existing) existing.remove();

  const badge = document.createElement("div");
  badge.id = "autoapply-badge";
  badge.innerHTML = `
    <div style="
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 2147483647;
      background: #1a1a2e;
      color: #e0e0e0;
      border-radius: 12px;
      padding: 12px 16px;
      font-family: system-ui, sans-serif;
      font-size: 13px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.4);
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 220px;
      border: 1px solid #3a3a5c;
    ">
      <span style="font-size: 18px;">🎯</span>
      <div>
        <div style="font-weight: 600; color: #a78bfa;">${company || "Job Application"}</div>
        <div style="font-size: 11px; color: #9ca3af; margin-top: 2px;">${atsHint || "AutoApply AI — Click to open"}</div>
      </div>
      <span style="margin-left: auto; color: #6b7280; font-size: 16px;">→</span>
    </div>
  `;

  badge.addEventListener("click", () => {
    chrome.runtime.sendMessage<Message>({ type: "OPEN_SIDEPANEL" });
  });

  document.body.appendChild(badge);

  // Auto-hide after 8 seconds
  setTimeout(() => badge.remove(), 8000);
}

// ── Apply button detection ─────────────────────────────────────────────────

function detectApplyButton(): boolean {
  const buttons = Array.from(document.querySelectorAll("button, a[role=button], [type=submit]"));
  return buttons.some((btn) => {
    const text = btn.textContent?.toLowerCase() || "";
    return /\bapply\b|\bapply now\b|\beasy apply\b|\bsubmit application\b/.test(text);
  });
}

// ── Main detection orchestrator ────────────────────────────────────────────

// ── JD text extraction ─────────────────────────────────────────────────────
// Scrapes the visible job description text from the page.
// Used to ground LLM answer generation in the actual JD — improves relevance.

function extractJdText(): string {
  // Priority selectors: platform-specific containers first, then generic fallbacks
  const JD_SELECTORS = [
    // Greenhouse
    "[data-testid='job-description']",
    ".job-post__body",
    ".job-description",
    // Lever
    ".content[data-qa='job-description']",
    ".posting-description",
    // Workday
    "[data-automation-id='jobPostingDescription']",
    // Ashby
    "[class*='JobPosting-jobDescription']",
    "[class*='job-description']",
    // SmartRecruiters
    ".job-description",
    // LinkedIn (job details page, not listings)
    ".jobs-description__content",
    ".jobs-description-content__text",
    // Indeed
    "#jobDescriptionText",
    "[data-testid='jobsearch-JobComponent-description']",
    // Generic high-signal selectors
    "article.job",
    "[class*='JobDescription']",
    "[class*='description-body']",
    "[id*='job-description']",
    "[id*='jobDescription']",
    "main article",
  ];

  for (const selector of JD_SELECTORS) {
    const el = document.querySelector(selector);
    if (el) {
      const text = el.textContent?.trim() ?? "";
      if (text.length > 200) return text.slice(0, 5000); // cap at 5K chars
    }
  }

  // Last resort: grab the largest block of text on the page that looks like a JD
  // (contains job-related keywords and is at least 300 chars)
  const candidates = Array.from(document.querySelectorAll("div, section, article"))
    .filter((el) => {
      const t = el.textContent ?? "";
      return (
        t.length >= 300 &&
        t.length <= 10000 &&
        /\b(responsibilities|requirements|qualifications|experience|skills|about the role|what you.ll do|we are looking for)\b/i.test(t)
      );
    })
    .sort((a, b) => (b.textContent?.length ?? 0) - (a.textContent?.length ?? 0));

  return (candidates[0]?.textContent?.trim() ?? "").slice(0, 5000);
}

function extractCompanyAndRole(url: string, docTitle: string): { company: string; roleTitle: string } {
  let company = "";
  let roleTitle = docTitle;

  // ── Platform-specific selectors ──────────────────────────────────────────

  // Greenhouse: hosted on greenhouse.io OR custom domain with ?gh_jid= param
  if (/greenhouse\.io/.test(url) || /[?&]gh_jid=/.test(url)) {
    const role = document.querySelector<HTMLElement>("h1.app-title, h1[data-qa='job-title'], .app__role-title")?.textContent?.trim();
    const org = document.querySelector<HTMLElement>(".company-name, .org-name, [data-qa='company-name']")?.textContent?.trim();
    if (role) roleTitle = role;
    if (org) company = org;
  }

  // Lever: job title in h2, company in .main-header-logo or meta
  if (/lever\.co/.test(url)) {
    const role = document.querySelector<HTMLElement>("h2, .posting-headline h2")?.textContent?.trim();
    const logoAlt = document.querySelector<HTMLImageElement>(".main-header-logo img")?.alt?.trim();
    const metaComp = document.querySelector<HTMLMetaElement>("meta[property='og:site_name']")?.content?.trim();
    if (role) roleTitle = role;
    company = logoAlt || metaComp || "";
  }

  // Workday: role in breadcrumb or h1
  if (/workday\.com|myworkday\.com/.test(url)) {
    const role = document.querySelector<HTMLElement>(
      "[data-automation-id='jobPostingHeader'] h2, [data-automation-id='jobPostingTitle'], .job-title"
    )?.textContent?.trim();
    const org = document.querySelector<HTMLElement>(
      "[data-automation-id='companyNameText'], .company-title"
    )?.textContent?.trim();
    // Workday subdomains: company is often in the subdomain (company.workday.com)
    const subdomainMatch = url.match(/https?:\/\/([^.]+)\.(?:myworkday|wd\d+\.myworkdayjobs)\.com/);
    if (role) roleTitle = role;
    if (org) company = org;
    else if (subdomainMatch) company = subdomainMatch[1].replace(/-/g, " ");
  }

  // Ashby
  if (/ashbyhq\.com/.test(url)) {
    const role = document.querySelector<HTMLElement>("h1.job-title, h1, [class*='JobTitle']")?.textContent?.trim();
    const org = document.querySelector<HTMLElement>("[class*='CompanyName'], [class*='company-name']")?.textContent?.trim();
    if (role) roleTitle = role;
    if (org) company = org;
    // Fallback: company subdomain
    if (!company) {
      const sub = url.match(/https?:\/\/jobs\.ashbyhq\.com\/([^/?#]+)/);
      if (sub) company = sub[1].replace(/-/g, " ");
    }
  }

  // SmartRecruiters
  if (/smartrecruiters\.com/.test(url)) {
    const role = document.querySelector<HTMLElement>(".job-title, h1")?.textContent?.trim();
    const org = document.querySelector<HTMLElement>(".company-name, [class*='CompanyName']")?.textContent?.trim();
    if (role) roleTitle = role;
    if (org) company = org;
  }

  // LinkedIn job details
  if (/linkedin\.com/.test(url)) {
    const role = document.querySelector<HTMLElement>(".job-details-jobs-unified-top-card__job-title, h1.topcard__title, .jobs-unified-top-card__job-title")?.textContent?.trim();
    const org = document.querySelector<HTMLElement>(".job-details-jobs-unified-top-card__company-name a, .topcard__org-name-link, .jobs-unified-top-card__company-name a")?.textContent?.trim();
    if (role) roleTitle = role;
    if (org) company = org;
  }

  // Indeed job details
  if (/indeed\.com/.test(url)) {
    const role = document.querySelector<HTMLElement>("[data-testid='jobsearch-JobInfoHeader-title'] span, h1[data-testid='simpler-jobTitle']")?.textContent?.trim();
    const org = document.querySelector<HTMLElement>("[data-testid='inlineHeader-companyName'] a, .jobsearch-CompanyInfoContainer a")?.textContent?.trim();
    if (role) roleTitle = role;
    if (org) company = org;
  }

  // ── OG meta fallback (works across many career sites) ───────────────────
  if (!company) {
    const ogSite = document.querySelector<HTMLMetaElement>("meta[property='og:site_name']")?.content?.trim();
    const metaAppName = document.querySelector<HTMLMetaElement>("meta[name='application-name']")?.content?.trim();
    company = ogSite || metaAppName || "";
  }

  // ── Title-based fallback ─────────────────────────────────────────────────
  if (!company) {
    // "Software Engineer at Google | Careers" → "Google"
    const atMatch = docTitle.match(/\bat\s+([A-Z][A-Za-z0-9\s&.,'()-]+?)(?:\s*[\-–|·]|$)/);
    if (atMatch) company = atMatch[1].trim();
  }
  if (!roleTitle || roleTitle === docTitle) {
    // Use first segment of title before separator
    const titleRole = docTitle.split(/[\-–|·]/)[0].trim();
    if (titleRole && titleRole.length > 3) roleTitle = titleRole;
  }

  // Clean up common suffixes in company names
  company = company.replace(/\s*[-–|·].*$/, "").replace(/\s*(careers|jobs|hiring|apply)\s*$/i, "").trim();

  return { company, roleTitle };
}

// ── Job page heuristics (fallback for unknown ATS / custom career domains) ──

export function detectJobPageHeuristic(): boolean {
  const jobKeywords = /\b(job|position|role|career|engineer|developer|manager|analyst|opening|vacancy)\b/i;
  const headings = Array.from(document.querySelectorAll('h1, h2, h3, title'));
  const hasJobTitle = headings.some(el => jobKeywords.test(el.textContent || ''));

  const formSignals = [
    'input[type="text"][name*="name" i], input[autocomplete*="name" i]',
    'input[type="email"], input[autocomplete="email"]',
    'input[type="tel"], input[autocomplete="tel"]',
    'input[type="file"][accept*=".pdf" i], input[type="file"][accept*=".doc" i]',
    'textarea',
  ].filter(selector => document.querySelector(selector) !== null).length;

  const hasApplyButton = Array.from(document.querySelectorAll("button, [type=submit]"))
    .some(b => /\b(apply|submit)\b/i.test(b.textContent || ""));
  return (hasJobTitle && formSignals >= 1) || (hasJobTitle && hasApplyButton);
}

function buildAndSendContext() {
  const url = window.location.href;
  const title = document.title;

  // Determine mode
  let mode: "apply" | "scout" | null = null;
  if (/linkedin\.com\/jobs|indeed\.com\/(viewjob|jobs)|glassdoor\.com\/(job-listing|Jobs)/.test(url)) {
    mode = "scout";
  } else if (
    /greenhouse\.io|lever\.co|workday\.com|myworkday\.com|taleo\.net|smartrecruiters\.com|careers\.|\/careers\/|\/jobs\//.test(url) ||
    detectApplyButton()
  ) {
    mode = "apply";
  }

  // Heuristic fallback for unknown ATS / custom career domains
  let heuristicDetected = false;
  if (!mode && detectJobPageHeuristic()) {
    mode = "apply";
    heuristicDetected = true;
  }

  if (!mode) return;

  const fields = mode === "apply" ? detectFields() : [];
  const questions = mode === "apply" ? detectQuestions() : [];
  const jdText = mode === "apply" ? extractJdText() : "";

  // Extract company and role using platform-specific selectors, then title fallback
  const { company, roleTitle } = extractCompanyAndRole(url, title);

  const context: PageContext = {
    mode,
    company,
    roleTitle,
    jobUrl: url,
    platform: detectPlatform(url),
    detectedFields: fields,
    openQuestions: questions,
    jdText,
  };

  chrome.runtime.sendMessage<Message>({ type: "PAGE_CONTEXT_UPDATE", payload: context });

  // Notify background that a job page was heuristically or generically detected → opens sidepanel
  if (heuristicDetected || (mode === "apply" && detectPlatform(url) === "generic")) {
    chrome.runtime.sendMessage<Message>({ type: "JOB_PAGE_DETECTED", context }).catch(() => {});
  }

  // In scout mode, also send the scraped job cards so JobScout shows all results
  if (mode === "scout") {
    const cards: JobCard[] = extractJobCards();
    if (cards.length > 0) {
      chrome.runtime.sendMessage<Message>({ type: "JOB_CARDS_UPDATE", payload: cards });
    }
  }

  // Only show the sidepanel badge on pages where the floating panel is NOT injected.
  // Floating panel handles greenhouse, lever, workday, ashby, smartrecruiters, bamboohr, icims, jobvite, taleo.
  const hasFloatingPanel = /greenhouse\.io|lever\.co|workday\.com|myworkday\.com|ashbyhq\.com|smartrecruiters\.com|bamboohr\.com|icims\.com|jobvite\.com|taleo\.net/.test(url);
  if (mode === "apply" && company && !hasFloatingPanel) {
    injectOverlayBadge(company, `${fields.length} fields detected`);
  }
}

function detectPlatform(url: string): string {
  if (/linkedin\.com/.test(url)) return "linkedin";
  if (/greenhouse\.io/.test(url)) return "greenhouse";
  if (/lever\.co/.test(url)) return "lever";
  if (/workday\.com|myworkday\.com/.test(url)) return "workday";
  if (/indeed\.com/.test(url)) return "indeed";
  if (/glassdoor\.com/.test(url)) return "glassdoor";
  return "generic";
}

// ── Message listener (from sidepanel via background) ──────────────────────

chrome.runtime.onMessage.addListener((message: Message) => {
  if (message.type === "FILL_FIELD") {
    const { fieldId, value } = message.payload;
    const el =
      (document.getElementById(fieldId) as HTMLInputElement | null) ||
      document.querySelector<HTMLInputElement>(`[name="${fieldId}"]`);
    if (el) {
      el.focus();
      // Use native setter to trigger React/Vue controlled inputs
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (nativeSetter) nativeSetter.call(el, value);
      else el.value = value;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  if (message.type === "FILL_ANSWER") {
    const { questionId, text } = message.payload;
    const el: HTMLElement | null =
      (document.getElementById(questionId) as HTMLElement | null) ||
      document.querySelector<HTMLElement>(`[name="${questionId}"]`) ||
      document.querySelector<HTMLTextAreaElement>("textarea");
    if (!el) return;
    el.focus();

    // Handle contenteditable (Ashby, newer Greenhouse, etc.)
    if (el.getAttribute("contenteditable") === "true" || el.contentEditable === "true") {
      document.execCommand("selectAll", false);
      document.execCommand("insertText", false, text);
      if (!el.textContent?.includes(text.slice(0, 20))) {
        el.textContent = text;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
      }
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      if (nativeSetter) nativeSetter.call(el, text);
      else (el as HTMLTextAreaElement).value = text;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  if (message.type === "ATTACH_RESUME") {
    const { fieldId, pdfUrl } = message.payload;
    const fileInput =
      (document.getElementById(fieldId) as HTMLInputElement | null) ||
      document.querySelector<HTMLInputElement>(`input[type="file"][accept*="pdf"], input[type="file"]`);
    if (!fileInput) return;

    fetch(pdfUrl)
      .then((r) => r.blob())
      .then((blob) => {
        const file = new File([blob], "resume.pdf", { type: "application/pdf" });
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
        fileInput.dispatchEvent(new Event("change", { bubbles: true }));
        fileInput.dispatchEvent(new Event("input", { bubbles: true }));
      })
      .catch(console.error);
  }
});

// ── Iframe guard ──────────────────────────────────────────────────────────
// When running in a sub-frame (all_frames: true), only proceed if the frame
// looks like an ATS application form — not an ad, analytics pixel, or auth popup.
// Criteria: frame URL matches known ATS patterns OR the frame contains form inputs.

function shouldRunInFrame(): boolean {
  // Always run in the top-level frame
  if (window.self === window.top) return true;

  const frameUrl = window.location.href;

  // Definitely ATS frames — always scan
  const ATS_FRAME_PATTERNS = [
    /workday\.com/i, /myworkday\.com/i, /greenhouse\.io/i, /lever\.co/i,
    /taleo\.net/i, /icims\.com/i, /jobvite\.com/i, /smartrecruiters\.com/i,
    /bamboohr\.com/i, /ashbyhq\.com/i, /successfactors\.com/i, /oracle\.com\/hcm/i,
  ];
  if (ATS_FRAME_PATTERNS.some((p) => p.test(frameUrl))) return true;

  // Unknown frame URL: scan only if the frame already has form inputs, textareas, or
  // contenteditable fields (avoids running on ad iframes, tracking pixels, OAuth popups, etc.)
  const hasFormInputs =
    document.querySelectorAll("input:not([type=hidden]), textarea, select, [contenteditable=true]").length > 0;
  return hasFormInputs;
}

// ── Run on load and on SPA navigation ─────────────────────────────────────

// ── Form submission detection — auto-mark application as "applied" ─────────
// Only runs in the main frame (top-level page), not sub-frames.
function watchFormSubmissionForTracker() {
  if (window.self !== window.top) return; // skip sub-frames

  const notifySubmission = () => {
    // Send to background which will update the tracked application status
    chrome.runtime.sendMessage<Message>({ type: "APPLICATION_SUBMITTED", payload: { url: window.location.href } });
  };

  document.addEventListener("submit", notifySubmission, { capture: true });
  document.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement)?.closest("button, [type=submit], a[role=button]") as HTMLElement | null;
    if (!btn) return;
    const text = btn.textContent?.toLowerCase() ?? "";
    if (/\b(submit application|submit my application|complete application|send application)\b/.test(text)) {
      notifySubmission();
    }
  }, { capture: true });
}

if (!shouldRunInFrame()) {
  // This is a frame we should ignore (ad iframe, tracking pixel, etc.) — exit early
  // Export empty to satisfy module system
} else {

buildAndSendContext();
watchFormSubmissionForTracker();

// Re-scan when SPA frameworks (React/Vue) render form fields after document_idle.
// Greenhouse, Lever, Workday all inject inputs 1-3s after the initial script run.
// Multi-step forms (Workday steps, Greenhouse stages) add new questions on each step.
let _mutationDebounce: ReturnType<typeof setTimeout> | null = null;

function hasSignificantFormChange(mutations: MutationRecord[]): boolean {
  for (const m of mutations) {
    for (const node of Array.from(m.addedNodes)) {
      if (!(node instanceof HTMLElement)) continue;
      // Significant if the added subtree contains a form input, textarea, or contenteditable
      if (
        node.matches("input, textarea, select, [contenteditable=true]") ||
        node.querySelector("input:not([type=hidden]), textarea, select, [contenteditable=true]")
      ) {
        return true;
      }
    }
  }
  return false;
}

const _fieldObserver = new MutationObserver((mutations) => {
  if (!hasSignificantFormChange(mutations)) return; // skip cosmetic DOM updates
  if (_mutationDebounce !== null) clearTimeout(_mutationDebounce);
  _mutationDebounce = setTimeout(buildAndSendContext, 600);
});
if (document.body) {
  _fieldObserver.observe(document.body, { childList: true, subtree: true });
}

// Re-run on SPA navigation (pushState / replaceState)
const _pushState = history.pushState.bind(history);
history.pushState = function (...args) {
  _pushState(...args);
  setTimeout(buildAndSendContext, 800);
};
window.addEventListener("popstate", () => setTimeout(buildAndSendContext, 800));

} // end shouldRunInFrame() guard

// IframeFieldBridge: respond to scan requests from parent frame
window.addEventListener("message", (e: MessageEvent) => {
  if (e.data?.type !== "AAP_SCAN_FIELDS") return;
  const fields = detectFields();
  (e.source as Window)?.postMessage({ type: "AAP_FIELDS_RESULT", fields }, "*");
});

// IframeFieldBridge: handle fill requests from parent frame
window.addEventListener("message", (e: MessageEvent) => {
  if (e.data?.type !== "AAP_FILL_FIELD") return;
  const { fieldId, value } = e.data as { fieldId: string; value: string };
  if (fieldId && value !== undefined) {
    const el = document.querySelector(`[data-aap-id="${fieldId}"]`) as HTMLInputElement | HTMLTextAreaElement | null;
    if (el) {
      el.focus();
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set
        ?? Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
      nativeInputValueSetter?.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
});

export {};
