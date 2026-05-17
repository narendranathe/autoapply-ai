/**
 * Legacy → server-side provider key migration (issue #198).
 *
 * Background
 * ----------
 * Before #197/#198, the extension stored each provider's API key in
 * `chrome.storage.local.providerConfigs[name].api_key` and forwarded it
 * with every generation request. That defeats server-side credential
 * isolation: any compromised page or extension can read the key, and the
 * key crosses the wire on every call.
 *
 * After the fix, keys live on the backend; the extension only ever sends
 * `{name, model}` in the wire payload, and the backend looks the key up
 * against the authenticated user. This module performs the one-time
 * migration on the user's behalf so existing installs upgrade silently.
 *
 * Migration shape
 * ---------------
 * For every entry `{enabled, apiKey, model}` with a non-empty `apiKey`:
 *
 *   1. PUT  {apiBase}/users/provider-configs/{name}  {api_key: <key>}
 *   2. On success: strip the `apiKey` field from the local entry.
 *      Local state becomes `{provider, model, enabled}` (provider = name).
 *   3. On failure: keep the local entry untouched and report the error
 *      so the caller can surface a "retry" banner.
 *
 * Idempotency
 * -----------
 * Entries without `apiKey` are already migrated and are skipped — running
 * this twice does NOT re-PUT keys that have already been moved.
 *
 * Pure boundary
 * -------------
 * The migration takes its dependencies (fetch, storage, auth headers) as
 * parameters so unit tests can run without a real Chrome/network. The
 * `options.ts` glue is the only caller that wires real `chrome.storage`
 * and `fetch`.
 */

/** Local provider config shape that may still carry a legacy plaintext key. */
export interface LocalProviderConfig {
  enabled?: boolean;
  /** Legacy plaintext key (#198). Present only before migration. */
  apiKey?: string;
  model?: string;
}

/** Map keyed by provider name (e.g. "anthropic", "openai"). */
export type ProviderConfigsMap = Record<string, LocalProviderConfig>;

/** Result for a single provider's migration attempt. */
export interface ProviderMigrationResult {
  name: string;
  /** "migrated" means we PUT successfully and stripped local apiKey. */
  status: "migrated" | "already_migrated" | "skipped_no_key" | "failed";
  error?: string;
}

/** Summary across all providers. Used to decide whether to show the banner. */
export interface MigrationSummary {
  results: ProviderMigrationResult[];
  /** Configs after migration — with `apiKey` stripped for migrated entries. */
  updatedConfigs: ProviderConfigsMap;
  /** Whether anything failed and needs user-visible retry. */
  hasFailures: boolean;
  /** Whether anything was actually migrated this run (vs. all already done). */
  changed: boolean;
}

export interface MigrationDeps {
  apiBase: string;
  authHeaders: () => Record<string, string>;
  fetch: typeof fetch;
}

/**
 * PUT the api_key for one provider. Internal helper.
 *
 * Returns `{ok: true}` on 2xx, `{ok: false, error}` on anything else.
 * Network errors are caught and reported the same way as HTTP failures
 * so the caller doesn't need separate handling.
 */
async function putProviderKey(
  name: string,
  apiKey: string,
  deps: MigrationDeps,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const resp = await deps.fetch(`${deps.apiBase}/users/provider-configs/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...deps.authHeaders() },
      body: JSON.stringify({ api_key: apiKey }),
    });
    if (resp.ok) return { ok: true };
    let detail = "";
    try { detail = await resp.text(); } catch { /* ignore */ }
    return { ok: false, error: `HTTP ${resp.status}${detail ? `: ${detail.slice(0, 200)}` : ""}` };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/**
 * Migrate every legacy plaintext key in `configs` to the backend.
 *
 * Idempotent: entries already missing `apiKey` are reported as
 * `already_migrated` / `skipped_no_key` and produce no network call. This
 * means re-running on every options-page load is cheap and safe.
 *
 * The returned `updatedConfigs` strips `apiKey` from successfully migrated
 * entries; entries that failed keep the original `apiKey` so the user can
 * retry later. The caller is expected to write `updatedConfigs` back into
 * `chrome.storage.local.providerConfigs`.
 */
export async function migrateProviderKeys(
  configs: ProviderConfigsMap,
  deps: MigrationDeps,
): Promise<MigrationSummary> {
  const results: ProviderMigrationResult[] = [];
  const updatedConfigs: ProviderConfigsMap = {};
  let changed = false;
  let hasFailures = false;

  for (const [name, cfg] of Object.entries(configs)) {
    // Default: carry the entry through unchanged.
    updatedConfigs[name] = { ...cfg };

    if (cfg.apiKey === undefined || cfg.apiKey === null) {
      // Already migrated — entry has no legacy key.
      results.push({ name, status: "already_migrated" });
      continue;
    }

    const trimmed = String(cfg.apiKey).trim();
    if (trimmed.length === 0) {
      // Empty string — user hasn't entered a key. Drop the field so future
      // runs treat it as already_migrated.
      const next: LocalProviderConfig = { ...cfg };
      delete next.apiKey;
      updatedConfigs[name] = next;
      results.push({ name, status: "skipped_no_key" });
      changed = true;
      continue;
    }

    const put = await putProviderKey(name, trimmed, deps);
    if (put.ok) {
      const next: LocalProviderConfig = { ...cfg };
      delete next.apiKey;
      updatedConfigs[name] = next;
      results.push({ name, status: "migrated" });
      changed = true;
    } else {
      // Keep legacy state on failure so the next attempt can retry.
      results.push({ name, status: "failed", error: put.error });
      hasFailures = true;
    }
  }

  return { results, updatedConfigs, hasFailures, changed };
}
