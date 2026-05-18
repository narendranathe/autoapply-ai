/**
 * Tests for the manifest CSP (P1-E, #198 round 2).
 *
 * The source ``manifest.json`` MUST declare a ``connect-src`` directive
 * that whitelists the API hosts and Clerk. Without it, extension pages
 * inherit Chrome's default CSP for MV3 (``self`` only) and outbound
 * fetches to ``https://autoapply-ai-api.fly.dev`` fail silently.
 *
 * In a production build, ``vite.config.ts`` strips loopback origins from
 * the CSP. The post-build ``verify-manifest.mjs`` script enforces that
 * (so this test only validates the *source* manifest carries the right
 * shape; the prod scrub is exercised by the build pipeline itself).
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
// extension/src/shared/__tests__/ → extension/manifest.json
const manifestPath = resolve(__dirname, "..", "..", "..", "manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const csp = manifest.content_security_policy?.extension_pages ?? "";

test("P1-E: manifest declares an extension_pages CSP", () => {
  assert.ok(csp.length > 0, "extension_pages CSP must be set");
});

test("P1-E: CSP declares connect-src", () => {
  assert.match(csp, /connect-src\s/);
});

test("P1-E: connect-src whitelists the production API host", () => {
  assert.match(csp, /https:\/\/autoapply-ai-api\.fly\.dev/);
});

test("P1-E: connect-src whitelists Clerk", () => {
  assert.match(csp, /clerk\.feasible-liger-35\.clerk\.accounts\.dev/);
});

test("P1-E: connect-src includes 'self' so same-origin requests still work", () => {
  const m = /connect-src\s+([^;]+)/.exec(csp);
  assert.ok(m, "connect-src directive must be present");
  const tokens = m[1].split(/\s+/).filter(Boolean);
  assert.ok(tokens.includes("'self'"), "connect-src must include 'self'");
});

test("P1-E: connect-src includes localhost in source manifest (stripped in prod build)", () => {
  // The source manifest keeps localhost so dev builds work; the
  // production stripper in vite.config.ts removes it.
  assert.match(csp, /http:\/\/localhost(:\d+)?/);
});
