/**
 * Wire-format tests for the generation endpoints in `shared/api.ts` (#198).
 *
 * Every generation call must:
 *  - send a `providers` form field (NOT `providers_json`)
 *  - encode an array of `{name, model}` objects with NO `api_key` field
 *
 * The test installs a fetch stub that captures the FormData body of each
 * outgoing request, then asserts on the captured payloads. `chrome.storage`
 * is stubbed minimally so the module's `ensureInit` resolves immediately.
 *
 * Runner: node --test --experimental-strip-types
 */

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

// ── chrome.storage shim ─────────────────────────────────────────────────────
const storageData = new Map();
globalThis.chrome = {
  storage: {
    local: {
      async get(keyOrKeys) {
        const keys = typeof keyOrKeys === "string"
          ? [keyOrKeys]
          : Array.isArray(keyOrKeys) ? keyOrKeys : Object.keys(keyOrKeys ?? {});
        const out = {};
        for (const k of keys) if (storageData.has(k)) out[k] = storageData.get(k);
        return out;
      },
      async set(obj) { for (const [k, v] of Object.entries(obj)) storageData.set(k, v); },
      async remove(keyOrKeys) {
        const keys = Array.isArray(keyOrKeys) ? keyOrKeys : [keyOrKeys];
        for (const k of keys) storageData.delete(k);
      },
    },
    onChanged: { addListener: () => {} },
  },
};

// ── fetch capture ────────────────────────────────────────────────────────────
const calls = [];
async function readFormData(body) {
  // FormData → plain object for assertion.
  const out = {};
  for (const [k, v] of body.entries()) out[k] = v;
  return out;
}
globalThis.fetch = async (url, init) => {
  const captured = { url: String(url), method: init?.method ?? "GET", headers: init?.headers ?? {} };
  if (init?.body instanceof FormData) {
    captured.form = await readFormData(init.body);
  } else if (typeof init?.body === "string") {
    captured.json = (() => { try { return JSON.parse(init.body); } catch { return init.body; } })();
  }
  calls.push(captured);
  return {
    ok: true,
    status: 200,
    text: async () => "",
    json: async () => ({ drafts: [], draft_providers: [], questions: [], total: 0, bullets: [], summary: "", trimmed: "", char_count: 0, provider_used: "anthropic" }),
  };
};

storageData.set("apiBaseUrl", "https://api.example.com/api/v1");
storageData.set("clerkUserId", "u1");

const api = await import("../api.ts");
const { vaultApi, workHistoryApi } = api;

beforeEach(() => { calls.length = 0; });

function assertProvidersField(form) {
  assert.ok("providers" in form, "must send `providers` field");
  assert.ok(!("providers_json" in form), "must NOT send legacy `providers_json` field");
  const parsed = JSON.parse(form.providers);
  for (const p of parsed) {
    assert.ok("name" in p, "each provider must have name");
    assert.ok("model" in p, "each provider must have model");
    assert.equal("api_key" in p, false, `provider ${p.name} must not carry api_key on wire`);
    assert.equal("apiKey" in p, false, `provider ${p.name} must not carry apiKey on wire`);
  }
  return parsed;
}

// ── generateAnswers ─────────────────────────────────────────────────────────

test("vaultApi.generateAnswers sends `providers` (no providers_json, no api_key)", async () => {
  await vaultApi.generateAnswers({
    questionText: "why?",
    questionCategory: "motivation",
    companyName: "Acme",
    roleTitle: "SWE",
    jdText: "...",
    workHistoryText: "...",
    providers: [{ name: "anthropic", model: "claude-sonnet-4-6" }],
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.ok(calls[0].url.endsWith("/vault/generate/answers"));
  const parsed = assertProvidersField(calls[0].form);
  assert.deepEqual(parsed, [{ name: "anthropic", model: "claude-sonnet-4-6" }]);
});

// ── generateTailored ─────────────────────────────────────────────────────────

test("vaultApi.generateTailored sends `providers` (no providers_json, no api_key)", async () => {
  await vaultApi.generateTailored({
    baseResumeId: "r1",
    jdText: "jd",
    companyName: "Acme",
    providers: [{ name: "openai", model: "gpt-4o" }],
  });
  assert.ok(calls[0].url.endsWith("/vault/generate/tailored"));
  assertProvidersField(calls[0].form);
});

// ── interviewPrep ───────────────────────────────────────────────────────────

test("vaultApi.interviewPrep sends `providers` (no providers_json, no api_key)", async () => {
  await vaultApi.interviewPrep({
    companyName: "Acme",
    providers: [{ name: "anthropic", model: "claude-sonnet-4-6" }],
  });
  assert.ok(calls[0].url.endsWith("/vault/interview-prep"));
  assertProvidersField(calls[0].form);
});

// ── generateCoverLetter ─────────────────────────────────────────────────────

test("vaultApi.generateCoverLetter sends `providers` (no providers_json, no api_key)", async () => {
  await vaultApi.generateCoverLetter({
    companyName: "Acme",
    providers: [{ name: "groq", model: "llama-3.3-70b-versatile" }],
  });
  assert.ok(calls[0].url.endsWith("/vault/generate/cover-letter"));
  assertProvidersField(calls[0].form);
});

// ── trimAnswer ──────────────────────────────────────────────────────────────

test("vaultApi.trimAnswer sends `providers` (no providers_json, no api_key)", async () => {
  await vaultApi.trimAnswer({
    answerText: "long text...",
    maxChars: 100,
    providers: [{ name: "anthropic", model: "claude-sonnet-4-6" }],
  });
  assert.ok(calls[0].url.endsWith("/vault/generate/answers/trim"));
  assertProvidersField(calls[0].form);
});

// ── generateSummary ─────────────────────────────────────────────────────────

test("vaultApi.generateSummary sends `providers` (no providers_json, no api_key)", async () => {
  await vaultApi.generateSummary({
    companyName: "Acme",
    roleTitle: "SWE",
    jdText: "...",
    providers: [{ name: "anthropic", model: "claude-sonnet-4-6" }],
  });
  assert.ok(calls[0].url.endsWith("/vault/generate/summary"));
  assertProvidersField(calls[0].form);
});

// ── generateBullets ─────────────────────────────────────────────────────────

test("vaultApi.generateBullets sends `providers` (no providers_json, no api_key)", async () => {
  await vaultApi.generateBullets({
    companyName: "Acme",
    roleTitle: "SWE",
    jdText: "...",
    providers: [{ name: "openai", model: "gpt-4o" }],
  });
  assert.ok(calls[0].url.endsWith("/vault/generate/bullets"));
  assertProvidersField(calls[0].form);
});

// ── importFromResume ────────────────────────────────────────────────────────

test("workHistoryApi.importFromResume sends `providers` (no providers_json, no api_key)", async () => {
  const file = new File(["resume content"], "resume.pdf", { type: "application/pdf" });
  await workHistoryApi.importFromResume(file, [
    { name: "anthropic", model: "claude-sonnet-4-6" },
  ]);
  assert.ok(calls[0].url.endsWith("/work-history/import-from-resume"));
  assertProvidersField(calls[0].form);
});

// ── No api_key leak even when input erroneously carries one ─────────────────

test("api.ts strips api_key even if a caller accidentally passes it", async () => {
  // TypeScript would reject this, but JS callers (or buggy hooks) could still
  // attempt it. The mapper inside api.ts must hard-strip the field.
  await vaultApi.generateAnswers({
    questionText: "q",
    questionCategory: "custom",
    companyName: "Acme",
    roleTitle: "SWE",
    jdText: "",
    workHistoryText: "",
    providers: [
      // @ts-expect-error — extra prop intentionally passed to validate strip
      { name: "anthropic", model: "claude-sonnet-4-6", api_key: "LEAK", apiKey: "LEAK" },
    ],
  });
  const parsed = JSON.parse(calls[0].form.providers);
  for (const p of parsed) {
    assert.equal("api_key" in p, false);
    assert.equal("apiKey" in p, false);
  }
  // And the entire serialised body must not contain the key.
  assert.equal(calls[0].form.providers.includes("LEAK"), false, "api_key value must not appear in payload");
});
