/**
 * Tests for the migration-banner accessibility markup (P1-G, #198
 * round 2; P2-B, #198 round 3).
 *
 * Screen-reader announcements
 * ---------------------------
 * The migration banner is a *live region*. When it appears (or its
 * count text changes) screen readers must announce the new content
 * without the user having to navigate to it. Two ARIA contracts back
 * that up:
 *
 *   - Banner container: ``role="status"`` + ``aria-live="polite"`` +
 *     ``aria-atomic="true"`` so the entire message is queued and
 *     re-announced when it updates without interrupting the user.
 *
 *     Round 2 used ``role=alert`` + ``aria-live=assertive`` which
 *     produced 6 interruptions during a 6-provider migration (banner
 *     text refreshes after each provider completes). Round 3
 *     downgrades to ``polite`` — the banner is informational, not a
 *     time-critical alert, so progress-style announcements should
 *     queue, not preempt.
 *
 *   - Status line below the button: ``role="status"`` +
 *     ``aria-live="polite"`` (unchanged) so per-step migration
 *     progress doesn't interrupt the user mid-keystroke.
 *
 * These tests scan the static HTML for those attributes.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
// extension/src/options/__tests__/ → extension/src/options/index.html
const htmlPath = resolve(__dirname, "..", "index.html");
const html = readFileSync(htmlPath, "utf8");

// Pull just the banner element by id and inspect attributes from a
// substring window. Avoids the cost of a real DOM parser.
function extractElementById(html, id) {
  const idx = html.indexOf(`id="${id}"`);
  if (idx < 0) return null;
  // Walk backwards to the opening "<" to capture the full open tag.
  const tagStart = html.lastIndexOf("<", idx);
  // Find the end of the open tag.
  const tagEnd = html.indexOf(">", idx);
  return html.slice(tagStart, tagEnd + 1);
}

test("P2-B: banner has role=status (non-interruptive)", () => {
  const tag = extractElementById(html, "provider-migrate-banner");
  assert.ok(tag, "banner element must exist");
  assert.match(tag, /role="status"/);
  // Regression: must not be ``role=alert``. ``alert`` is assertive by
  // default and would interrupt the user once per banner refresh.
  assert.doesNotMatch(tag, /role="alert"/);
});

test("P2-B: banner has aria-live=polite (queues, does not preempt)", () => {
  const tag = extractElementById(html, "provider-migrate-banner");
  assert.ok(tag);
  assert.match(tag, /aria-live="polite"/);
  // Regression: must not be ``aria-live=assertive`` — that produced
  // 6 interruptions during a 6-provider migration.
  assert.doesNotMatch(tag, /aria-live="assertive"/);
});

test("P1-G: banner has aria-atomic=true so updates re-announce", () => {
  const tag = extractElementById(html, "provider-migrate-banner");
  assert.ok(tag);
  assert.match(tag, /aria-atomic="true"/);
});

test("P1-G: status line has role=status (not interruptive)", () => {
  const tag = extractElementById(html, "provider-migrate-status");
  assert.ok(tag, "status element must exist");
  assert.match(tag, /role="status"/);
});

test("P1-G: status line has aria-live=polite", () => {
  const tag = extractElementById(html, "provider-migrate-status");
  assert.ok(tag);
  assert.match(tag, /aria-live="polite"/);
});

test("P1-G: migrate button is described by the banner text", () => {
  const tag = extractElementById(html, "provider-migrate-btn");
  assert.ok(tag, "button element must exist");
  assert.match(tag, /aria-describedby="provider-migrate-banner-text"/);
});
