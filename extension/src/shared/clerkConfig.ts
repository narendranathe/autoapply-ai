/** Clerk publishable key — safe to expose in client-side code. Never commit sk_ keys. */
export const CLERK_PUBLISHABLE_KEY =
  "pk_test_ZmVhc2libGUtbGlnZXItMzUuY2xlcmsuYWNjb3VudHMuZGV2JA==";

/** Read whether Clerk JWT auth is enabled from storage (default: false). */
export async function getEnableClerkJWT(): Promise<boolean> {
  const data = await chrome.storage.local.get("enableClerkJWT");
  return Boolean(data.enableClerkJWT);
}

/**
 * Initialize Clerk SDK and start a 55-second JWT refresh interval.
 *
 * - Reads `enableClerkJWT` from chrome.storage.local; returns early (no-op) if false.
 * - Creates a Clerk instance, calls `.load()`, then stores the user ID.
 * - Starts a setInterval every 55,000 ms to refresh the JWT token.
 *
 * Safe to call multiple times — only one interval is created.
 */
let _clerkRefreshInterval: ReturnType<typeof setInterval> | null = null;

export async function initClerk(): Promise<void> {
  const enabled = await getEnableClerkJWT();
  if (!enabled) return;

  try {
    const { Clerk } = await import("@clerk/clerk-js");
    const clerk = new Clerk(CLERK_PUBLISHABLE_KEY);
    await clerk.load();

    const userId = clerk.user?.id ?? null;
    if (userId) {
      await chrome.storage.local.set({ clerkUserId: userId });
    }

    // Refresh JWT every 55 seconds
    const refreshToken = async () => {
      try {
        const session = clerk.session;
        if (!session) return;
        const token = await session.getToken();
        if (token) {
          // Decode exp from JWT payload (middle segment)
          const parts = token.split(".");
          let exp = 0;
          if (parts.length === 3) {
            try {
              const payload = JSON.parse(atob(parts[1])) as { exp?: number };
              exp = payload.exp ?? 0;
            } catch { /* ignore decode errors */ }
          }
          await chrome.storage.local.set({ clerkToken: token, clerkTokenExp: exp });
        }
      } catch { /* ignore refresh errors — token will expire naturally */ }
    };

    // Perform an immediate refresh, then schedule repeating refreshes
    await refreshToken();

    if (_clerkRefreshInterval !== null) {
      clearInterval(_clerkRefreshInterval);
    }
    _clerkRefreshInterval = setInterval(() => {
      refreshToken().catch(() => { /* noop */ });
    }, 55_000);
  } catch { /* Clerk unavailable (e.g. offline) — silently skip */ }
}
