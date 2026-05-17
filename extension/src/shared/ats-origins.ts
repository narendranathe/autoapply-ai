/**
 * ats-origins.ts — Allowlist of postMessage origins for the 5 tracked ATS
 * Platforms (`linkedin`, `greenhouse`, `lever`, `workday`, `indeed`).
 *
 * Used by IframeFieldBridge (detector.ts + floatingPanel.ts) to scope
 * `postMessage` calls and validate `event.origin` on receive. Messages
 * to/from any origin not in this list are dropped — never broadcast to "*".
 *
 * HTTPS-only: ATS surfaces in production are served over TLS, and the
 * extension never legitimately talks to plaintext http:// ATS origins.
 */

export const ATS_ORIGIN_PATTERNS: RegExp[] = [
  /^https:\/\/([a-z0-9-]+\.)*linkedin\.com$/i,
  /^https:\/\/([a-z0-9-]+\.)*greenhouse\.io$/i,
  /^https:\/\/([a-z0-9-]+\.)*lever\.co$/i,
  /^https:\/\/([a-z0-9-]+\.)*workday\.com$/i,
  /^https:\/\/([a-z0-9-]+\.)*myworkday\.com$/i,
  /^https:\/\/([a-z0-9-]+\.)*myworkdayjobs\.com$/i,
  /^https:\/\/([a-z0-9-]+\.)*indeed\.com$/i,
];

export function isAllowedAtsOrigin(origin: string | null | undefined): boolean {
  if (!origin || origin === "null" || origin === "*") return false;
  return ATS_ORIGIN_PATTERNS.some((re) => re.test(origin));
}

/**
 * Derive the target origin for an iframe from its `src` attribute.
 *
 * Why `src` and not `contentWindow.location.href`?
 * Reading `contentWindow.location.href` throws `SecurityError` on
 * cross-origin iframes — which is the case this bridge exists to serve
 * (e.g. a Greenhouse iframe embedded on a customer's career site). Using
 * `src` lets us derive the *intended* target origin from the parent's
 * own DOM, which the parent controls and the browser already trusts.
 *
 * Is it safe to trust parent-controlled `src`?
 * Yes — `postMessage(msg, targetOrigin)` only delivers the message if the
 * frame's *current* origin matches `targetOrigin`. So if `src` is stale,
 * malicious, or wrong, the browser drops the message rather than
 * mis-delivering it. The downstream `isAllowedAtsOrigin` check then
 * filters to the ATS allowlist before we ever call `postMessage`.
 *
 * Returns null for `about:blank`, `javascript:`, `data:`, empty src, or
 * any URL that fails to parse — these have no meaningful origin to post to.
 */
export function resolveIframeOrigin(iframe: HTMLIFrameElement | { src?: string | null }): string | null {
  try {
    const src = iframe.src;
    if (!src) return null;
    // Opaque / no-origin schemes — there is nothing safe to postMessage to.
    const lowered = src.trim().toLowerCase();
    if (
      lowered === "" ||
      lowered === "about:blank" ||
      lowered.startsWith("about:") ||
      lowered.startsWith("javascript:") ||
      lowered.startsWith("data:") ||
      lowered.startsWith("blob:")
    ) {
      return null;
    }
    const origin = new URL(src).origin;
    // `new URL("file:///foo").origin === "null"` — never use that as targetOrigin.
    if (!origin || origin === "null") return null;
    return origin;
  } catch {
    return null;
  }
}
