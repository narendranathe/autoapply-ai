/**
 * ats-origins.ts — Allowlist of postMessage origins for the 5 tracked ATS
 * Platforms (`linkedin`, `greenhouse`, `lever`, `workday`, `indeed`).
 *
 * Used by IframeFieldBridge (detector.ts + floatingPanel.ts) to scope
 * `postMessage` calls and validate `event.origin` on receive. Messages
 * to/from any origin not in this list are dropped — never broadcast to "*".
 */

export const ATS_ORIGIN_PATTERNS: RegExp[] = [
  /^https?:\/\/([a-z0-9-]+\.)*linkedin\.com$/i,
  /^https?:\/\/([a-z0-9-]+\.)*greenhouse\.io$/i,
  /^https?:\/\/([a-z0-9-]+\.)*lever\.co$/i,
  /^https?:\/\/([a-z0-9-]+\.)*workday\.com$/i,
  /^https?:\/\/([a-z0-9-]+\.)*myworkday\.com$/i,
  /^https?:\/\/([a-z0-9-]+\.)*myworkdayjobs\.com$/i,
  /^https?:\/\/([a-z0-9-]+\.)*indeed\.com$/i,
];

export function isAllowedAtsOrigin(origin: string | null | undefined): boolean {
  if (!origin || origin === "null" || origin === "*") return false;
  return ATS_ORIGIN_PATTERNS.some((re) => re.test(origin));
}

export function resolveIframeOrigin(iframe: HTMLIFrameElement): string | null {
  try {
    const href = iframe.contentWindow?.location?.href;
    if (!href) return null;
    return new URL(href).origin;
  } catch {
    return null;
  }
}
