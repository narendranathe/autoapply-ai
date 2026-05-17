/**
 * Provider key migration helpers (P0 issue #198 — implementation B).
 *
 * Background
 * ----------
 * Historically the extension stored each provider API key in
 * ``chrome.storage.local["providerConfigs"][name].apiKey`` and shipped the
 * plaintext key on every backend call as ``providers_json``. That has two
 * security problems:
 *
 * 1. The plaintext key sits in extension local storage indefinitely.
 * 2. The plaintext key crosses the wire on every generation request, even
 *    though the backend already has an encrypted copy keyed by the user.
 *
 * Strategy (implementation B)
 * ---------------------------
 * - Build a new sanitised provider list shape: ``{name, model}`` only —
 *   never ``apiKey``. This is what gets sent to the backend.
 * - Migration is **explicit and verified**:
 *     * The Options page shows a persistent banner whenever there are
 *       providers with a local ``apiKey`` still in storage.
 *     * The user clicks "Migrate" — for each provider with a key, we
 *       ``PUT /users/provider-configs/{name}`` followed by a
 *       ``GET /users/provider-configs`` and only when the GET confirms
 *       ``has_key=true`` do we strip the local ``apiKey``. This avoids
 *       silent data loss if the PUT failed.
 * - Migrations are per-provider — a partial failure leaves the others
 *   migrated and the banner keeps showing the remaining count.
 *
 * Public API
 * ----------
 * - ``buildProviderList(configs)`` — pure, no apiKey in output.
 * - ``countUnmigratedKeys(configs)`` — how many local keys still need to move.
 * - ``migrateProviderKey(name, key, fetchFn, opts)`` — PUT → GET → verify.
 * - ``stripLocalKey(configs, name)`` — pure helper to clear ``apiKey`` from one entry.
 */

export type ProviderEntry = {
  enabled?: boolean;
  apiKey?: string;
  model?: string;
};

export type ProvidersMap = Record<string, ProviderEntry>;

/**
 * Sanitised provider descriptor sent to the backend.
 *
 * Critically: there is **no** ``apiKey`` field. The backend reads the key
 * from its own ``user_provider_configs`` table.
 */
export type ProviderRef = { name: string; model: string };

const PROVIDER_RANK: Record<string, number> = {
  anthropic: 1,
  openai: 2,
  gemini: 3,
  groq: 4,
  perplexity: 5,
  kimi: 6,
};

const PROVIDER_MODELS: Record<string, string> = {
  anthropic: "claude-sonnet-4-6",
  openai: "gpt-4o",
  gemini: "gemini-1.5-flash",
  groq: "llama-3.3-70b-versatile",
  perplexity: "sonar",
  kimi: "moonshot-v1-32k",
};

/**
 * Build the sanitised provider list to send to the backend.
 *
 * A provider is *included* when either (a) it has a local ``apiKey``
 * (pre-migration) or (b) it has been explicitly enabled. The output
 * never carries the key — the backend resolves it server-side.
 *
 * Pure function: deterministic ordering by ``PROVIDER_RANK``.
 */
export function buildProviderList(configs: ProvidersMap | undefined | null): ProviderRef[] {
  if (!configs) return [];
  return Object.entries(configs)
    .filter(([, cfg]) => {
      // Include if local key exists OR explicit enabled flag. After migration
      // local keys are gone, so enabled flag is what keeps the entry alive.
      return !!cfg && (!!cfg.apiKey || cfg.enabled === true);
    })
    .map(([name, cfg]) => ({
      name,
      model: (cfg?.model || PROVIDER_MODELS[name] || "").trim(),
    }))
    .sort((a, b) => (PROVIDER_RANK[a.name] ?? 50) - (PROVIDER_RANK[b.name] ?? 50));
}

/**
 * Whether a row should be considered an "unmigrated" candidate.
 *
 * P1-C (#198 round 2): a provider that the user explicitly disabled
 * (``enabled === false``) but kept a local key for is *not* a migration
 * candidate. Without this check the migration would silently re-enable
 * the provider when it ran, contradicting the user's choice.
 *
 * The pre-migration default is ``enabled === undefined`` (the field
 * may not exist yet on legacy entries). Those rows are still counted —
 * we only skip the row when ``enabled`` is *explicitly* false.
 */
function _isUnmigratedCandidate(cfg: ProviderEntry | undefined): boolean {
  if (!cfg) return false;
  if (!cfg.apiKey) return false;
  if (cfg.enabled === false) return false;
  return true;
}

/**
 * Count providers that still have a local ``apiKey`` *and* are not
 * explicitly disabled — these are the rows the migration banner reports
 * as "remaining" and the migration loop will attempt.
 */
export function countUnmigratedKeys(configs: ProvidersMap | undefined | null): number {
  if (!configs) return 0;
  return Object.values(configs).filter(_isUnmigratedCandidate).length;
}

/**
 * Names of providers that still have a local ``apiKey`` and are not
 * explicitly disabled.
 */
export function unmigratedProviderNames(configs: ProvidersMap | undefined | null): string[] {
  if (!configs) return [];
  return Object.entries(configs)
    .filter(([, cfg]) => _isUnmigratedCandidate(cfg))
    .map(([name]) => name);
}

export type MigrateResult =
  | { name: string; ok: true }
  | { name: string; ok: false; reason: string };

export interface MigrateOptions {
  apiBase: string;
  authHeaders: Record<string, string>;
  /**
   * Optional model override sent in the PUT body.
   */
  modelOverride?: string | null;
  /**
   * Whether the extension is running in a dev build. Required so the
   * apiBase revalidation step (P1-D) uses the same rules as
   * ``validateApiBaseUrl`` does on the Options page.
   *
   * Optional for backwards compat — defaults to ``false`` (= production
   * rules: https only, no http://localhost).
   */
  isDev?: boolean;
  /**
   * Inject the validator. Lets call sites avoid the cross-module import
   * cycle (options.ts already imports providerMigration which would
   * otherwise need to import options.ts → offlineQueue.ts → ...).
   *
   * Defaults to the shared ``validateApiBaseUrl`` helper.
   */
  validateApiBase?: (raw: string, isDev: boolean) => { ok: true } | { ok: false; reason: string };
}

/**
 * Compute the same fingerprint the backend returns: first 8 hex chars of
 * ``sha256(plaintext)``. Pure helper exported for tests.
 */
export async function computeKeyFingerprint(plaintext: string): Promise<string> {
  if (!plaintext) return "";
  const enc = new TextEncoder().encode(plaintext);
  const digest = await crypto.subtle.digest("SHA-256", enc);
  const bytes = new Uint8Array(digest);
  // Hex-encode the first 4 bytes → 8 hex chars, matching backend.
  return Array.from(bytes.subarray(0, 4))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Migrate one provider key to the backend, then **verify** before the
 * caller strips the local copy.
 *
 * P0-A (#198 round 2): the previous PUT → GET → check ``has_key=true``
 * gate was forgeable. If some other row already had a stale key for the
 * same provider, the GET reported ``has_key=true`` and the local key got
 * stripped even when the PUT silently failed. To close this we now:
 *
 *   1. Locally compute ``sha256(plaintext)[:8]`` as the expected
 *      fingerprint.
 *   2. ``PUT /users/provider-configs/{name}`` — server echoes the
 *      fingerprint of the plaintext it just received.
 *   3. Compare the PUT response fingerprint to the expected one. If they
 *      mismatch, the server stored something other than what we sent
 *      (or returned a stale row from cache) — bail out, keep the local
 *      key.
 *   4. ``GET /users/provider-configs`` and re-check the fingerprint
 *      matches. This catches the case where the PUT response was forged
 *      / the underlying store rolled back.
 *
 * Only on both fingerprint matches do we return ``{ok: true}``.
 */
export async function migrateProviderKey(
  name: string,
  apiKey: string,
  fetchFn: typeof fetch,
  opts: MigrateOptions,
): Promise<MigrateResult> {
  if (!apiKey) return { name, ok: false, reason: "no local key to migrate" };
  if (!opts.apiBase) return { name, ok: false, reason: "no apiBase configured" };

  // P1-D (#198 round 2): re-validate the apiBase right before the PUT.
  // ``options.ts`` validates the URL when the user saves it, but storage
  // could be tampered with afterwards (extension API, sync replication,
  // dev panel) so we re-check on every migration. Same rules as the
  // background drain (#91) — https in prod, http://localhost in dev only.
  if (opts.validateApiBase) {
    const v = opts.validateApiBase(opts.apiBase, opts.isDev ?? false);
    if (!v.ok) {
      return { name, ok: false, reason: `apiBase rejected: ${v.reason}` };
    }
  }

  const expectedFingerprint = await computeKeyFingerprint(apiKey);

  // Step 1: PUT
  let putResp: Response;
  try {
    putResp = await fetchFn(`${opts.apiBase}/users/provider-configs/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { ...opts.authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey, model_override: opts.modelOverride ?? null }),
    });
  } catch (e) {
    return { name, ok: false, reason: `PUT network error: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (!putResp.ok) {
    return { name, ok: false, reason: `PUT failed: ${putResp.status}` };
  }

  // Step 1.5: parse PUT response, compare fingerprint. A non-JSON or
  // missing-fingerprint response is treated as a verification failure —
  // the server must opt in to the new contract.
  let putJson: { has_key?: boolean; key_fingerprint?: string | null } = {};
  try {
    putJson = (await putResp.json()) as typeof putJson;
  } catch {
    return { name, ok: false, reason: "PUT: invalid JSON" };
  }
  if (!putJson.key_fingerprint) {
    return { name, ok: false, reason: "PUT: missing key_fingerprint (backend out of date)" };
  }
  if (putJson.key_fingerprint !== expectedFingerprint) {
    return {
      name,
      ok: false,
      reason: `PUT: fingerprint mismatch (server=${putJson.key_fingerprint} local=${expectedFingerprint})`,
    };
  }

  // Step 2: GET to verify the row truly persisted with our key (not a
  // cached / stale entry from a previous PUT).
  let getResp: Response;
  try {
    getResp = await fetchFn(`${opts.apiBase}/users/provider-configs`, {
      method: "GET",
      headers: opts.authHeaders,
    });
  } catch (e) {
    return { name, ok: false, reason: `GET network error: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (!getResp.ok) {
    return { name, ok: false, reason: `verification GET failed: ${getResp.status}` };
  }

  let json: {
    configs?: Array<{ provider_name?: string; has_key?: boolean; key_fingerprint?: string | null }>;
  } = {};
  try {
    json = (await getResp.json()) as typeof json;
  } catch {
    return { name, ok: false, reason: "verification GET: invalid JSON" };
  }

  const row = (json.configs ?? []).find((c) => c.provider_name === name);
  if (!row) return { name, ok: false, reason: "verification: provider missing from response" };
  if (row.has_key !== true) return { name, ok: false, reason: "verification: has_key is false" };
  if (!row.key_fingerprint) {
    return { name, ok: false, reason: "verification: missing key_fingerprint" };
  }
  if (row.key_fingerprint !== expectedFingerprint) {
    return {
      name,
      ok: false,
      reason: `verification: fingerprint mismatch (server=${row.key_fingerprint} local=${expectedFingerprint})`,
    };
  }

  return { name, ok: true };
}

/**
 * Pure: return a copy of ``configs`` with ``apiKey`` cleared on the given
 * provider. The row is kept (now empty ``apiKey``) so the UI can still
 * show the provider as configured server-side.
 *
 * P1-C (#198 round 2): we DO NOT force ``enabled: true``. Forcing it
 * would silently re-enable a provider the user had explicitly disabled
 * (``enabled: false``). When ``enabled`` was never set on the entry we
 * default it to ``true`` so a pre-migration row that had a key (and
 * was implicitly active by virtue of having a key) keeps working.
 */
export function stripLocalKey(configs: ProvidersMap, name: string): ProvidersMap {
  const existing = configs[name];
  if (!existing) return configs;
  const next: ProvidersMap = { ...configs };
  // Preserve an explicit choice; default undefined → true.
  const enabled = existing.enabled === false ? false : (existing.enabled ?? true);
  next[name] = { ...existing, apiKey: "", enabled };
  return next;
}
