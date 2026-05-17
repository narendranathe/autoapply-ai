/**
 * Tests for the provider-key migration module (P0 issue #198 — impl B).
 *
 * Runner: node --test --experimental-strip-types — loads the .ts module
 * directly so the production source is exercised.
 *
 * Coverage:
 *   - buildProviderList is pure and never emits api_key / apiKey.
 *   - countUnmigratedKeys / unmigratedProviderNames track banner state.
 *   - migrateProviderKey: PUT → GET verification gate.
 *   - migrateProviderKey: failure modes (PUT fails, GET fails, GET says
 *     has_key=false, network error).
 *   - stripLocalKey: pure, only the named entry loses its apiKey.
 *
 * Run:
 *   cd extension && pnpm test
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const mod = await import("../providerMigration.ts");
const {
  buildProviderList,
  countUnmigratedKeys,
  unmigratedProviderNames,
  migrateProviderKey,
  stripLocalKey,
  computeKeyFingerprint,
} = mod;

// Convenience: precompute fingerprints for the canonical test keys.
const FP_SK_ANT_XYZ = await computeKeyFingerprint("sk-ant-xyz");
const FP_SK_ANT = await computeKeyFingerprint("sk-ant");
const FP_SK_OAI = await computeKeyFingerprint("sk-oai");

// ── buildProviderList — pure, never includes a key ──────────────────────────

test("buildProviderList: empty map → []", () => {
  assert.deepEqual(buildProviderList({}), []);
});

test("buildProviderList: null / undefined → []", () => {
  assert.deepEqual(buildProviderList(null), []);
  assert.deepEqual(buildProviderList(undefined), []);
});

test("buildProviderList: never emits apiKey or api_key in output", () => {
  const out = buildProviderList({
    anthropic: { apiKey: "sk-ant-xyz", model: "claude-sonnet-4-6" },
    openai: { apiKey: "sk-oai-abc", model: "gpt-4o" },
  });
  for (const entry of out) {
    assert.ok(!("apiKey" in entry), `entry ${entry.name} leaked apiKey`);
    assert.ok(!("api_key" in entry), `entry ${entry.name} leaked api_key`);
  }
  // Spot-check expected shape — name + model only.
  assert.deepEqual(Object.keys(out[0]).sort(), ["model", "name"]);
});

test("buildProviderList: orders providers by canonical rank", () => {
  const out = buildProviderList({
    perplexity: { apiKey: "p", model: "sonar" },
    anthropic: { apiKey: "a", model: "claude-sonnet-4-6" },
    groq: { apiKey: "g", model: "llama-3.3-70b-versatile" },
    openai: { apiKey: "o", model: "gpt-4o" },
  });
  assert.deepEqual(
    out.map((p) => p.name),
    ["anthropic", "openai", "groq", "perplexity"],
  );
});

test("buildProviderList: partially-migrated map keeps post-migration entries (enabled:true, no key)", () => {
  const out = buildProviderList({
    // migrated — no apiKey, enabled remembered server-side
    anthropic: { apiKey: "", enabled: true, model: "claude-sonnet-4-6" },
    // not migrated yet — still has local key
    openai: { apiKey: "sk-oai-abc", model: "gpt-4o" },
    // never configured
    gemini: { apiKey: "", enabled: false, model: "gemini-1.5-flash" },
  });
  assert.deepEqual(
    out.map((p) => p.name),
    ["anthropic", "openai"],
  );
  for (const entry of out) {
    assert.ok(!("apiKey" in entry));
  }
});

test("buildProviderList: fully-migrated map (all keys stripped) still exposes enabled providers", () => {
  const out = buildProviderList({
    anthropic: { apiKey: "", enabled: true, model: "claude-sonnet-4-6" },
    groq: { apiKey: "", enabled: true, model: "llama-3.3-70b-versatile" },
  });
  assert.equal(out.length, 2);
  assert.deepEqual(out.map((p) => p.name).sort(), ["anthropic", "groq"]);
});

test("buildProviderList: model falls back to canonical when entry has no model", () => {
  const out = buildProviderList({
    anthropic: { apiKey: "k" },
  });
  assert.equal(out[0].model, "claude-sonnet-4-6");
});

// ── countUnmigratedKeys / unmigratedProviderNames ──────────────────────────

test("countUnmigratedKeys: counts entries that still have a local apiKey", () => {
  assert.equal(countUnmigratedKeys({}), 0);
  assert.equal(countUnmigratedKeys(null), 0);
  assert.equal(
    countUnmigratedKeys({
      anthropic: { apiKey: "a" },
      openai: { apiKey: "" },
      groq: { apiKey: "g" },
    }),
    2,
  );
});

test("unmigratedProviderNames: returns names of unmigrated providers", () => {
  const names = unmigratedProviderNames({
    anthropic: { apiKey: "a" },
    openai: { apiKey: "" },
    groq: { apiKey: "g" },
  });
  assert.deepEqual(names.sort(), ["anthropic", "groq"]);
});

// ── migrateProviderKey — PUT then GET verification ─────────────────────────

function makeFetchSequence(responses) {
  const calls = [];
  const fetchFn = async (url, init) => {
    calls.push({ url: String(url), init: init ?? {} });
    const next = responses.shift();
    if (!next) throw new Error("unexpected extra fetch call");
    if (typeof next === "function") return next(url, init);
    return next;
  };
  return { fetchFn, calls };
}

function okResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
    json: async () => body,
  };
}

const AUTH = { "X-Clerk-User-Id": "u-1" };
const BASE = "https://api.example.test/api/v1";

test("migrateProviderKey: PUT → GET verifies has_key=true → ok:true", async () => {
  const { fetchFn, calls } = makeFetchSequence([
    okResponse({ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT_XYZ }),
    okResponse({
      configs: [
        {
          provider_name: "anthropic",
          has_key: true,
          is_enabled: true,
          key_fingerprint: FP_SK_ANT_XYZ,
        },
      ],
    }),
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant-xyz", fetchFn, {
    apiBase: BASE,
    authHeaders: AUTH,
  });
  assert.deepEqual(res, { name: "anthropic", ok: true });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].init.method, "PUT");
  assert.match(calls[0].url, /\/users\/provider-configs\/anthropic$/);
  // The PUT body must include the plaintext key (TLS to server) so the
  // server can encrypt + store it.
  const body = JSON.parse(calls[0].init.body);
  assert.equal(body.api_key, "sk-ant-xyz");
  // Verification GET hits the listing endpoint.
  assert.equal(calls[1].init.method, "GET");
  assert.match(calls[1].url, /\/users\/provider-configs$/);
});

test("migrateProviderKey: empty apiKey → ok:false (does not call backend)", async () => {
  const { fetchFn, calls } = makeFetchSequence([]);
  const res = await migrateProviderKey("anthropic", "", fetchFn, { apiBase: BASE, authHeaders: AUTH });
  assert.equal(res.ok, false);
  assert.equal(calls.length, 0);
});

test("migrateProviderKey: PUT returns 500 → ok:false, no GET issued", async () => {
  const { fetchFn, calls } = makeFetchSequence([
    okResponse("internal error", 500),
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, { apiBase: BASE, authHeaders: AUTH });
  assert.equal(res.ok, false);
  assert.equal(calls.length, 1);
  assert.match(res.reason, /PUT failed: 500/);
});

test("migrateProviderKey: GET verification returns has_key=false → ok:false", async () => {
  const { fetchFn } = makeFetchSequence([
    okResponse({ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }),
    okResponse({
      configs: [{ provider_name: "anthropic", has_key: false, key_fingerprint: null }],
    }),
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, { apiBase: BASE, authHeaders: AUTH });
  assert.equal(res.ok, false);
  assert.match(res.reason, /has_key is false/);
});

test("migrateProviderKey: GET verification omits the provider → ok:false", async () => {
  const { fetchFn } = makeFetchSequence([
    okResponse({ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }),
    okResponse({
      configs: [{ provider_name: "openai", has_key: true, key_fingerprint: FP_SK_OAI }],
    }),
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, { apiBase: BASE, authHeaders: AUTH });
  assert.equal(res.ok, false);
  assert.match(res.reason, /provider missing/);
});

test("migrateProviderKey: GET verification network failure → ok:false", async () => {
  const fetchFn = async (url) => {
    if (String(url).endsWith("/users/provider-configs")) {
      throw new Error("connection refused");
    }
    return okResponse({ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT });
  };
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, { apiBase: BASE, authHeaders: AUTH });
  assert.equal(res.ok, false);
  assert.match(res.reason, /GET network error/);
});

test("migrateProviderKey: GET returns non-JSON body → ok:false", async () => {
  const { fetchFn } = makeFetchSequence([
    okResponse({ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }),
    {
      ok: true,
      status: 200,
      text: async () => "not json",
      json: async () => { throw new Error("parse"); },
    },
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, { apiBase: BASE, authHeaders: AUTH });
  assert.equal(res.ok, false);
  assert.match(res.reason, /invalid JSON/);
});

test("migrateProviderKey: includes model_override in PUT body when provided", async () => {
  const { fetchFn, calls } = makeFetchSequence([
    okResponse({ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }),
    okResponse({
      configs: [{ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }],
    }),
  ]);
  await migrateProviderKey("anthropic", "sk-ant", fetchFn, {
    apiBase: BASE,
    authHeaders: AUTH,
    modelOverride: "claude-sonnet-4-6",
  });
  const body = JSON.parse(calls[0].init.body);
  assert.equal(body.model_override, "claude-sonnet-4-6");
});

// ── P0-A fingerprint verification (#198 round 2) ───────────────────────────

test("migrateProviderKey: PUT response missing key_fingerprint → ok:false", async () => {
  // Simulates an old backend that hasn't deployed the fingerprint contract.
  const { fetchFn } = makeFetchSequence([
    okResponse({ provider_name: "anthropic", has_key: true }), // no fingerprint
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, {
    apiBase: BASE,
    authHeaders: AUTH,
  });
  assert.equal(res.ok, false);
  assert.match(res.reason, /missing key_fingerprint/);
});

test("migrateProviderKey: PUT fingerprint mismatch → ok:false (forgery defence)", async () => {
  // Simulates the attack scenario: the server has a stale row from a prior
  // PUT under a different key; the listing route returns has_key=true but
  // the fingerprint doesn't match what the client just sent.
  const { fetchFn } = makeFetchSequence([
    okResponse({
      provider_name: "anthropic",
      has_key: true,
      key_fingerprint: "deadbeef", // wrong fingerprint
    }),
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, {
    apiBase: BASE,
    authHeaders: AUTH,
  });
  assert.equal(res.ok, false);
  assert.match(res.reason, /PUT: fingerprint mismatch/);
});

test("migrateProviderKey: PUT non-JSON body → ok:false", async () => {
  const { fetchFn } = makeFetchSequence([
    {
      ok: true,
      status: 200,
      text: async () => "yo",
      json: async () => { throw new Error("parse"); },
    },
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, {
    apiBase: BASE,
    authHeaders: AUTH,
  });
  assert.equal(res.ok, false);
  assert.match(res.reason, /PUT: invalid JSON/);
});

test("migrateProviderKey: GET fingerprint mismatch → ok:false (forgery defence)", async () => {
  // The PUT echoes the correct fingerprint, but the subsequent GET
  // returns a different one — server-side rollback / race / poisoned
  // cache. Keep the local key.
  const { fetchFn } = makeFetchSequence([
    okResponse({ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }),
    okResponse({
      configs: [
        { provider_name: "anthropic", has_key: true, key_fingerprint: "deadbeef" },
      ],
    }),
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, {
    apiBase: BASE,
    authHeaders: AUTH,
  });
  assert.equal(res.ok, false);
  assert.match(res.reason, /verification: fingerprint mismatch/);
});

test("migrateProviderKey: GET missing key_fingerprint → ok:false", async () => {
  const { fetchFn } = makeFetchSequence([
    okResponse({ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }),
    okResponse({
      configs: [{ provider_name: "anthropic", has_key: true }], // no fingerprint
    }),
  ]);
  const res = await migrateProviderKey("anthropic", "sk-ant", fetchFn, {
    apiBase: BASE,
    authHeaders: AUTH,
  });
  assert.equal(res.ok, false);
  assert.match(res.reason, /verification: missing key_fingerprint/);
});

test("computeKeyFingerprint: deterministic + 8 hex chars + matches backend sha256[:8]", async () => {
  const fp = await computeKeyFingerprint("sk-ant-xyz");
  assert.equal(fp.length, 8);
  assert.match(fp, /^[0-9a-f]{8}$/);
  // sha256("sk-ant-xyz") starts with these 8 hex chars (per node crypto):
  // verified once and pinned.
  const { createHash } = await import("node:crypto");
  const expected = createHash("sha256").update("sk-ant-xyz").digest("hex").slice(0, 8);
  assert.equal(fp, expected);
});

// ── stripLocalKey — pure helper, single-row mutation ───────────────────────

test("stripLocalKey: clears apiKey on the named entry only", () => {
  const before = {
    anthropic: { apiKey: "a", model: "claude-sonnet-4-6" },
    openai: { apiKey: "o", model: "gpt-4o" },
  };
  const after = stripLocalKey(before, "anthropic");
  assert.equal(after.anthropic.apiKey, "");
  assert.equal(after.anthropic.enabled, true);
  assert.equal(after.openai.apiKey, "o"); // untouched
  // ``before`` must be untouched — pure helper
  assert.equal(before.anthropic.apiKey, "a");
});

test("stripLocalKey: unknown provider → original map returned unchanged", () => {
  const before = { anthropic: { apiKey: "a", model: "claude-sonnet-4-6" } };
  const after = stripLocalKey(before, "unknown-provider");
  assert.equal(after, before);
});

// ── End-to-end migration sequence ──────────────────────────────────────────

test("migration sequence: two providers, one succeeds + one fails → partial state", async () => {
  // The first migration succeeds (anthropic), the second (openai) fails the
  // verification GET. The caller would strip anthropic but leave openai.
  let configs = {
    anthropic: { apiKey: "sk-ant", model: "claude-sonnet-4-6" },
    openai: { apiKey: "sk-oai", model: "gpt-4o" },
  };

  const { fetchFn } = makeFetchSequence([
    okResponse({ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }),
    okResponse({
      configs: [{ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }],
    }),
    okResponse({ provider_name: "openai", has_key: true, key_fingerprint: FP_SK_OAI }),
    okResponse({
      configs: [{ provider_name: "anthropic", has_key: true, key_fingerprint: FP_SK_ANT }],
    }), // openai missing
  ]);

  const r1 = await migrateProviderKey("anthropic", configs.anthropic.apiKey, fetchFn, { apiBase: BASE, authHeaders: AUTH });
  if (r1.ok) configs = stripLocalKey(configs, "anthropic");

  const r2 = await migrateProviderKey("openai", configs.openai.apiKey, fetchFn, { apiBase: BASE, authHeaders: AUTH });
  if (r2.ok) configs = stripLocalKey(configs, "openai");

  assert.equal(r1.ok, true);
  assert.equal(r2.ok, false);
  // anthropic key gone, openai key still local
  assert.equal(configs.anthropic.apiKey, "");
  assert.equal(configs.openai.apiKey, "sk-oai");
  // Banner count reflects the one remaining unmigrated key
  assert.equal(countUnmigratedKeys(configs), 1);
  assert.deepEqual(unmigratedProviderNames(configs), ["openai"]);
});
