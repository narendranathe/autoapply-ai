import { AUTH_STORAGE_KEYS, buildAuthHeaders } from "./authHelper";

/**
 * indeedApply.ts
 *
 * Injects an "⚡ AutoFill Step" button into the Indeed Apply modal/iframe.
 * Indeed's apply flow is either:
 *   a) An in-page overlay at indeed.com/apply (React SPA, multiple steps)
 *   b) An external redirect to the employer ATS (handled by floatingPanel)
 *
 * This module handles case (a): the native Indeed Apply flow.
 *
 * DOM landmarks:
 *   - Apply container: #indeed-ia, .ia-JobApplication, [data-testid="ia-questions-form"]
 *   - Step indicator: [class*="ia-BasePage-header"]
 *   - Next button: [data-testid="ia-continue-button"]
 *   - Submit button: [data-testid="ia-submit-button"]
 *
 * Strategy:
 *   Watch for the apply container to render → inject AutoFill button.
 *   On click: fill profile fields, generate answers for textarea questions.
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

interface ProviderCfg {
  enabled: boolean;
  apiKey: string;
  model: string;
}

// ── Label matchers ─────────────────────────────────────────────────────────

const LABEL_MAP: Array<{ patterns: RegExp[]; getValue: (p: Profile) => string }> = [
  { patterns: [/first\s*name/i, /given\s*name/i],        getValue: (p) => p.firstName },
  { patterns: [/last\s*name/i, /surname/i, /family/i],   getValue: (p) => p.lastName },
  { patterns: [/^full\s*name/i, /^name$/i],              getValue: (p) => `${p.firstName} ${p.lastName}`.trim() },
  { patterns: [/email/i],                                 getValue: (p) => p.email },
  { patterns: [/phone/i, /mobile/i, /\btel\b/i],         getValue: (p) => p.phone },
  { patterns: [/city/i],                                  getValue: (p) => p.city },
  { patterns: [/\bstate\b/i, /province/i],               getValue: (p) => p.state },
  { patterns: [/zip/i, /postal/i],                        getValue: (p) => p.zip },
  { patterns: [/country/i],                               getValue: (p) => p.country || "United States" },
  { patterns: [/linkedin/i],                              getValue: (p) => p.linkedinUrl },
  { patterns: [/github/i],                                getValue: (p) => p.githubUrl },
  { patterns: [/portfolio/i, /website/i],                 getValue: (p) => p.portfolioUrl },
  { patterns: [/\bdegree\b/i, /education/i],             getValue: (p) => p.degree },
  { patterns: [/years.*exp/i, /experience.*years/i],     getValue: (p) => p.yearsExperience },
  { patterns: [/salary/i, /compensation/i],              getValue: (p) => p.salary },
  {
    patterns: [/sponsor/i, /visa/i, /work\s*auth/i],
    getValue: (p) => p.sponsorship?.toLowerCase().includes("no") ? "No" : "Yes",
  },
];

// ── DOM helpers ────────────────────────────────────────────────────────────

function getLabel(el: HTMLElement, root: HTMLElement): string {
  const aria = el.getAttribute("aria-label");
  if (aria) return aria.trim();

  const labelledBy = el.getAttribute("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy.split(" ")
      .map((id) => document.getElementById(id)?.textContent).filter(Boolean).join(" ");
    if (text) return text.trim();
  }

  const id = el.id;
  if (id) {
    const label = root.querySelector(`label[for="${CSS.escape(id)}"]`);
    if (label) return label.textContent?.trim() ?? "";
  }

  // Walk up to find label/legend
  let parent = el.parentElement;
  for (let i = 0; i < 6; i++) {
    if (!parent || parent === root) break;
    const label = parent.querySelector("label, legend, [class*='label'], [class*='Label']");
    if (label && !label.contains(el)) return label.textContent?.trim() ?? "";
    parent = parent.parentElement;
  }

  return el.getAttribute("placeholder")?.trim() ?? "";
}

function matchValue(label: string, profile: Profile): string | null {
  if (!label) return null;
  for (const { patterns, getValue } of LABEL_MAP) {
    if (patterns.some((p) => p.test(label))) {
      const val = getValue(profile);
      return val || null;
    }
  }
  return null;
}

function fillReact(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  if (!value) return;
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, value); else el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  el.dispatchEvent(new Event("blur", { bubbles: true }));
}

function fillSelect(el: HTMLSelectElement, value: string): boolean {
  if (!value) return false;
  const lower = value.toLowerCase();
  for (const opt of el.options) {
    if (opt.value.toLowerCase() === lower || opt.text.toLowerCase().includes(lower)) {
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      if (setter) setter.call(el, opt.value); else el.value = opt.value;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }
  return false;
}

function fillRadio(container: HTMLElement, value: string): boolean {
  const lower = value.toLowerCase();
  for (const radio of container.querySelectorAll<HTMLInputElement>("input[type=radio]")) {
    const label = getLabel(radio, container);
    if (label.toLowerCase().includes(lower) || radio.value.toLowerCase().includes(lower)) {
      radio.click();
      radio.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }
  return false;
}

// ── Toast helper ────────────────────────────────────────────────────────────

function showToast(root: HTMLElement, msg: string, type: "ok" | "err" | "info" = "info"): void {
  let toast = root.querySelector<HTMLDivElement>("#__aap_indeed_toast__") as HTMLDivElement | null;
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "__aap_indeed_toast__";
    Object.assign(toast.style, {
      position: "fixed",
      top: "16px",
      right: "16px",
      zIndex: "2147483647",
      padding: "8px 14px",
      borderRadius: "8px",
      fontSize: "12px",
      fontFamily: "system-ui,sans-serif",
      fontWeight: "600",
      boxShadow: "0 2px 12px rgba(0,0,0,0.35)",
      maxWidth: "280px",
      transition: "opacity .3s",
      pointerEvents: "none",
    });
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.opacity = "1";
  toast.style.background = type === "ok" ? "#166534" : type === "err" ? "#7f1d1d" : "#1e1b4b";
  toast.style.color = "#fff";
  const timer = setTimeout(() => { if (toast) toast.style.opacity = "0"; }, 3500);
  clearTimeout(parseInt(toast.dataset.timer ?? "0"));
  toast.dataset.timer = String(timer);
}

// ── Extract job context from Indeed page ──────────────────────────────────

function extractIndeedCompany(): string {
  return (
    document.querySelector<HTMLElement>("[data-testid='inlineHeader-companyName']")?.textContent?.trim() ??
    document.querySelector<HTMLElement>(".jobsearch-InlineCompanyRating-companyHeader")?.textContent?.trim() ??
    document.querySelector<HTMLElement>("[class*='companyName']")?.textContent?.trim() ??
    ""
  );
}

function extractIndeedJd(): string {
  return (
    document.querySelector<HTMLElement>("#jobDescriptionText")?.innerText ??
    document.querySelector<HTMLElement>(".jobsearch-jobDescriptionText")?.innerText ??
    ""
  ).slice(0, 2000);
}

// ── AutoFill logic ─────────────────────────────────────────────────────────

const BTN_ID = "__aap_indeed_autofill__";

function getApplyRoot(): HTMLElement | null {
  return (
    document.querySelector<HTMLElement>("#indeed-ia") ??
    document.querySelector<HTMLElement>(".ia-JobApplication") ??
    document.querySelector<HTMLElement>("[data-testid='ia-questions-form']") ??
    document.querySelector<HTMLElement>("[class*='ia-BasePage']") ??
    document.querySelector<HTMLElement>(".jobs-apply-content") ??
    // Indeed sometimes uses an overlay div
    document.querySelector<HTMLElement>("[data-testid='desktopApplyModal']")
  );
}

function injectButton(applyRoot: HTMLElement): void {
  if (applyRoot.querySelector(`#${BTN_ID}`)) return;

  const btn = document.createElement("button");
  btn.id = BTN_ID;
  btn.type = "button";
  btn.innerHTML = "&#9889; AutoFill Step";
  Object.assign(btn.style, {
    position: "fixed",
    bottom: "72px",
    right: "20px",
    zIndex: "2147483647",
    background: "linear-gradient(135deg,#6d28d9 0%,#4f46e5 100%)",
    color: "#fff",
    border: "none",
    borderRadius: "20px",
    padding: "9px 16px",
    fontSize: "12px",
    fontWeight: "700",
    fontFamily: "system-ui,sans-serif",
    cursor: "pointer",
    boxShadow: "0 2px 12px rgba(109,40,217,0.45)",
    letterSpacing: "0.03em",
  });
  btn.addEventListener("click", () => void runFill(applyRoot, btn));
  document.body.appendChild(btn);
}

async function runFill(applyRoot: HTMLElement, btn: HTMLButtonElement): Promise<void> {
  btn.disabled = true;
  btn.innerHTML = "&#9889; Filling…";

  const raw = await chrome.storage.local.get(["profile", "apiBaseUrl", "providerConfigs", ...AUTH_STORAGE_KEYS]);
  const profile = raw.profile as Profile | undefined;
  if (!profile) {
    showToast(applyRoot, "No profile found — configure in Options first.", "err");
    btn.disabled = false;
    btn.innerHTML = "&#9889; AutoFill Step";
    return;
  }

  const apiBase = (raw.apiBaseUrl as string | undefined) || "https://autoapply-ai-api.fly.dev/api/v1";
  const configs = (raw.providerConfigs as Record<string, ProviderCfg> | undefined) ?? {};
  const providers = Object.entries(configs)
    .filter(([, c]) => !!c.apiKey)
    .map(([name, c]) => ({ name, api_key: c.apiKey, model: c.model }));

  // Use the currently visible step, or the whole apply root
  const stepRoot =
    applyRoot.querySelector<HTMLElement>("[data-testid='ia-questions-form']") ??
    applyRoot.querySelector<HTMLElement>("[class*='ia-BasePage']") ??
    applyRoot;

  let filled = 0;
  let generated = 0;

  // Text / email / tel inputs
  for (const input of stepRoot.querySelectorAll<HTMLInputElement>(
    "input[type=text], input[type=email], input[type=tel], input[type=number], input:not([type])"
  )) {
    if (input.readOnly || input.disabled || input.value) continue;
    const label = getLabel(input, stepRoot);
    const value = matchValue(label, profile);
    if (value) { fillReact(input, value); filled++; }
  }

  // Selects
  for (const sel of stepRoot.querySelectorAll<HTMLSelectElement>("select")) {
    if (sel.disabled) continue;
    const label = getLabel(sel, stepRoot);
    const value = matchValue(label, profile);
    if (value && fillSelect(sel, value)) filled++;
  }

  // Radio groups (sponsorship yes/no, relocation, etc.)
  for (const group of stepRoot.querySelectorAll<HTMLElement>("[role=radiogroup], fieldset")) {
    const label = group.querySelector("legend, label, [class*='label']")?.textContent?.trim() ?? "";
    if (!label) continue;
    const value = matchValue(label, profile);
    if (value && fillRadio(group, value)) filled++;
  }

  // Textareas — generate via API
  const textareas = Array.from(stepRoot.querySelectorAll<HTMLTextAreaElement>("textarea"))
    .filter((ta) => !ta.disabled && !ta.readOnly);

  const authHdrs = buildAuthHeaders(raw);
  if (textareas.length > 0) {
    showToast(applyRoot, `Generating ${textareas.length} answer${textareas.length > 1 ? "s" : ""}…`, "info");
    for (const ta of textareas) {
      const label = getLabel(ta, stepRoot);
      if (!label || label.length < 6) continue;
      try {
        const fd = new FormData();
        fd.append("question_text", label);
        fd.append("question_category", "custom");
        fd.append("company_name", extractIndeedCompany());
        fd.append("jd_text", extractIndeedJd());
        if (providers.length > 0) fd.append("providers_json", JSON.stringify(providers));
        if (ta.maxLength > 0) fd.append("max_length", String(ta.maxLength));
        const resp = await fetch(`${apiBase}/vault/generate/answers`, {
          method: "POST",
          headers: authHdrs,
          body: fd,
        });
        if (resp.ok) {
          const json = await resp.json() as { drafts?: string[] };
          const draft = json.drafts?.[0];
          if (draft) { fillReact(ta, draft); generated++; }
        }
      } catch { /* non-fatal */ }
    }
  }

  const parts = [
    filled > 0 ? `${filled} filled` : "",
    generated > 0 ? `${generated} generated` : "",
    filled + generated === 0 ? "Nothing to fill" : "",
  ].filter(Boolean).join(" · ");

  showToast(applyRoot, `${parts} ✓`, filled + generated > 0 ? "ok" : "info");
  btn.disabled = false;
  btn.innerHTML = "&#9889; AutoFill Step";
}

// ── Init ────────────────────────────────────────────────────────────────────

export function initIndeedApply(): void {
  if (!/indeed\.com/i.test(window.location.href)) return;

  let buttonInjected = false;

  const observer = new MutationObserver(() => {
    const root = getApplyRoot();
    if (root && !buttonInjected) {
      buttonInjected = true;
      setTimeout(() => injectButton(root), 500);
    } else if (!root && buttonInjected) {
      buttonInjected = false;
      document.getElementById(BTN_ID)?.remove();
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  // If apply form already present on load
  const existing = getApplyRoot();
  if (existing) {
    buttonInjected = true;
    setTimeout(() => injectButton(existing), 500);
  }
}
