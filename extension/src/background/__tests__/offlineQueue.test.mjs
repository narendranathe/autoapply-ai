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

test("successful 2xx → entry marked synced, not dead-lettered", async () => {
  const queue = [makeEdit()];
  const result = await processOfflineQueue(queue, fetchScript([okResponse()]));
  assert.equal(result.syncedCount, 1);
  assert.equal(result.newlyDeadLettered.length, 0);
  assert.equal(result.active.length, 1);
  assert.equal(result.active[0].synced, true);
});

test("non-2xx response increments failureCount and captures lastError", async () => {
  const queue = [makeEdit()];
  const result = await processOfflineQueue(queue, fetchScript([errResponse(503)]));
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
  );
  assert.equal(result.active[0].failureCount, 1);
  assert.equal(result.active[0].lastError, "ECONNREFUSED");
});

test("job failing 3× → moves to dead-letter", async () => {
  let entry = makeEdit();

  let r = await processOfflineQueue([entry], fetchScript([errResponse(500)]));
  assert.equal(r.newlyDeadLettered.length, 0);
  assert.equal(r.active[0].failureCount, 1);
  entry = r.active[0];

  r = await processOfflineQueue([entry], fetchScript([errResponse(500)]));
  assert.equal(r.newlyDeadLettered.length, 0);
  assert.equal(r.active[0].failureCount, 2);
  entry = r.active[0];

  r = await processOfflineQueue([entry], fetchScript([errResponse(500)]));
  assert.equal(r.newlyDeadLettered.length, 1);
  assert.equal(r.newlyDeadLettered[0].failureCount, 3);
  assert.equal(r.newlyDeadLettered[0].lastError, "HTTP 500");
  assert.equal(r.active.length, 0);
});

test("job succeeding on 2nd retry → stays out of dead-letter", async () => {
  let entry = makeEdit();

  let r = await processOfflineQueue([entry], fetchScript([errResponse(500)]));
  assert.equal(r.active[0].failureCount, 1);
  entry = r.active[0];

  r = await processOfflineQueue([entry], fetchScript([okResponse()]));
  assert.equal(r.syncedCount, 1);
  assert.equal(r.newlyDeadLettered.length, 0);
  assert.equal(r.active.length, 1);
  assert.equal(r.active[0].synced, true);
  assert.equal(r.active[0].failureCount, 1);
});

test("already-synced entries are passed through unchanged", async () => {
  const synced = makeEdit({ id: "edit-synced", synced: true });
  const pending = makeEdit({ id: "edit-pending" });
  const fetchFn = fetchScript([okResponse()]);
  const r = await processOfflineQueue([synced, pending], fetchFn);
  assert.equal(r.active.length, 2);
  assert.equal(r.syncedCount, 1);
  assert.equal(r.active.find((e) => e.id === "edit-synced").synced, true);
});

test("mixed batch: one syncs, one dead-letters, one retries", async () => {
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
  const r = await processOfflineQueue(queue, fetchFn);
  assert.equal(r.syncedCount, 1);
  assert.equal(r.newlyDeadLettered.length, 1);
  assert.equal(r.newlyDeadLettered[0].id, "b");
  assert.equal(r.newlyDeadLettered[0].failureCount, 3);
  assert.equal(r.active.length, 2);
  const c = r.active.find((e) => e.id === "c");
  assert.equal(c.failureCount, 2);
  assert.equal(c.lastError, "HTTP 502");
});

test("undefined failureCount on legacy entries defaults to 0", async () => {
  const legacy = {
    id: "legacy",
    versionTag: "v1",
    markdownContent: "# x",
    timestamp: 1,
    synced: false,
  };
  const r = await processOfflineQueue([legacy], fetchScript([errResponse(500)]));
  assert.equal(r.active[0].failureCount, 1);
});
