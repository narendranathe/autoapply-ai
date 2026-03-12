/**
 * workdayApply.ts
 *
 * Injects an "⚡ AutoFill Step" button into Workday application pages.
 * Workday uses a multi-step wizard rendered in a single-page app.
 * Each step has a form with labeled inputs, selects, and text areas.
 *
 * Lifecycle:
 *  initWorkdayApply() → MutationObserver watches for wizard container
 *  → injectButton() → user clicks ⚡ → runFill()
 *  → fills inputs from profile | generates textarea answers via API
 */

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
  degree: string;
  yearsExperience: string;
  sponsorship: string;
  salary: string;
}

interface StorageData {
  profile?: Profile;
  clerkUserId?: string;
  apiBaseUrl?: string;
  providerConfigs?: Record<string, { enabled: boolean; apiKey: string; model: string }>;
}

// ── Label → Profile field mapping ─────────────────────────────────────────

const LABEL_TO_VALUE: Array<{ patterns: RegExp[]; getValue: (p: Profile) => string }> = [
  { patterns: [/first\s*name/i, /given\s*name/i, /fname/i],         getValue: (p) => p.firstName },
  { patterns: [/last\s*name/i, /surname/i, /family\s*name/i],       getValue: (p) => p.lastName },
  { patterns: [/^full\s*name/i, /^your\s*name/i, /^name$/i],        getValue: (p) => `${p.firstName} ${p.lastName}`.trim() },
  { patterns: [/email/i],                                             getValue: (p) => p.email },
  { patterns: [/phone/i, /mobile/i, /\btel\b/i, /cell/i],           getValue: (p) => p.phone },
  { patterns: [/city/i, /town/i],                                    getValue: (p) => p.city },
  { patterns: [/\bstate\b/i, /province/i, /region/i],               getValue: (p) => p.state },
  { patterns: [/zip/i, /postal/i],                                   getValue: (p) => p.zip },
  { patterns: [/country/i],                                           getValue: (p) => p.country || "United States" },
  { patterns: [/linkedin/i],                                          getValue: (p) => p.linkedinUrl },
  { patterns: [/github/i],                                            getValue: (p) => p.githubUrl },
  { patterns: [/portfolio/i, /website/i, /personal\s*url/i],         getValue: (p) => p.portfolioUrl },
  { patterns: [/\bdegree\b/i, /education\s*level/i, /highest.*edu/i],getValue: (p) => p.degree },
  { patterns: [/years.*experience/i, /experience.*years/i],          getValue: (p) => p.yearsExperience },
  { patterns: [/salary/i, /compensation/i, /desired.*pay/i],         getValue: (p) => p.salary },
  {
    patterns: [/visa/i, /sponsor/i, /work\s*auth/i, /authorized.*work/i],
    getValue: (p) => (p.sponsorship?.toLowerCase().includes("no") ? "No" : "Yes"),
  },
];

// ── DOM helpers ────────────────────────────────────────────────────────────

/**
 * Get the Workday wizard/form container.
 * Workday uses several possible selectors across versions.
 */
function getFormRoot(): HTMLElement | null {
  return (
    document.querySelector<HTMLElement>("[data-automation-id='applicationPage']") ??
    document.querySelector<HTMLElement>("[data-automation-id='formContainer']") ??
    document.querySelector<HTMLElement>(".WDUI-FormLayout") ??
    document.querySelector<HTMLElement>("[class*='applicationMain']") ??
    document.querySelector<HTMLElement>("main[role='main']") ??
    document.querySelector<HTMLElement>("[role='main']")
  );
}

function getLabel(el: HTMLElement): string {
  // 1. aria-label
  const aria = el.getAttribute("aria-label");
  if (aria) return aria.trim();

  // 2. aria-labelledby
  const labelledBy = el.getAttribute("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent)
      .filter(Boolean)
      .join(" ");
    if (text) return text.trim();
  }

  // 3. data-automation-id (Workday-specific)
  const autoId = el.getAttribute("data-automation-id");
  if (autoId) return autoId.replace(/[-_]/g, " ").trim();

  // 4. associated <label for="id">
  const id = el.id;
  if (id) {
    const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
    if (label) return label.textContent?.trim() ?? "";
  }

  // 5. Walk up to label/legend
  let parent = el.parentElement;
  for (let i = 0; i < 8; i++) {
    if (!parent) break;
    const label = parent.querySelector(
      "label, legend, [data-automation-id*='label'], [class*='label']"
    );
    if (label && !label.contains(el)) return label.textContent?.trim() ?? "";
    parent = parent.parentElement;
  }

  return el.getAttribute("placeholder")?.trim() ?? "";
}

function matchLabel(label: string, profile: Profile): string | null {
  if (!label) return null;
  for (const { patterns, getValue } of LABEL_TO_VALUE) {
    if (patterns.some((p) => p.test(label))) {
      const val = getValue(profile);
      return val || null;
    }
  }
  return null;
}

/** Fill a text/email/tel input using React-compatible native setter */
function fillInput(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  if (!value) return;
  const proto =
    el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) {
    setter.call(el, value);
  } else {
    el.value = value;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  el.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true }));
  el.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true }));
}

/** Fill a <select> by option text or value (case-insensitive, partial match) */
function fillSelect(el: HTMLSelectElement, value: string): boolean {
  if (!value) return false;
  const lower = value.toLowerCase();
  for (const opt of el.options) {
    if (
      opt.value.toLowerCase() === lower ||
      opt.text.toLowerCase() === lower ||
      opt.text.toLowerCase().includes(lower)
    ) {
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      if (setter) setter.call(el, opt.value);
      else el.value = opt.value;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }
  return false;
}

/** Click a radio whose label matches value (case-insensitive) */
function fillRadio(container: HTMLElement, value: string): boolean {
  const lower = value.toLowerCase();
  const radios = container.querySelectorAll<HTMLInputElement>("input[type=radio]");
  for (const radio of radios) {
    const label = getLabel(radio);
    if (label.toLowerCase().includes(lower) || radio.value.toLowerCase().includes(lower)) {
      radio.click();
      radio.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }
  return false;
}

// ── Status overlay ─────────────────────────────────────────────────────────

const TOAST_ID = "__aap_wd_toast__";

function showToast(msg: string, type: "ok" | "err" | "info" = "info"): void {
  let toast = document.getElementById(TOAST_ID) as HTMLDivElement | null;
  if (!toast) {
    toast = document.createElement("div");
    toast.id = TOAST_ID;
    Object.assign(toast.style, {
      position: "fixed",
      top: "12px",
      right: "12px",
      zIndex: "2147483647",
      padding: "8px 14px",
      borderRadius: "10px",
      fontSize: "12px",
      fontFamily: "system-ui,sans-serif",
      fontWeight: "600",
      boxShadow: "0 2px 12px rgba(0,0,0,0.3)",
      transition: "opacity .3s",
      maxWidth: "320px",
      pointerEvents: "none",
    });
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.opacity = "1";
  toast.style.background = type === "ok" ? "#166534" : type === "err" ? "#7f1d1d" : "#1e1b4b";
  toast.style.color = "#fff";
  clearTimeout(parseInt(toast.dataset.timer ?? "0"));
  const timer = setTimeout(() => {
    if (toast) toast.style.opacity = "0";
  }, 3500);
  toast.dataset.timer = String(timer);
}

// ── AutoFill button injection ───────────────────────────────────────────────

const BTN_ID = "__aap_wd_autofill__";

function injectButton(): void {
  if (document.getElementById(BTN_ID)) return;

  const btn = document.createElement("button");
  btn.id = BTN_ID;
  btn.type = "button";
  btn.innerHTML = "&#9889; AutoFill Step";
  btn.setAttribute("aria-label", "AutoApply AI — auto-fill this application step");
  Object.assign(btn.style, {
    position: "fixed",
    bottom: "80px",
    right: "16px",
    zIndex: "2147483646",
    background: "linear-gradient(135deg,#6d28d9 0%,#4f46e5 100%)",
    color: "#fff",
    border: "none",
    borderRadius: "22px",
    padding: "10px 18px",
    fontSize: "13px",
    fontWeight: "700",
    fontFamily: "system-ui,sans-serif",
    cursor: "pointer",
    boxShadow: "0 2px 16px rgba(109,40,217,0.5)",
    letterSpacing: "0.03em",
    transition: "opacity .15s, transform .1s",
  });

  btn.addEventListener("mouseenter", () => {
    btn.style.opacity = "0.88";
    btn.style.transform = "scale(1.03)";
  });
  btn.addEventListener("mouseleave", () => {
    btn.style.opacity = "1";
    btn.style.transform = "scale(1)";
  });
  btn.addEventListener("click", () => void runFill(btn));
  document.body.appendChild(btn);
}

function removeButton(): void {
  document.getElementById(BTN_ID)?.remove();
}

// ── Core fill logic ────────────────────────────────────────────────────────

async function runFill(btn: HTMLButtonElement): Promise<void> {
  btn.disabled = true;
  btn.textContent = "⏳ Filling…";
  showToast("AutoApply AI: scanning form…", "info");

  const data = (await chrome.storage.local.get([
    "profile",
    "clerkUserId",
    "apiBaseUrl",
    "providerConfigs",
  ])) as StorageData;

  const profile = data.profile;
  if (!profile) {
    showToast("⚠ No profile saved. Open options → Personal Profile.", "err");
    btn.disabled = false;
    btn.textContent = "⚡ AutoFill Step";
    return;
  }

  const apiBase = data.apiBaseUrl || "https://autoapply-ai-api.fly.dev/api/v1";
  const userId = data.clerkUserId;
  const providers: Array<{ name: string; api_key: string; model: string }> = Object.entries(
    data.providerConfigs ?? {}
  )
    .filter(([, cfg]) => cfg.enabled && cfg.apiKey)
    .map(([name, cfg]) => ({ name, api_key: cfg.apiKey, model: cfg.model }));

  const root = getFormRoot();
  if (!root) {
    showToast("⚠ Could not find Workday form. Try scrolling to the form.", "err");
    btn.disabled = false;
    btn.textContent = "⚡ AutoFill Step";
    return;
  }

  let filledCount = 0;
  let textareaCount = 0;

  // ── 1. Fill text inputs ─────────────────────────────────────────────────
  const inputs = root.querySelectorAll<HTMLInputElement>(
    "input[type=text], input[type=email], input[type=tel], input[type=number], input[type=url]"
  );
  for (const input of inputs) {
    if (input.readOnly || input.disabled) continue;
    const label = getLabel(input);
    const value = matchLabel(label, profile);
    if (value) {
      fillInput(input, value);
      filledCount++;
    }
  }

  // ── 2. Fill select dropdowns ────────────────────────────────────────────
  const selects = root.querySelectorAll<HTMLSelectElement>("select");
  for (const sel of selects) {
    if (sel.disabled) continue;
    const label = getLabel(sel);
    const value = matchLabel(label, profile);
    if (value && fillSelect(sel, value)) filledCount++;
  }

  // ── 3. Fill radio groups ────────────────────────────────────────────────
  const radioGroups = root.querySelectorAll<HTMLElement>(
    "[role=radiogroup], fieldset, [data-automation-id*='radio']"
  );
  for (const group of radioGroups) {
    const groupLabel = getLabel(group as HTMLElement);
    const value = matchLabel(groupLabel, profile);
    if (value && fillRadio(group as HTMLElement, value)) filledCount++;
  }

  // ── 4. Generate answers for textareas (open-ended questions) ───────────
  const textareas = root.querySelectorAll<HTMLTextAreaElement>("textarea");
  for (const ta of textareas) {
    if (ta.disabled || ta.readOnly || ta.value.trim()) continue;
    const question = getLabel(ta);
    if (!question) continue;

    textareaCount++;
    const maxLen = ta.maxLength > 0 ? ta.maxLength : undefined;

    // Classify question category (simple heuristic)
    const cat = classifyQuestion(question);

    // Fetch work history text for grounding
    let workHistoryText = "";
    if (userId) {
      try {
        const whResp = await fetch(`${apiBase}/work-history/text`, {
          headers: { "X-Clerk-User-Id": userId },
        });
        if (whResp.ok) {
          const whData = (await whResp.json()) as { text?: string };
          workHistoryText = whData.text ?? "";
        }
      } catch {
        // ignore — proceed without work history
      }
    }

    // Extract page context for company/role
    const company = extractCompanyName();
    const roleTitle = extractRoleTitle();
    const jdText = extractJdText();

    // Call answers API
    try {
      const fd = new FormData();
      fd.append("question_text", question);
      fd.append("question_category", cat);
      fd.append("company_name", company);
      fd.append("role_title", roleTitle);
      fd.append("jd_text", jdText);
      fd.append("work_history_text", workHistoryText);
      if (maxLen) fd.append("max_length", String(maxLen));
      if (providers.length > 0) fd.append("providers_json", JSON.stringify(providers));

      const headers: Record<string, string> = {};
      if (userId) headers["X-Clerk-User-Id"] = userId;

      const resp = await fetch(`${apiBase}/vault/generate/answers`, {
        method: "POST",
        headers,
        body: fd,
      });

      if (resp.ok) {
        const result = (await resp.json()) as { drafts?: string[] };
        const draft = result.drafts?.[0];
        if (draft) {
          fillInput(ta, draft);
          filledCount++;
        }
      }
    } catch {
      // skip this textarea
    }
  }

  // ── 5. Handle Workday custom combobox inputs ────────────────────────────
  // Workday sometimes uses div-based comboboxes (role=combobox) with hidden inputs
  const comboboxes = root.querySelectorAll<HTMLElement>("[role=combobox]");
  for (const cb of comboboxes) {
    const input = cb.querySelector<HTMLInputElement>("input") ?? (cb as unknown as HTMLInputElement);
    if (!input?.value?.trim()) {
      const label = getLabel(cb);
      const value = matchLabel(label, profile);
      if (value && input) {
        fillInput(input, value);
        filledCount++;
      }
    }
  }

  showToast(
    textareaCount > 0
      ? `✓ Filled ${filledCount} field${filledCount !== 1 ? "s" : ""} (including ${textareaCount} AI answer${textareaCount !== 1 ? "s" : ""})`
      : `✓ Filled ${filledCount} field${filledCount !== 1 ? "s" : ""}`,
    filledCount > 0 ? "ok" : "info"
  );

  btn.disabled = false;
  btn.textContent = "⚡ AutoFill Step";
}

// ── Page context helpers ───────────────────────────────────────────────────

function extractCompanyName(): string {
  // Try hostname: "company.myworkday.com" → "Company"
  const hostname = window.location.hostname;
  const parts = hostname.split(".");
  if (parts.length >= 3 && (parts[1] === "myworkday" || parts[1] === "workday")) {
    return parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
  }
  // Try page title
  const titleMatch = document.title.match(/at\s+([A-Z][a-zA-Z\s]+?)(?:\s[-–|]|$)/);
  if (titleMatch) return titleMatch[1].trim();
  return document.title.split(/[-–|]/)[0].trim();
}

function extractRoleTitle(): string {
  // Workday typically shows the job title in the page header
  const h1 = document.querySelector<HTMLElement>(
    "h1, [data-automation-id='jobPostingHeader'], [class*='jobTitle']"
  );
  return h1?.textContent?.trim() ?? document.title;
}

function extractJdText(): string {
  const jdEl = document.querySelector<HTMLElement>(
    "[data-automation-id='job-posting-details'], [class*='jobDescription'], [class*='job-description']"
  );
  return (jdEl?.textContent ?? "").slice(0, 3000);
}

function classifyQuestion(text: string): string {
  const t = text.toLowerCase();
  if (/cover\s*letter/i.test(t)) return "cover_letter";
  if (/why.*compan|why.*us|why.*join/i.test(t)) return "why_company";
  if (/why.*hire|why.*you|what.*bring/i.test(t)) return "why_hire";
  if (/tell.*about.*yourself|describe.*yourself|background/i.test(t)) return "about_yourself";
  if (/strength/i.test(t)) return "strength";
  if (/weakness/i.test(t)) return "weakness";
  if (/challenge|difficult|obstacle/i.test(t)) return "challenge";
  if (/leadership|led|managed|team/i.test(t)) return "leadership";
  if (/conflict|disagree|feedback/i.test(t)) return "conflict";
  if (/motivat|passion|excit/i.test(t)) return "motivation";
  if (/5\s*year|career\s*goal|long.term/i.test(t)) return "five_years";
  if (/impact|achiev|accomplish/i.test(t)) return "impact";
  return "custom";
}

// ── Observer & init ───────────────────────────────────────────────────────

function isWorkdayPage(): boolean {
  const url = window.location.href;
  return /myworkday\.com|workday\.com\/[^/]+\/d\/jobs/.test(url);
}

let _observing = false;

export function initWorkdayApply(): void {
  if (!isWorkdayPage()) return;
  if (_observing) return;
  _observing = true;

  // Inject immediately if the form is already present
  if (getFormRoot()) injectButton();

  // Watch for SPA navigation that loads the application form
  const observer = new MutationObserver(() => {
    if (!isWorkdayPage()) {
      removeButton();
      return;
    }
    if (getFormRoot()) {
      injectButton();
    } else {
      removeButton();
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
}
