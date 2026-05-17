/**
 * Tests for the read-modify-write race protection in
 * ``migrateProviderKeysOnClick`` (P1-B, #198 round 2).
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
 * These tests exercise the pure pieces of the loop logic (``stripLocalKey``
 * + an in-memory simulation of the storage) so they run without a real
 * browser.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const { stripLocalKey } = await import("../../shared/providerMigration.ts");

/**
 * Simulate the post-migration "merge then write" step in isolation.
 *
 * @param {string} name           provider to strip
 * @param {object} workingCopy    the migration loop's local copy
 * @param {object} freshFromDisk  what chrome.storage.local.get returns now
 * @returns {object}              what would be written via .set()
 */
function mergeStrip(name, workingCopy, freshFromDisk) {
  const latest = freshFromDisk ?? workingCopy;
  return stripLocalKey(latest, name);
}

test("P1-B: re-read before write preserves a concurrent edit to another row", () => {
  // Tab A reads {anthropic: KEY-A, openai: KEY-O-OLD} at loop start.
  const workingCopy = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
    openai: { apiKey: "KEY-O-OLD", model: "gpt-4o" },
  };
  // Between PUT and SET, Tab B updates ``openai`` to KEY-O-NEW.
  const freshFromDisk = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
    openai: { apiKey: "KEY-O-NEW", model: "gpt-4o" },
  };

  const written = mergeStrip("anthropic", workingCopy, freshFromDisk);

  // Anthropic's apiKey is stripped (the explicit mutation we wanted).
  assert.equal(written.anthropic.apiKey, "");
  assert.equal(written.anthropic.enabled, true);
  // OpenAI's concurrent update is preserved (this is the race we close).
  assert.equal(written.openai.apiKey, "KEY-O-NEW");
});

test("P1-B: re-read picks up a brand new row added by another tab", () => {
  const workingCopy = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
  };
  // Tab B added a new ``groq`` row.
  const freshFromDisk = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
    groq: { apiKey: "KEY-G", model: "llama-3.3-70b-versatile" },
  };

  const written = mergeStrip("anthropic", workingCopy, freshFromDisk);

  assert.equal(written.anthropic.apiKey, "");
  // groq survives — without the merge it would have been gone.
  assert.equal(written.groq.apiKey, "KEY-G");
});

test("P1-B: when storage is unchanged the merge is a no-op besides our strip", () => {
  const workingCopy = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
    openai: { apiKey: "KEY-O", model: "gpt-4o" },
  };

  const written = mergeStrip("anthropic", workingCopy, workingCopy);

  assert.equal(written.anthropic.apiKey, "");
  assert.equal(written.openai.apiKey, "KEY-O");
});

test("P1-B: if the freshest snapshot lost our row (other tab deleted it), still don't crash", () => {
  // Tab B deleted the anthropic row entirely while we were migrating
  // it. stripLocalKey returns the input unchanged when the name is
  // missing, which is the correct safe behaviour — we don't resurrect
  // a row another tab decided to remove.
  const workingCopy = {
    anthropic: { apiKey: "KEY-A", model: "claude-sonnet-4-6" },
  };
  const freshFromDisk = {};

  const written = mergeStrip("anthropic", workingCopy, freshFromDisk);

  assert.deepEqual(written, {});
});
