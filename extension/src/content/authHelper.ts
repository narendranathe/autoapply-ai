/**
 * authHelper.ts
 *
 * Shared utility for content script autofill — builds auth headers for fetch requests.
 * Prefers Authorization: Bearer <token> when a valid JWT is stored, falls back to
 * X-Clerk-User-Id for backwards compatibility.
 */

interface StoredAuth {
  clerkUserId?: string;
  clerkToken?: string;
  clerkTokenExp?: number;
}

/** Build auth headers from chrome.storage.local values. */
export function buildAuthHeaders(data: StoredAuth): Record<string, string> {
  const token = data.clerkToken;
  const exp = data.clerkTokenExp ?? 0;
  const tokenValid = token && (exp === 0 || Date.now() / 1000 < exp - 30);
  if (tokenValid) return { Authorization: `Bearer ${token}` };
  return data.clerkUserId ? { "X-Clerk-User-Id": data.clerkUserId } : {};
}

/** Keys to request from chrome.storage.local to get auth data. */
export const AUTH_STORAGE_KEYS = ["clerkUserId", "clerkToken", "clerkTokenExp"] as const;
