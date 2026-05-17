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

const { processOfflineQueue, MAX_OFFLINE_RETRY } = await import(queueModulePath);

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
