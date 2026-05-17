/**
 * Offline sync queue — pure helpers for draining the markdown edit queue
 * with a dead-letter mechanism. Extracted from worker.ts for testability.
 */

import type { OfflineEdit } from "../shared/types";

export const MAX_OFFLINE_RETRY = 3;
export const OFFLINE_QUEUE_KEY = "offline_queue";
export const OFFLINE_QUEUE_FAILED_KEY = "offline_queue_failed";
export const SYNC_ENDPOINT = "http://localhost:8000/api/v1/vault/sync-markdown";

export interface ProcessQueueResult {
  active: OfflineEdit[];
  newlyDeadLettered: OfflineEdit[];
  syncedCount: number;
}

/**
 * Process the offline queue against a fetch function.
 *
 * For each unsynced entry:
 *   - On a 2xx response → mark synced.
 *   - On a non-2xx response or thrown error → increment failureCount and
 *     capture lastError.
 *   - When failureCount reaches MAX_OFFLINE_RETRY → entry is dead-lettered
 *     (returned via `newlyDeadLettered` so the caller can persist it).
 *
 * Returns the surviving "active" queue (synced + still-retrying entries),
 * the dead-lettered batch, and the count synced this pass.
 */
export async function processOfflineQueue(
  queue: OfflineEdit[],
  fetchFn: typeof fetch,
  endpoint: string = SYNC_ENDPOINT,
): Promise<ProcessQueueResult> {
  const active: OfflineEdit[] = [];
  const newlyDeadLettered: OfflineEdit[] = [];
  let syncedCount = 0;

  for (const original of queue) {
    if (original.synced) {
      active.push(original);
      continue;
    }

    const entry: OfflineEdit = {
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
        active.push(entry);
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
