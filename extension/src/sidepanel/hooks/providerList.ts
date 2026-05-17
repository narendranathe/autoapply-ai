/**
 * Pure wire-format builder for the provider list (#198).
 *
 * Separated from `useProviders.ts` so it can be unit-tested under
 * `node --test` without pulling in React. The hook re-exports the
 * `buildProviderList` / `getFreshProviders` names from this file.
 *
 * Security invariant (#198): the returned objects MUST NOT carry
 * `api_key` or `apiKey`. The backend looks up the encrypted key for
 * the authenticated user; sending it over the wire defeats that.
 */

/** Wire-format provider entry — what the backend receives. */
export type ProviderConfig = { name: string; model: string };

/**
 * Legacy local storage shape. `apiKey` is present only for users who haven't
 * yet completed the migration to server-side key storage; it is stripped
 * from the wire payload here.
 */
export interface StoredProviderConfig {
  enabled?: boolean;
  apiKey?: string;
  model?: string;
}

const PROVIDER_RANK: Record<string, number> = {
  anthropic: 1, openai: 2, gemini: 3, groq: 4, perplexity: 5, kimi: 6,
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
 * Build the wire payload from the local providerConfigs map.
 *
 * Filters to entries that are either explicitly `enabled` (post-migration
 * state where the key now lives server-side) OR still carry a legacy local
 * `apiKey` (pre-migration state). In both cases the returned object only
 * contains `{name, model}` — never `apiKey` / `api_key`.
 *
 * Sorted by `PROVIDER_RANK` so the highest-priority provider runs first.
 */
export function buildProviderList(
  configs: Record<string, StoredProviderConfig>,
): ProviderConfig[] {
  return Object.entries(configs)
    .filter(([, cfg]) => !!cfg.apiKey || !!cfg.enabled)
    .map(([name, cfg]) => ({
      name,
      model: cfg.model || PROVIDER_MODELS[name] || "",
    }))
    .sort((a, b) => (PROVIDER_RANK[a.name] ?? 50) - (PROVIDER_RANK[b.name] ?? 50));
}

/** Read providerConfigs from chrome.storage and return the wire-format list. */
export async function getFreshProviders(): Promise<ProviderConfig[]> {
  return new Promise((resolve) => {
    chrome.storage.local.get("providerConfigs", (data) => {
      if (!data.providerConfigs) {
        resolve([]);
        return;
      }
      resolve(
        buildProviderList(
          data.providerConfigs as Record<string, StoredProviderConfig>,
        ),
      );
    });
  });
}
