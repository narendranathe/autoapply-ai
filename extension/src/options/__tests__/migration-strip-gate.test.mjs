/**
 * Mutation-coverage tests for the strip gate in the migration loop
 * (#198 round 2).
 *
 * Invariant: ``stripLocalKey`` MUST only run when ``migrateProviderKey``
 * returned ``{ok: true}``. A previous version that swallowed errors
 * could silently strip on the failure path, losing the user's key
 * forever.
 *
 * These tests pin that invariant by exercising the conditional in a
 * pure simulation of the loop body — no DOM, no chrome.* required.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const { stripLocalKey } = await import("../../shared/providerMigration.ts");

/**
 * Simulate exactly what ``migrateProviderKeysOnClick`` does for one
 * provider given a migration result. The real loop also re-reads
 * storage (the P1-B fix) but the strip-gate decision is local.
 */
function loopBodyForOne(name, key, model, migrationResult, configs) {
  if (!key) return configs; // skip — no migration attempted
  if (migrationResult.ok) {
    return stripLocalKey(configs, name);
  }
  return configs;
}

test("strip gate: ok:true → apiKey cleared", () => {
  const before = { anthropic: { apiKey: "k", model: "m" } };
  const after = loopBodyForOne(
    "anthropic",
    "k",
    "m",
    { name: "anthropic", ok: true },
    before,
  );
  assert.equal(after.anthropic.apiKey, "");
});

test("strip gate: ok:false → apiKey PRESERVED (the bug we're guarding against)", () => {
  // Every category of failure must leave the local key intact so the
  // user can re-try migration.
  const failureCases = [
    { name: "anthropic", ok: false, reason: "PUT failed: 500" },
    { name: "anthropic", ok: false, reason: "PUT: fingerprint mismatch (...)" },
    { name: "anthropic", ok: false, reason: "verification: has_key is false" },
    { name: "anthropic", ok: false, reason: "GET network error: connection refused" },
    { name: "anthropic", ok: false, reason: "apiBase rejected: not https" },
  ];
  for (const res of failureCases) {
    const before = { anthropic: { apiKey: "k", model: "m" } };
    const after = loopBodyForOne("anthropic", "k", "m", res, before);
    assert.equal(
      after.anthropic.apiKey,
      "k",
      `reason="${res.reason}" — apiKey must survive failed migration`,
    );
  }
});

test("strip gate: empty key → no migration attempt + no mutation", () => {
  const before = { anthropic: { apiKey: "", model: "m" } };
  // Note: we pass a phantom ok:true to prove the early-return on empty
  // key short-circuits before the strip even runs.
  const after = loopBodyForOne("anthropic", "", "m", { name: "anthropic", ok: true }, before);
  assert.equal(after, before);
});
