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

const {
  processOfflineQueue,
  MAX_OFFLINE_RETRY,
  resolveSyncEndpoint,
  DEFAULT_API_BASE,
  SYNC_MARKDOWN_PATH,
} = await import(queueModulePath);

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

// ───────────────────────────────────────────────────────────────────────────
// Issue #91 — drainOfflineQueue must read apiBaseUrl from chrome.storage.local
// ───────────────────────────────────────────────────────────────────────────
//
// drainOfflineQueue() in worker.ts previously hardcoded http://localhost:8000
// regardless of what the user had configured, silently dropping offline edits
// in production. The fix routes URL resolution through resolveSyncEndpoint()
// which reads `apiBaseUrl` out of a chrome.storage.local-shaped object.
//
// These tests pin the public contract of resolveSyncEndpoint and exercise the
// end-to-end "mock chrome.storage.local → drainOfflineQueue posts to the
// configured base" path via a faked storage layer.

test("resolveSyncEndpoint: uses apiBaseUrl from storage when set", () => {
  const got = resolveSyncEndpoint({ apiBaseUrl: "https://api.example.com/api/v1" });
  assert.equal(got, "https://api.example.com/api/v1/vault/sync-markdown");
});

test("resolveSyncEndpoint: prefers a user-configured localhost over the prod default", () => {
  // A developer with localhost:8000 saved in storage should hit their own
  // backend, not the fly.dev production host.
  const got = resolveSyncEndpoint({ apiBaseUrl: "http://localhost:8000/api/v1" });
  assert.equal(got, "http://localhost:8000/api/v1/vault/sync-markdown");
});

test("resolveSyncEndpoint: falls back to DEFAULT_API_BASE when storage is empty", () => {
  // Critical regression guard for issue #91: must NOT default to localhost.
  const got = resolveSyncEndpoint({});
  assert.equal(got, `${DEFAULT_API_BASE}${SYNC_MARKDOWN_PATH}`);
  assert.ok(!got.includes("localhost"), "fallback must not contain localhost");
});

test("resolveSyncEndpoint: falls back when apiBaseUrl is missing / undefined / empty string", () => {
  const expected = `${DEFAULT_API_BASE}${SYNC_MARKDOWN_PATH}`;
  assert.equal(resolveSyncEndpoint(undefined), expected);
  assert.equal(resolveSyncEndpoint(null), expected);
  assert.equal(resolveSyncEndpoint({ apiBaseUrl: undefined }), expected);
  assert.equal(resolveSyncEndpoint({ apiBaseUrl: "" }), expected);
});

test("resolveSyncEndpoint: rejects non-string apiBaseUrl values", () => {
  // Defensive — if storage is corrupted (number, object, null) we still fall
  // back to the prod default rather than producing an unusable URL.
  const expected = `${DEFAULT_API_BASE}${SYNC_MARKDOWN_PATH}`;
  assert.equal(resolveSyncEndpoint({ apiBaseUrl: 8000 }), expected);
  assert.equal(resolveSyncEndpoint({ apiBaseUrl: null }), expected);
  assert.equal(resolveSyncEndpoint({ apiBaseUrl: { url: "x" } }), expected);
});

test("DEFAULT_API_BASE points at production, never localhost", () => {
  // Belt-and-suspenders: if someone ever flips this to localhost, the test
  // suite must fail loudly.
  assert.ok(
    !DEFAULT_API_BASE.includes("localhost"),
    `DEFAULT_API_BASE must not be localhost; got ${DEFAULT_API_BASE}`,
  );
  assert.ok(DEFAULT_API_BASE.startsWith("https://"), "DEFAULT_API_BASE must be https://");
});

test("drainOfflineQueue path: chrome.storage.local.apiBaseUrl flows through to fetch URL", async () => {
  // End-to-end-ish: simulate the exact code path drainOfflineQueue takes —
  // read from a faked chrome.storage.local, resolve the endpoint, then run
  // processOfflineQueue with a capturing fetch. The URL we assert is what
  // the worker would actually POST to in production.
  const storageData = {
    apiBaseUrl: "https://staging.example.com/api/v1",
    offline_queue: [makeEdit({ id: "e-1" })],
  };
  const chromeStorageLocal = {
    get: async (keys) => {
      const arr = Array.isArray(keys) ? keys : [keys];
      const out = {};
      for (const k of arr) if (k in storageData) out[k] = storageData[k];
      return out;
    },
  };

  // Mirror the read drainOfflineQueue performs.
  const stored = await chromeStorageLocal.get(["offline_queue", "apiBaseUrl"]);
  const endpoint = resolveSyncEndpoint(stored);

  const capturedUrls = [];
  const capturingFetch = async (url) => {
    capturedUrls.push(url);
    return okResponse();
  };

  const result = await processOfflineQueue(stored.offline_queue, capturingFetch, endpoint);

  assert.equal(result.syncedCount, 1);
  assert.equal(capturedUrls.length, 1);
  assert.equal(capturedUrls[0], "https://staging.example.com/api/v1/vault/sync-markdown");
  assert.ok(!capturedUrls[0].includes("localhost"));
});

test("drainOfflineQueue path: empty chrome.storage.local does NOT post to localhost", async () => {
  // The original bug: user never configured apiBaseUrl, queue drains to
  // http://localhost:8000 in production. This test pins the fix.
  const storageData = {
    // apiBaseUrl deliberately absent.
    offline_queue: [makeEdit({ id: "e-1" })],
  };
  const chromeStorageLocal = {
    get: async (keys) => {
      const arr = Array.isArray(keys) ? keys : [keys];
      const out = {};
      for (const k of arr) if (k in storageData) out[k] = storageData[k];
      return out;
    },
  };

  const stored = await chromeStorageLocal.get(["offline_queue", "apiBaseUrl"]);
  const endpoint = resolveSyncEndpoint(stored);

  const capturedUrls = [];
  const capturingFetch = async (url) => {
    capturedUrls.push(url);
    return okResponse();
  };

  await processOfflineQueue(stored.offline_queue, capturingFetch, endpoint);

  assert.equal(capturedUrls.length, 1);
  assert.ok(
    !capturedUrls[0].includes("localhost"),
    `drain must not post to localhost when storage is empty; got ${capturedUrls[0]}`,
  );
  assert.equal(capturedUrls[0], `${DEFAULT_API_BASE}${SYNC_MARKDOWN_PATH}`);
});
