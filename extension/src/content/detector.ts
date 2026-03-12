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

// ── Field detection ────────────────────────────────────────────────────────

const FIELD_PATTERNS: Array<{ type: FieldType; patterns: RegExp[] }> = [
  { type: "first_name", patterns: [/first[_\s-]?name/i, /fname/i, /given[_\s-]?name/i] },
  { type: "last_name",  patterns: [/last[_\s-]?name/i, /lname/i, /family[_\s-]?name/i, /surname/i] },
  { type: "full_name",  patterns: [/^name$/i, /full[_\s-]?name/i, /your[_\s-]?name/i] },
  { type: "email",      patterns: [/email/i] },
  { type: "phone",      patterns: [/phone/i, /mobile/i, /tel/i, /cell/i] },
  { type: "address",    patterns: [/address/i, /street/i] },
  { type: "city",       patterns: [/^city$/i, /city[_\s]?name/i] },
  { type: "state",      patterns: [/\bstate\b/i, /province/i, /region/i] },
  { type: "zip",        patterns: [/zip/i, /postal/i, /postcode/i] },
  { type: "country",    patterns: [/country/i, /nation/i, /reside\b/i, /resident/i, /united states/i] },
  { type: "us_resident", patterns: [/reside in the u\.?s/i, /us resident/i, /live in the (us|united states)/i] },
  { type: "linkedin",   patterns: [/linkedin/i] },
  { type: "github",     patterns: [/github/i] },
  { type: "portfolio",  patterns: [/portfolio/i, /personal[_\s-]?site/i, /personal[_\s-]?web/i] },
  { type: "website",    patterns: [/^website$/i, /web[_\s-]?site/i, /personal[_\s-]?url/i] },
  { type: "degree",     patterns: [/\bdegree\b/i, /education level/i, /highest.*degree/i, /level.*education/i, /\beducation\b/i] },
  { type: "skills",     patterns: [/skill/i] },
  { type: "years_experience", patterns: [/years.+experience/i, /experience.+years/i, /yoe/i] },
  { type: "salary",     patterns: [/salary/i, /compensation/i, /pay[_\s-]?expectation/i] },
  { type: "sponsorship", patterns: [/sponsor/i, /visa/i, /work[_\s-]?auth/i, /authorized.+work/i, /immigration/i, /h-?1b/i, /require.*employment/i] },
  { type: "demographic", patterns: [/race/i, /ethnicity/i, /gender/i, /veteran/i, /disability/i, /hispanic/i, /latino/i, /pronoun/i] },
];

const QUESTION_CATEGORY_PATTERNS: Array<{ category: QuestionCategory; patterns: RegExp[] }> = [
  { category: "cover_letter", patterns: [/cover.?letter/i, /letter of interest/i, /motivation letter/i] },
  { category: "why_company", patterns: [/why.+(want|interested|join|work|here|company)/i, /what draws you/i, /why do you want to work/i] },
  { category: "why_hire", patterns: [/why (should|hire|choose|best candidate)/i, /what makes you (unique|stand out)/i, /why are you the right/i] },
  { category: "about_yourself", patterns: [/tell us about yourself/i, /introduce yourself/i, /walk us through/i, /about yourself/i] },
  { category: "strength", patterns: [/strength/i, /excel at/i, /best at/i, /what are you good at/i] },
  { category: "weakness", patterns: [/weakness/i, /area.+improvement/i, /struggle with/i, /grow.+professionally/i] },
  { category: "challenge", patterns: [/challenge/i, /difficult situation/i, /obstacle/i, /failure/i, /overcame/i, /tough problem/i] },
  { category: "leadership", patterns: [/led|lead/i, /leadership/i, /managed a team/i, /team lead/i, /mentor/i] },
  { category: "conflict", patterns: [/conflict/i, /disagreement/i, /difficult coworker/i, /colleague/i, /difficult person/i] },
  { category: "motivation", patterns: [/motivat/i, /passion/i, /what drives/i, /inspires you/i] },
  { category: "five_years", patterns: [/5 years|five years/i, /career goal/i, /long.term/i, /see yourself/i, /where do you see/i] },
  { category: "impact", patterns: [/proud of/i, /biggest accomplishment/i, /greatest achievement/i, /most proud/i] },
  { category: "fit", patterns: [/align.+value/i, /culture/i, /what do you know about us/i, /research.+company/i, /our mission/i] },
  { category: "sponsorship", patterns: [/sponsor/i, /visa/i, /work authorization/i] },
];

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
      "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio]), select"
    )
  );
  const fields: DetectedField[] = [];

  for (const el of inputs) {
    const fieldType = classifyField(el as HTMLInputElement);
    if (fieldType === "unknown") continue;

    fields.push({
      fieldId: el.id || el.name || `field_${fields.length}`,
      fieldType,
      label: getFieldLabel(el as HTMLElement),
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
  const textareas = Array.from(document.querySelectorAll<HTMLTextAreaElement>("textarea"));
  const questions: DetectedQuestion[] = [];

  for (const ta of textareas) {
    const label = getFieldLabel(ta);
    if (!label) continue;
    if (!isEssayQuestion(label)) continue;

    let category: QuestionCategory = "custom";
    for (const { category: cat, patterns } of QUESTION_CATEGORY_PATTERNS) {
      if (patterns.some((p) => p.test(label))) {
        category = cat;
        break;
      }
    }

    questions.push({
      questionId: ta.id || `q_${questions.length}`,
      questionText: label,
      category,
      fieldType: "textarea",
      maxLength: ta.maxLength > 0 ? ta.maxLength : undefined,
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

  if (!mode) return;

  const fields = mode === "apply" ? detectFields() : [];
  const questions = mode === "apply" ? detectQuestions() : [];
  const jdText = mode === "apply" ? extractJdText() : "";

  // Extract company from URL / title
  let company = "";
  const atMatch = title.match(/\bat\s+([A-Z][a-zA-Z\s]+?)(?:\s*[\-–|]|$)/);
  if (atMatch) company = atMatch[1].trim();

  const context: PageContext = {
    mode,
    company,
    roleTitle: title,
    jobUrl: url,
    platform: detectPlatform(url),
    detectedFields: fields,
    openQuestions: questions,
    jdText,
  };

  chrome.runtime.sendMessage<Message>({ type: "PAGE_CONTEXT_UPDATE", payload: context });

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
    const el =
      (document.getElementById(questionId) as HTMLTextAreaElement | null) ||
      document.querySelector<HTMLTextAreaElement>(`[name="${questionId}"]`) ||
      document.querySelector<HTMLTextAreaElement>("textarea");
    if (el) {
      el.focus();
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      if (nativeSetter) nativeSetter.call(el, text);
      else el.value = text;
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

  // Unknown frame URL: scan only if the frame already has form inputs or textareas
  // (avoids running on ad iframes, tracking pixels, OAuth popups, etc.)
  const hasFormInputs =
    document.querySelectorAll("input:not([type=hidden]), textarea, select").length > 0;
  return hasFormInputs;
}

// ── Run on load and on SPA navigation ─────────────────────────────────────

if (!shouldRunInFrame()) {
  // This is a frame we should ignore (ad iframe, tracking pixel, etc.) — exit early
  // Export empty to satisfy module system
} else {

buildAndSendContext();

// Re-scan when SPA frameworks (React/Vue) render form fields after document_idle.
// Greenhouse, Lever, Workday all inject inputs 1-3s after the initial script run.
let _mutationDebounce: ReturnType<typeof setTimeout> | null = null;
const _fieldObserver = new MutationObserver(() => {
  if (_mutationDebounce !== null) clearTimeout(_mutationDebounce);
  _mutationDebounce = setTimeout(buildAndSendContext, 1000);
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

export {};
