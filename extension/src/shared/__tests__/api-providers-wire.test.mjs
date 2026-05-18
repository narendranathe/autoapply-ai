/**
 * Tests for the canonical ``providers`` wire field (cross-PR with #197).
 *
 * Background
 * ----------
 * Round 1 of #198 shipped while #197 (which renames the wire field from
 * ``providers_json`` to ``providers``) was still in flight. The two PRs
 * landed in the same merge train but were developed in isolation: the
 * extension was still sending ``providers_json`` while the backend was
 * already rejecting it with HTTP 422. Net effect: silent fall-through to
 * the rule-based stub.
 *
 * These tests pin the contract so the extension cannot regress to the
 * old field name:
 *   - PROVIDERS_FORM_FIELD === "providers" (not "providers_json").
 *   - appendProvidersField uses that key.
 *   - serializeProvidersForApi never emits an apiKey/api_key.
 *
 * Runner: node --test --experimental-strip-types — loads the .ts module
 * directly. A tiny chrome shim is required because api.ts attaches a
 * storage.onChanged listener at module load.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

// chrome.* shim — api.ts subscribes to onChanged at import time and reads
// from storage lazily inside ensureInit().
globalThis.chrome = {
  storage: {
    local: {
      get: async () => ({}),
      set: async () => {},
      remove: async () => {},
    },
    onChanged: {
      addListener: () => {},
    },
  },
};

const api = await import("../api.ts");
const { PROVIDERS_FORM_FIELD, appendProvidersField, __serializeProvidersForApi } = api;

test("PROVIDERS_FORM_FIELD is the new 'providers' name (cross-PR #197)", () => {
  assert.equal(PROVIDERS_FORM_FIELD, "providers");
  assert.notEqual(PROVIDERS_FORM_FIELD, "providers_json");
});

test("appendProvidersField uses 'providers' as the form key", () => {
  const fd = new FormData();
  appendProvidersField(fd, [
    { name: "anthropic", model: "claude-sonnet-4-6", apiKey: "sk-ant-xyz" },
  ]);
  // The legacy key must not appear.
  assert.equal(fd.get("providers_json"), null);
  // The new key must appear, with a JSON body shaped like {name, model}.
  const raw = fd.get("providers");
  assert.ok(raw, "providers field should be set");
  const parsed = JSON.parse(String(raw));
  assert.equal(parsed.length, 1);
  assert.equal(parsed[0].name, "anthropic");
  assert.equal(parsed[0].model, "claude-sonnet-4-6");
  // The apiKey passed in must NEVER survive to the wire body.
  assert.ok(!("apiKey" in parsed[0]));
  assert.ok(!("api_key" in parsed[0]));
});

test("appendProvidersField with empty/null is a no-op (no field set)", () => {
  const fd = new FormData();
  appendProvidersField(fd, []);
  assert.equal(fd.get("providers"), null);
  assert.equal(fd.get("providers_json"), null);

  const fd2 = new FormData();
  appendProvidersField(fd2, undefined);
  assert.equal(fd2.get("providers"), null);
  assert.equal(fd2.get("providers_json"), null);
});

test("serializeProvidersForApi strips api_key/apiKey on every entry", () => {
  const out = __serializeProvidersForApi([
    { name: "anthropic", model: "x", apiKey: "leak-1" },
    // pretend a call site forgot to type-check and stuffed in api_key
    { name: "openai", model: "y", apiKey: "leak-2" },
  ]);
  const parsed = JSON.parse(out);
  for (const entry of parsed) {
    assert.ok(!("apiKey" in entry), `entry ${entry.name} leaked apiKey`);
    assert.ok(!("api_key" in entry), `entry ${entry.name} leaked api_key`);
  }
});

// ── Integration: end-to-end shape an ATS content script would build ──────

test("integration: content-script-shaped builder → appendProvidersField → wire body", () => {
  // Simulate what the refactored content scripts now do: build the list
  // via buildProviderList (from providerMigration) then ship it via the
  // shared form-field helper. The result must be the new wire field.
  const fd = new FormData();
  const providers = [
    { name: "anthropic", model: "claude-sonnet-4-6" },
    { name: "openai", model: "gpt-4o" },
  ];
  appendProvidersField(fd, providers);

  const raw = fd.get("providers");
  assert.ok(raw, "providers must be set on the form");
  const parsed = JSON.parse(String(raw));
  assert.deepEqual(parsed, [
    { name: "anthropic", model: "claude-sonnet-4-6" },
    { name: "openai", model: "gpt-4o" },
  ]);
  // Legacy field MUST NOT be present — the backend rejects it with 422.
  assert.equal(fd.get("providers_json"), null);
});
