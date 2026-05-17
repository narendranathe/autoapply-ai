/**
 * Tests for buildProviderList — the wire-format payload builder (#198).
 *
 * The single most important invariant: the returned array MUST NOT contain
 * any `api_key` / `apiKey` field. The backend resolves stored keys against
 * the authenticated user; sending them over the wire defeats the fix.
 *
 * Runner: node --test --experimental-strip-types
 */

import { test } from "node:test";
import assert from "node:assert/strict";

// `useProviders` calls `useState` / `useEffect` at module load when imported
// through the hook function — but `buildProviderList` itself is a pure
// function we can import directly. Stub chrome.storage so the module's
// side-effects don't blow up if loaded.
globalThis.chrome = globalThis.chrome ?? {
  storage: {
    local: {
      get: () => Promise.resolve({}),
      set: () => Promise.resolve(),
      remove: () => Promise.resolve(),
    },
    onChanged: { addListener: () => {}, removeListener: () => {} },
  },
};

// Import the pure helper, not the React hook — `useProviders.ts` itself
// pulls in React which isn't installed in the test environment.
const { buildProviderList } = await import("../providerList.ts");

test("buildProviderList omits api_key for every provider (#198)", () => {
  const configs = {
    anthropic: { enabled: true, apiKey: "sk-ant-secret-1", model: "claude-sonnet-4-6" },
    openai:    { enabled: true, apiKey: "sk-openai-secret-2", model: "gpt-4o" },
  };
  const result = buildProviderList(configs);
  assert.equal(result.length, 2);
  for (const p of result) {
    assert.equal("api_key" in p, false, `${p.name} must not carry api_key on the wire`);
    assert.equal("apiKey" in p, false, `${p.name} must not carry apiKey on the wire`);
  }
});

test("buildProviderList carries name and model only", () => {
  const result = buildProviderList({
    anthropic: { apiKey: "k1", model: "claude-sonnet-4-6" },
  });
  assert.deepEqual(result, [{ name: "anthropic", model: "claude-sonnet-4-6" }]);
});

test("buildProviderList falls back to default model when omitted", () => {
  const result = buildProviderList({
    anthropic: { apiKey: "k1" },
    openai:    { apiKey: "k2" },
    gemini:    { apiKey: "k3" },
    groq:      { apiKey: "k4" },
    perplexity:{ apiKey: "k5" },
    kimi:      { apiKey: "k6" },
  });
  const byName = Object.fromEntries(result.map((p) => [p.name, p.model]));
  assert.equal(byName.anthropic, "claude-sonnet-4-6");
  assert.equal(byName.openai, "gpt-4o");
  assert.equal(byName.gemini, "gemini-1.5-flash");
  assert.equal(byName.groq, "llama-3.3-70b-versatile");
  assert.equal(byName.perplexity, "sonar");
  assert.equal(byName.kimi, "moonshot-v1-32k");
});

test("buildProviderList sorts by priority rank", () => {
  // Insert in random order — expect anthropic > openai > gemini > groq.
  const result = buildProviderList({
    groq:      { apiKey: "k", model: "llama" },
    openai:    { apiKey: "k", model: "gpt" },
    anthropic: { apiKey: "k", model: "claude" },
    gemini:    { apiKey: "k", model: "gem" },
  });
  assert.deepEqual(result.map((p) => p.name), ["anthropic", "openai", "gemini", "groq"]);
});

test("buildProviderList filters out unconfigured providers (no apiKey AND no enabled)", () => {
  const result = buildProviderList({
    anthropic: { apiKey: "", model: "claude" },     // empty key, not enabled → skip
    openai:    { apiKey: "k", model: "gpt" },        // has key → include
    gemini:    { enabled: true, model: "gem" },      // server-side migrated (#198) → include
  });
  const names = result.map((p) => p.name);
  assert.ok(!names.includes("anthropic"));
  assert.ok(names.includes("openai"));
  assert.ok(names.includes("gemini"));
});

test("buildProviderList includes server-side-migrated entries (enabled but no local apiKey)", () => {
  // Post-migration state: local has no apiKey but enabled=true. The wire
  // payload must still send the provider so backend looks up the stored key.
  const result = buildProviderList({
    anthropic: { enabled: true, model: "claude-sonnet-4-6" },
  });
  assert.equal(result.length, 1);
  assert.equal(result[0].name, "anthropic");
  assert.equal("apiKey" in result[0], false);
});
