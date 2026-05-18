/**
 * detection-thresholds.ts — Strategy C tunable thresholds (issue #109).
 *
 * Four values were previously hardcoded inline. They are now persisted under
 * the `detectionThresholds` key in `chrome.storage.local` and surfaced as
 * sliders in the Options page ("Advanced Detection Settings").
 *
 * Call sites should call `getThresholdsCached()` for synchronous access after
 * `initThresholds()` has resolved once on startup; the cache is auto-refreshed
 * via `chrome.storage.onChanged` so user edits take effect without a reload.
 *
 * NOTE: this module intentionally has no runtime dependencies on chrome.* at
 * import time so it remains testable under plain Node (`node --test`). The
 * storage hooks short-circuit when `chrome.storage` is not present.
 */

import type { DetectionThresholds } from "./types";

// ── Defaults ────────────────────────────────────────────────────────────────
// These constants are the single source of truth. Do NOT inline magic numbers
// at call sites — read them from here (or, at runtime, from getThresholdsCached).

export const DEFAULT_ATS_AUTOFILL_MIN = 0.75;
export const DEFAULT_VAULT_SIMILARITY_FLOOR = 0.25;
export const DEFAULT_RESIZE_DELTA_PX = 50;
export const DEFAULT_RAG_REWARD_WEIGHT = 0.7;

export const DEFAULT_THRESHOLDS: Readonly<DetectionThresholds> = Object.freeze({
  atsAutofillMin: DEFAULT_ATS_AUTOFILL_MIN,
  vaultSimilarityFloor: DEFAULT_VAULT_SIMILARITY_FLOOR,
  resizeDeltaPx: DEFAULT_RESIZE_DELTA_PX,
  ragRewardWeight: DEFAULT_RAG_REWARD_WEIGHT,
});

export const STORAGE_KEY = "detectionThresholds";

// Per-field validation ranges. UI sliders must respect these.
export const THRESHOLD_RANGES = {
  atsAutofillMin:       { min: 0,  max: 1,   step: 0.01 },
  vaultSimilarityFloor: { min: 0,  max: 1,   step: 0.01 },
  resizeDeltaPx:        { min: 10, max: 500, step: 5    },
  ragRewardWeight:      { min: 0,  max: 1,   step: 0.01 },
} as const satisfies Record<keyof DetectionThresholds, { min: number; max: number; step: number }>;

// ── Validation / normalisation ──────────────────────────────────────────────

function clamp(value: number, lo: number, hi: number): number {
  // NaN is genuinely unrecoverable; fall back to the range minimum. Infinity
  // is treated as a saturating signal — clamp it to the corresponding bound.
  if (Number.isNaN(value)) return lo;
  if (value <= lo) return lo;
  if (value >= hi) return hi;
  return value;
}

/**
 * Coerce an unknown blob (e.g. raw storage payload) into a valid
 * DetectionThresholds object — out-of-range or non-finite values are clamped
 * to the per-field range; missing keys fall back to defaults.
 */
export function normalizeThresholds(raw: unknown): DetectionThresholds {
  const r = (raw && typeof raw === "object" ? raw : {}) as Partial<Record<keyof DetectionThresholds, unknown>>;
  const pick = (key: keyof DetectionThresholds): number => {
    const range = THRESHOLD_RANGES[key];
    const v = r[key];
    if (typeof v !== "number") return DEFAULT_THRESHOLDS[key];
    return clamp(v, range.min, range.max);
  };
  return {
    atsAutofillMin: pick("atsAutofillMin"),
    vaultSimilarityFloor: pick("vaultSimilarityFloor"),
    resizeDeltaPx: pick("resizeDeltaPx"),
    ragRewardWeight: pick("ragRewardWeight"),
  };
}

// ── Cache (synchronous accessor) ────────────────────────────────────────────

let _cached: DetectionThresholds = { ...DEFAULT_THRESHOLDS };
let _initPromise: Promise<DetectionThresholds> | null = null;

/** Synchronous accessor — safe to call after `initThresholds()` resolves. */
export function getThresholdsCached(): DetectionThresholds {
  return _cached;
}

function chromeStorage(): chrome.storage.LocalStorageArea | null {
  // Guard for non-extension environments (node:test, jsdom).
  if (typeof chrome === "undefined" || !chrome?.storage?.local) return null;
  return chrome.storage.local;
}

/**
 * Load thresholds from chrome.storage.local; falls back to defaults if the
 * key is absent or the payload is malformed. Safe to call repeatedly —
 * subsequent calls reuse the in-flight promise.
 */
export async function loadThresholds(): Promise<DetectionThresholds> {
  const storage = chromeStorage();
  if (!storage) {
    _cached = { ...DEFAULT_THRESHOLDS };
    return _cached;
  }
  const data = await storage.get(STORAGE_KEY);
  const raw = data[STORAGE_KEY];
  _cached = raw === undefined ? { ...DEFAULT_THRESHOLDS } : normalizeThresholds(raw);
  return _cached;
}

/** Cached init — call once at extension startup; idempotent. */
export function initThresholds(): Promise<DetectionThresholds> {
  if (!_initPromise) _initPromise = loadThresholds();
  return _initPromise;
}

/** Persist thresholds to chrome.storage.local (normalised before write). */
export async function saveThresholds(next: Partial<DetectionThresholds>): Promise<DetectionThresholds> {
  const merged = normalizeThresholds({ ..._cached, ...next });
  _cached = merged;
  const storage = chromeStorage();
  if (storage) await storage.set({ [STORAGE_KEY]: merged });
  return merged;
}

/** Reset stored thresholds back to defaults. */
export async function resetThresholds(): Promise<DetectionThresholds> {
  _cached = { ...DEFAULT_THRESHOLDS };
  const storage = chromeStorage();
  if (storage) await storage.set({ [STORAGE_KEY]: { ...DEFAULT_THRESHOLDS } });
  return _cached;
}

/** Test-only — reset module state between cases. Not exported in production paths. */
export function __resetForTests(): void {
  _cached = { ...DEFAULT_THRESHOLDS };
  _initPromise = null;
}

// ── Auto-refresh cache when storage changes (e.g. user saves new values) ───
// Guarded so the module remains importable under Node.
if (typeof chrome !== "undefined" && chrome?.storage?.onChanged?.addListener) {
  chrome.storage.onChanged.addListener((changes) => {
    const change = changes[STORAGE_KEY];
    if (!change) return;
    _cached = change.newValue === undefined
      ? { ...DEFAULT_THRESHOLDS }
      : normalizeThresholds(change.newValue);
  });
}
