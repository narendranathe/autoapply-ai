/**
 * Offline sync queue — pure helpers for draining the markdown edit queue
 * with a dead-letter mechanism. Extracted from worker.ts for testability.
 */

import type { OfflineEdit } from "../shared/types";

export const MAX_OFFLINE_RETRY = 3;
export const OFFLINE_QUEUE_KEY = "offline_queue";
export const OFFLINE_QUEUE_FAILED_KEY = "offline_queue_failed";

/**
 * Production fallback for the API base URL when the user has not configured
 * one in chrome.storage.local. NEVER fall back to localhost here — that would
 * silently break drains for any user running a packaged extension build.
 */
export const DEFAULT_API_BASE = "https://autoapply-ai-api.fly.dev/api/v1";

/** Endpoint suffix appended to the configured API base for the markdown drain. */
export const SYNC_MARKDOWN_PATH = "/vault/sync-markdown";

/**
 * Resolve the full sync endpoint to POST offline edits to.
 *
 * Reads `apiBaseUrl` from the supplied chrome.storage.local-shaped object and
 * falls back to DEFAULT_API_BASE only when the value is missing or empty.
 *
 * Kept pure (takes the storage value, not chrome directly) so it can be
 * tested with a plain object and so that worker.ts can mock-free unit-test
 * the URL-resolution behaviour that issue #91 was about.
 */
export function resolveSyncEndpoint(
  storage: { apiBaseUrl?: unknown } | null | undefined,
): string {
  const raw = storage?.apiBaseUrl;
  const apiBase =
    typeof raw === "string" && raw.length > 0 ? raw : DEFAULT_API_BASE;
  return `${apiBase}${SYNC_MARKDOWN_PATH}`;
}

export interface ProcessQueueResult {
  active: OfflineEdit[];
  newlyDeadLettered: OfflineEdit[];
  syncedCount: number;
}

/**
 * Process the offline queue against a fetch function.
 *
 * For each unsynced entry:
 *   - On a 2xx response → mark synced and DROP from active (so the queue
 *     does not grow unboundedly).
 *   - On a non-2xx response or thrown error → increment failureCount and
 *     capture lastError.
 *   - When failureCount reaches MAX_OFFLINE_RETRY → entry is dead-lettered
 *     (returned via `newlyDeadLettered` so the caller can persist it).
 *
 * Pre-existing already-synced entries are also dropped from `active`. If
 * such an entry has failureCount > 0 it is preserved in `newlyDeadLettered`
 * so the caller can record the prior failures.
 *
 * Returns the surviving "active" queue (still-retrying entries only),
 * the dead-lettered batch, and the count synced this pass.
 *
 * The `endpoint` is REQUIRED — there is no module-level default, since a
 * hard-coded localhost URL would silently break production drains. Callers
 * MUST read the configured API base from storage and pass it explicitly.
 */
export async function processOfflineQueue(
  queue: OfflineEdit[],
  fetchFn: typeof fetch,
  endpoint: string,
): Promise<ProcessQueueResult> {
  if (!endpoint) {
    throw new Error("processOfflineQueue: endpoint is required");
  }

  const active: OfflineEdit[] = [];
  const newlyDeadLettered: OfflineEdit[] = [];
  let syncedCount = 0;

  for (const original of queue) {
    if (original.synced) {
      // Already-synced entries are dropped from active. If they have prior
      // failures, preserve them in the dead-letter pile so history isn't lost.
      if ((original.failureCount ?? 0) > 0) {
        newlyDeadLettered.push(original);
      }
      continue;
    }

    // failureCount is optional on the type (legacy entries lack it); narrow
    // to a definite number inside this loop so TS doesn't complain on the
    // arithmetic below.
    const entry: OfflineEdit & { failureCount: number } = {
      ...original,
      failureCount: original.failureCount ?? 0,
    };

    try {
      const fd = new FormData();
      fd.append("version_tag", entry.versionTag);
      fd.append("markdown_content", entry.markdownContent);
      fd.append("timestamp", String(entry.timestamp));

      const resp = await fetchFn(endpoint, { method: "POST", body: fd });

      if (resp.ok) {
        entry.synced = true;
        syncedCount += 1;
        // Drop synced entries from active — do not let the queue grow forever.
      } else {
        entry.failureCount += 1;
        entry.lastError = `HTTP ${resp.status}`;
        if (entry.failureCount >= MAX_OFFLINE_RETRY) {
          newlyDeadLettered.push(entry);
        } else {
          active.push(entry);
        }
      }
    } catch (err) {
      entry.failureCount += 1;
      entry.lastError = err instanceof Error ? err.message : String(err);
      if (entry.failureCount >= MAX_OFFLINE_RETRY) {
        newlyDeadLettered.push(entry);
      } else {
        active.push(entry);
      }
    }
  }

  return { active, newlyDeadLettered, syncedCount };
}
