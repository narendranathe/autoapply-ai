/**
 * floatingPanel.ts — Simplify/Jobright-style floating panel for job application pages.
 *
 * Injected as a content script. Uses Shadow DOM for full CSS isolation.
 * No React — pure TypeScript/DOM.
 */

import type { DetectedField, DetectedQuestion, FieldType, QuestionCategory } from "../shared/types";
import { FIELD_PATTERNS, QUESTION_CATEGORY_PATTERNS } from "../shared/detection-patterns";
import { initAshbyApply } from "./ashbyApply";
import { initBambooHRApply } from "./bamboohrApply";
import { initGreenhouseApply } from "./greenhouseApply";
import { initICIMSApply } from "./icimsApply";
import { initIndeedApply } from "./indeedApply";
import { initJobviteApply } from "./jobviteApply";
import { initLeverApply } from "./leverApply";
import { initLinkedInEasyApply } from "./linkedinEasyApply";
import { initSmartRecruitersApply } from "./smartRecruitersApply";
import { initTaleoApply } from "./taleoApply";
import { initWorkdayApply } from "./workdayApply";

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

// ── Types ──────────────────────────────────────────────────────────────────

interface Profile {
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  city: string;
  state: string;
  zip: string;
  country: string;
  linkedinUrl: string;
  githubUrl: string;
  portfolioUrl: string;
  yearsExperience: string;
  degree: string;
  sponsorship: string;
  salary: string;
}

interface QuestionState {
  question: DetectedQuestion;
  drafts: string[];
  draftProviders: string[];
  selectedDraft: number;
  loading: boolean;
  loadingProvider: string;  // which provider is being tried (shown in spinner)
  loadingStartMs: number;   // timestamp when loading started (for elapsed time)
  error: string | null;
}

// ── Constants ──────────────────────────────────────────────────────────────

const JOB_PAGE_PATTERNS = [
  /greenhouse\.io/,
  /lever\.co/,
  /workday\.com/,
  /myworkday\.com/,
  /taleo\.net/,
  /smartrecruiters\.com/,
  /icims\.com/,
  /jobvite\.com/,
  /ashbyhq\.com/,
  /linkedin\.com\/jobs\/view/,
  /indeed\.com\/viewjob/,
  /careers\./,
  /\/careers\//,
  /\/jobs\//,
];

// ── Helpers ────────────────────────────────────────────────────────────────

function isJobPage(): boolean {
  const url = window.location.href;
  if (JOB_PAGE_PATTERNS.some((p) => p.test(url))) return true;
  // Heuristic: job-related heading + at least one form element
  const jobKeywords = /\b(job|position|role|career|engineer|developer|manager|analyst|opening|vacancy|apply|application)\b/i;
  const hasJobTitle = Array.from(document.querySelectorAll("h1, h2, h3")).some(el => jobKeywords.test(el.textContent || ""));
  const hasFormSignal = !!document.querySelector('input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select, [contenteditable="true"]');
  return hasJobTitle && hasFormSignal;
}

function extractCompanyAndRoleFromPage(): { company: string; roleTitle: string } {
  const url = window.location.href;
  const docTitle = document.title;
  let company = "";
  let roleTitle = "";

  if (/greenhouse\.io/.test(url)) {
    roleTitle = document.querySelector<HTMLElement>("h1.app-title, h1[data-qa='job-title'], .app__role-title")?.textContent?.trim() ?? "";
    company = document.querySelector<HTMLElement>(".company-name, .org-name, [data-qa='company-name']")?.textContent?.trim() ?? "";
  } else if (/lever\.co/.test(url)) {
    roleTitle = document.querySelector<HTMLElement>("h2, .posting-headline h2")?.textContent?.trim() ?? "";
    company = document.querySelector<HTMLImageElement>(".main-header-logo img")?.alt?.trim()
      ?? document.querySelector<HTMLMetaElement>("meta[property='og:site_name']")?.content?.trim()
      ?? "";
  } else if (/workday\.com|myworkday\.com/.test(url)) {
    roleTitle = document.querySelector<HTMLElement>("[data-automation-id='jobPostingHeader'] h2, [data-automation-id='jobPostingTitle']")?.textContent?.trim() ?? "";
    company = document.querySelector<HTMLElement>("[data-automation-id='companyNameText']")?.textContent?.trim() ?? "";
    if (!company) {
      const sub = url.match(/https?:\/\/([^.]+)\.(?:myworkday|wd\d+\.myworkdayjobs)\.com/);
      if (sub) company = sub[1].replace(/-/g, " ");
    }
  } else if (/ashbyhq\.com/.test(url)) {
    roleTitle = document.querySelector<HTMLElement>("h1.job-title, h1, [class*='JobTitle']")?.textContent?.trim() ?? "";
    company = document.querySelector<HTMLElement>("[class*='CompanyName'], [class*='company-name']")?.textContent?.trim() ?? "";
    if (!company) {
      const sub = url.match(/https?:\/\/jobs\.ashbyhq\.com\/([^/?#]+)/);
      if (sub) company = sub[1].replace(/-/g, " ");
    }
  } else if (/smartrecruiters\.com/.test(url)) {
    roleTitle = document.querySelector<HTMLElement>(".job-title, h1")?.textContent?.trim() ?? "";
    company = document.querySelector<HTMLElement>(".company-name, [class*='CompanyName']")?.textContent?.trim() ?? "";
  }

  // OG meta fallback
  if (!company) {
    company = document.querySelector<HTMLMetaElement>("meta[property='og:site_name']")?.content?.trim()
      ?? document.querySelector<HTMLMetaElement>("meta[name='application-name']")?.content?.trim()
      ?? "";
  }

  // Title pattern fallback
  if (!company) {
    const atMatch = docTitle.match(/\bat\s+([A-Z][A-Za-z0-9\s&.,'()-]+?)(?:\s*[\-–|·]|$)/);
    if (atMatch) company = atMatch[1].trim();
  }
  if (!roleTitle) {
    // Generic: first h1 or first title segment
    roleTitle = document.querySelector("h1")?.textContent?.trim().slice(0, 100)
      ?? docTitle.split(/[\-–|·]/)[0]?.trim()
      ?? docTitle;
  }
  if (!company) {
    const hostname = window.location.hostname.replace(/^www\./, "");
    const parts = hostname.split(".");
    const SKIP = new Set(["careers", "jobs", "apply", "hiring", "work", "talent", "recruit"]);
    const namePart = parts.find(p => p.length > 2 && !SKIP.has(p.toLowerCase())) ?? parts[0] ?? "";
    company = namePart.split(/[-_]/).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ").trim();
  }

  // Clean trailing noise
  company = company.replace(/\s*[-–|·].*$/, "").replace(/\s*(careers|jobs|hiring|apply)\s*$/i, "").trim();

  return { company, roleTitle };
}

function extractCompanyFromPage(): string {
  return extractCompanyAndRoleFromPage().company;
}

function extractRoleFromPage(): string {
  return extractCompanyAndRoleFromPage().roleTitle;
}

function extractJdText(): string {
  const selectors = [
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
    // LinkedIn
    ".jobs-description__content",
    ".jobs-description-content__text",
    // Indeed
    "#jobDescriptionText",
    "[data-testid='jobsearch-JobComponent-description']",
    // Generic
    "[id*='job-description']",
    "[id*='jobDescription']",
    "[class*='JobDescription']",
    "[class*='description-body']",
    "[class*='posting-body']",
    "[class*='job-details']",
    ".content-wrapper",
    "main article",
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el && (el.textContent?.length ?? 0) > 200) {
      return (el.textContent ?? "").slice(0, 5000);
    }
  }
  // Heuristic fallback: largest div/section with job-related keywords
  const candidates = Array.from(document.querySelectorAll("div, section, article"))
    .filter((el) => {
      const t = el.textContent ?? "";
      return (
        t.length >= 300 &&
        t.length <= 10000 &&
        /\b(responsibilities|requirements|qualifications|experience|skills|about the role)\b/i.test(t)
      );
    })
    .sort((a, b) => (b.textContent?.length ?? 0) - (a.textContent?.length ?? 0));
  return (candidates[0]?.textContent?.trim() ?? "").slice(0, 5000);
}

function getFieldLabel(el: HTMLElement): string {
  const ariaLabel = el.getAttribute("aria-label") ?? "";
  if (ariaLabel) return ariaLabel;
  const placeholder = el.getAttribute("placeholder") ?? "";
  if (placeholder) return placeholder;
  const id = el.getAttribute("id");
  if (id) {
    const label = document.querySelector(`label[for="${id}"]`);
    if (label) return label.textContent?.trim() ?? "";
  }
  let parent = el.parentElement;
  for (let i = 0; i < 5; i++) {
    if (!parent) break;
    const label = parent.querySelector("label, legend");
    if (label && label !== el) return label.textContent?.trim() ?? "";
    parent = parent.parentElement;
  }
  // Check field wrapper with class-based label
  const wrapper = el.closest("[class*='field'], [class*='Field'], [class*='form-group'], [class*='form-item'], [class*='FormItem'], [class*='FormField']");
  if (wrapper) {
    const wrapperLabel = wrapper.querySelector("label, legend, [class*='label'], [class*='Label']");
    if (wrapperLabel && wrapperLabel !== el) {
      const text = wrapperLabel.textContent?.trim() ?? "";
      if (text) return text;
    }
  }
  // Check previous sibling for label text
  const prev = el.previousElementSibling;
  if (prev && ["SPAN", "DIV", "LABEL", "P"].includes(prev.tagName)) {
    const text = prev.textContent?.trim() ?? "";
    if (text && text.length < 80) return text;
  }
  return el.getAttribute("name") ?? "";
}

function classifyField(el: HTMLInputElement | HTMLSelectElement): FieldType {
  if (el instanceof HTMLInputElement && el.type === "file") {
    const nearbyText = getFieldLabel(el).toLowerCase();
    if (/cover/i.test(nearbyText)) return "cover_letter_upload";
    return "resume_upload";
  }
  const label = getFieldLabel(el).toLowerCase();
  const name = (el.getAttribute("name") ?? "").toLowerCase();
  const id = (el.getAttribute("id") ?? "").toLowerCase();
  const combined = `${label} ${name} ${id}`;
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
    if (fieldType === "demographic") continue;
    if (fieldType === "unknown" && !getFieldLabel(el)) continue;
    // Tag element with a stable data attribute so we can re-find it for fill
    const autoId = `aap_f${fields.length}`;
    el.setAttribute("data-aap-id", autoId);
    const label = getFieldLabel(el);
    const labelHash = computeLabelHash(label);
    fields.push({
      fieldId: autoId,
      fieldType,
      label,
      labelHash,
      currentValue: (el as HTMLInputElement).value ?? "",
      suggestedValue: "",
      confidence: 0.9,
    });
  }
  return fields;
}

function detectQuestions(): DetectedQuestion[] {
  const textareas = Array.from(document.querySelectorAll<HTMLTextAreaElement>("textarea"));
  const questions: DetectedQuestion[] = [];
  for (const ta of textareas) {
    const label = getFieldLabel(ta);
    if (!label || label.length < 3) continue;
    let category: QuestionCategory = "custom";
    for (const { category: cat, patterns } of QUESTION_CATEGORY_PATTERNS) {
      if (patterns.some((p) => p.test(label))) {
        category = cat;
        break;
      }
    }
    // Tag textarea with stable data attribute for reliable fill later
    const autoId = `aap_q${questions.length}`;
    ta.setAttribute("data-aap-id", autoId);
    questions.push({
      questionId: autoId,
      questionText: label,
      category,
      fieldType: "textarea",
      maxLength: ta.maxLength > 0 ? ta.maxLength : undefined,
    });
  }
  return questions;
}

function profileValue(fieldType: FieldType, profile: Profile): string {
  const map: Partial<Record<FieldType, string>> = {
    first_name: profile.firstName,
    last_name: profile.lastName,
    full_name: `${profile.firstName} ${profile.lastName}`.trim(),
    email: profile.email,
    phone: profile.phone,
    city: profile.city,
    state: profile.state,
    zip: profile.zip,
    country: profile.country || "United States",
    us_resident: profile.country ? (profile.country.toLowerCase().includes("united states") || profile.country.toLowerCase() === "us" ? "Yes" : "No") : "Yes",
    linkedin: profile.linkedinUrl,
    github: profile.githubUrl,
    portfolio: profile.portfolioUrl,
    website: profile.portfolioUrl,
    degree: profile.degree,
    years_experience: profile.yearsExperience,
    salary: profile.salary,
    sponsorship: profile.sponsorship,
  };
  return map[fieldType] ?? "";
}

function fillDomField(fieldId: string, value: string): void {
  const el =
    document.querySelector<HTMLElement>(`[data-aap-id="${fieldId}"]`) ??
    (document.getElementById(fieldId) as HTMLElement | null) ??
    document.querySelector<HTMLElement>(`[name="${fieldId}"]`);
  if (!el) return;

  // Handle contenteditable divs (Ashby, newer Greenhouse, etc.)
  if (el.getAttribute("contenteditable") === "true" || el.contentEditable === "true") {
    el.focus();
    // Select all existing content and replace
    document.execCommand("selectAll", false);
    document.execCommand("insertText", false, value);
    // Fallback: set innerHTML if execCommand didn't work
    if (!el.textContent?.includes(value.slice(0, 20))) {
      el.textContent = value;
      el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
    }
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return;
  }

  // Handle React-controlled inputs and textareas via native value setter
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  if (el instanceof HTMLTextAreaElement && nativeTextAreaValueSetter) {
    nativeTextAreaValueSetter.call(el, value);
  } else if (el instanceof HTMLInputElement && nativeInputValueSetter) {
    nativeInputValueSetter.call(el, value);
  } else {
    (el as HTMLInputElement).value = value;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function detectPlatform(url: string): string {
  if (/linkedin\.com/.test(url)) return "linkedin";
  if (/greenhouse\.io/.test(url)) return "greenhouse";
  if (/lever\.co/.test(url)) return "lever";
  if (/workday\.com|myworkday\.com/.test(url)) return "workday";
  if (/ashbyhq\.com/.test(url)) return "ashby";
  if (/smartrecruiters\.com/.test(url)) return "smartrecruiters";
  if (/bamboohr\.com/.test(url)) return "bamboohr";
  if (/icims\.com/.test(url)) return "icims";
  if (/taleo\.net/.test(url)) return "taleo";
  if (/indeed\.com/.test(url)) return "indeed";
  return "generic";
}

function scoreColor(score: number): string {
  if (score >= 80) return "#10b981";
  if (score >= 65) return "#f59e0b";
  if (score >= 50) return "#f97316";
  return "#f87171";
}

function companyHue(name: string): number {
  let sum = 0;
  for (let i = 0; i < name.length; i++) sum += name.charCodeAt(i);
  return sum % 360;
}

function truncate(s: string, max: number): string {
  return s.length <= max ? s : s.slice(0, max) + "…";
}

function categoryLabel(cat: QuestionCategory): string {
  const labels: Record<QuestionCategory, string> = {
    cover_letter: "Cover Letter",
    why_company: "Why Us",
    why_hire: "Why You",
    about_yourself: "About",
    strength: "Strength",
    weakness: "Weakness",
    challenge: "Challenge",
    leadership: "Leadership",
    conflict: "Conflict",
    motivation: "Motivation",
    five_years: "5 Years",
    impact: "Impact",
    fit: "Culture Fit",
    sponsorship: "Visa",
    custom: "Custom",
  };
  return labels[cat] ?? "Custom";
}

// ── FloatingPanel class ────────────────────────────────────────────────────

class FloatingPanel {
  private host: HTMLDivElement;
  private shadow: ShadowRoot;
  private isOpen: boolean = false;
  private apiBase: string = "https://autoapply-ai-api.fly.dev/api/v1";
  private clerkUserId: string | null = null;
  private clerkToken: string | null = null;
  private clerkTokenExp: number = 0;
  private providers: Array<{ name: string; api_key: string; model: string }> = [];
  private profile: Profile = {
    firstName: "", lastName: "", email: "", phone: "",
    city: "", state: "", zip: "", country: "United States",
    linkedinUrl: "", githubUrl: "", portfolioUrl: "",
    degree: "", yearsExperience: "", sponsorship: "", salary: "",
  };
  private company: string = "";
  private roleTitle: string = "";
  private jdText: string = "";
  private fields: DetectedField[] = [];
  private questionStates: QuestionState[] = [];
  private atsScore: number | null = null;
  private loadingAts: boolean = false;
  private workHistoryText: string = "";
  private promptTemplates: Record<string, string> = {};
  private categoryModelRoutes: Record<string, string> = {};
  private trackedAppId: string | null = null;

  /** Build auth headers: prefer JWT Bearer, fall back to X-Clerk-User-Id. */
  private authHeaders(extraHeaders?: Record<string, string>): Record<string, string> {
    const tokenValid = this.clerkToken && (this.clerkTokenExp === 0 || Date.now() / 1000 < this.clerkTokenExp - 30);
    const auth: Record<string, string> = tokenValid
      ? { Authorization: `Bearer ${this.clerkToken}` }
      : this.clerkUserId
      ? { "X-Clerk-User-Id": this.clerkUserId }
      : {};
    return { ...auth, ...extraHeaders };
  }

  constructor() {
    this.host = document.createElement("div");
    this.host.id = "__autoapply_host__";
    // display:block is required — all:initial resets display to inline,
    // which breaks the fixed-positioned children inside the shadow DOM.
    this.host.setAttribute(
      "style",
      "all:initial;display:block;position:fixed;inset:0;pointer-events:none;z-index:2147483647;"
    );
    this.shadow = this.host.attachShadow({ mode: "open" });
    document.documentElement.appendChild(this.host);
    this.render();
  }

  async init(): Promise<void> {
    const data = await chrome.storage.local.get(["apiBaseUrl", "clerkUserId", "clerkToken", "clerkTokenExp", "profile", "providerConfigs", "promptTemplates", "categoryModelRoutes"]);
    if (data.apiBaseUrl) this.apiBase = data.apiBaseUrl as string;
    if (data.clerkUserId) this.clerkUserId = data.clerkUserId as string;
    if (data.clerkToken) this.clerkToken = data.clerkToken as string;
    if (data.clerkTokenExp) this.clerkTokenExp = data.clerkTokenExp as number;
    if (data.profile) this.profile = data.profile as Profile;
    if (data.promptTemplates) this.promptTemplates = data.promptTemplates as Record<string, string>;
    if (data.categoryModelRoutes) this.categoryModelRoutes = data.categoryModelRoutes as Record<string, string>;
    if (data.providerConfigs) {
      const RANK: Record<string, number> = { anthropic: 1, openai: 2, gemini: 3, groq: 4, perplexity: 5, kimi: 6 };
      this.providers = Object.entries(data.providerConfigs as Record<string, { enabled: boolean; apiKey: string; model: string }>)
        .filter(([, cfg]) => !!cfg.apiKey)  // enabled = has a key
        .map(([name, cfg]) => ({ name, api_key: cfg.apiKey, model: cfg.model }))
        .sort((a, b) => (RANK[a.name] ?? 50) - (RANK[b.name] ?? 50));
    }

    // Fetch full work history text for LLM context
    try {
      const whResp = await fetch(`${this.apiBase}/work-history/text`, {
        headers: this.authHeaders(),
      });
      if (whResp.ok) {
        const whJson = await whResp.json() as { text?: string };
        if (whJson.text) this.workHistoryText = whJson.text;
      }
    } catch {
      // non-fatal — falls back to empty string; LLM will use JD context only
    }

    this.company = extractCompanyFromPage();
    this.roleTitle = extractRoleFromPage();
    this.jdText = extractJdText();
    this.fields = detectFields();
    this.questionStates = detectQuestions().map((q) => ({
      question: q,
      drafts: [],
      draftProviders: [],
      selectedDraft: 0,
      loading: false,
      loadingProvider: "",
      loadingStartMs: 0,
      error: null,
    }));
    this.render();
    this.loadAtsScore();
    this.observeMutations();

    // SPAs often render the form asynchronously after the initial paint.
    // Retry detection at 1s and 3s so we catch late-rendering fields/questions.
    setTimeout(() => this.redetect(), 1000);
    setTimeout(() => this.redetect(), 3000);

    // Track this application visit (idempotent — safe to call on every page load)
    this.trackApplication();

    // Auto-mark as "applied" when the form is submitted
    this.watchFormSubmission();

    // L4: record category usage, then pre-generate answers for top categories
    this.trackCategoryUsage();
    this.preGenerateTopCategories();
  }

  private async trackApplication(): Promise<void> {
    if (!this.clerkUserId || !this.company) return;
    try {
      const resp = await fetch(`${this.apiBase}/applications/track`, {
        method: "POST",
        headers: this.authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          company_name: this.company,
          role_title: this.roleTitle,
          job_url: window.location.href,
          platform: detectPlatform(window.location.href),
        }),
      });
      if (resp.ok) {
        const json = await resp.json() as { application_id: string };
        this.trackedAppId = json.application_id;
      }
    } catch {
      // non-fatal
    }
  }

  private watchFormSubmission(): void {
    // Listen for form submit events and "Submit Application" button clicks
    const markApplied = () => {
      if (!this.clerkUserId || !this.trackedAppId) return;
      // Mark as "applied" — fire-and-forget, non-blocking
      fetch(`${this.apiBase}/applications/${this.trackedAppId}`, {
        method: "PATCH",
        headers: this.authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ status: "applied" }),
      }).catch(() => {});
    };

    // Form submit event (works for traditional forms)
    document.addEventListener("submit", markApplied, { capture: true });

    // Button click heuristic: "Submit Application" / "Submit" / "Apply" buttons
    document.addEventListener("click", (e) => {
      const btn = (e.target as HTMLElement)?.closest("button, [type=submit], a[role=button]") as HTMLElement | null;
      if (!btn) return;
      const text = btn.textContent?.toLowerCase() ?? "";
      if (/\b(submit application|submit my application|complete application|send application)\b/.test(text)) {
        markApplied();
      }
    }, { capture: true });
  }

  /**
   * L4: Increment usage counter for each detected question category.
   * Stored in chrome.storage.local as { categoryUsage: Record<string, number> }
   */
  private trackCategoryUsage(): void {
    if (this.questionStates.length === 0) return;
    const seen = new Set<string>(this.questionStates.map((s) => s.question.category));
    chrome.storage.local.get("categoryUsage").then((data) => {
      const usage = (data.categoryUsage ?? {}) as Record<string, number>;
      for (const cat of seen) {
        usage[cat] = (usage[cat] ?? 0) + 1;
      }
      chrome.storage.local.set({ categoryUsage: usage }).catch(() => {});
    }).catch(() => {});
  }

  /**
   * L4: Pre-generate answers for questions whose category has been seen >= 2 times before
   * (i.e., the user has encountered this category on a previous page).
   * Limits concurrent pre-generations to 2 at a time to avoid hammering the API.
   */
  private async preGenerateTopCategories(): Promise<void> {
    if (!this.clerkUserId || this.questionStates.length === 0) return;

    const data = await chrome.storage.local.get("categoryUsage").catch(() => ({})) as { categoryUsage?: Record<string, number> };
    const usage = data.categoryUsage ?? {};

    // Find question states that:
    // 1. Have no drafts yet (nothing to pre-gen if already done)
    // 2. Belong to a category the user has encountered before (count >= 2)
    const candidates = this.questionStates
      .map((state, idx) => ({ state, idx, count: usage[state.question.category] ?? 0 }))
      .filter(({ state, count }) => state.drafts.length === 0 && !state.loading && count >= 2)
      .sort((a, b) => b.count - a.count) // highest-frequency first
      .slice(0, 3); // max 3 pre-generated per page load

    if (candidates.length === 0) return;

    // Small delay so the panel renders first — improves perceived perf
    await new Promise<void>((r) => setTimeout(r, 600));

    // Generate in batches of 2 to limit API concurrency
    for (let i = 0; i < candidates.length; i += 2) {
      const batch = candidates.slice(i, i + 2);
      await Promise.allSettled(batch.map(({ idx }) => this.generateAnswer(idx)));
    }
  }

  private async loadAtsScore(): Promise<void> {
    if (!this.clerkUserId || !this.company) return;
    this.loadingAts = true;
    this.render();
    try {
      const fd = new FormData();
      fd.append("company_name", this.company);
      if (this.jdText) fd.append("jd_text", this.jdText);
      const resp = await fetch(`${this.apiBase}/vault/retrieve`, {
        method: "POST",
        headers: this.authHeaders(),
        body: fd,
      });
      if (resp.ok) {
        const json = await resp.json() as { ats_result?: { overallScore?: number } | null };
        if (json.ats_result?.overallScore != null) {
          this.atsScore = json.ats_result.overallScore;
        }
      }
    } catch {
      // non-fatal — panel still shows without score
    } finally {
      this.loadingAts = false;
      this.render();
    }
  }

  private async generateAnswer(stateIndex: number): Promise<void> {
    const state = this.questionStates[stateIndex];
    if (!state) return;
    state.loading = true;
    state.loadingProvider = this.providers.length > 0 ? (this.providers[0]?.name ?? "") : "";
    state.loadingStartMs = Date.now();
    state.error = null;
    this.render();

    // Live elapsed-time ticker — re-renders every second so user sees activity
    const tickerInterval = setInterval(() => {
      if (state.loading) this.render();
    }, 1000);

    try {
      const fd = new FormData();
      fd.append("question_text", state.question.questionText);
      fd.append("question_category", state.question.category);
      fd.append("company_name", this.company);
      fd.append("role_title", this.roleTitle);
      fd.append("jd_text", this.jdText);
      fd.append("work_history_text", this.workHistoryText);
      if (this.providers.length > 0) {
        // L5: model routing — if user has set a preferred provider for this category,
        // rotate it to the front so the API uses it first
        const preferredProviderName = this.categoryModelRoutes[state.question.category];
        let orderedProviders = this.providers;
        if (preferredProviderName) {
          const preferred = this.providers.filter((p) => p.name === preferredProviderName);
          const rest = this.providers.filter((p) => p.name !== preferredProviderName);
          if (preferred.length > 0) orderedProviders = [...preferred, ...rest];
        }
        state.loadingProvider = orderedProviders[0]?.name ?? "";
        fd.append("providers_json", JSON.stringify(orderedProviders));
      }
      if (state.question.maxLength && state.question.maxLength > 0) {
        fd.append("max_length", String(state.question.maxLength));
      }
      const catInstructions = this.promptTemplates[state.question.category] || this.promptTemplates["custom"];
      if (catInstructions) fd.append("category_instructions", catInstructions);
      const resp = await fetch(`${this.apiBase}/vault/generate/answers`, {
        method: "POST",
        headers: this.authHeaders(),
        body: fd,
      });
      if (!resp.ok) throw new Error(`API error ${resp.status}`);
      const json = await resp.json() as { drafts?: string[]; draft_providers?: string[] };
      state.drafts = json.drafts ?? [];
      state.draftProviders = json.draft_providers ?? [];
      state.selectedDraft = 0;
    } catch (e) {
      state.error = e instanceof Error ? e.message : "Generation failed";
    } finally {
      clearInterval(tickerInterval);
      state.loading = false;
      state.loadingProvider = "";
      this.render();
    }
  }

  private async saveAndFill(stateIndex: number, text: string): Promise<void> {
    const state = this.questionStates[stateIndex];
    if (!state) return;
    // Fill DOM field first (immediate UX)
    fillDomField(state.question.questionId, text);
    // Then persist in background (non-blocking)
    if (this.clerkUserId) {
      try {
        const fd = new FormData();
        fd.append("question_text", state.question.questionText);
        fd.append("question_category", state.question.category);
        fd.append("answer_text", text);
        fd.append("company_name", this.company);
        fd.append("role_title", this.roleTitle);
        await fetch(`${this.apiBase}/vault/answers/save`, {
          method: "POST",
          headers: this.authHeaders(),
          body: fd,
        });
      } catch {
        // Ignore save errors — fill already happened
      }
    }
  }

  private fillAll(): void {
    for (const field of this.fields) {
      if (field.fieldType === "resume_upload" || field.fieldType === "cover_letter_upload") continue;
      const value = profileValue(field.fieldType, this.profile);
      if (value) fillDomField(field.fieldId, value);
    }
  }

  toggle(): void {
    this.isOpen = !this.isOpen;
    this.render();
  }

  redetect(): void {
    this.jdText = extractJdText();

    // ── Fields ──────────────────────────────────────────────────────────────
    const newFields = detectFields();
    if (newFields.length > 0) {
      // Dedup against already-tracked fields using composite key (fieldId + labelHash)
      // to avoid re-adding the same field when the panel re-scans a stable form.
      const existingIds = new Set(this.fields.map((f) => f.fieldId + ":" + f.labelHash));
      const dedupedFields = newFields.filter((f) => !existingIds.has(f.fieldId + ":" + f.labelHash));
      // Merge: keep existing tracked fields still in DOM, then add truly new ones
      const stillPresent = this.fields.filter(
        (f) => !!document.querySelector(`[data-aap-id="${f.fieldId}"]`)
      );
      this.fields = [...stillPresent, ...dedupedFields];
    } else if (this.fields.length > 0) {
      // New scan found nothing — check which existing tagged elements are still in the DOM.
      // Keep those; remove only the ones that have genuinely disappeared.
      const stillPresent = this.fields.filter(
        (f) => !!document.querySelector(`[data-aap-id="${f.fieldId}"]`)
      );
      this.fields = stillPresent;
    }

    // ── Questions ────────────────────────────────────────────────────────────
    const newQuestions = detectQuestions();
    // Add new questions not yet tracked
    const existingIds = new Set(this.questionStates.map((s) => s.question.questionId));
    for (const q of newQuestions) {
      if (!existingIds.has(q.questionId)) {
        this.questionStates.push({ question: q, drafts: [], draftProviders: [], selectedDraft: 0, loading: false, loadingProvider: "", loadingStartMs: 0, error: null });
      }
    }
    // Remove only questions whose textarea has actually left the DOM
    this.questionStates = this.questionStates.filter(
      (s) => !!document.querySelector(`[data-aap-id="${s.question.questionId}"]`)
    );

    this.render();
  }

  private observeMutations(): void {
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    const observer = new MutationObserver((mutations) => {
      // Re-append host if SPA framework removed it from <html>
      if (!document.documentElement.contains(this.host)) {
        document.documentElement.appendChild(this.host);
      }
      // Only re-detect when form elements actually appear/disappear (step navigation)
      // This avoids expensive re-renders on every cosmetic DOM update
      const hasFormChange = mutations.some((m) =>
        Array.from(m.addedNodes).concat(Array.from(m.removedNodes)).some((node) => {
          if (!(node instanceof HTMLElement)) return false;
          return (
            node.matches("input, textarea, select, [contenteditable=true]") ||
            !!node.querySelector("input:not([type=hidden]), textarea, select, [contenteditable=true]")
          );
        })
      );
      if (!hasFormChange) return;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      // 800ms gives SPA frameworks enough time to finish rendering the next step
      debounceTimer = setTimeout(() => this.redetect(), 800);
    });
    if (document.body) {
      observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  private css(): string {
    return `
      *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

      /* ── Keyframe Animations ───────────────────────────────────────────── */
      @keyframes shimmer {
        0%   { background-position: -400px 0; }
        100% { background-position: 400px 0; }
      }
      @keyframes pulse-glow {
        0%, 100% { box-shadow: 0 0 6px rgba(139,92,246,0.4), 0 0 14px rgba(99,102,241,0.2); }
        50%       { box-shadow: 0 0 12px rgba(139,92,246,0.7), 0 0 28px rgba(99,102,241,0.4); }
      }
      @keyframes gradient-sweep {
        0%   { background-position: 0% 50%; }
        50%  { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
      }
      @keyframes spin {
        to { transform: rotate(360deg); }
      }
      @keyframes dot-bounce {
        0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
        40%            { transform: scale(1);   opacity: 1;   }
      }
      @keyframes slide-in-right {
        from { transform: translateX(100%); opacity: 0; }
        to   { transform: translateX(0);   opacity: 1; }
      }
      @keyframes fade-up {
        from { transform: translateY(6px); opacity: 0; }
        to   { transform: translateY(0);   opacity: 1; }
      }
      @keyframes bar-grow {
        from { width: 0 !important; }
      }

      /* ── Toggle Tab ────────────────────────────────────────────────────── */
      .toggle-tab {
        position: fixed;
        right: 0;
        top: 50%;
        transform: translateY(-50%);
        width: 42px;
        background: linear-gradient(180deg, #13102b 0%, #0d0d1f 100%);
        border: 1px solid rgba(139,92,246,0.35);
        border-right: none;
        border-radius: 10px 0 0 10px;
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 12px 0;
        gap: 5px;
        cursor: pointer;
        pointer-events: all;
        z-index: 2;
        transition: background 0.2s, border-color 0.2s, box-shadow 0.2s;
        box-shadow: -3px 0 18px rgba(99,102,241,0.18), -1px 0 6px rgba(0,0,0,0.5);
      }
      .toggle-tab:hover {
        background: linear-gradient(180deg, #1a1540 0%, #10102a 100%);
        border-color: rgba(139,92,246,0.65);
        box-shadow: -4px 0 22px rgba(139,92,246,0.3), -1px 0 8px rgba(0,0,0,0.6);
      }
      .tab-logo {
        font-size: 17px;
        line-height: 1;
        filter: drop-shadow(0 0 5px rgba(167,139,250,0.7));
      }
      .tab-label {
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 7.5px;
        font-weight: 800;
        background: linear-gradient(135deg, #a78bfa 0%, #67e8f9 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        text-align: center;
        line-height: 1.25;
        letter-spacing: 0.04em;
        white-space: pre-line;
      }
      .tab-score {
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 9px;
        font-weight: 900;
        text-align: center;
        line-height: 1;
        filter: drop-shadow(0 0 4px currentColor);
      }

      /* ── Main Panel ────────────────────────────────────────────────────── */
      .panel {
        position: fixed;
        right: 0;
        top: 0;
        width: 348px;
        height: 100vh;
        background: linear-gradient(160deg, #0c0c1e 0%, #080814 60%, #0a0a18 100%);
        border-left: 1px solid rgba(99,102,241,0.2);
        transform: translateX(100%);
        transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
        overflow-y: auto;
        overflow-x: hidden;
        display: flex;
        flex-direction: column;
        pointer-events: all;
        z-index: 1;
        font-family: system-ui, -apple-system, sans-serif;
        color: #f1f5f9;
        box-shadow: -6px 0 40px rgba(0,0,0,0.7), -2px 0 0 rgba(99,102,241,0.08);
      }
      .panel.open {
        transform: translateX(0);
        animation: slide-in-right 0.28s cubic-bezier(0.4,0,0.2,1);
      }
      .panel::-webkit-scrollbar { width: 3px; }
      .panel::-webkit-scrollbar-track { background: transparent; }
      .panel::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, #7c3aed, #4f46e5);
        border-radius: 3px;
      }

      /* ── Header ────────────────────────────────────────────────────────── */
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 13px 16px;
        background: linear-gradient(135deg, rgba(20,16,45,0.98) 0%, rgba(12,12,30,0.98) 100%);
        border-bottom: 1px solid rgba(99,102,241,0.18);
        position: sticky;
        top: 0;
        z-index: 10;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
      }
      .header::after {
        content: '';
        position: absolute;
        bottom: 0;
        left: 16px;
        right: 16px;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(139,92,246,0.5), rgba(99,102,241,0.5), transparent);
      }
      .header-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px;
        font-weight: 800;
        background: linear-gradient(90deg, #c4b5fd 0%, #818cf8 50%, #67e8f9 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.02em;
      }
      .header-title span {
        font-size: 17px;
        filter: drop-shadow(0 0 6px rgba(167,139,250,0.8));
        -webkit-text-fill-color: initial;
      }
      .close-btn {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        color: #64748b;
        cursor: pointer;
        font-size: 14px;
        line-height: 1;
        padding: 5px 7px;
        border-radius: 6px;
        pointer-events: all;
        transition: color 0.2s, background 0.2s, border-color 0.2s;
      }
      .close-btn:hover {
        color: #f1f5f9;
        background: rgba(255,255,255,0.09);
        border-color: rgba(139,92,246,0.4);
      }

      /* ── Company Section ───────────────────────────────────────────────── */
      .company-section {
        display: flex;
        align-items: center;
        gap: 11px;
        padding: 13px 16px;
        border-bottom: 1px solid rgba(99,102,241,0.12);
        background: rgba(255,255,255,0.015);
        animation: fade-up 0.3s ease both;
      }
      .company-avatar {
        width: 38px;
        height: 38px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 17px;
        font-weight: 900;
        color: #fff;
        flex-shrink: 0;
        letter-spacing: -0.02em;
        border: 1.5px solid rgba(255,255,255,0.15);
        box-shadow: 0 2px 12px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.1);
        text-shadow: 0 1px 4px rgba(0,0,0,0.4);
      }
      .company-info { flex: 1; min-width: 0; }
      .company-name {
        font-size: 13px;
        font-weight: 700;
        color: #e2e8f0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        letter-spacing: -0.01em;
      }
      .role-name {
        font-size: 11px;
        color: #6b7a99;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-top: 2px;
      }
      .score-chip {
        flex-shrink: 0;
        font-size: 12px;
        font-weight: 900;
        padding: 4px 9px;
        border-radius: 20px;
        border: 1.5px solid;
        background: rgba(0,0,0,0.3);
        line-height: 1.4;
        backdrop-filter: blur(4px);
        letter-spacing: -0.01em;
        text-shadow: 0 0 8px currentColor;
        animation: pulse-glow 3s ease-in-out infinite;
      }

      /* ── Score Bar ─────────────────────────────────────────────────────── */
      .score-bar-wrap {
        padding: 10px 16px 2px;
      }
      .score-bar-label {
        display: flex;
        justify-content: space-between;
        font-size: 10px;
        font-weight: 600;
        color: #4b5878;
        margin-bottom: 6px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }
      .score-bar-track {
        height: 5px;
        background: rgba(255,255,255,0.06);
        border-radius: 3px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,0.04);
      }
      .score-bar-fill {
        height: 100%;
        border-radius: 3px;
        transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
        animation: bar-grow 0.9s cubic-bezier(0.4,0,0.2,1) both;
        box-shadow: 0 0 8px currentColor;
        position: relative;
      }
      .score-bar-fill::after {
        content: '';
        position: absolute;
        top: 0; right: 0;
        width: 20px; height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.35));
        border-radius: 3px;
      }

      /* ── CTA Button ────────────────────────────────────────────────────── */
      .cta-section {
        padding: 12px 16px 0;
      }
      .cta-btn {
        width: 100%;
        padding: 11px 16px;
        background: linear-gradient(120deg, #7c3aed 0%, #6d28d9 25%, #4f46e5 60%, #06b6d4 100%);
        background-size: 250% 250%;
        border: none;
        border-radius: 10px;
        color: #fff;
        font-size: 13px;
        font-weight: 800;
        cursor: pointer;
        pointer-events: all;
        letter-spacing: -0.01em;
        transition: transform 0.15s, box-shadow 0.2s;
        animation: gradient-sweep 4s ease infinite;
        box-shadow: 0 2px 16px rgba(109,40,217,0.45), 0 1px 4px rgba(0,0,0,0.3);
        position: relative;
        overflow: hidden;
      }
      .cta-btn::before {
        content: '';
        position: absolute;
        top: 0; left: -100%;
        width: 60%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.18), transparent);
        transition: left 0.5s ease;
      }
      .cta-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 24px rgba(109,40,217,0.6), 0 2px 8px rgba(0,0,0,0.4);
      }
      .cta-btn:hover::before { left: 140%; }
      .cta-btn:active { transform: translateY(0); box-shadow: 0 1px 8px rgba(109,40,217,0.4); }

      /* ── Section Headings ──────────────────────────────────────────────── */
      .section {
        padding: 12px 16px 0;
      }
      .section-heading {
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 0.1em;
        color: #3b4a6b;
        text-transform: uppercase;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .section-heading::after {
        content: '';
        flex: 1;
        height: 1px;
        background: linear-gradient(90deg, rgba(99,102,241,0.2), transparent);
      }

      /* ── Field Rows ────────────────────────────────────────────────────── */
      .field-row {
        display: flex;
        align-items: center;
        gap: 9px;
        padding: 8px 11px;
        background: rgba(255,255,255,0.025);
        border: 1px solid rgba(99,102,241,0.12);
        border-radius: 9px;
        margin-bottom: 5px;
        transition: background 0.2s, border-color 0.2s, box-shadow 0.2s;
        animation: fade-up 0.25s ease both;
        backdrop-filter: blur(4px);
      }
      .field-row:hover {
        background: rgba(99,102,241,0.07);
        border-color: rgba(99,102,241,0.28);
        box-shadow: 0 0 0 1px rgba(99,102,241,0.1), 0 2px 10px rgba(0,0,0,0.2);
      }
      .field-info { flex: 1; min-width: 0; }
      .field-label {
        font-size: 11px;
        font-weight: 500;
        color: #94a3b8;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .field-value {
        font-size: 11px;
        color: #3d4f72;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-top: 1px;
      }
      .fill-btn, .attach-btn {
        flex-shrink: 0;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 700;
        cursor: pointer;
        pointer-events: all;
        border: 1px solid rgba(124,58,237,0.5);
        background: rgba(124,58,237,0.1);
        color: #a78bfa;
        transition: background 0.2s, border-color 0.2s, box-shadow 0.2s, color 0.2s;
        white-space: nowrap;
        letter-spacing: -0.01em;
      }
      .fill-btn:hover, .attach-btn:hover {
        background: rgba(124,58,237,0.22);
        border-color: rgba(139,92,246,0.7);
        color: #c4b5fd;
        box-shadow: 0 0 10px rgba(124,58,237,0.25);
      }

      /* ── Question Cards ────────────────────────────────────────────────── */
      .question-card {
        background: rgba(255,255,255,0.028);
        border: 1px solid rgba(99,102,241,0.15);
        border-radius: 11px;
        padding: 12px;
        margin-bottom: 7px;
        transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
        animation: fade-up 0.28s ease both;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        position: relative;
        overflow: hidden;
      }
      .question-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(139,92,246,0.4), rgba(99,102,241,0.3), transparent);
      }
      .question-card:hover {
        background: rgba(99,102,241,0.05);
        border-color: rgba(99,102,241,0.3);
        box-shadow: 0 0 0 1px rgba(99,102,241,0.1), 0 4px 20px rgba(0,0,0,0.25);
      }
      .question-text {
        font-size: 12px;
        color: #c8d4e8;
        line-height: 1.5;
        margin-bottom: 8px;
        font-weight: 400;
      }
      .question-meta {
        display: flex;
        gap: 5px;
        flex-wrap: wrap;
        margin-bottom: 10px;
      }

      /* ── Pills ─────────────────────────────────────────────────────────── */
      .pill {
        font-size: 9px;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 20px;
        background: rgba(255,255,255,0.05);
        color: #475569;
        border: 1px solid rgba(255,255,255,0.07);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        backdrop-filter: blur(4px);
      }
      .pill-cat {
        color: #a78bfa;
        border: 1px solid rgba(139,92,246,0.3);
        background: rgba(139,92,246,0.1);
        text-shadow: 0 0 8px rgba(167,139,250,0.5);
      }

      /* ── Generate Button ───────────────────────────────────────────────── */
      .generate-btn {
        width: 100%;
        padding: 8px;
        background: linear-gradient(120deg, rgba(109,40,217,0.15) 0%, rgba(79,70,229,0.15) 100%);
        border: 1px solid rgba(109,40,217,0.4);
        border-radius: 8px;
        color: #a78bfa;
        font-size: 11px;
        font-weight: 700;
        cursor: pointer;
        pointer-events: all;
        transition: background 0.2s, border-color 0.2s, box-shadow 0.2s, color 0.2s;
        letter-spacing: -0.01em;
        position: relative;
        overflow: hidden;
      }
      .generate-btn::before {
        content: '';
        position: absolute;
        top: 0; left: -100%;
        width: 60%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(167,139,250,0.12), transparent);
        transition: left 0.4s ease;
      }
      .generate-btn:hover {
        background: linear-gradient(120deg, rgba(109,40,217,0.28) 0%, rgba(79,70,229,0.25) 100%);
        border-color: rgba(139,92,246,0.65);
        color: #c4b5fd;
        box-shadow: 0 0 16px rgba(109,40,217,0.3), inset 0 0 12px rgba(139,92,246,0.06);
      }
      .generate-btn:hover::before { left: 140%; }
      .generate-btn:disabled {
        opacity: 0.4;
        cursor: not-allowed;
        box-shadow: none;
      }

      /* ── Draft Controls ────────────────────────────────────────────────── */
      .copy-draft-btn {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.1);
        color: #64748b;
        cursor: pointer;
        padding: 5px 8px;
        border-radius: 6px;
        font-size: 13px;
        line-height: 1;
        transition: color 0.2s, border-color 0.2s, background 0.2s, box-shadow 0.2s;
        pointer-events: all;
      }
      .copy-draft-btn:hover {
        color: #a78bfa;
        border-color: rgba(124,58,237,0.5);
        background: rgba(124,58,237,0.1);
        box-shadow: 0 0 8px rgba(124,58,237,0.2);
      }
      .regen-btn {
        background: none;
        border: none;
        color: #3b4a6b;
        cursor: pointer;
        pointer-events: all;
        font-size: 14px;
        padding: 3px 5px;
        border-radius: 5px;
        transition: color 0.2s, background 0.2s;
      }
      .regen-btn:hover {
        color: #a78bfa;
        background: rgba(124,58,237,0.1);
      }
      .draft-tabs {
        display: flex;
        gap: 4px;
        margin-bottom: 8px;
      }
      .draft-tab {
        flex: 1;
        padding: 5px 4px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 6px;
        color: #475569;
        font-size: 10px;
        font-weight: 700;
        cursor: pointer;
        pointer-events: all;
        text-align: center;
        transition: all 0.2s;
        letter-spacing: -0.01em;
      }
      .draft-tab.active {
        background: linear-gradient(135deg, rgba(109,40,217,0.3) 0%, rgba(79,70,229,0.25) 100%);
        border-color: rgba(139,92,246,0.5);
        color: #c4b5fd;
        box-shadow: 0 0 10px rgba(109,40,217,0.2);
        text-shadow: 0 0 6px rgba(196,181,253,0.5);
      }
      .draft-text {
        font-size: 11px;
        color: #94a3b8;
        line-height: 1.55;
        background: rgba(0,0,0,0.3);
        border: 1px solid rgba(99,102,241,0.12);
        border-radius: 7px;
        padding: 8px 10px;
        margin-bottom: 7px;
        max-height: 105px;
        overflow-y: auto;
        white-space: pre-wrap;
        backdrop-filter: blur(4px);
        transition: border-color 0.2s;
      }
      .draft-text:hover {
        border-color: rgba(99,102,241,0.25);
      }
      .draft-text::-webkit-scrollbar { width: 3px; }
      .draft-text::-webkit-scrollbar-track { background: transparent; }
      .draft-text::-webkit-scrollbar-thumb {
        background: rgba(99,102,241,0.3);
        border-radius: 2px;
      }
      .draft-actions {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      /* ── Fill Answer Button ────────────────────────────────────────────── */
      .fill-answer-btn {
        flex: 1;
        padding: 7px;
        background: linear-gradient(120deg, #7c3aed 0%, #6d28d9 40%, #4f46e5 100%);
        background-size: 200% 200%;
        border: none;
        border-radius: 7px;
        color: #fff;
        font-size: 11px;
        font-weight: 800;
        cursor: pointer;
        pointer-events: all;
        transition: transform 0.15s, box-shadow 0.2s;
        animation: gradient-sweep 3s ease infinite;
        box-shadow: 0 2px 10px rgba(109,40,217,0.4);
        letter-spacing: -0.01em;
        position: relative;
        overflow: hidden;
      }
      .fill-answer-btn::before {
        content: '';
        position: absolute;
        top: 0; left: -100%;
        width: 60%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
        transition: left 0.4s ease;
      }
      .fill-answer-btn:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 18px rgba(109,40,217,0.55);
      }
      .fill-answer-btn:hover::before { left: 140%; }
      .fill-answer-btn:active { transform: translateY(0); }

      /* ── Error & Loading States ────────────────────────────────────────── */
      .error-text {
        font-size: 10px;
        color: #f87171;
        margin-top: 5px;
        padding: 4px 8px;
        background: rgba(248,113,113,0.08);
        border: 1px solid rgba(248,113,113,0.2);
        border-radius: 5px;
        line-height: 1.4;
      }
      .loading-text {
        font-size: 11px;
        color: #4b5878;
        text-align: center;
        padding: 8px 0;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        letter-spacing: 0.02em;
      }
      .loading-text::before,
      .loading-text::after {
        content: '●';
        font-size: 6px;
        animation: dot-bounce 1.4s ease-in-out infinite both;
      }
      .loading-text::before { animation-delay: 0s; color: #7c3aed; }
      .loading-text::after  { animation-delay: 0.28s; color: #4f46e5; }
      .provider-badge {
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        padding: 1px 6px;
        border-radius: 99px;
        background: rgba(124,58,237,0.2);
        border: 1px solid rgba(124,58,237,0.4);
        color: #a78bfa;
        margin-left: 2px;
      }
      .elapsed-time {
        font-size: 9px;
        color: #475569;
        margin-left: 2px;
        font-variant-numeric: tabular-nums;
      }
      .loading-spinner-wrap {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 10px 0;
      }
      .loading-spinner-wrap::before {
        content: '';
        width: 18px;
        height: 18px;
        border: 2px solid rgba(99,102,241,0.2);
        border-top-color: #7c3aed;
        border-radius: 50%;
        animation: spin 0.75s linear infinite;
        display: block;
      }

      /* ── Footer ────────────────────────────────────────────────────────── */
      .footer {
        margin-top: auto;
        padding: 12px 16px 16px;
        border-top: 1px solid rgba(99,102,241,0.1);
        background: linear-gradient(0deg, rgba(7,7,18,0.9) 0%, transparent 100%);
      }
      .auth-warn {
        font-size: 10px;
        color: #fbbf24;
        background: rgba(251,191,36,0.07);
        border: 1px solid rgba(251,191,36,0.2);
        border-radius: 8px;
        padding: 8px 11px;
        line-height: 1.45;
        backdrop-filter: blur(4px);
      }
      .footer-brand {
        font-size: 9.5px;
        background: linear-gradient(90deg, rgba(99,102,241,0.25), rgba(139,92,246,0.35), rgba(99,102,241,0.25));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        text-align: center;
        margin-top: 8px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        font-weight: 700;
      }
    `;
  }

  private render(): void {
    const { isOpen, company, roleTitle, atsScore, loadingAts, fields, questionStates, clerkUserId } = this;
    const hue = companyHue(company || "A");
    const companyInitial = (company || "?").charAt(0).toUpperCase();
    const fillableCount = fields.filter(
      (f) => f.fieldType !== "resume_upload" && f.fieldType !== "cover_letter_upload"
    ).length;

    const scoreChipHtml =
      atsScore !== null
        ? `<div class="score-chip" style="color:${scoreColor(atsScore)};border-color:${scoreColor(atsScore)};">${atsScore}</div>`
        : loadingAts
        ? `<div class="score-chip" style="color:#475569;border-color:#1f1f38;font-size:10px;">…</div>`
        : "";

    const tabScoreHtml =
      atsScore !== null
        ? `<div class="tab-score" style="color:${scoreColor(atsScore)};">${atsScore}</div>`
        : "";

    const scoreBarHtml =
      atsScore !== null
        ? `<div class="score-bar-wrap">
            <div class="score-bar-label"><span>ATS Match</span><span style="color:${scoreColor(atsScore)}">${atsScore}%</span></div>
            <div class="score-bar-track">
              <div class="score-bar-fill" style="width:${atsScore}%;background:${scoreColor(atsScore)};"></div>
            </div>
           </div>`
        : "";

    const ctaHtml =
      fillableCount > 0
        ? `<div class="cta-section">
            <button class="cta-btn" id="__aap_autofill__">&#9889; Autofill ${fillableCount} field${fillableCount !== 1 ? "s" : ""}</button>
           </div>`
        : "";

    const fieldsHtml =
      fields.length > 0
        ? `<div class="section">
            <div class="section-heading">Form Fields ${fields.length}</div>
            ${fields
              .map((f, i) => {
                const isFile = f.fieldType === "resume_upload" || f.fieldType === "cover_letter_upload";
                const suggested = isFile ? "" : (profileValue(f.fieldType, this.profile) || "—");
                const btn = isFile
                  ? `<button class="attach-btn" data-field-idx="${i}">Attach</button>`
                  : `<button class="fill-btn" data-field-idx="${i}">Fill</button>`;
                return `<div class="field-row">
                  <div class="field-info">
                    <div class="field-label">${truncate(f.label || f.fieldType.replace(/_/g, " "), 36)}</div>
                    ${!isFile ? `<div class="field-value">${truncate(suggested, 30)}</div>` : ""}
                  </div>
                  ${btn}
                </div>`;
              })
              .join("")}
           </div>`
        : "";

    const questionsHtml =
      questionStates.length > 0
        ? `<div class="section">
            <div class="section-heading">Questions ${questionStates.length}</div>
            ${questionStates
              .map((state, qi) => {
                const q = state.question;
                const hasDrafts = state.drafts.length > 0;
                const selectedText = state.drafts[state.selectedDraft] ?? "";

                const draftTabsHtml = hasDrafts
                  ? `<div class="draft-tabs">
                      ${state.drafts
                        .map((_, di) => {
                          const provName = state.draftProviders[di];
                          const label = provName
                            ? provName.charAt(0).toUpperCase() + provName.slice(1)
                            : `Draft ${di + 1}`;
                          return `<button class="draft-tab ${di === state.selectedDraft ? "active" : ""}" data-q-idx="${qi}" data-d-idx="${di}">${label}</button>`;
                        })
                        .join("")}
                     </div>
                     <div class="draft-text">${selectedText.replace(/</g, "&lt;")}</div>
                     <div class="draft-actions">
                       <button class="fill-answer-btn" data-q-idx="${qi}" data-draft-text="${encodeURIComponent(selectedText)}">Fill Answer &#8595;</button>
                       <button class="copy-draft-btn" data-q-idx="${qi}" data-draft-text="${encodeURIComponent(selectedText)}" title="Copy to clipboard">&#9112;</button>
                       <button class="regen-btn" title="Regenerate" data-q-idx="${qi}" id="__aap_regen_${qi}__">&#8635;</button>
                     </div>`
                  : state.loading
                  ? (() => {
                      const elapsedSec = state.loadingStartMs ? Math.floor((Date.now() - state.loadingStartMs) / 1000) : 0;
                      const providerBadge = state.loadingProvider
                        ? `<span class="provider-badge">${state.loadingProvider}</span>`
                        : "";
                      const elapsed = elapsedSec > 0 ? `<span class="elapsed-time">${elapsedSec}s</span>` : "";
                      return `<div class="loading-text">Generating… ${providerBadge}${elapsed}</div>`;
                    })()
                  : `<button class="generate-btn" data-q-idx="${qi}" ${state.loading ? "disabled" : ""}>&#10022; Generate Answer</button>`;

                const errorHtml = state.error
                  ? `<div class="error-text">${state.error}</div>`
                  : "";

                return `<div class="question-card">
                  <div class="question-text">${truncate(q.questionText, 120).replace(/</g, "&lt;")}</div>
                  <div class="question-meta">
                    <span class="pill pill-cat">${categoryLabel(q.category)}</span>
                    ${q.maxLength ? `<span class="pill">${q.maxLength} chars</span>` : ""}
                  </div>
                  ${draftTabsHtml}
                  ${errorHtml}
                </div>`;
              })
              .join("")}
           </div>`
        : "";

    const footerHtml = `<div class="footer">
      ${
        !clerkUserId
          ? `<div class="auth-warn">&#9888; Sign in via the extension options page to enable AI features (answer generation, ATS scoring).</div>`
          : ""
      }
      <div class="footer-brand">AutoApply AI</div>
    </div>`;

    this.shadow.innerHTML = `<style>${this.css()}</style>
      <div class="toggle-tab" id="__aap_toggle__">
        <div class="tab-logo">&#9889;</div>
        <div class="tab-label">AUTO\nAPPLY</div>
        ${tabScoreHtml}
      </div>
      <div class="panel ${isOpen ? "open" : ""}" id="__aap_panel__">
        <div class="header">
          <div class="header-title"><span>&#9889;</span> AutoApply AI</div>
          <button class="close-btn" id="__aap_close__">&#x2715;</button>
        </div>
        <div class="company-section">
          <div class="company-avatar" style="background:hsl(${hue},55%,35%);">${companyInitial}</div>
          <div class="company-info">
            <div class="company-name">${company || "Detecting…"}</div>
            <div class="role-name">${truncate(roleTitle, 52)}</div>
          </div>
          ${scoreChipHtml}
        </div>
        ${scoreBarHtml}
        ${ctaHtml}
        ${fieldsHtml}
        ${questionsHtml}
        ${footerHtml}
      </div>`;

    this.wireEvents();
  }

  private wireEvents(): void {
    const toggle = this.shadow.getElementById("__aap_toggle__");
    const close = this.shadow.getElementById("__aap_close__");
    const autofill = this.shadow.getElementById("__aap_autofill__");

    toggle?.addEventListener("click", () => this.toggle());
    close?.addEventListener("click", () => this.toggle());
    autofill?.addEventListener("click", () => this.fillAll());

    // Fill individual field buttons
    this.shadow.querySelectorAll<HTMLButtonElement>(".fill-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.fieldIdx ?? "0", 10);
        const field = this.fields[idx];
        if (!field) return;
        const value = profileValue(field.fieldType, this.profile);
        if (value) fillDomField(field.fieldId, value);
      });
    });

    // Attach resume buttons — open a local file picker then transfer the file via blob URL
    this.shadow.querySelectorAll<HTMLButtonElement>(".attach-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.fieldIdx ?? "0", 10);
        const field = this.fields[idx];
        if (!field) return;

        // Create a hidden file input to open the OS file picker
        const picker = document.createElement("input");
        picker.type = "file";
        picker.accept = ".pdf,.docx,.doc";
        picker.style.display = "none";
        document.body.appendChild(picker);

        picker.addEventListener("change", () => {
          const file = picker.files?.[0];
          if (!file) { picker.remove(); return; }

          // Create an object URL so detector.ts can fetch the bytes
          const blobUrl = URL.createObjectURL(file);
          chrome.runtime.sendMessage({
            type: "ATTACH_RESUME",
            payload: { fieldId: field.fieldId, pdfUrl: blobUrl },
          });

          // Revoke after a short delay
          setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
          picker.remove();
          btn.textContent = "✓ Attached";
          setTimeout(() => { btn.textContent = "Attach"; }, 3000);
        });

        picker.click();
      });
    });

    // Generate answer buttons
    this.shadow.querySelectorAll<HTMLButtonElement>(".generate-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const qi = parseInt(btn.dataset.qIdx ?? "0", 10);
        void this.generateAnswer(qi);
      });
    });

    // Draft tab buttons
    this.shadow.querySelectorAll<HTMLButtonElement>(".draft-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const qi = parseInt(btn.dataset.qIdx ?? "0", 10);
        const di = parseInt(btn.dataset.dIdx ?? "0", 10);
        const state = this.questionStates[qi];
        if (state) {
          state.selectedDraft = di;
          this.render();
        }
      });
    });

    // Fill answer buttons
    this.shadow.querySelectorAll<HTMLButtonElement>(".fill-answer-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const qi = parseInt(btn.dataset.qIdx ?? "0", 10);
        const encoded = btn.dataset.draftText ?? "";
        const text = decodeURIComponent(encoded);
        void this.saveAndFill(qi, text);
      });
    });

    // Copy draft buttons
    this.shadow.querySelectorAll<HTMLButtonElement>(".copy-draft-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const encoded = btn.dataset.draftText ?? "";
        const text = decodeURIComponent(encoded);
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
          const orig = btn.innerHTML;
          btn.innerHTML = "&#10003;"; // checkmark
          btn.style.color = "#22c55e";
          setTimeout(() => {
            btn.innerHTML = orig;
            btn.style.color = "";
          }, 1500);
        }).catch(() => {
          // Fallback for older browser contexts
          const ta = document.createElement("textarea");
          ta.value = text;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        });
      });
    });

    // Regenerate buttons
    this.shadow.querySelectorAll<HTMLButtonElement>(".regen-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const qi = parseInt(btn.dataset.qIdx ?? "0", 10);
        const state = this.questionStates[qi];
        if (state) {
          state.drafts = [];
          state.selectedDraft = 0;
          void this.generateAnswer(qi);
        }
      });
    });
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────────────

let panelInstance: FloatingPanel | null = null;

function bootstrap() {
  if (!isJobPage()) return;
  if (document.getElementById("__autoapply_host__")) return;
  panelInstance = new FloatingPanel();
  void panelInstance.init();
  // P2: platform-specific autofill scripts
  initLinkedInEasyApply();
  initIndeedApply();
  initWorkdayApply();
  initAshbyApply();
  initSmartRecruitersApply();
  initLeverApply();
  initICIMSApply();
  initTaleoApply();
  initGreenhouseApply();
  initBambooHRApply();
  initJobviteApply();
}

// Run after DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrap);
} else {
  bootstrap();
}

// SPA navigation support
const _origPushState = history.pushState.bind(history);
history.pushState = function (...args: Parameters<typeof history.pushState>) {
  _origPushState(...args);
  setTimeout(() => {
    if (!panelInstance && isJobPage()) {
      bootstrap();
    } else if (panelInstance) {
      panelInstance.redetect();
    }
  }, 800);
};

window.addEventListener("popstate", () => {
  setTimeout(() => {
    if (!panelInstance && isJobPage()) {
      bootstrap();
    } else if (panelInstance) {
      panelInstance.redetect();
    }
  }, 800);
});

export {};
