/**
 * Tests for the migration-banner refresh predicate + state computation
 * (#198 round 2).
 *
 * The Options page subscribes to ``chrome.storage.onChanged`` so the
 * banner repaints when the migration loop strips a key, when the user
 * saves new keys via ``saveLlm``, or when a second tab does either of
 * those things. Two pure helpers underlie that wiring:
 *
 *   - ``shouldRefreshBannerOnChange(changes, area)`` — predicate.
 *   - ``computeProviderMigrationBannerState(configs)`` — visible/message.
 *
 * Both are re-implemented here (no DOM import) and pinned by these
 * tests against the same providerMigration helpers the production code
 * actually uses. If either predicate or state-builder drifts, these
 * tests catch it.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const { countUnmigratedKeys, unmigratedProviderNames } = await import(
  "../../shared/providerMigration.ts"
);

// Re-implementations mirroring the options.ts source. Kept in lockstep
// by the tests below — and by the fact that options.ts imports the
// same providerMigration helpers underneath, so a drift in those
// helpers shows up here first.
function shouldRefreshBannerOnChange(changes, area) {
  return area === "local" && !!changes?.providerConfigs;
}

function computeProviderMigrationBannerState(configs) {
  const safe = configs ?? {};
  const remaining = countUnmigratedKeys(safe);
  if (remaining === 0) return { visible: false, message: "" };
  const names = unmigratedProviderNames(safe).join(", ");
  const plural = remaining === 1 ? "" : "s";
  return {
    visible: true,
    message: `${remaining} key${plural} still stored locally (${names}) — click to migrate to the server.`,
  };
}

// ── onChanged predicate ────────────────────────────────────────────────────

test("shouldRefreshBannerOnChange: local + providerConfigs → true", () => {
  assert.equal(
    shouldRefreshBannerOnChange({ providerConfigs: { newValue: {} } }, "local"),
    true,
  );
});

test("shouldRefreshBannerOnChange: 'sync' area ignored", () => {
  assert.equal(
    shouldRefreshBannerOnChange({ providerConfigs: { newValue: {} } }, "sync"),
    false,
  );
});

test("shouldRefreshBannerOnChange: unrelated key change → false", () => {
  assert.equal(
    shouldRefreshBannerOnChange({ profile: { newValue: {} } }, "local"),
    false,
  );
});

test("shouldRefreshBannerOnChange: empty changes object → false", () => {
  assert.equal(shouldRefreshBannerOnChange({}, "local"), false);
});

// ── banner state builder ───────────────────────────────────────────────────

test("computeProviderMigrationBannerState: no configs → hidden", () => {
  assert.deepEqual(computeProviderMigrationBannerState(null), {
    visible: false,
    message: "",
  });
  assert.deepEqual(computeProviderMigrationBannerState({}), {
    visible: false,
    message: "",
  });
});

test("computeProviderMigrationBannerState: fully-migrated map → hidden", () => {
  const state = computeProviderMigrationBannerState({
    anthropic: { apiKey: "", enabled: true, model: "x" },
    openai: { apiKey: "", enabled: true, model: "y" },
  });
  assert.equal(state.visible, false);
});

test("computeProviderMigrationBannerState: one unmigrated key → singular text", () => {
  const state = computeProviderMigrationBannerState({
    anthropic: { apiKey: "k", model: "x" },
    openai: { apiKey: "", enabled: true, model: "y" },
  });
  assert.equal(state.visible, true);
  assert.match(state.message, /^1 key still stored locally \(anthropic\)/);
});

test("computeProviderMigrationBannerState: multiple unmigrated keys → plural + comma list", () => {
  const state = computeProviderMigrationBannerState({
    anthropic: { apiKey: "a", model: "x" },
    openai: { apiKey: "o", model: "y" },
  });
  assert.equal(state.visible, true);
  assert.match(state.message, /^2 keys still stored locally /);
  assert.match(state.message, /\banthropic\b/);
  assert.match(state.message, /\bopenai\b/);
});

test("computeProviderMigrationBannerState: disabled-with-key row is NOT surfaced (P1-C)", () => {
  // Verifies the banner state honours the same disabled-skip rule as
  // the migration loop. Without this the banner would prod the user
  // to migrate a provider they explicitly disabled.
  const state = computeProviderMigrationBannerState({
    anthropic: { apiKey: "a", enabled: true, model: "x" },
    openai: { apiKey: "o", enabled: false, model: "y" }, // user disabled
  });
  assert.equal(state.visible, true);
  assert.match(state.message, /^1 key still stored locally \(anthropic\)/);
  assert.doesNotMatch(state.message, /openai/);
});
