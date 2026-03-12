/**
 * linkedinEasyApply.ts
 *
 * Injects an "⚡ AutoFill Step" button into the LinkedIn Easy Apply modal.
 * Fills text inputs/selects from stored profile, generates answers for
 * textarea screening questions via the backend API.
 *
 * Lifecycle:
 *  initLinkedInEasyApply() → MutationObserver watches for modal open
 *  → injectAutoFillButton() → user clicks ⚡ → fillCurrentStep()
 *  → for each input: profile fill | for each textarea: API generate
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

// ── Label patterns for field matching ─────────────────────────────────────

const LABEL_TO_VALUE: Array<{ patterns: RegExp[]; getValue: (p: Profile) => string }> = [
  { patterns: [/first\s*name/i, /given\s*name/i, /fname/i],          getValue: (p) => p.firstName },
  { patterns: [/last\s*name/i, /surname/i, /family\s*name/i],        getValue: (p) => p.lastName },
  { patterns: [/^full\s*name/i, /^your\s*name/i, /^name$/i],         getValue: (p) => `${p.firstName} ${p.lastName}`.trim() },
  { patterns: [/email/i],                                              getValue: (p) => p.email },
  { patterns: [/phone/i, /mobile/i, /\btel\b/i, /cell/i],            getValue: (p) => p.phone },
  { patterns: [/city/i],                                               getValue: (p) => p.city },
  { patterns: [/\bstate\b/i, /province/i],                            getValue: (p) => p.state },
  { patterns: [/zip/i, /postal/i],                                     getValue: (p) => p.zip },
  { patterns: [/country/i],                                            getValue: (p) => p.country || "United States" },
  { patterns: [/linkedin/i],                                           getValue: (p) => p.linkedinUrl },
  { patterns: [/github/i],                                             getValue: (p) => p.githubUrl },
  { patterns: [/portfolio/i, /website/i, /personal\s*url/i],          getValue: (p) => p.portfolioUrl },
  { patterns: [/\bdegree\b/i, /education\s*level/i],                  getValue: (p) => p.degree },
  { patterns: [/years.*experience/i, /experience.*years/i],           getValue: (p) => p.yearsExperience },
  { patterns: [/salary/i, /compensation/i],                           getValue: (p) => p.salary },
  {
    patterns: [/visa/i, /sponsor/i, /work\s*auth/i],
    getValue: (p) => p.sponsorship?.toLowerCase().includes("no") ? "No" : "Yes",
  },
];

// ── DOM helpers ────────────────────────────────────────────────────────────

function getLabel(el: HTMLElement, root: HTMLElement): string {
  // 1. aria-label
  const aria = el.getAttribute("aria-label");
  if (aria) return aria.trim();

  // 2. aria-labelledby
  const labelledBy = el.getAttribute("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy.split(" ").map((id) => document.getElementById(id)?.textContent).filter(Boolean).join(" ");
    if (text) return text.trim();
  }

  // 3. associated <label for="id">
  const id = el.id;
  if (id) {
    const label = root.querySelector(`label[for="${CSS.escape(id)}"]`);
    if (label) return label.textContent?.trim() ?? "";
  }

  // 4. Walk up to nearby <label> or legend
  let parent = el.parentElement;
  for (let i = 0; i < 6; i++) {
    if (!parent || parent === root) break;
    const label = parent.querySelector("label, legend, [class*='label']");
    if (label && !label.contains(el)) return label.textContent?.trim() ?? "";
    parent = parent.parentElement;
  }

  // 5. placeholder
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

/** Fill a text/email/tel/number input or textarea using React-compatible native setter */
function fillInput(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  if (!value) return;
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) {
    setter.call(el, value);
  } else {
    el.value = value;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

/** Fill a <select> by matching option text or value (case-insensitive) */
function fillSelect(el: HTMLSelectElement, value: string): boolean {
  if (!value) return false;
  const lower = value.toLowerCase();
  for (const opt of el.options) {
    if (opt.value.toLowerCase() === lower || opt.text.toLowerCase() === lower || opt.text.toLowerCase().includes(lower)) {
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      if (setter) setter.call(el, opt.value); else el.value = opt.value;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }
  return false;
}

/** Click a radio button whose label text matches value (Yes/No etc.) */
function fillRadio(container: HTMLElement, value: string): boolean {
  const lower = value.toLowerCase();
  const radios = container.querySelectorAll<HTMLInputElement>("input[type=radio]");
  for (const radio of radios) {
    const label = getLabel(radio, container);
    if (label.toLowerCase().includes(lower) || radio.value.toLowerCase().includes(lower)) {
      radio.click();
      radio.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }
  return false;
}

// ── AutoFill button injection ───────────────────────────────────────────────

const BTN_ID = "__aap_li_autofill__";
const OVERLAY_ID = "__aap_li_overlay__";

function getModal(): HTMLElement | null {
  return (
    document.querySelector<HTMLElement>(".jobs-easy-apply-content") ??
    document.querySelector<HTMLElement>("[data-test-modal-id='easy-apply-modal']") ??
    document.querySelector<HTMLElement>(".jobs-apply-content") ??
    document.querySelector<HTMLElement>("[class*='jobs-easy-apply'][role='dialog']")
  );
}

function injectAutoFillButton(modal: HTMLElement): void {
  if (modal.querySelector(`#${BTN_ID}`)) return; // already injected

  const btn = document.createElement("button");
  btn.id = BTN_ID;
  btn.type = "button";
  btn.innerHTML = "&#9889; AutoFill Step";
  btn.setAttribute("aria-label", "AutoApply AI — auto-fill this application step");
  Object.assign(btn.style, {
    position: "absolute",
    bottom: "16px",
    right: "72px",
    zIndex: "9999",
    background: "linear-gradient(135deg,#6d28d9 0%,#4f46e5 100%)",
    color: "#fff",
    border: "none",
    borderRadius: "20px",
    padding: "8px 14px",
    fontSize: "12px",
    fontWeight: "700",
    fontFamily: "system-ui,sans-serif",
    cursor: "pointer",
    boxShadow: "0 2px 12px rgba(109,40,217,0.45)",
    letterSpacing: "0.03em",
    transition: "opacity .15s",
  });

  // Ensure modal is relatively positioned for absolute child
  const modalStyle = window.getComputedStyle(modal);
  if (modalStyle.position === "static") modal.style.position = "relative";

  btn.addEventListener("mouseenter", () => { btn.style.opacity = "0.88"; });
  btn.addEventListener("mouseleave", () => { btn.style.opacity = "1"; });
  btn.addEventListener("click", () => void fillCurrentStep(modal, btn));
  modal.appendChild(btn);
}

function removeAutoFillButton(modal: HTMLElement): void {
  modal.querySelector(`#${BTN_ID}`)?.remove();
  document.getElementById(OVERLAY_ID)?.remove();
}

// ── Status toast ────────────────────────────────────────────────────────────

function showToast(modal: HTMLElement, msg: string, type: "ok" | "err" | "info" = "info"): void {
  let toast = modal.querySelector<HTMLDivElement>("#__aap_li_toast__");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "__aap_li_toast__";
    Object.assign(toast.style, {
      position: "absolute",
      top: "8px",
      right: "12px",
      zIndex: "10000",
      padding: "6px 12px",
      borderRadius: "8px",
      fontSize: "11px",
      fontFamily: "system-ui,sans-serif",
      fontWeight: "600",
      boxShadow: "0 2px 8px rgba(0,0,0,0.25)",
      transition: "opacity .3s",
      maxWidth: "260px",
    });
    modal.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.opacity = "1";
  toast.style.background = type === "ok" ? "#166534" : type === "err" ? "#7f1d1d" : "#1e1b4b";
  toast.style.color = "#fff";
  clearTimeout(parseInt(toast.dataset.timer ?? "0"));
  const timer = setTimeout(() => { if (toast) toast.style.opacity = "0"; }, 3500);
  toast.dataset.timer = String(timer);
}

// ── Main fill logic ────────────────────────────────────────────────────────

async function fillCurrentStep(modal: HTMLElement, btn: HTMLButtonElement): Promise<void> {
  btn.disabled = true;
  btn.innerHTML = "&#9889; Filling…";

  const storageData = await chrome.storage.local.get([
    "profile", "clerkUserId", "apiBaseUrl", "providerConfigs",
  ]) as StorageData;

  const profile = storageData.profile;
  if (!profile) {
    showToast(modal, "No profile found — fill in the Options page first.", "err");
    btn.disabled = false;
    btn.innerHTML = "&#9889; AutoFill Step";
    return;
  }

  const apiBase = storageData.apiBaseUrl || "https://autoapply-ai-api.fly.dev/api/v1";
  const clerkUserId = storageData.clerkUserId;
  const providerConfigs = storageData.providerConfigs ?? {};
  const providers = Object.entries(providerConfigs)
    .filter(([, cfg]) => !!cfg.apiKey)
    .map(([name, cfg]) => ({ name, api_key: cfg.apiKey, model: cfg.model }));

  // Find form root (current step content)
  const formRoot =
    modal.querySelector<HTMLElement>(".jobs-easy-apply-form-section__grouping") ??
    modal.querySelector<HTMLElement>("form") ??
    modal.querySelector<HTMLElement>("[class*='easy-apply-form']") ??
    modal;

  let filled = 0;
  let generated = 0;

  // ── 1. Text inputs, email, tel, number ──────────────────────────────────
  const textInputs = formRoot.querySelectorAll<HTMLInputElement>(
    "input[type=text], input[type=email], input[type=tel], input[type=number], input:not([type])"
  );
  for (const input of textInputs) {
    if (input.readOnly || input.disabled) continue;
    const label = getLabel(input, formRoot);
    const value = matchLabel(label, profile);
    if (value && !input.value) {
      fillInput(input, value);
      filled++;
    }
  }

  // ── 2. Selects ────────────────────────────────────────────────────────────
  const selects = formRoot.querySelectorAll<HTMLSelectElement>("select");
  for (const select of selects) {
    if (select.disabled) continue;
    const label = getLabel(select, formRoot);
    // Phone country code — prefer "+1 United States"
    if (/phone.*type|phone.*code|country.*code/i.test(label)) {
      fillSelect(select, "United States") || fillSelect(select, "+1");
      filled++;
      continue;
    }
    // Phone type → Mobile
    if (/phone.*type|mobile.*type/i.test(label)) {
      fillSelect(select, "Mobile");
      filled++;
      continue;
    }
    const value = matchLabel(label, profile);
    if (value) {
      const ok = fillSelect(select, value);
      if (ok) filled++;
    }
  }

  // ── 3. Radio groups (Yes/No for work authorization, sponsorship) ──────────
  const radioGroups = formRoot.querySelectorAll<HTMLElement>(
    ".jobs-easy-apply-form-element, fieldset, [role=radiogroup]"
  );
  for (const group of radioGroups) {
    const label = group.querySelector("label, legend, [class*='label']")?.textContent?.trim() ?? "";
    if (!label) continue;
    const value = matchLabel(label, profile);
    if (value) {
      const ok = fillRadio(group, value);
      if (ok) filled++;
    }
  }

  // ── 4. Textareas — generate answers via API ───────────────────────────────
  const textareas = formRoot.querySelectorAll<HTMLTextAreaElement>("textarea");
  const pendingAnswers: Array<{ el: HTMLTextAreaElement; label: string }> = [];
  for (const ta of textareas) {
    const label = getLabel(ta, formRoot);
    if (!label || label.length < 8) continue; // skip unlabeled / tiny textareas
    pendingAnswers.push({ el: ta, label });
  }

  if (pendingAnswers.length > 0 && clerkUserId) {
    showToast(modal, `Generating ${pendingAnswers.length} answer${pendingAnswers.length > 1 ? "s" : ""}…`, "info");
    for (const { el, label } of pendingAnswers) {
      try {
        const fd = new FormData();
        fd.append("question_text", label);
        fd.append("question_category", "custom");
        fd.append("company_name", extractCompanyName());
        fd.append("jd_text", extractJdSummary());
        if (providers.length > 0) fd.append("providers_json", JSON.stringify(providers));
        if (el.maxLength > 0) fd.append("max_length", String(el.maxLength));

        const resp = await fetch(`${apiBase}/vault/generate/answers`, {
          method: "POST",
          headers: { "X-Clerk-User-Id": clerkUserId },
          body: fd,
        });
        if (resp.ok) {
          const json = await resp.json() as { drafts?: string[] };
          const draft = json.drafts?.[0];
          if (draft) {
            fillInput(el, draft);
            generated++;
          }
        }
      } catch {
        // Non-fatal — textarea stays empty
      }
    }
  }

  const summary = [
    filled > 0 ? `${filled} field${filled > 1 ? "s" : ""} filled` : "",
    generated > 0 ? `${generated} answer${generated > 1 ? "s" : ""} generated` : "",
    filled === 0 && generated === 0 ? "Nothing new to fill" : "",
  ].filter(Boolean).join(" · ");

  showToast(modal, `${summary} ✓`, filled + generated > 0 ? "ok" : "info");
  btn.disabled = false;
  btn.innerHTML = "&#9889; AutoFill Step";
}

// ── Page context helpers ───────────────────────────────────────────────────

function extractCompanyName(): string {
  // LinkedIn job details pane has the company name in a specific element
  const companyEl =
    document.querySelector<HTMLElement>(".job-details-jobs-unified-top-card__company-name a") ??
    document.querySelector<HTMLElement>("[class*='jobs-unified-top-card__company-name']") ??
    document.querySelector<HTMLElement>(".jobs-details-top-card__company-url") ??
    document.querySelector<HTMLElement>("[data-company-name]");
  return companyEl?.textContent?.trim() ?? "";
}

function extractJdSummary(): string {
  const jdEl =
    document.querySelector<HTMLElement>(".jobs-description-content__text") ??
    document.querySelector<HTMLElement>("[class*='jobs-description']") ??
    document.querySelector<HTMLElement>("#job-details");
  return (jdEl?.innerText ?? "").slice(0, 2000);
}

// ── Modal watcher ──────────────────────────────────────────────────────────

export function initLinkedInEasyApply(): void {
  if (!/linkedin\.com/i.test(window.location.href)) return;

  let currentModal: HTMLElement | null = null;

  const observer = new MutationObserver(() => {
    const modal = getModal();
    if (modal && modal !== currentModal) {
      currentModal = modal;
      // Small delay so LinkedIn finishes rendering the form
      setTimeout(() => {
        if (getModal()) injectAutoFillButton(modal);
      }, 600);
    } else if (!modal && currentModal) {
      // Modal was closed
      currentModal = null;
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  // Also handle case where modal is already open on init (rare)
  const existing = getModal();
  if (existing) {
    currentModal = existing;
    setTimeout(() => injectAutoFillButton(existing), 600);
  }
}
