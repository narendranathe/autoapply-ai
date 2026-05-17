/**
 * Offline sync queue — pure helpers for draining the markdown edit queue
 * with a dead-letter mechanism. Extracted from worker.ts for testability.
 */

import type { OfflineEdit } from "../shared/types";

export const MAX_OFFLINE_RETRY = 3;
export const OFFLINE_QUEUE_KEY = "offline_queue";
export const OFFLINE_QUEUE_FAILED_KEY = "offline_queue_failed";
export const DEV_FALLBACK_API_BASE = "http://localhost:8000/api/v1";

export interface ProcessQueueResult {
  active: OfflineEdit[];
  newlyDeadLettered: OfflineEdit[];
  syncedCount: number;
}

export type ResolveDrainEndpointResult =
  | { ok: true; endpoint: string; usedFallback: boolean }
  | { ok: false; reason: "missing_in_prod" };

/**
 * Validate that a configured `apiBaseUrl` is safe to POST queued markdown
 * edits to.
 *
 * Rules (issue #91 round-2 hardening):
 *   - URL must parse via the `URL(...)` constructor — `javascript:`,
 *     `data:`, `file:`, `not a url`, etc. all fail this gate.
 *   - In production, ONLY `https:` is accepted. An `http:` URL in prod is
 *     a downgrade vector and is rejected.
 *   - In development, `http:` is allowed but ONLY when the host is
 *     `localhost` or `127.0.0.1`. Plain `http://attacker.example.com` is
 *     still rejected even in dev.
 *
 * Returns `null` when the URL is acceptable, otherwise a short reason for
 * logging / UI surfacing.
 */
export function validateApiBaseUrl(
  raw: string,
  isDev: boolean,
): { ok: true } | { ok: false; reason: string } {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return { ok: false, reason: "not a valid URL" };
  }

  const scheme = parsed.protocol;
  if (scheme === "https:") {
    return { ok: true };
  }
  if (scheme === "http:") {
    const host = parsed.hostname;
    const isLoopback = host === "localhost" || host === "127.0.0.1" || host === "::1";
    if (!isLoopback) {
      return { ok: false, reason: "http:// is only allowed for localhost" };
    }
    if (!isDev) {
      return { ok: false, reason: "http://localhost is only allowed in dev builds" };
    }
    return { ok: true };
  }
  return { ok: false, reason: `scheme ${scheme} is not allowed (https only)` };
}

/**
 * Resolve the URL the drain should POST to.
 *
 * Defensive rules (issue #91):
 *   1. If `apiBaseUrl` is configured in storage → validate it. Bad schemes
 *      (`javascript:`, `data:`, `file://`, plain `http://attacker.com`) are
 *      treated the same as "missing in prod" so the queue is preserved and
 *      no edits are exfiltrated to an attacker-controlled host.
 *   2. Otherwise, in dev builds only → fall back to localhost.
 *   3. Otherwise (production with no configured URL) → return ok:false. The
 *      caller MUST skip the drain entirely and preserve the queue. Defaulting
 *      to localhost in prod silently loses every edit because the loopback
 *      address resolves inside the user's machine, not our API.
 *
 * The helper is pure — no chrome/storage access — so tests can hit every
 * branch without mocking globals.
 */
export function resolveDrainEndpoint(
  storedApiBase: string | undefined,
  isDev: boolean,
): ResolveDrainEndpointResult {
  const base = (storedApiBase ?? "").trim();
  if (base) {
    const trimmed = base.replace(/\/$/, "");
    const validation = validateApiBaseUrl(trimmed, isDev);
    if (validation.ok) {
      return {
        ok: true,
        endpoint: `${trimmed}/vault/sync-markdown`,
        usedFallback: false,
      };
    }
    // A bad URL is functionally "missing in prod" — we refuse to use it and
    // preserve the queue. The dev fallback path below intentionally does NOT
    // rescue this case: if the user typed a bad URL in dev we should still
    // surface it rather than silently send edits to localhost.
    return { ok: false, reason: "missing_in_prod" };
  }
  if (isDev) {
    return {
      ok: true,
      endpoint: `${DEV_FALLBACK_API_BASE}/vault/sync-markdown`,
      usedFallback: true,
    };
  }
  return { ok: false, reason: "missing_in_prod" };
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
