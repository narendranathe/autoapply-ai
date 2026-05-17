/**
 * Tests for the offline queue dead-letter mechanism (issue #106).
 *
 * Test infrastructure: node --test (built-in) + --experimental-strip-types
 * so we can import the TS module directly. processOfflineQueue is a pure
 * function — no DOM/chrome globals needed at import time.
 *
 * Run:
 *   cd extension && node --test --experimental-strip-types \
 *     src/background/__tests__/offlineQueue.test.mjs
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const queueModulePath = path.resolve(__dirname, "../offlineQueue.ts");

const { processOfflineQueue, MAX_OFFLINE_RETRY, resolveDrainEndpoint, DEV_FALLBACK_API_BASE } =
  await import(queueModulePath);

// Tests pass an explicit endpoint — there is no module-level default any more.
const TEST_ENDPOINT = "https://test.example.com/api/v1/vault/sync-markdown";

function makeEdit(overrides = {}) {
  return {
    id: "edit-1",
    versionTag: "v1",
    markdownContent: "# hello",
    timestamp: 1700000000,
    synced: false,
    failureCount: 0,
    ...overrides,
  };
}

function okResponse() {
  return { ok: true, status: 200 };
}

function errResponse(status = 500) {
  return { ok: false, status };
}

function fetchScript(responses) {
  let i = 0;
  return async () => {
    const next = responses[i++];
    if (next instanceof Error) throw next;
    return next;
  };
}

test("MAX_OFFLINE_RETRY is 3", () => {
  assert.equal(MAX_OFFLINE_RETRY, 3);
});

test("successful 2xx → entry marked synced and DROPPED from active", async () => {
  const queue = [makeEdit()];
  const result = await processOfflineQueue(queue, fetchScript([okResponse()]), TEST_ENDPOINT);
  assert.equal(result.syncedCount, 1);
  assert.equal(result.newlyDeadLettered.length, 0);
  // Synced entries must NOT accumulate in active — the queue would otherwise
  // grow unboundedly across drains.
  assert.equal(result.active.length, 0);
});

test("non-2xx response increments failureCount and captures lastError", async () => {
  const queue = [makeEdit()];
  const result = await processOfflineQueue(queue, fetchScript([errResponse(503)]), TEST_ENDPOINT);
  assert.equal(result.syncedCount, 0);
  assert.equal(result.newlyDeadLettered.length, 0);
  assert.equal(result.active.length, 1);
  assert.equal(result.active[0].failureCount, 1);
  assert.equal(result.active[0].lastError, "HTTP 503");
  assert.equal(result.active[0].synced, false);
});

test("thrown fetch error captured in lastError", async () => {
  const queue = [makeEdit()];
  const result = await processOfflineQueue(
    queue,
    fetchScript([new Error("ECONNREFUSED")]),
    TEST_ENDPOINT,
  );
  assert.equal(result.active[0].failureCount, 1);
  assert.equal(result.active[0].lastError, "ECONNREFUSED");
});

test("job failing 3× → moves to dead-letter", async () => {
  let entry = makeEdit();

  let r = await processOfflineQueue([entry], fetchScript([errResponse(500)]), TEST_ENDPOINT);
  assert.equal(r.newlyDeadLettered.length, 0);
  assert.equal(r.active[0].failureCount, 1);
  entry = r.active[0];

  r = await processOfflineQueue([entry], fetchScript([errResponse(500)]), TEST_ENDPOINT);
  assert.equal(r.newlyDeadLettered.length, 0);
  assert.equal(r.active[0].failureCount, 2);
  entry = r.active[0];

  r = await processOfflineQueue([entry], fetchScript([errResponse(500)]), TEST_ENDPOINT);
  assert.equal(r.newlyDeadLettered.length, 1);
  assert.equal(r.newlyDeadLettered[0].failureCount, 3);
  assert.equal(r.newlyDeadLettered[0].lastError, "HTTP 500");
  assert.equal(r.active.length, 0);
});

test("job succeeding on 2nd retry → stays out of dead-letter and out of active", async () => {
  let entry = makeEdit();

  let r = await processOfflineQueue([entry], fetchScript([errResponse(500)]), TEST_ENDPOINT);
  assert.equal(r.active[0].failureCount, 1);
  entry = r.active[0];

  r = await processOfflineQueue([entry], fetchScript([okResponse()]), TEST_ENDPOINT);
  assert.equal(r.syncedCount, 1);
  assert.equal(r.newlyDeadLettered.length, 0);
  // Once synced, the entry is removed from the active queue — it does not
  // hang around with synced=true.
  assert.equal(r.active.length, 0);
});

test("already-synced entries (no prior failures) are REMOVED from active", async () => {
  const synced = makeEdit({ id: "edit-synced", synced: true });
  const pending = makeEdit({ id: "edit-pending" });
  const fetchFn = fetchScript([okResponse()]);
  const r = await processOfflineQueue([synced, pending], fetchFn, TEST_ENDPOINT);
  // Both entries end up synced. Neither should remain in active — that's the
  // whole point of the unbounded-growth fix. The pending edit was just
  // POSTed this pass (syncedCount=1) and the pre-synced entry is dropped.
  assert.equal(r.syncedCount, 1);
  assert.equal(r.active.length, 0);
  assert.equal(r.newlyDeadLettered.length, 0);
});

test("synced entry with prior failureCount > 0 moves to dead-letter, not active", async () => {
  // A previously-failing entry that finally synced but carries a non-zero
  // failure history should be preserved in the dead-letter pile so the user
  // can see "this one had trouble" — but not in active (it's done).
  const syncedWithHistory = makeEdit({
    id: "edit-bumpy",
    synced: true,
    failureCount: 2,
    lastError: "HTTP 502",
  });
  const r = await processOfflineQueue([syncedWithHistory], fetchScript([]), TEST_ENDPOINT);
  assert.equal(r.syncedCount, 0); // Already synced — not POSTed again this pass.
  assert.equal(r.active.length, 0);
  assert.equal(r.newlyDeadLettered.length, 1);
  assert.equal(r.newlyDeadLettered[0].id, "edit-bumpy");
  assert.equal(r.newlyDeadLettered[0].failureCount, 2);
});

test("mixed batch: one syncs (dropped from active), one dead-letters, one retries", async () => {
  const queue = [
    makeEdit({ id: "a" }),
    makeEdit({ id: "b", failureCount: 2 }),
    makeEdit({ id: "c", failureCount: 1 }),
  ];
  const fetchFn = fetchScript([
    okResponse(),
    errResponse(502),
    errResponse(502),
  ]);
  const r = await processOfflineQueue(queue, fetchFn, TEST_ENDPOINT);
  assert.equal(r.syncedCount, 1);
  assert.equal(r.newlyDeadLettered.length, 1);
  assert.equal(r.newlyDeadLettered[0].id, "b");
  assert.equal(r.newlyDeadLettered[0].failureCount, 3);
  // 'a' is dropped from active (synced); 'c' remains for another retry.
  assert.equal(r.active.length, 1);
  assert.equal(r.active[0].id, "c");
  assert.equal(r.active[0].failureCount, 2);
  assert.equal(r.active[0].lastError, "HTTP 502");
});

test("undefined failureCount on legacy entries defaults to 0", async () => {
  const legacy = {
    id: "legacy",
    versionTag: "v1",
    markdownContent: "# x",
    timestamp: 1,
    synced: false,
  };
  const r = await processOfflineQueue([legacy], fetchScript([errResponse(500)]), TEST_ENDPOINT);
  assert.equal(r.active[0].failureCount, 1);
});

test("processOfflineQueue requires an explicit endpoint (no default)", async () => {
  // Regression guard: previously SYNC_ENDPOINT defaulted to localhost, which
  // silently broke production drains. Endpoint is now required.
  const queue = [makeEdit()];
  await assert.rejects(
    () => processOfflineQueue(queue, fetchScript([okResponse()])),
    /endpoint is required/,
  );
  await assert.rejects(
    () => processOfflineQueue(queue, fetchScript([okResponse()]), ""),
    /endpoint is required/,
  );
});

// ── resolveDrainEndpoint: issue #91 — apiBaseUrl from storage ─────────────

test("resolveDrainEndpoint: configured prod URL wins over dev fallback", () => {
  // Prod build, prod URL configured → use it. The dev fallback must NOT shadow
  // a real apiBaseUrl just because isDev happens to be true.
  const r = resolveDrainEndpoint("https://autoapply-ai-api.fly.dev/api/v1", false);
  assert.equal(r.ok, true);
  assert.equal(r.endpoint, "https://autoapply-ai-api.fly.dev/api/v1/vault/sync-markdown");
  assert.equal(r.usedFallback, false);
});

test("resolveDrainEndpoint: configured prod URL used even when isDev=true", () => {
  // If the user explicitly configured an API base, honor it regardless of build
  // mode — they may be pointing a dev build at a staging server.
  const r = resolveDrainEndpoint("https://staging.example.com/api/v1", true);
  assert.equal(r.ok, true);
  assert.equal(r.endpoint, "https://staging.example.com/api/v1/vault/sync-markdown");
  assert.equal(r.usedFallback, false);
});

test("resolveDrainEndpoint: trailing slash in configured URL is normalized", () => {
  const r = resolveDrainEndpoint("https://api.example.com/api/v1/", false);
  assert.equal(r.ok, true);
  assert.equal(r.endpoint, "https://api.example.com/api/v1/vault/sync-markdown");
});

test("resolveDrainEndpoint: missing URL in dev → localhost fallback", () => {
  const r = resolveDrainEndpoint(undefined, true);
  assert.equal(r.ok, true);
  assert.equal(r.usedFallback, true);
  assert.equal(r.endpoint, `${DEV_FALLBACK_API_BASE}/vault/sync-markdown`);
});

test("resolveDrainEndpoint: empty string URL in dev → localhost fallback", () => {
  // Defensive: storage returning "" should behave like "missing".
  const r = resolveDrainEndpoint("", true);
  assert.equal(r.ok, true);
  assert.equal(r.usedFallback, true);
});

test("resolveDrainEndpoint: whitespace-only URL in dev → localhost fallback", () => {
  const r = resolveDrainEndpoint("   ", true);
  assert.equal(r.ok, true);
  assert.equal(r.usedFallback, true);
});

test("resolveDrainEndpoint: missing URL in PROD → ok:false (preserve queue)", () => {
  // The core of issue #91: when no apiBaseUrl is configured and we're in a
  // production build, we MUST NOT default to localhost. The caller is expected
  // to skip the drain and leave queue entries in place for a future retry.
  const r = resolveDrainEndpoint(undefined, false);
  assert.equal(r.ok, false);
  assert.equal(r.reason, "missing_in_prod");
});

test("resolveDrainEndpoint: empty URL in PROD → ok:false", () => {
  const r = resolveDrainEndpoint("", false);
  assert.equal(r.ok, false);
});

// ── End-to-end: chrome.storage.local mock + drain ─────────────────────────

/**
 * Lightweight `chrome.storage.local` mock that snapshots the keys requested,
 * mirroring the real API surface used in drainOfflineQueue.
 */
function makeChromeStorageMock(initial) {
  const store = { ...initial };
  return {
    get: async (keys) => {
      const out = {};
      const list = Array.isArray(keys) ? keys : [keys];
      for (const k of list) out[k] = store[k];
      return out;
    },
    set: async (patch) => {
      Object.assign(store, patch);
    },
    _store: store,
  };
}

test("drain reads apiBaseUrl from chrome.storage.local and POSTs to prod URL", async () => {
  // Simulates the worker code path: storage returns a production URL, we
  // resolve the endpoint, then process the queue against that endpoint.
  const PROD_URL = "https://autoapply-ai-api.fly.dev/api/v1";
  const storage = makeChromeStorageMock({
    offline_queue: [makeEdit({ id: "prod-edit" })],
    apiBaseUrl: PROD_URL,
  });

  const stored = await storage.get(["offline_queue", "apiBaseUrl"]);
  assert.equal(stored.apiBaseUrl, PROD_URL);

  const resolved = resolveDrainEndpoint(stored.apiBaseUrl, /* isDev */ false);
  assert.equal(resolved.ok, true);
  assert.equal(resolved.endpoint, `${PROD_URL}/vault/sync-markdown`);

  // Capture the URL the drain actually hits — this is the bug regression guard.
  const calls = [];
  const recordingFetch = async (url, init) => {
    calls.push({ url, method: init?.method });
    return okResponse();
  };

  const result = await processOfflineQueue(stored.offline_queue, recordingFetch, resolved.endpoint);
  assert.equal(result.syncedCount, 1);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `${PROD_URL}/vault/sync-markdown`);
  assert.equal(calls[0].method, "POST");
  // No `localhost` anywhere in the actual request URL.
  assert.equal(/localhost/.test(calls[0].url), false);
});

test("drain with missing apiBaseUrl in prod PRESERVES queue (no fetch)", async () => {
  // Storage has queued edits but NO apiBaseUrl. In a prod build the caller
  // must skip the drain and leave the queue intact for a future retry.
  const storage = makeChromeStorageMock({
    offline_queue: [makeEdit({ id: "stuck-edit" }), makeEdit({ id: "stuck-edit-2" })],
    // apiBaseUrl deliberately absent
  });

  const stored = await storage.get(["offline_queue", "apiBaseUrl"]);
  assert.equal(stored.apiBaseUrl, undefined);

  const resolved = resolveDrainEndpoint(stored.apiBaseUrl, /* isDev */ false);
  assert.equal(resolved.ok, false);

  // The worker short-circuits before calling fetch. Simulate that: we must NOT
  // touch processOfflineQueue (it would require a real endpoint), and we must
  // NOT mutate the queue.
  let fetchCalled = false;
  const recordingFetch = async () => {
    fetchCalled = true;
    return okResponse();
  };

  if (resolved.ok) {
    // Should not reach here; included for type narrowing parity with worker.ts.
    await processOfflineQueue(stored.offline_queue, recordingFetch, resolved.endpoint);
  }

  assert.equal(fetchCalled, false);
  // Queue still has both entries — the bug fix is "don't drop on misconfigured URL".
  assert.equal(storage._store.offline_queue.length, 2);
  assert.equal(storage._store.offline_queue[0].id, "stuck-edit");
  assert.equal(storage._store.offline_queue[1].id, "stuck-edit-2");
});

test("drain with missing apiBaseUrl in DEV uses localhost fallback", async () => {
  // Dev convenience path: no configured URL but isDev=true → localhost.
  const storage = makeChromeStorageMock({
    offline_queue: [makeEdit({ id: "dev-edit" })],
  });

  const stored = await storage.get(["offline_queue", "apiBaseUrl"]);
  const resolved = resolveDrainEndpoint(stored.apiBaseUrl, /* isDev */ true);
  assert.equal(resolved.ok, true);
  assert.equal(resolved.usedFallback, true);
  assert.equal(resolved.endpoint, `${DEV_FALLBACK_API_BASE}/vault/sync-markdown`);

  const calls = [];
  const recordingFetch = async (url) => {
    calls.push(url);
    return okResponse();
  };
  const result = await processOfflineQueue(stored.offline_queue, recordingFetch, resolved.endpoint);
  assert.equal(result.syncedCount, 1);
  assert.equal(calls[0], `${DEV_FALLBACK_API_BASE}/vault/sync-markdown`);
});
