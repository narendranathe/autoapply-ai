/**
 * Tests for the migration-banner accessibility markup (P1-G, #198 round 2).
 *
 * Screen-reader announcements
 * ---------------------------
 * The migration banner is a *live region*. When it appears (or its
 * count text changes) screen readers must announce the new content
 * without the user having to navigate to it. Two ARIA contracts back
 * that up:
 *
 *   - Banner container: ``role="alert"`` (assertive announcement of
 *     the count + provider list when it first appears) +
 *     ``aria-live="assertive"`` + ``aria-atomic="true"`` so the entire
 *     message is re-announced when it updates.
 *
 *   - Status line below the button: ``role="status"`` +
 *     ``aria-live="polite"`` so per-step migration progress (e.g.
 *     "Migrated anthropic, openai") doesn't interrupt the user
 *     mid-keystroke.
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

test("P1-G: banner has role=alert", () => {
  const tag = extractElementById(html, "provider-migrate-banner");
  assert.ok(tag, "banner element must exist");
  assert.match(tag, /role="alert"/);
});

test("P1-G: banner has aria-live=assertive", () => {
  const tag = extractElementById(html, "provider-migrate-banner");
  assert.ok(tag);
  assert.match(tag, /aria-live="assertive"/);
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
