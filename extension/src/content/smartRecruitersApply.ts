import { AUTH_STORAGE_KEYS, buildAuthHeaders } from "./authHelper";

/**
 * smartRecruitersApply.ts
 *
 * Injects an "⚡ AutoFill" button into SmartRecruiters application forms.
 * SmartRecruiters (smartrecruiters.com) is used by enterprise companies.
 *
 * DOM landmarks:
 *   - Form container: [data-smarttoken="applicationForm"],
 *                     .smartr-application, #application-form
 *   - Steps: [data-smarttoken="step-content"], .smartr-step-content
 */

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

const LABEL_MAP: Array<{ patterns: RegExp[]; getValue: (p: Profile) => string }> = [
  { patterns: [/first\s*name/i, /given\s*name/i, /fname/i],       getValue: (p) => p.firstName },
  { patterns: [/last\s*name/i, /surname/i, /family\s*name/i],     getValue: (p) => p.lastName },
  { patterns: [/^full\s*name/i, /^your\s*name/i, /^name$/i],      getValue: (p) => `${p.firstName} ${p.lastName}`.trim() },
  { patterns: [/email/i],                                           getValue: (p) => p.email },
  { patterns: [/phone/i, /mobile/i, /\btel\b/i],                  getValue: (p) => p.phone },
  { patterns: [/city/i, /town/i],                                   getValue: (p) => p.city },
  { patterns: [/\bstate\b/i, /province/i, /region/i],             getValue: (p) => p.state },
  { patterns: [/zip/i, /postal/i],                                  getValue: (p) => p.zip },
  { patterns: [/country/i],                                         getValue: (p) => p.country || "United States" },
  { patterns: [/linkedin/i],                                        getValue: (p) => p.linkedinUrl },
  { patterns: [/github/i],                                          getValue: (p) => p.githubUrl },
  { patterns: [/portfolio/i, /website/i],                          getValue: (p) => p.portfolioUrl },
  { patterns: [/\bdegree\b/i, /education\s*level/i],               getValue: (p) => p.degree },
  { patterns: [/years.*exp/i, /experience.*years/i],               getValue: (p) => p.yearsExperience },
  { patterns: [/salary/i, /compensation/i],                        getValue: (p) => p.salary },
  {
    patterns: [/sponsor/i, /visa/i, /work\s*auth/i],
    getValue: (p) => (p.sponsorship?.toLowerCase().includes("no") ? "No" : "Yes"),
  },
];

function getLabel(el: HTMLElement): string {
  const aria = el.getAttribute("aria-label");
  if (aria) return aria.trim();

  const labelledBy = el.getAttribute("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent)
      .filter(Boolean)
      .join(" ");
    if (text) return text.trim();
  }

  const id = el.id;
  if (id) {
    const lbl = document.querySelector(`label[for="${CSS.escape(id)}"]`);
    if (lbl) return lbl.textContent?.trim() ?? "";
  }

  // SmartRecruiters uses data-smarttoken attributes
  const token = el.getAttribute("data-smarttoken");
  if (token) return token.replace(/[-_]/g, " ").replace(/([A-Z])/g, " $1").trim();

  let parent = el.parentElement;
  for (let i = 0; i < 6; i++) {
    if (!parent) break;
    const lbl = parent.querySelector("label, legend, [class*='label']");
    if (lbl && !lbl.contains(el)) return lbl.textContent?.trim() ?? "";
    parent = parent.parentElement;
  }
  return el.getAttribute("placeholder")?.trim() ?? "";
}

function matchLabel(label: string, profile: Profile): string | null {
  if (!label) return null;
  for (const { patterns, getValue } of LABEL_MAP) {
    if (patterns.some((p) => p.test(label))) return getValue(profile) || null;
  }
  return null;
}

function fillInput(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  if (!value) return;
  const proto =
    el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, value);
  else el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function fillSelect(el: HTMLSelectElement, value: string): boolean {
  if (!value) return false;
  const lower = value.toLowerCase();
  for (const opt of el.options) {
    if (opt.value.toLowerCase() === lower || opt.text.toLowerCase().includes(lower)) {
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

const TOAST_ID = "__aap_sr_toast__";
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
  const timer = setTimeout(() => { if (toast) toast.style.opacity = "0"; }, 3500);
  toast.dataset.timer = String(timer);
}

function getFormRoot(): HTMLElement | null {
  return (
    document.querySelector<HTMLElement>("[data-smarttoken='applicationForm']") ??
    document.querySelector<HTMLElement>(".smartr-application") ??
    document.querySelector<HTMLElement>("#application-form") ??
    document.querySelector<HTMLElement>("[class*='ApplicationForm']") ??
    document.querySelector<HTMLElement>("main form") ??
    document.querySelector<HTMLElement>("form[action*='apply']")
  );
}

const BTN_ID = "__aap_sr_autofill__";

function injectButton(): void {
  if (document.getElementById(BTN_ID)) return;
  const btn = document.createElement("button");
  btn.id = BTN_ID;
  btn.type = "button";
  btn.innerHTML = "&#9889; AutoFill";
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
  btn.addEventListener("mouseenter", () => { btn.style.opacity = "0.88"; btn.style.transform = "scale(1.03)"; });
  btn.addEventListener("mouseleave", () => { btn.style.opacity = "1"; btn.style.transform = "scale(1)"; });
  btn.addEventListener("click", () => void runFill(btn));
  document.body.appendChild(btn);
}

function removeButton(): void {
  document.getElementById(BTN_ID)?.remove();
}

async function runFill(btn: HTMLButtonElement): Promise<void> {
  btn.disabled = true;
  btn.textContent = "⏳ Filling…";

  const data = await chrome.storage.local.get(["profile", "apiBaseUrl", "providerConfigs", ...AUTH_STORAGE_KEYS]);
  const profile = data.profile as Profile | undefined;
  if (!profile) {
    showToast("⚠ No profile saved. Open options → Personal Profile.", "err");
    btn.disabled = false;
    btn.innerHTML = "&#9889; AutoFill";
    return;
  }

  const apiBase = (data.apiBaseUrl as string | undefined) || "https://autoapply-ai-api.fly.dev/api/v1";
  const providers = Object.entries(
    (data.providerConfigs as Record<string, { enabled: boolean; apiKey: string; model: string }> | undefined) ?? {}
  )
    .filter(([, cfg]) => cfg.enabled && cfg.apiKey)
    .map(([name, cfg]) => ({ name, api_key: cfg.apiKey, model: cfg.model }));

  const root = getFormRoot();
  if (!root) {
    showToast("⚠ Could not find SmartRecruiters form.", "err");
    btn.disabled = false;
    btn.innerHTML = "&#9889; AutoFill";
    return;
  }

  let filledCount = 0;

  for (const input of root.querySelectorAll<HTMLInputElement>(
    "input[type=text], input[type=email], input[type=tel], input[type=number], input[type=url]"
  )) {
    if (input.disabled || input.readOnly) continue;
    const val = matchLabel(getLabel(input), profile);
    if (val) { fillInput(input, val); filledCount++; }
  }

  for (const sel of root.querySelectorAll<HTMLSelectElement>("select")) {
    if (sel.disabled) continue;
    const val = matchLabel(getLabel(sel), profile);
    if (val && fillSelect(sel, val)) filledCount++;
  }

  // Textareas → AI-generated answers
  let workHistoryText = "";
  try {
    const r = await fetch(`${apiBase}/work-history/text`, { headers: buildAuthHeaders(data) });
    if (r.ok) { const d = (await r.json()) as { text?: string }; workHistoryText = d.text ?? ""; }
  } catch { /* ignore */ }

  const company = document.title.split(/[-–|]/)[0].trim();
  const h1 = document.querySelector<HTMLElement>("h1");
  const roleTitle = h1?.textContent?.trim() ?? document.title;
  const jdEl = document.querySelector<HTMLElement>("[class*='description'], [class*='job-description']");
  const jdText = (jdEl?.textContent ?? "").slice(0, 3000);

  for (const ta of root.querySelectorAll<HTMLTextAreaElement>("textarea")) {
    if (ta.disabled || ta.readOnly || ta.value.trim()) continue;
    const question = getLabel(ta);
    if (!question) continue;

    const cat = classifyQuestion(question);
    try {
      const fd = new FormData();
      fd.append("question_text", question);
      fd.append("question_category", cat);
      fd.append("company_name", company);
      fd.append("role_title", roleTitle);
      fd.append("jd_text", jdText);
      fd.append("work_history_text", workHistoryText);
      if (ta.maxLength > 0) fd.append("max_length", String(ta.maxLength));
      if (providers.length > 0) fd.append("providers_json", JSON.stringify(providers));

      const headers = buildAuthHeaders(data);

      const r = await fetch(`${apiBase}/vault/generate/answers`, { method: "POST", headers, body: fd });
      if (r.ok) {
        const res = (await r.json()) as { drafts?: string[] };
        const draft = res.drafts?.[0];
        if (draft) { fillInput(ta, draft); filledCount++; }
      }
    } catch { /* skip */ }
  }

  showToast(`✓ Filled ${filledCount} field${filledCount !== 1 ? "s" : ""}`, filledCount > 0 ? "ok" : "info");
  btn.disabled = false;
  btn.innerHTML = "&#9889; AutoFill";
}

function classifyQuestion(text: string): string {
  const t = text.toLowerCase();
  if (/cover\s*letter/i.test(t)) return "cover_letter";
  if (/why.*compan|why.*us|why.*join/i.test(t)) return "why_company";
  if (/why.*hire|why.*you/i.test(t)) return "why_hire";
  if (/tell.*about.*yourself|background/i.test(t)) return "about_yourself";
  if (/strength/i.test(t)) return "strength";
  if (/weakness/i.test(t)) return "weakness";
  if (/challenge|difficult/i.test(t)) return "challenge";
  if (/motivat|passion/i.test(t)) return "motivation";
  return "custom";
}

function isSmartRecruitersPage(): boolean {
  return /smartrecruiters\.com/.test(window.location.href);
}

let _observing = false;

export function initSmartRecruitersApply(): void {
  if (!isSmartRecruitersPage()) return;
  if (_observing) return;
  _observing = true;

  if (getFormRoot()) injectButton();

  const observer = new MutationObserver(() => {
    if (!isSmartRecruitersPage()) { removeButton(); return; }
    if (getFormRoot()) injectButton();
    else removeButton();
  });

  observer.observe(document.body, { childList: true, subtree: true });
}
