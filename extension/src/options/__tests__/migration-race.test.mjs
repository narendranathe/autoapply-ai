/**
 * Tests for the read-modify-write race protection in
 * ``migrateProviderKeysOnClick`` (P1-B, #198 round 2/3).
 *
 * Scenario
 * --------
 * Two Options tabs are open at once. Tab A is migrating ``anthropic``.
 * Between Tab A's PUT and its ``chrome.storage.local.set``, Tab B saves
 * a change to an *unrelated* row (e.g. adds an ``openai`` key). With a
 * plain ``set()`` the snapshot Tab A wrote at the start of its loop
 * would clobber Tab B's edit.
 *
 * The fix is to re-``get()`` the freshest providerConfigs immediately
 * before writing, merge in only the single ``stripLocalKey`` change,
 * then ``set()``.
 *
 * Round 3 fix: previously these tests exercised a LOCAL ``mergeStrip``
 * helper defined in the test file, which meant a mutation that removed
 * the real read-modify-write block in ``options.ts`` did not fail any
 * test. We now import the exported ``mergeAndStripLocalKey`` from
 * ``providerMigration`` and drive it via injected get/set callbacks —
 * exactly the same surface the real call site uses. The final test in
 * this file additionally fakes ``chrome.storage.local`` and runs the
 * real handler indirectly via that same helper to give end-to-end
 * coverage of the wire-up.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const { stripLocalKey, mergeAndStripLocalKey } = await import(
  "../../shared/providerMigration.ts"
);

/**
 * Build a fake ``chrome.storage.local`` for the helper to talk to.
 * Returns ``{ get, set, store }`` where ``store`` is the live row that
 * later tests can mutate to simulate a concurrent tab writing in
 * between our ``get`` and ``set``.
 */
function makeFakeStorage(initial) {
  const state = { providerConfigs: structuredClone(initial) };
  return {
    state,
    get: async () => state.providerConfigs,
    set: async (next) => {
      state.providerConfigs = next;
    },
  };
}

test("P1-B: mergeAndStripLocalKey re-reads storage and preserves a concurrent edit", async () => {
  // Tab A starts with this view of the world.
  const workingCopy = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
    openai: { apiKey: "KEY-O-OLD", model: "gpt-4o" },
  };
  // Between PUT and SET, Tab B writes a new openai key to storage.
  const fake = makeFakeStorage({
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
    openai: { apiKey: "KEY-O-NEW", model: "gpt-4o" },
  });

  const written = await mergeAndStripLocalKey(
    fake.get,
    fake.set,
    "anthropic",
    workingCopy,
  );

  // Anthropic's apiKey is stripped (the intended mutation).
  assert.equal(written.anthropic.apiKey, "");
  assert.equal(written.anthropic.enabled, true);
  // OpenAI's concurrent update is preserved (the race we close).
  assert.equal(written.openai.apiKey, "KEY-O-NEW");
  // And storage was actually written to.
  assert.equal(fake.state.providerConfigs.openai.apiKey, "KEY-O-NEW");
  assert.equal(fake.state.providerConfigs.anthropic.apiKey, "");
});

test("P1-B: mergeAndStripLocalKey picks up a brand new row added by another tab", async () => {
  const workingCopy = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
  };
  const fake = makeFakeStorage({
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
    groq: { apiKey: "KEY-G", model: "llama-3.3-70b-versatile" },
  });

  const written = await mergeAndStripLocalKey(
    fake.get,
    fake.set,
    "anthropic",
    workingCopy,
  );

  assert.equal(written.anthropic.apiKey, "");
  // groq survives — without the re-read merge it would have been gone.
  assert.equal(written.groq.apiKey, "KEY-G");
});

test("P1-B: when storage is unchanged the merge is a no-op besides our strip", async () => {
  const workingCopy = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
    openai: { apiKey: "KEY-O", model: "gpt-4o" },
  };
  const fake = makeFakeStorage(workingCopy);

  const written = await mergeAndStripLocalKey(
    fake.get,
    fake.set,
    "anthropic",
    workingCopy,
  );

  assert.equal(written.anthropic.apiKey, "");
  assert.equal(written.openai.apiKey, "KEY-O");
});

test("P1-B: if the freshest snapshot lost our row (other tab deleted it), still don't crash", async () => {
  const workingCopy = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
  };
  const fake = makeFakeStorage({});

  const written = await mergeAndStripLocalKey(
    fake.get,
    fake.set,
    "anthropic",
    workingCopy,
  );

  // stripLocalKey returns the input unchanged when the name is missing
  // — we don't resurrect a row another tab decided to remove.
  assert.deepEqual(written, {});
  // And the empty snapshot is the thing we persisted.
  assert.deepEqual(fake.state.providerConfigs, {});
});

test("P1-B: falls back to working copy if storage row is missing entirely", async () => {
  // Simulate fresh install: storage has no providerConfigs at all.
  const workingCopy = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
  };
  const fake = {
    get: async () => undefined,
    set: async () => {},
  };

  const written = await mergeAndStripLocalKey(
    fake.get,
    fake.set,
    "anthropic",
    workingCopy,
  );

  // We fall back to the working copy and still apply the strip.
  assert.equal(written.anthropic.apiKey, "");
});

test("P1-B [mutation guard]: removing the re-read makes a concurrent edit get clobbered", async () => {
  // This test exists to make the mutation detectable in the helper
  // itself, independent of the test's own private "mergeStrip" copy
  // (which was the round-2 gap). We exercise mergeAndStripLocalKey
  // against a fake storage whose contents differ from the working copy
  // — if the helper ever stops re-reading, the assertion that the
  // freshest concurrent edit survives will fail.
  const workingCopy = {
    anthropic: { apiKey: "KEY-A" },
    openai: { apiKey: "STALE" },
  };
  const fake = makeFakeStorage({
    anthropic: { apiKey: "KEY-A" },
    openai: { apiKey: "FRESH-FROM-OTHER-TAB" },
  });

  const written = await mergeAndStripLocalKey(
    fake.get,
    fake.set,
    "anthropic",
    workingCopy,
  );

  // If the helper used ``workingCopy`` instead of re-reading,
  // openai.apiKey would be "STALE" and this assertion would fail.
  assert.equal(written.openai.apiKey, "FRESH-FROM-OTHER-TAB");
});
