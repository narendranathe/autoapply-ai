/**
 * Tests for the legacy → server-side provider key migration (#198).
 *
 * The pure function `migrateProviderKeys(configs, deps)` is the unit under
 * test: it takes the local providerConfigs map, a fetch + auth + apiBase
 * bundle, and returns an `updatedConfigs` map with `apiKey` stripped from
 * migrated entries, plus a per-provider result list.
 *
 * Runner: node --test --experimental-strip-types
 */

import { test } from "node:test";
import assert from "node:assert/strict";

// No chrome stub needed — providerKeyMigration is pure (no storage access).
const { migrateProviderKeys } = await import("../providerKeyMigration.ts");

function makeFetchCapturing(onCall, response = { ok: true }) {
  const calls = [];
  const fetchFn = async (url, init) => {
    calls.push({ url, init });
    if (typeof onCall === "function") onCall({ url, init });
    return {
      ok: response.ok,
      status: response.status ?? (response.ok ? 200 : 500),
      text: async () => response.body ?? "",
    };
  };
  return { fetchFn, calls };
}

const baseDeps = (overrides = {}) => ({
  apiBase: "https://api.example.com/api/v1",
  authHeaders: () => ({ "X-Clerk-User-Id": "u1" }),
  fetch: async () => ({ ok: true, status: 200, text: async () => "" }),
  ...overrides,
});

test("migrates a single legacy plaintext key via PUT and strips it locally", async () => {
  const { fetchFn, calls } = makeFetchCapturing();
  const configs = {
    anthropic: { enabled: true, apiKey: "sk-ant-real-key", model: "claude-sonnet-4-6" },
  };
  const result = await migrateProviderKeys(configs, baseDeps({ fetch: fetchFn }));

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.example.com/api/v1/users/provider-configs/anthropic");
  assert.equal(calls[0].init.method, "PUT");
  const body = JSON.parse(calls[0].init.body);
  assert.equal(body.api_key, "sk-ant-real-key");
  // Local entry must be stripped of apiKey.
  assert.equal("apiKey" in result.updatedConfigs.anthropic, false);
  assert.equal(result.updatedConfigs.anthropic.enabled, true);
  assert.equal(result.updatedConfigs.anthropic.model, "claude-sonnet-4-6");
  assert.equal(result.results[0].status, "migrated");
  assert.equal(result.hasFailures, false);
  assert.equal(result.changed, true);
});

test("idempotent: re-running on already-migrated entries makes zero PUTs", async () => {
  const { fetchFn, calls } = makeFetchCapturing();
  const configs = {
    // No apiKey — already migrated.
    anthropic: { enabled: true, model: "claude-sonnet-4-6" },
    openai:    { enabled: true, model: "gpt-4o" },
  };
  const result = await migrateProviderKeys(configs, baseDeps({ fetch: fetchFn }));
  assert.equal(calls.length, 0);
  assert.equal(result.changed, false);
  assert.equal(result.hasFailures, false);
  for (const r of result.results) assert.equal(r.status, "already_migrated");
});

test("network failure preserves local apiKey and reports failure", async () => {
  const fetchFn = async () => { throw new Error("ECONNREFUSED"); };
  const configs = {
    anthropic: { enabled: true, apiKey: "sk-ant-keep-me", model: "claude-sonnet-4-6" },
  };
  const result = await migrateProviderKeys(configs, baseDeps({ fetch: fetchFn }));
  assert.equal(result.hasFailures, true);
  // Legacy state preserved so user can retry.
  assert.equal(result.updatedConfigs.anthropic.apiKey, "sk-ant-keep-me");
  assert.equal(result.results[0].status, "failed");
  assert.match(result.results[0].error, /ECONNREFUSED/);
});

test("non-2xx response preserves local apiKey and reports failure", async () => {
  const { fetchFn } = makeFetchCapturing(null, { ok: false, status: 401, body: "unauthorized" });
  const configs = {
    anthropic: { enabled: true, apiKey: "sk-ant", model: "claude-sonnet-4-6" },
  };
  const result = await migrateProviderKeys(configs, baseDeps({ fetch: fetchFn }));
  assert.equal(result.hasFailures, true);
  assert.equal(result.updatedConfigs.anthropic.apiKey, "sk-ant");
  assert.equal(result.results[0].status, "failed");
  assert.match(result.results[0].error, /401/);
});

test("mixed: migrates good keys, preserves failing keys", async () => {
  let calls = 0;
  const fetchFn = async (url) => {
    calls++;
    // Fail PUTs for the "openai" provider only.
    if (String(url).endsWith("/openai")) {
      return { ok: false, status: 502, text: async () => "bad gateway" };
    }
    return { ok: true, status: 200, text: async () => "" };
  };
  const configs = {
    anthropic: { enabled: true, apiKey: "good-1", model: "claude" },
    openai:    { enabled: true, apiKey: "fail-2", model: "gpt-4o" },
  };
  const result = await migrateProviderKeys(configs, baseDeps({ fetch: fetchFn }));

  assert.equal(calls, 2);
  assert.equal("apiKey" in result.updatedConfigs.anthropic, false);
  assert.equal(result.updatedConfigs.openai.apiKey, "fail-2");
  assert.equal(result.hasFailures, true);

  const byName = Object.fromEntries(result.results.map((r) => [r.name, r.status]));
  assert.equal(byName.anthropic, "migrated");
  assert.equal(byName.openai, "failed");
});

test("empty-string apiKey is dropped locally and not PUT to backend", async () => {
  const { fetchFn, calls } = makeFetchCapturing();
  const configs = {
    anthropic: { enabled: false, apiKey: "   ", model: "claude" },
  };
  const result = await migrateProviderKeys(configs, baseDeps({ fetch: fetchFn }));
  assert.equal(calls.length, 0);
  // Empty key field is dropped so subsequent runs treat it as already_migrated.
  assert.equal("apiKey" in result.updatedConfigs.anthropic, false);
  assert.equal(result.results[0].status, "skipped_no_key");
  assert.equal(result.changed, true);
  assert.equal(result.hasFailures, false);
});

test("sends Authorization Bearer when authHeaders provides it", async () => {
  const { fetchFn, calls } = makeFetchCapturing();
  const configs = {
    anthropic: { enabled: true, apiKey: "sk-1", model: "claude" },
  };
  await migrateProviderKeys(configs, {
    apiBase: "https://api.example.com/api/v1",
    authHeaders: () => ({ "Authorization": "Bearer jwt-abc" }),
    fetch: fetchFn,
  });
  const headers = calls[0].init.headers;
  assert.equal(headers["Authorization"], "Bearer jwt-abc");
  assert.equal(headers["Content-Type"], "application/json");
});

test("URL-encodes provider name in path", async () => {
  const { fetchFn, calls } = makeFetchCapturing();
  const configs = {
    // Real provider names are alphanumeric, but the encoder must still run.
    "weird name": { enabled: true, apiKey: "k", model: "m" },
  };
  await migrateProviderKeys(configs, baseDeps({ fetch: fetchFn }));
  assert.equal(calls[0].url, "https://api.example.com/api/v1/users/provider-configs/weird%20name");
});

test("does not re-PUT after a successful migration cycle", async () => {
  const { fetchFn, calls } = makeFetchCapturing();
  const configs = {
    anthropic: { enabled: true, apiKey: "sk-ant", model: "claude" },
  };
  // First run: should PUT.
  const first = await migrateProviderKeys(configs, baseDeps({ fetch: fetchFn }));
  assert.equal(calls.length, 1);
  // Second run on the stripped configs: must not PUT again.
  const second = await migrateProviderKeys(first.updatedConfigs, baseDeps({ fetch: fetchFn }));
  assert.equal(calls.length, 1);
  assert.equal(second.changed, false);
});
