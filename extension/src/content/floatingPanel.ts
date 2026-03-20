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
  draftSources?: Array<{ source: "vault" | "llm"; similarityScore?: number }>;
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
  private _preAutoFillValues = new Map<string, string>();
  private showAutoFillBanner = false;
  private coverLetter: string = "";
  private coverLetterSource: "vault" | "generated" | "" = "";
  private _iframeMap = new Map<string, HTMLIFrameElement>();

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
    void this.prefetchCoverLetter();
    this.observeMutations();
    this.attachSPAResizeObserver();

    // IframeFieldBridge: listen for field scan results from same-origin iframes
    window.addEventListener("message", (e: MessageEvent) => {
      if (e.data?.type === "AAP_FIELDS_RESULT" && Array.isArray(e.data.fields)) {
        const iframeFields = e.data.fields as import("../shared/types").DetectedField[];
        // Find the source iframe
        const sourceFrame = Array.from(document.querySelectorAll("iframe")).find(
          (f) => f.contentWindow === e.source
        ) as HTMLIFrameElement | undefined;
        if (!sourceFrame) return;
        // Merge with dedup (fieldId + labelHash composite from #57)
        const existingKeys = new Set(this.fields.map((f) => f.fieldId + ":" + f.labelHash));
        const newIframeFields = iframeFields.filter((f) => !existingKeys.has(f.fieldId + ":" + f.labelHash));
        for (const f of newIframeFields) {
          this._iframeMap.set(f.fieldId, sourceFrame);
        }
        if (newIframeFields.length > 0) {
          this.fields = [...this.fields, ...newIframeFields];
          this.render();
        }
      }
    });

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

    // Background sync profile from backend — non-blocking, silent fail
    this.syncProfileFromBackend().catch(() => {});
  }

  private async syncProfileFromBackend(): Promise<void> {
    if (!this.clerkUserId && !this.clerkToken) return; // not authenticated

    try {
      const resp = await fetch(`${this.apiBase}/auth/me`, {
        headers: this.authHeaders(),
      });
      if (!resp.ok) return;

      const remote = await resp.json() as {
        first_name?: string | null;
        last_name?: string | null;
        phone?: string | null;
        city?: string | null;
        state?: string | null;
        zip_code?: string | null;
        country?: string | null;
        linkedin_url?: string | null;
        github_url?: string | null;
        portfolio_url?: string | null;
        degree?: string | null;
        years_experience?: string | null;
        salary?: string | null;
        sponsorship?: string | null;
      };

      const merged: Partial<Profile> = { ...this.profile };
      if (remote.first_name) merged.firstName = remote.first_name;
      if (remote.last_name) merged.lastName = remote.last_name;
      if (remote.phone) merged.phone = remote.phone;
      if (remote.city) merged.city = remote.city;
      if (remote.state) merged.state = remote.state;
      if (remote.zip_code) merged.zip = remote.zip_code;
      if (remote.country) merged.country = remote.country;
      if (remote.linkedin_url) merged.linkedinUrl = remote.linkedin_url;
      if (remote.github_url) merged.githubUrl = remote.github_url;
      if (remote.portfolio_url) merged.portfolioUrl = remote.portfolio_url;
      if (remote.degree) merged.degree = remote.degree;
      if (remote.years_experience) merged.yearsExperience = remote.years_experience;
      if (remote.salary) merged.salary = remote.salary;
      if (remote.sponsorship) merged.sponsorship = remote.sponsorship;

      this.profile = merged as Profile;
      await chrome.storage.local.set({ profile: merged });
    } catch {
      // silent fail — content script operates offline-first
    }
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
      .filter(({ state, count }) => state.drafts.length < 2 && !state.loading && count >= 2)
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
          this.maybeAutoFill();
        }
      }
    } catch {
      // non-fatal — panel still shows without score
    } finally {
      this.loadingAts = false;
      this.render();
    }
  }

  private async prefetchCoverLetter(): Promise<void> {
    if (!this.company || !this.clerkUserId) return;
    // Idempotency guard — don't re-fetch if already done for this URL
    const urlHash = btoa(window.location.href).slice(0, 16);
    const guardKey = `aap_cl_prefetched_${urlHash}`;
    if (sessionStorage.getItem(guardKey)) return;
    sessionStorage.setItem(guardKey, "1");
    try {
      const params = new URLSearchParams({ company: this.company, limit: "1" });
      const resp = await fetch(`${this.apiBase}/vault/cover-letters?${params}`, {
        headers: this.authHeaders(),
      });
      if (!resp.ok) return;
      const json = await resp.json() as { items?: Array<{ answer_text: string }> };
      const items = json.items ?? [];
      if (items.length > 0) {
        this.coverLetter = items[0].answer_text;
        this.coverLetterSource = "vault";
        this.render();
        return;
      }
      // No saved letter — queue background generation if JD text available
      if (this.jdText) {
        void this.generateCoverLetterBackground();
      }
    } catch {
      // non-fatal
    }
  }

  private async generateCoverLetterBackground(): Promise<void> {
    // Only generate if no letter yet
    if (this.coverLetter) return;
    try {
      const fd = new FormData();
      fd.append("company_name", this.company);
      if (this.roleTitle) fd.append("role_title", this.roleTitle);
      if (this.jdText) fd.append("jd_text", this.jdText);
      fd.append("tone", "professional");
      fd.append("word_limit", "400");
      const resp = await fetch(`${this.apiBase}/vault/generate/cover-letter`, {
        method: "POST",
        headers: this.authHeaders(),
        body: fd,
      });
      if (!resp.ok) return;
      const json = await resp.json() as { cover_letter?: string };
      if (json.cover_letter) {
        this.coverLetter = json.cover_letter;
        this.coverLetterSource = "generated";
        this.render();
      }
    } catch {
      // non-fatal
    }
  }

  private maybeAutoFill(): void {
    if (this.atsScore === null || this.atsScore < 0.75) return;
    if (this.fields.length === 0) return;
    const dismissKey = `aap_autofill_dismissed_${this.company.toLowerCase().replace(/\s+/g, "_")}`;
    if (sessionStorage.getItem(dismissKey)) return;
    // Snapshot current DOM values for Undo
    this._preAutoFillValues.clear();
    for (const field of this.fields) {
      const el = document.querySelector(`[data-aap-id="${field.fieldId}"]`) as HTMLInputElement | HTMLTextAreaElement | null;
      if (el) this._preAutoFillValues.set(field.fieldId, (el as HTMLInputElement).value ?? "");
    }
    this.fillAll();
    this.showAutoFillBanner = true;
    this.render();
  }

  private undoAutoFill(): void {
    for (const [fieldId, value] of this._preAutoFillValues) {
      this.fillFieldSmart(fieldId, value);
    }
    this.showAutoFillBanner = false;
    this.render();
  }

  private async fetchVaultAnswers(questionText: string, category: string, stateIndex: number): Promise<void> {
    const state = this.questionStates[stateIndex];
    if (!state || state.drafts.length > 0) return; // skip if already has drafts
    if (!this.clerkUserId) return;
    try {
      const params = new URLSearchParams({ question_text: questionText, question_category: category, top_k: "3" });
      const resp = await fetch(`${this.apiBase}/vault/answers/similar?${params}`, {
        headers: this.authHeaders(),
      });
      if (!resp.ok) return;
      const json = await resp.json() as { answers?: Array<{ answer_text: string; similarity_score: number; reward_score: number }> };
      const vaultDrafts = (json.answers ?? [])
        .filter(a => a.similarity_score >= 0.25)
        .map(a => ({ text: a.answer_text, source: "vault" as const, similarityScore: a.similarity_score }));
      if (vaultDrafts.length === 0) return;
      // Re-check index is still valid (page may have navigated)
      const currentState = this.questionStates[stateIndex];
      if (!currentState || currentState.drafts.length > 0) return;
      currentState.drafts = vaultDrafts.map(d => d.text);
      currentState.draftSources = vaultDrafts.map(d => ({ source: d.source, similarityScore: d.similarityScore }));
      this.render();
    } catch {
      // non-fatal — fall back to LLM generation
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
      if (value) this.fillFieldSmart(field.fieldId, value);
    }
  }

  /** Fill a field — routes to iframe postMessage if the field came from a same-origin iframe. */
  private fillFieldSmart(fieldId: string, value: string): void {
    const sourceIframe = this._iframeMap.get(fieldId);
    if (sourceIframe) {
      sourceIframe.contentWindow?.postMessage({ type: "AAP_FILL_FIELD", fieldId, value }, "*");
    } else {
      fillDomField(fieldId, value);
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
        // Fire vault recall in background — do not await (non-blocking)
        void this.fetchVaultAnswers(q.questionText, q.category, this.questionStates.length - 1);
      }
    }
    // Remove only questions whose textarea has actually left the DOM
    this.questionStates = this.questionStates.filter(
      (s) => !!document.querySelector(`[data-aap-id="${s.question.questionId}"]`)
    );

    this.scanIframes();
    this.render();
  }

  private scanIframes(): void {
    const iframes = Array.from(document.querySelectorAll("iframe")) as HTMLIFrameElement[];
    for (const iframe of iframes) {
      try {
        // Test same-origin access
        void iframe.contentWindow?.location.href;
        iframe.contentWindow?.postMessage({ type: "AAP_SCAN_FIELDS" }, "*");
      } catch {
        // Cross-origin — skip silently
      }
    }
  }

  private attachSPAResizeObserver(): void {
    const SPA_SELECTORS = [
      ".app-container", "main",
      '[data-qa="job-container"]', ".form-wrapper",
      "[class*=step]", "[class*=wizard]",
    ];
    let spaResizeTimer: ReturnType<typeof setTimeout> | null = null;
    const prevHeights = new Map<Element, number>();
    const observer = new ResizeObserver((entries) => {
      let significantChange = false;
      for (const entry of entries) {
        const newH = entry.contentRect.height;
        const oldH = prevHeights.get(entry.target) ?? newH;
        prevHeights.set(entry.target, newH);
        if (Math.abs(newH - oldH) > 50) significantChange = true;
      }
      if (!significantChange) return;
      if (spaResizeTimer !== null) clearTimeout(spaResizeTimer);
      spaResizeTimer = setTimeout(() => this.redetect(), 400);
    });
    for (const sel of SPA_SELECTORS) {
      document.querySelectorAll(sel).forEach((el) => {
        prevHeights.set(el, el.getBoundingClientRect().height);
        observer.observe(el);
      });
    }
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

  // ── Design tokens (obsidian dark, teal accent — Claude-quality) ───────────
  private css(): string {
    return `
      *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

      /* ── Design tokens ─────────────────────────────────────────────────── */
      /* Obsidian: #0a0b0d  Surface: #111318  Surface2: #1a1d25            */
      /* Teal: #00c4b4  Teal dark: #009688  Teal glow: rgba(0,196,180,0.15) */
      /* Text primary: #e0e4ef  Text secondary: #8b92a8  Muted: #5a6278    */

      /* ── Keyframe Animations ───────────────────────────────────────────── */
      @keyframes slideInRight {
        from { transform: translateX(100%); }
        to   { transform: translateX(0); }
      }
      @keyframes slideOutRight {
        from { transform: translateX(0); }
        to   { transform: translateX(100%); }
      }
      @keyframes fadeUp {
        from { opacity: 0; transform: translateY(8px); }
        to   { opacity: 1; transform: translateY(0); }
      }
      @keyframes shimmer {
        from { background-position: -200% 0; }
        to   { background-position: 200% 0; }
      }
      @keyframes fabAppear {
        from { transform: scale(0); opacity: 0; }
        to   { transform: scale(1); opacity: 1; }
      }
      @keyframes spin {
        from { transform: rotate(0deg); }
        to   { transform: rotate(360deg); }
      }
      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50%       { opacity: 0.4; }
      }
      @keyframes bar-grow {
        from { width: 0 !important; }
      }
      @keyframes dot-bounce {
        0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
        40%            { transform: scale(1);   opacity: 1; }
      }

      /* ── FAB Toggle Button ─────────────────────────────────────────────── */
      .toggle-tab {
        position: fixed;
        bottom: 24px;
        right: 24px;
        width: 52px;
        height: 52px;
        border-radius: 50%;
        background: #111318;
        border: 1.5px solid rgba(0,196,180,0.4);
        box-shadow: 0 0 20px rgba(0,196,180,0.15), 0 4px 16px rgba(0,0,0,0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        pointer-events: all;
        z-index: 3;
        transition: transform 0.2s cubic-bezier(0.34,1.56,0.64,1), border-color 0.2s, box-shadow 0.2s;
        animation: fabAppear 0.4s cubic-bezier(0.34,1.56,0.64,1) both;
        user-select: none;
        position: fixed;
      }
      .toggle-tab:hover {
        transform: scale(1.05);
        border-color: rgba(0,196,180,0.7);
        box-shadow: 0 0 28px rgba(0,196,180,0.25), 0 6px 20px rgba(0,0,0,0.5);
      }
      .toggle-tab:active {
        transform: scale(0.97);
      }
      .toggle-tab.panel-open {
        border-color: rgba(0,196,180,0.6);
        box-shadow: 0 0 24px rgba(0,196,180,0.2), 0 4px 16px rgba(0,0,0,0.5);
      }
      .fab-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        color: #00c4b4;
        filter: drop-shadow(0 0 6px rgba(0,196,180,0.5));
        transition: transform 0.25s cubic-bezier(0.34,1.56,0.64,1);
        line-height: 1;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .toggle-tab.panel-open .fab-icon {
        transform: rotate(45deg);
      }
      .fab-badge {
        position: absolute;
        top: -3px;
        right: -3px;
        min-width: 18px;
        height: 18px;
        border-radius: 9px;
        background: #00c4b4;
        color: #0a0b0d;
        font-size: 9px;
        font-weight: 800;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0 4px;
        border: 1.5px solid #111318;
        letter-spacing: -0.02em;
        font-family: system-ui, -apple-system, sans-serif;
      }

      /* ── Main Panel ────────────────────────────────────────────────────── */
      .panel {
        position: fixed;
        right: 0;
        top: 0;
        width: 380px;
        height: 100vh;
        background: #0a0b0d;
        border-left: 1px solid rgba(255,255,255,0.07);
        box-shadow: -8px 0 32px rgba(0,0,0,0.6);
        transform: translateX(100%);
        transition: transform 0.2s ease-in;
        display: flex;
        flex-direction: column;
        pointer-events: all;
        z-index: 2;
        font-family: system-ui, -apple-system, sans-serif;
        color: #e0e4ef;
        will-change: transform;
      }
      .panel.open {
        transform: translateX(0);
        transition: transform 0.25s cubic-bezier(0.22,1,0.36,1);
        animation: slideInRight 0.25s cubic-bezier(0.22,1,0.36,1) both;
      }

      /* ── Panel Header ──────────────────────────────────────────────────── */
      .header {
        flex-shrink: 0;
        height: 56px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 16px;
        background: rgba(10,11,13,0.95);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(255,255,255,0.06);
        z-index: 10;
      }
      .header-left {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .header-logo {
        font-size: 18px;
        color: #00c4b4;
        filter: drop-shadow(0 0 4px rgba(0,196,180,0.4));
        line-height: 1;
        display: flex;
        align-items: center;
      }
      .header-title {
        font-size: 14px;
        font-weight: 600;
        color: #e0e4ef;
        letter-spacing: -0.01em;
      }
      .header-actions {
        display: flex;
        align-items: center;
        gap: 4px;
      }
      .header-btn {
        width: 32px;
        height: 32px;
        border-radius: 8px;
        background: transparent;
        border: none;
        color: #5a6278;
        cursor: pointer;
        pointer-events: all;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 16px;
        line-height: 1;
        transition: background 0.15s, color 0.15s;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .header-btn:hover {
        background: rgba(255,255,255,0.06);
        color: #e0e4ef;
      }
      /* Legacy selector kept for wireEvents compatibility */
      .close-btn {
        width: 32px;
        height: 32px;
        border-radius: 8px;
        background: transparent;
        border: none;
        color: #5a6278;
        cursor: pointer;
        pointer-events: all;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 16px;
        line-height: 1;
        transition: background 0.15s, color 0.15s;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .close-btn:hover {
        background: rgba(255,255,255,0.06);
        color: #e0e4ef;
      }

      /* ── Company Context Bar ───────────────────────────────────────────── */
      .company-section {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 16px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        background: rgba(255,255,255,0.015);
        animation: fadeUp 0.3s ease both;
      }
      .company-avatar {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        background: rgba(0,196,180,0.15);
        border: 1px solid rgba(0,196,180,0.3);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: 700;
        color: #00c4b4;
        flex-shrink: 0;
        letter-spacing: -0.02em;
      }
      .company-info { flex: 1; min-width: 0; }
      .company-name {
        font-size: 13px;
        font-weight: 600;
        color: #e0e4ef;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .role-name {
        font-size: 11px;
        color: #8b92a8;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-top: 1px;
      }
      .score-chip {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        gap: 5px;
        font-size: 11px;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 99px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.1);
        color: #8b92a8;
        letter-spacing: -0.01em;
        white-space: nowrap;
      }
      .score-chip-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
        display: inline-block;
      }

      /* ── Scrollable Content Area ───────────────────────────────────────── */
      .panel-body {
        flex: 1;
        overflow-y: auto;
        overflow-x: hidden;
        padding: 12px;
        min-height: 0;
      }
      .panel-body::-webkit-scrollbar { width: 2px; }
      .panel-body::-webkit-scrollbar-track { background: transparent; }
      .panel-body::-webkit-scrollbar-thumb {
        background: rgba(0,196,180,0.25);
        border-radius: 1px;
      }
      .panel-body::-webkit-scrollbar-thumb:hover {
        background: rgba(0,196,180,0.45);
      }

      /* ── Score Bar Card ────────────────────────────────────────────────── */
      .score-bar-wrap {
        margin-bottom: 8px;
        padding: 12px;
        background: #111318;
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.07);
        animation: fadeUp 0.3s ease both;
      }
      .score-bar-label {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 11px;
        font-weight: 600;
        color: #5a6278;
        margin-bottom: 8px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      .score-bar-label span:last-child {
        font-size: 13px;
        font-weight: 700;
        letter-spacing: -0.01em;
        text-transform: none;
      }
      .score-bar-track {
        height: 6px;
        background: rgba(255,255,255,0.06);
        border-radius: 3px;
        overflow: hidden;
      }
      .score-bar-fill {
        height: 100%;
        border-radius: 3px;
        animation: bar-grow 0.6s ease-out both;
        position: relative;
      }

      /* ── CTA / Autofill Button ─────────────────────────────────────────── */
      .cta-section {
        margin-bottom: 8px;
      }
      .cta-btn {
        width: 100%;
        height: 44px;
        background: linear-gradient(135deg, #00c4b4 0%, #009688 100%);
        border: none;
        border-radius: 10px;
        color: #fff;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
        pointer-events: all;
        letter-spacing: -0.01em;
        transition: filter 0.15s, transform 0.15s, box-shadow 0.15s;
        box-shadow: 0 2px 16px rgba(0,196,180,0.3), 0 1px 4px rgba(0,0,0,0.3);
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .cta-btn:hover {
        filter: brightness(1.06);
        transform: translateY(-1px);
        box-shadow: 0 4px 24px rgba(0,196,180,0.4), 0 2px 8px rgba(0,0,0,0.3);
      }
      .cta-btn:active {
        transform: scale(0.98);
        filter: brightness(0.97);
        box-shadow: 0 1px 8px rgba(0,196,180,0.2);
      }

      /* ── Section Cards ─────────────────────────────────────────────────── */
      .section {
        background: #111318;
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.07);
        padding: 12px;
        margin-bottom: 8px;
        animation: fadeUp 0.25s ease both;
      }
      .section-heading {
        font-size: 11px;
        font-weight: 600;
        color: #5a6278;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .section-count {
        font-size: 10px;
        font-weight: 600;
        padding: 1px 6px;
        border-radius: 99px;
        background: rgba(255,255,255,0.06);
        color: #8b92a8;
        letter-spacing: 0;
        text-transform: none;
      }

      /* ── Field Cards ───────────────────────────────────────────────────── */
      .field-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 12px;
        background: #1a1d25;
        border-radius: 8px;
        margin-bottom: 5px;
        transition: background 0.15s;
        cursor: default;
      }
      .field-row:last-child { margin-bottom: 0; }
      .field-row:hover {
        background: rgba(255,255,255,0.04);
      }
      .field-info { flex: 1; min-width: 0; }
      .field-label {
        font-size: 11px;
        font-weight: 400;
        color: #8b92a8;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .field-value {
        font-size: 13px;
        font-weight: 500;
        color: #e0e4ef;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-top: 2px;
      }
      .fill-btn, .attach-btn {
        flex-shrink: 0;
        height: 28px;
        padding: 0 12px;
        border-radius: 14px;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        pointer-events: all;
        border: 1px solid rgba(0,196,180,0.4);
        background: rgba(0,196,180,0.08);
        color: #00c4b4;
        transition: background 0.15s, border-color 0.15s;
        white-space: nowrap;
        display: flex;
        align-items: center;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .fill-btn:hover, .attach-btn:hover {
        background: rgba(0,196,180,0.16);
        border-color: rgba(0,196,180,0.65);
      }

      /* ── Question Cards ────────────────────────────────────────────────── */
      .question-card {
        background: #111318;
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 10px;
        padding: 12px;
        margin-bottom: 6px;
        transition: border-color 0.15s;
        animation: fadeUp 0.28s ease both;
      }
      .question-card:last-child { margin-bottom: 0; }
      .question-card:hover {
        border-color: rgba(255,255,255,0.12);
      }
      .question-text {
        font-size: 13px;
        color: #e0e4ef;
        line-height: 1.5;
        margin-bottom: 8px;
        font-weight: 400;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
      .question-meta {
        display: flex;
        gap: 5px;
        flex-wrap: wrap;
        margin-bottom: 10px;
        align-items: center;
      }

      /* ── Pills ─────────────────────────────────────────────────────────── */
      .pill {
        font-size: 10px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 99px;
        background: rgba(255,255,255,0.05);
        color: #5a6278;
        border: 1px solid rgba(255,255,255,0.07);
        letter-spacing: 0;
      }
      .pill-cat {
        color: #00c4b4;
        border: 1px solid rgba(0,196,180,0.3);
        background: rgba(0,196,180,0.08);
      }

      /* ── Draft Tabs ────────────────────────────────────────────────────── */
      .draft-tabs {
        display: flex;
        gap: 3px;
        margin-bottom: 8px;
        background: rgba(255,255,255,0.03);
        border-radius: 8px;
        padding: 3px;
      }
      .draft-tab {
        flex: 1;
        padding: 5px 6px;
        background: transparent;
        border: none;
        border-radius: 6px;
        color: #5a6278;
        font-size: 11px;
        font-weight: 600;
        cursor: pointer;
        pointer-events: all;
        text-align: center;
        transition: background 0.15s, color 0.15s;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .draft-tab.active {
        background: #1a1d25;
        color: #00c4b4;
        box-shadow: 0 1px 4px rgba(0,0,0,0.3);
      }
      .draft-tab:hover:not(.active) {
        color: #8b92a8;
        background: rgba(255,255,255,0.04);
      }

      /* ── Draft Text / Answer Preview ───────────────────────────────────── */
      .draft-text {
        font-size: 12px;
        color: #8b92a8;
        line-height: 1.6;
        background: rgba(0,0,0,0.3);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
        max-height: 110px;
        overflow-y: auto;
        white-space: pre-wrap;
        transition: border-color 0.15s;
      }
      .draft-text:hover {
        border-color: rgba(0,196,180,0.2);
      }
      .draft-text::-webkit-scrollbar { width: 2px; }
      .draft-text::-webkit-scrollbar-track { background: transparent; }
      .draft-text::-webkit-scrollbar-thumb {
        background: rgba(0,196,180,0.25);
        border-radius: 1px;
      }
      .draft-actions {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      /* ── Generate Button ───────────────────────────────────────────────── */
      .generate-btn {
        width: 100%;
        padding: 9px;
        background: transparent;
        border: 1px solid rgba(0,196,180,0.35);
        border-radius: 8px;
        color: #00c4b4;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        pointer-events: all;
        transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
        letter-spacing: -0.01em;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .generate-btn:hover {
        background: rgba(0,196,180,0.08);
        border-color: rgba(0,196,180,0.6);
        box-shadow: 0 0 12px rgba(0,196,180,0.1);
      }
      .generate-btn:active {
        background: rgba(0,196,180,0.12);
      }
      .generate-btn:disabled {
        opacity: 0.35;
        cursor: not-allowed;
      }

      /* ── Fill Answer Button ────────────────────────────────────────────── */
      .fill-answer-btn {
        flex: 1;
        height: 34px;
        background: linear-gradient(135deg, #00c4b4 0%, #009688 100%);
        border: none;
        border-radius: 8px;
        color: #fff;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        pointer-events: all;
        transition: filter 0.15s, transform 0.15s, box-shadow 0.15s;
        box-shadow: 0 2px 10px rgba(0,196,180,0.25);
        letter-spacing: -0.01em;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .fill-answer-btn:hover {
        filter: brightness(1.08);
        transform: translateY(-1px);
        box-shadow: 0 4px 16px rgba(0,196,180,0.35);
      }
      .fill-answer-btn:active {
        transform: scale(0.98);
        filter: brightness(0.97);
      }

      /* ── Copy / Regen Buttons ──────────────────────────────────────────── */
      .copy-draft-btn {
        width: 34px;
        height: 34px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        color: #5a6278;
        cursor: pointer;
        border-radius: 8px;
        font-size: 14px;
        line-height: 1;
        transition: color 0.15s, border-color 0.15s, background 0.15s;
        pointer-events: all;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .copy-draft-btn:hover {
        color: #00c4b4;
        border-color: rgba(0,196,180,0.35);
        background: rgba(0,196,180,0.06);
      }
      .regen-btn {
        width: 34px;
        height: 34px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        color: #5a6278;
        cursor: pointer;
        pointer-events: all;
        font-size: 15px;
        border-radius: 8px;
        transition: color 0.15s, background 0.15s, border-color 0.15s;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .regen-btn:hover {
        color: #8b92a8;
        background: rgba(255,255,255,0.06);
        border-color: rgba(255,255,255,0.12);
      }

      /* ── Loading States ────────────────────────────────────────────────── */
      .loading-text {
        font-size: 12px;
        color: #5a6278;
        text-align: center;
        padding: 10px 0;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
      }
      .loading-spinner {
        width: 16px;
        height: 16px;
        border: 2px solid rgba(0,196,180,0.15);
        border-top-color: #00c4b4;
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
        flex-shrink: 0;
        display: inline-block;
      }
      .provider-badge {
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 1px 6px;
        border-radius: 99px;
        background: rgba(0,196,180,0.1);
        border: 1px solid rgba(0,196,180,0.25);
        color: #00c4b4;
      }
      .elapsed-time {
        font-size: 9px;
        color: #5a6278;
        font-variant-numeric: tabular-nums;
        font-family: ui-monospace, monospace;
      }
      .loading-spinner-wrap {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 10px 0;
      }
      .loading-spinner-wrap::before {
        content: '';
        width: 16px;
        height: 16px;
        border: 2px solid rgba(0,196,180,0.15);
        border-top-color: #00c4b4;
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
        display: block;
      }

      /* ── Error ─────────────────────────────────────────────────────────── */
      .error-text {
        font-size: 11px;
        color: #f87171;
        margin-top: 6px;
        padding: 6px 10px;
        background: rgba(248,113,113,0.07);
        border: 1px solid rgba(248,113,113,0.18);
        border-radius: 7px;
        line-height: 1.4;
      }

      /* ── Footer ────────────────────────────────────────────────────────── */
      .footer {
        flex-shrink: 0;
        padding: 12px 16px 16px;
        border-top: 1px solid rgba(255,255,255,0.05);
      }
      .auth-warn {
        font-size: 11px;
        color: #f59e0b;
        background: rgba(245,158,11,0.07);
        border: 1px solid rgba(245,158,11,0.18);
        border-radius: 8px;
        padding: 8px 12px;
        line-height: 1.5;
        margin-bottom: 8px;
      }
      .footer-brand {
        font-size: 10px;
        color: #5a6278;
        text-align: center;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        font-weight: 600;
      }

      /* ── AutoFill Banner ───────────────────────────────────────────────── */
      .aap-autofill-banner {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: rgba(0,196,180,0.08);
        border: 1px solid rgba(0,196,180,0.25);
        border-radius: 8px;
        padding: 8px 12px;
        margin-bottom: 8px;
        font-size: 12px;
        color: #00c4b4;
        animation: fadeUp 0.2s ease both;
      }
      .aap-autofill-actions { display: flex; gap: 6px; align-items: center; }
      .aap-btn-undo {
        background: rgba(0,196,180,0.15);
        border: 1px solid rgba(0,196,180,0.4);
        color: #00c4b4;
        border-radius: 6px;
        padding: 3px 10px;
        cursor: pointer;
        font-size: 11px;
        font-weight: 600;
        pointer-events: all;
        transition: background 0.15s;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .aap-btn-undo:hover { background: rgba(0,196,180,0.25); }
      .aap-btn-dismiss {
        background: transparent;
        border: none;
        color: #5a6278;
        cursor: pointer;
        font-size: 16px;
        padding: 0 2px;
        pointer-events: all;
        line-height: 1;
        transition: color 0.15s;
        font-family: system-ui, -apple-system, sans-serif;
      }
      .aap-btn-dismiss:hover { color: #8b92a8; }

      /* ── Similarity Badges ─────────────────────────────────────────────── */
      .aap-badge-vault {
        display: inline-block;
        padding: 1px 6px;
        border-radius: 9999px;
        font-size: 10px;
        font-weight: 600;
        background: rgba(0,196,180,0.1);
        color: #00c4b4;
        border: 1px solid rgba(0,196,180,0.25);
        margin-left: 5px;
        vertical-align: middle;
      }
      .aap-badge-llm {
        display: inline-block;
        padding: 1px 6px;
        border-radius: 9999px;
        font-size: 10px;
        font-weight: 600;
        background: rgba(139,92,246,0.1);
        color: #8b5cf6;
        border: 1px solid rgba(139,92,246,0.25);
        margin-left: 5px;
        vertical-align: middle;
      }
    `;
  }

  private render(): void {
    const { isOpen, company, roleTitle, atsScore, loadingAts, fields, questionStates, clerkUserId } = this;
    const companyInitial = (company || "A").charAt(0).toUpperCase();
    const fillableCount = fields.filter(
      (f) => f.fieldType !== "resume_upload" && f.fieldType !== "cover_letter_upload"
    ).length;

    // FAB badge: show ATS score if available
    const fabBadgeHtml = atsScore !== null
      ? `<div class="fab-badge" style="background:${scoreColor(atsScore)};color:#fff;">${atsScore}</div>`
      : "";

    // Score chip inside company context bar
    const scoreChipHtml = atsScore !== null
      ? `<div class="score-chip">
           <span class="score-chip-dot" style="background:${scoreColor(atsScore)};"></span>
           <span style="color:${scoreColor(atsScore)}">${atsScore}%</span>
         </div>`
      : loadingAts
      ? `<div class="score-chip"><span style="animation:pulse 1.5s ease infinite;display:inline-block;">…</span></div>`
      : "";

    // ATS score bar card
    const scoreBarHtml = atsScore !== null
      ? `<div class="score-bar-wrap">
           <div class="score-bar-label">
             <span>ATS Match</span>
             <span style="color:${scoreColor(atsScore)}">${atsScore}%</span>
           </div>
           <div class="score-bar-track">
             <div class="score-bar-fill" style="width:${atsScore}%;background:${scoreColor(atsScore)};box-shadow:0 0 8px ${scoreColor(atsScore)};"></div>
           </div>
         </div>`
      : "";

    // Autofill CTA
    const ctaHtml = fillableCount > 0
      ? `<div class="cta-section">
           <button class="cta-btn" id="__aap_autofill__">&#9889; Autofill ${fillableCount} field${fillableCount !== 1 ? "s" : ""}</button>
         </div>`
      : "";

    // Autofill undo banner
    const autoFillBannerHtml = this.showAutoFillBanner
      ? `<div class="aap-autofill-banner">
           <span>&#10003; Auto-filled ${fillableCount} fields from profile</span>
           <div class="aap-autofill-actions">
             <button class="aap-btn-undo" data-action="undo-autofill">Undo</button>
             <button class="aap-btn-dismiss" data-action="dismiss-autofill">&#x2715;</button>
           </div>
         </div>`
      : "";

    // Fields section
    const fieldsHtml = fields.length > 0
      ? `<div class="section" style="animation-delay:${0 * 30}ms">
           <div class="section-heading">Fields <span class="section-count">${fields.length}</span></div>
           ${fields.map((f, i) => {
             const isFile = f.fieldType === "resume_upload" || f.fieldType === "cover_letter_upload";
             const suggested = isFile ? "" : (profileValue(f.fieldType, this.profile) || "");
             const btn = isFile
               ? `<button class="attach-btn" data-field-idx="${i}">Attach</button>`
               : `<button class="fill-btn" data-field-idx="${i}">Fill</button>`;
             return `<div class="field-row">
               <div class="field-info">
                 <div class="field-label">${truncate(f.label || f.fieldType.replace(/_/g, " "), 38)}</div>
                 ${suggested ? `<div class="field-value">${truncate(suggested, 32)}</div>` : ""}
               </div>
               ${btn}
             </div>`;
           }).join("")}
         </div>`
      : "";

    // Cover letter section
    const coverLetterHtml = this.coverLetter
      ? `<div class="section" style="animation-delay:${1 * 30}ms">
           <div class="section-heading">
             Cover Letter
             ${this.coverLetterSource === "vault" ? `<span class="aap-badge-vault">From vault</span>` : ""}
           </div>
           <div class="draft-text" style="max-height:120px">${this.coverLetter.replace(/</g, "&lt;")}</div>
         </div>`
      : "";

    // Questions section
    const questionsHtml = questionStates.length > 0
      ? `<div class="section" style="animation-delay:${2 * 30}ms">
           <div class="section-heading">Questions <span class="section-count">${questionStates.length}</span></div>
           ${questionStates.map((state, qi) => {
             const q = state.question;
             const hasDrafts = state.drafts.length > 0;
             const selectedText = state.drafts[state.selectedDraft] ?? "";

             let draftContent = "";
             if (hasDrafts) {
               const tabsHtml = `<div class="draft-tabs">
                 ${state.drafts.map((_, di) => {
                   const src = state.draftSources?.[di];
                   const provName = state.draftProviders[di];
                   const label = provName
                     ? provName.charAt(0).toUpperCase() + provName.slice(1)
                     : `Draft ${di + 1}`;
                   const badge = src?.source === "vault"
                     ? `<span class="aap-badge-vault">${Math.round((src.similarityScore ?? 0) * 100)}%</span>`
                     : `<span class="aap-badge-llm">AI</span>`;
                   return `<button class="draft-tab ${di === state.selectedDraft ? "active" : ""}" data-q-idx="${qi}" data-d-idx="${di}">${label}${badge}</button>`;
                 }).join("")}
               </div>`;
               draftContent = `${tabsHtml}
                 <div class="draft-text">${selectedText.replace(/</g, "&lt;")}</div>
                 <div class="draft-actions">
                   <button class="fill-answer-btn" data-q-idx="${qi}" data-draft-text="${encodeURIComponent(selectedText)}">Fill Answer &#8595;</button>
                   <button class="copy-draft-btn" data-q-idx="${qi}" data-draft-text="${encodeURIComponent(selectedText)}" title="Copy">&#9112;</button>
                   <button class="regen-btn" title="Regenerate" data-q-idx="${qi}" id="__aap_regen_${qi}__">&#8635;</button>
                 </div>`;
             } else if (state.loading) {
               const elapsedSec = state.loadingStartMs ? Math.floor((Date.now() - state.loadingStartMs) / 1000) : 0;
               const providerBadge = state.loadingProvider
                 ? `<span class="provider-badge">${state.loadingProvider}</span>`
                 : "";
               const elapsed = elapsedSec > 0 ? `<span class="elapsed-time">${elapsedSec}s</span>` : "";
               draftContent = `<div class="loading-text"><span class="loading-spinner"></span>Generating… ${providerBadge}${elapsed}</div>`;
             } else {
               draftContent = `<button class="generate-btn" data-q-idx="${qi}" ${state.loading ? "disabled" : ""}>&#10022; Generate Answer</button>`;
             }

             const errorHtml = state.error
               ? `<div class="error-text">${state.error}</div>`
               : "";

             return `<div class="question-card">
               <div class="question-text">${truncate(q.questionText, 120).replace(/</g, "&lt;")}</div>
               <div class="question-meta">
                 <span class="pill pill-cat">${categoryLabel(q.category)}</span>
                 ${q.maxLength ? `<span class="pill">${q.maxLength} chars</span>` : ""}
               </div>
               ${draftContent}
               ${errorHtml}
             </div>`;
           }).join("")}
         </div>`
      : "";

    // Footer
    const footerHtml = `<div class="footer">
      ${!clerkUserId
        ? `<div class="auth-warn">&#9888; Sign in via the extension options page to enable AI features (answer generation, ATS scoring).</div>`
        : ""}
      <div class="footer-brand">AutoApply AI</div>
    </div>`;

    this.shadow.innerHTML = `<style>${this.css()}</style>
      <div class="toggle-tab${isOpen ? " panel-open" : ""}" id="__aap_toggle__">
        <div class="fab-icon">${isOpen ? "&#x2715;" : "&#9889;"}</div>
        ${fabBadgeHtml}
      </div>
      <div class="panel ${isOpen ? "open" : ""}" id="__aap_panel__">
        <div class="header">
          <div class="header-left">
            <div class="header-logo">&#9889;</div>
            <div class="header-title">AutoApply AI</div>
          </div>
          <div class="header-actions">
            <button class="close-btn" id="__aap_close__">&#x2715;</button>
          </div>
        </div>
        ${company ? `<div class="company-section">
          <div class="company-avatar">${companyInitial}</div>
          <div class="company-info">
            <div class="company-name">${company}</div>
            <div class="role-name">${truncate(roleTitle, 52)}</div>
          </div>
          ${scoreChipHtml}
        </div>` : ""}
        <div class="panel-body">
          ${scoreBarHtml}
          ${ctaHtml}
          ${autoFillBannerHtml}
          ${fieldsHtml}
          ${coverLetterHtml}
          ${questionsHtml}
        </div>
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

    // Auto-fill banner action buttons (undo / dismiss)
    this.shadow.querySelectorAll<HTMLButtonElement>("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        switch (btn.dataset.action) {
          case "undo-autofill":
            this.undoAutoFill();
            break;
          case "dismiss-autofill":
            this.showAutoFillBanner = false;
            sessionStorage.setItem(
              `aap_autofill_dismissed_${this.company.toLowerCase().replace(/\s+/g, "_")}`,
              "1"
            );
            this.render();
            break;
        }
      });
    });

    // Fill individual field buttons
    this.shadow.querySelectorAll<HTMLButtonElement>(".fill-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.fieldIdx ?? "0", 10);
        const field = this.fields[idx];
        if (!field) return;
        const value = profileValue(field.fieldType, this.profile);
        if (value) this.fillFieldSmart(field.fieldId, value);
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
          btn.style.color = "#10b981";
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
