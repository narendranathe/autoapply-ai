/**
 * Tests for the Strategy C detection thresholds helper (issue #109).
 *
 * Runner: node --test --experimental-strip-types — loads the .ts module
 * directly so the production source is exercised. A minimal in-memory
 * chrome.storage.local shim is installed on globalThis before import.
 *
 * Run:
 *   cd extension && npm test
 */

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

// ── chrome.storage.local in-memory shim ─────────────────────────────────────
// detection-thresholds.ts wires an `onChanged` listener at import time; the
// shim has to be in place before the dynamic import below.
const storageData = new Map();
const changeListeners = [];

globalThis.chrome = {
  storage: {
    local: {
      async get(keyOrKeys) {
        const keys = typeof keyOrKeys === "string"
          ? [keyOrKeys]
          : Array.isArray(keyOrKeys)
          ? keyOrKeys
          : Object.keys(keyOrKeys ?? {});
        const out = {};
        for (const k of keys) {
          if (storageData.has(k)) out[k] = storageData.get(k);
        }
        return out;
      },
      async set(obj) {
        const changes = {};
        for (const [k, v] of Object.entries(obj)) {
          changes[k] = { oldValue: storageData.get(k), newValue: v };
          storageData.set(k, v);
        }
        for (const fn of changeListeners) fn(changes, "local");
      },
      async remove(keyOrKeys) {
        const keys = Array.isArray(keyOrKeys) ? keyOrKeys : [keyOrKeys];
        const changes = {};
        for (const k of keys) {
          if (storageData.has(k)) {
            changes[k] = { oldValue: storageData.get(k), newValue: undefined };
            storageData.delete(k);
          }
        }
        for (const fn of changeListeners) fn(changes, "local");
      },
    },
    onChanged: {
      addListener(fn) { changeListeners.push(fn); },
    },
  },
};

const mod = await import("../detection-thresholds.ts");
const {
  DEFAULT_THRESHOLDS,
  DEFAULT_ATS_AUTOFILL_MIN,
  DEFAULT_VAULT_SIMILARITY_FLOOR,
  DEFAULT_RESIZE_DELTA_PX,
  DEFAULT_RAG_REWARD_WEIGHT,
  STORAGE_KEY,
  THRESHOLD_RANGES,
  normalizeThresholds,
  loadThresholds,
  saveThresholds,
  resetThresholds,
  getThresholdsCached,
  __resetForTests,
} = mod;

beforeEach(() => {
  storageData.clear();
  __resetForTests();
});

// ── Constants ───────────────────────────────────────────────────────────────

test("defaults match the spec values from issue #109", () => {
  assert.equal(DEFAULT_ATS_AUTOFILL_MIN, 0.75);
  assert.equal(DEFAULT_VAULT_SIMILARITY_FLOOR, 0.25);
  assert.equal(DEFAULT_RESIZE_DELTA_PX, 50);
  assert.equal(DEFAULT_RAG_REWARD_WEIGHT, 0.7);
  assert.deepEqual({ ...DEFAULT_THRESHOLDS }, {
    atsAutofillMin: 0.75,
    vaultSimilarityFloor: 0.25,
    resizeDeltaPx: 50,
    ragRewardWeight: 0.7,
  });
});

test("DEFAULT_THRESHOLDS is frozen — call sites cannot mutate it accidentally", () => {
  assert.throws(() => { DEFAULT_THRESHOLDS.atsAutofillMin = 0.9; }, TypeError);
});

test("THRESHOLD_RANGES covers all four threshold keys", () => {
  const keys = Object.keys(THRESHOLD_RANGES).sort();
  assert.deepEqual(keys, ["atsAutofillMin", "ragRewardWeight", "resizeDeltaPx", "vaultSimilarityFloor"]);
  for (const k of keys) {
    const r = THRESHOLD_RANGES[k];
    assert.ok(r.min < r.max, `${k}: min must be < max`);
    assert.ok(r.step > 0, `${k}: step must be > 0`);
  }
});

// ── normalizeThresholds ─────────────────────────────────────────────────────

test("normalizeThresholds: empty / non-object input → all defaults", () => {
  assert.deepEqual(normalizeThresholds(null), { ...DEFAULT_THRESHOLDS });
  assert.deepEqual(normalizeThresholds(undefined), { ...DEFAULT_THRESHOLDS });
  assert.deepEqual(normalizeThresholds({}), { ...DEFAULT_THRESHOLDS });
  assert.deepEqual(normalizeThresholds("garbage"), { ...DEFAULT_THRESHOLDS });
  assert.deepEqual(normalizeThresholds(42), { ...DEFAULT_THRESHOLDS });
});

test("normalizeThresholds: missing fields fall back to per-key defaults", () => {
  const result = normalizeThresholds({ atsAutofillMin: 0.5 });
  assert.equal(result.atsAutofillMin, 0.5);
  assert.equal(result.vaultSimilarityFloor, DEFAULT_VAULT_SIMILARITY_FLOOR);
  assert.equal(result.resizeDeltaPx, DEFAULT_RESIZE_DELTA_PX);
  assert.equal(result.ragRewardWeight, DEFAULT_RAG_REWARD_WEIGHT);
});

test("normalizeThresholds: non-number values fall back to defaults", () => {
  const result = normalizeThresholds({
    atsAutofillMin: "0.9", // string — rejected, not coerced
    vaultSimilarityFloor: null,
    resizeDeltaPx: true,
    ragRewardWeight: { x: 1 },
  });
  assert.deepEqual(result, { ...DEFAULT_THRESHOLDS });
});

test("normalizeThresholds: out-of-range values are clamped to per-field limits", () => {
  const result = normalizeThresholds({
    atsAutofillMin: 2.5,       // > 1 → clamp to 1
    vaultSimilarityFloor: -0.3,// < 0 → clamp to 0
    resizeDeltaPx: 9999,       // > 500 → clamp to 500
    ragRewardWeight: -10,      // < 0 → clamp to 0
  });
  assert.equal(result.atsAutofillMin, 1);
  assert.equal(result.vaultSimilarityFloor, 0);
  assert.equal(result.resizeDeltaPx, 500);
  assert.equal(result.ragRewardWeight, 0);
});

test("normalizeThresholds: NaN / Infinity → range min (never propagated)", () => {
  const result = normalizeThresholds({
    atsAutofillMin: NaN,
    vaultSimilarityFloor: Infinity,
    resizeDeltaPx: -Infinity,
    ragRewardWeight: NaN,
  });
  assert.equal(result.atsAutofillMin, 0);
  assert.equal(result.vaultSimilarityFloor, 1);     // +Infinity clamps to max
  assert.equal(result.resizeDeltaPx, 10);           // -Infinity → range min for resize
  assert.equal(result.ragRewardWeight, 0);
});

// ── loadThresholds ──────────────────────────────────────────────────────────

test("loadThresholds: returns defaults when storage key absent", async () => {
  const result = await loadThresholds();
  assert.deepEqual(result, { ...DEFAULT_THRESHOLDS });
  // Cache also primed.
  assert.deepEqual(getThresholdsCached(), { ...DEFAULT_THRESHOLDS });
});

test("loadThresholds: round-trips saved values", async () => {
  const custom = { atsAutofillMin: 0.6, vaultSimilarityFloor: 0.4, resizeDeltaPx: 100, ragRewardWeight: 0.5 };
  storageData.set(STORAGE_KEY, custom);
  const result = await loadThresholds();
  assert.deepEqual(result, custom);
  assert.deepEqual(getThresholdsCached(), custom);
});

test("loadThresholds: malformed payload → normalised back into valid range", async () => {
  storageData.set(STORAGE_KEY, { atsAutofillMin: 99, ragRewardWeight: "nope" });
  const result = await loadThresholds();
  assert.equal(result.atsAutofillMin, 1);
  assert.equal(result.ragRewardWeight, DEFAULT_RAG_REWARD_WEIGHT);
  assert.equal(result.vaultSimilarityFloor, DEFAULT_VAULT_SIMILARITY_FLOOR);
  assert.equal(result.resizeDeltaPx, DEFAULT_RESIZE_DELTA_PX);
});

// ── saveThresholds ──────────────────────────────────────────────────────────

test("saveThresholds: merges partial input over current cache", async () => {
  await loadThresholds();
  const updated = await saveThresholds({ atsAutofillMin: 0.8 });
  assert.equal(updated.atsAutofillMin, 0.8);
  assert.equal(updated.vaultSimilarityFloor, DEFAULT_VAULT_SIMILARITY_FLOOR);
  // Persisted to storage.
  assert.deepEqual(storageData.get(STORAGE_KEY), updated);
});

test("saveThresholds: clamps out-of-range writes before persisting", async () => {
  const updated = await saveThresholds({ atsAutofillMin: 5, resizeDeltaPx: -50 });
  assert.equal(updated.atsAutofillMin, 1);
  assert.equal(updated.resizeDeltaPx, 10);
  assert.equal(storageData.get(STORAGE_KEY).atsAutofillMin, 1);
});

test("saveThresholds: cache reflects the saved value synchronously after await", async () => {
  await saveThresholds({ ragRewardWeight: 0.3 });
  assert.equal(getThresholdsCached().ragRewardWeight, 0.3);
});

// ── resetThresholds ─────────────────────────────────────────────────────────

test("resetThresholds: writes defaults to storage and cache", async () => {
  await saveThresholds({ atsAutofillMin: 0.99 });
  const reset = await resetThresholds();
  assert.deepEqual(reset, { ...DEFAULT_THRESHOLDS });
  assert.deepEqual(storageData.get(STORAGE_KEY), { ...DEFAULT_THRESHOLDS });
  assert.deepEqual(getThresholdsCached(), { ...DEFAULT_THRESHOLDS });
});

// ── onChanged auto-refresh ──────────────────────────────────────────────────

test("storage.onChanged: external write refreshes the cache without re-loading", async () => {
  await loadThresholds(); // prime cache to defaults
  // Simulate another extension page (or sync) writing a new value.
  await chrome.storage.local.set({ [STORAGE_KEY]: {
    atsAutofillMin: 0.42, vaultSimilarityFloor: 0.42, resizeDeltaPx: 42, ragRewardWeight: 0.42,
  } });
  // The onChanged listener installed by the module should have updated the cache.
  assert.equal(getThresholdsCached().atsAutofillMin, 0.42);
  assert.equal(getThresholdsCached().resizeDeltaPx, 42);
});
