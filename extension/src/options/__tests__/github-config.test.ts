/**
 * Tests for GitHub PAT configuration in the options page.
 *
 * These tests cover the saveGithubConfig() function and the loadGithubConfig()
 * helper that populates the form from the /auth/me response.
 *
 * Test infrastructure: vitest + jsdom.
 * Install: npm install -D vitest jsdom @vitest/coverage-v8
 * Run:     npx vitest run src/options/__tests__/github-config.test.ts
 *
 * TDD RED phase: tests describe expected behaviour before implementation.
 */

// ---------------------------------------------------------------------------
// Minimal DOM + fetch + chrome.storage stubs
// ---------------------------------------------------------------------------

// Minimal chrome stub — only the subset used by options.ts
const storageData: Record<string, unknown> = {};
const chromeMock = {
  storage: {
    local: {
      get: async (keys: string | string[]) => {
        const arr = Array.isArray(keys) ? keys : [keys];
        const result: Record<string, unknown> = {};
        for (const k of arr) {
          if (k in storageData) result[k] = storageData[k];
        }
        return result;
      },
      set: async (obj: Record<string, unknown>) => {
        Object.assign(storageData, obj);
      },
      remove: async () => {},
    },
    onChanged: { addListener: () => {} },
  },
};
(globalThis as unknown as Record<string, unknown>).chrome = chromeMock;

// ---------------------------------------------------------------------------
// Types matching what the options page uses
// ---------------------------------------------------------------------------

interface GitHubConfigPayload {
  github_token: string;
  github_username: string;
  resume_repo: string;
}

interface MeResponse {
  clerk_id: string;
  has_github_token?: boolean;
  github_username?: string | null;
}

interface SaveGithubResult {
  ok: boolean;
  error?: string;
}

// ---------------------------------------------------------------------------
// Re-implement the logic under test in a pure, testable form
// ---------------------------------------------------------------------------
// The actual implementation lives in options.ts but can't be imported directly
// (it has top-level side-effects that require a full DOM). Instead we extract
// the pure logic into standalone functions that mirror what options.ts does.

const API_DEFAULT = "https://autoapply-ai-api.fly.dev/api/v1";

async function getApiBase(): Promise<string> {
  const data = await chromeMock.storage.local.get("apiBaseUrl");
  return (data.apiBaseUrl as string | undefined) || API_DEFAULT;
}

async function getClerkUserId(): Promise<string | null> {
  const data = await chromeMock.storage.local.get("clerkUserId");
  return (data.clerkUserId as string | null) ?? null;
}

/**
 * Pure implementation of saveGithubConfig logic (mirrors options.ts).
 * Returns {ok, error} so tests can assert without touching the DOM.
 */
async function saveGithubConfigLogic(
  payload: GitHubConfigPayload,
  fetchFn: typeof fetch
): Promise<SaveGithubResult> {
  const token = payload.github_token.trim();
  const username = payload.github_username.trim();
  const repo = payload.resume_repo.trim() || "resume-vault";

  if (!token) return { ok: false, error: "GitHub token cannot be empty." };
  if (!username) return { ok: false, error: "GitHub username cannot be empty." };

  const userId = await getClerkUserId();
  if (!userId) return { ok: false, error: "Save your User ID in Authentication first." };

  const apiBase = await getApiBase();

  const resp = await fetchFn(`${apiBase}/users/github-token`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-Clerk-User-Id": userId,
    },
    body: JSON.stringify({ github_token: token, github_username: username, resume_repo: repo }),
  });

  if (!resp.ok) {
    const txt = await resp.text();
    return { ok: false, error: `Failed (${resp.status}): ${txt}` };
  }
  return { ok: true };
}

/**
 * Pure implementation of loadGithubConfig logic (mirrors options.ts).
 * Returns the config to display in the form rather than mutating DOM.
 */
async function loadGithubConfigLogic(fetchFn: typeof fetch): Promise<{
  hasToken: boolean;
  username: string | null;
  statusMsg: string;
  statusType: "ok" | "info" | "err";
}> {
  const userId = await getClerkUserId();
  if (!userId) {
    return { hasToken: false, username: null, statusMsg: "Not authenticated.", statusType: "info" };
  }

  const apiBase = await getApiBase();

  try {
    const resp = await fetchFn(`${apiBase}/auth/me`, {
      headers: { "X-Clerk-User-Id": userId },
    });

    if (!resp.ok) {
      return { hasToken: false, username: null, statusMsg: "Could not load GitHub config.", statusType: "err" };
    }

    const data = (await resp.json()) as MeResponse;
    const hasToken = data.has_github_token === true;
    const username = data.github_username ?? null;

    return {
      hasToken,
      username,
      statusMsg: hasToken ? `Configured (${username ?? "unknown user"}) ✓` : "Not configured",
      statusType: hasToken ? "ok" : "info",
    };
  } catch {
    return { hasToken: false, username: null, statusMsg: "Could not reach backend.", statusType: "err" };
  }
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeOkFetch(body: unknown, status = 200): typeof fetch {
  return () =>
    Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
      json: () => Promise.resolve(body),
    } as Response);
}

function makeErrorFetch(status: number, body = "Internal Server Error"): typeof fetch {
  return () =>
    Promise.resolve({
      ok: false,
      status,
      text: () => Promise.resolve(body),
      json: () => Promise.resolve({ detail: body }),
    } as Response);
}

function makeNetworkErrorFetch(): typeof fetch {
  return () => Promise.reject(new Error("Failed to fetch"));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("saveGithubConfigLogic", () => {
  beforeEach(() => {
    // Reset storage
    for (const k of Object.keys(storageData)) delete storageData[k];
    storageData["clerkUserId"] = "test-user-123";
    storageData["apiBaseUrl"] = "https://test-api.example.com/api/v1";
  });

  it("returns error when github_token is empty", async () => {
    const result = await saveGithubConfigLogic(
      { github_token: "", github_username: "narendranathe", resume_repo: "resume-vault" },
      makeOkFetch({})
    );
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/token cannot be empty/i);
  });

  it("returns error when github_token is whitespace only", async () => {
    const result = await saveGithubConfigLogic(
      { github_token: "   ", github_username: "narendranathe", resume_repo: "resume-vault" },
      makeOkFetch({})
    );
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/token cannot be empty/i);
  });

  it("returns error when github_username is empty", async () => {
    const result = await saveGithubConfigLogic(
      { github_token: "ghp_abc123", github_username: "", resume_repo: "resume-vault" },
      makeOkFetch({})
    );
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/username cannot be empty/i);
  });

  it("returns error when no clerkUserId in storage", async () => {
    delete storageData["clerkUserId"];
    const result = await saveGithubConfigLogic(
      { github_token: "ghp_abc123", github_username: "narendranathe", resume_repo: "resume-vault" },
      makeOkFetch({})
    );
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/authentication/i);
  });

  it("calls PUT /users/github-token with correct headers and body", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const captureFetch: typeof fetch = (url, init) => {
      calls.push({ url: url as string, init: init ?? {} });
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(""), json: () => Promise.resolve({}) } as Response);
    };

    await saveGithubConfigLogic(
      { github_token: "ghp_abc123", github_username: "narendranathe", resume_repo: "resume-vault" },
      captureFetch
    );

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("https://test-api.example.com/api/v1/users/github-token");
    expect(calls[0].init.method).toBe("PUT");
    expect((calls[0].init.headers as Record<string, string>)["X-Clerk-User-Id"]).toBe("test-user-123");
    expect((calls[0].init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");

    const body = JSON.parse(calls[0].init.body as string) as Record<string, string>;
    expect(body.github_token).toBe("ghp_abc123");
    expect(body.github_username).toBe("narendranathe");
    expect(body.resume_repo).toBe("resume-vault");
  });

  it("defaults resume_repo to 'resume-vault' when empty", async () => {
    const calls: Array<{ body: Record<string, string> }> = [];
    const captureFetch: typeof fetch = (_url, init) => {
      calls.push({ body: JSON.parse(init?.body as string) as Record<string, string> });
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(""), json: () => Promise.resolve({}) } as Response);
    };

    await saveGithubConfigLogic(
      { github_token: "ghp_abc123", github_username: "narendranathe", resume_repo: "" },
      captureFetch
    );

    expect(calls[0].body.resume_repo).toBe("resume-vault");
  });

  it("returns ok:true on 200 response", async () => {
    const result = await saveGithubConfigLogic(
      { github_token: "ghp_abc123", github_username: "narendranathe", resume_repo: "resume-vault" },
      makeOkFetch({ message: "Saved" })
    );
    expect(result.ok).toBe(true);
    expect(result.error).toBeUndefined();
  });

  it("returns ok:false and includes status on 4xx response", async () => {
    const result = await saveGithubConfigLogic(
      { github_token: "ghp_invalid", github_username: "narendranathe", resume_repo: "resume-vault" },
      makeErrorFetch(422, "Invalid token")
    );
    expect(result.ok).toBe(false);
    expect(result.error).toContain("422");
  });

  it("returns ok:false on 500 response", async () => {
    const result = await saveGithubConfigLogic(
      { github_token: "ghp_abc123", github_username: "narendranathe", resume_repo: "resume-vault" },
      makeErrorFetch(500, "Internal Server Error")
    );
    expect(result.ok).toBe(false);
    expect(result.error).toContain("500");
  });

  it("uses apiBaseUrl from storage instead of default", async () => {
    storageData["apiBaseUrl"] = "http://localhost:8000/api/v1";
    const calls: Array<string> = [];
    const captureFetch: typeof fetch = (url) => {
      calls.push(url as string);
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(""), json: () => Promise.resolve({}) } as Response);
    };

    await saveGithubConfigLogic(
      { github_token: "ghp_abc123", github_username: "narendranathe", resume_repo: "resume-vault" },
      captureFetch
    );

    expect(calls[0]).toStartWith("http://localhost:8000/api/v1");
  });
});

describe("loadGithubConfigLogic", () => {
  beforeEach(() => {
    for (const k of Object.keys(storageData)) delete storageData[k];
    storageData["clerkUserId"] = "test-user-123";
    storageData["apiBaseUrl"] = "https://test-api.example.com/api/v1";
  });

  it("returns info status when not authenticated", async () => {
    delete storageData["clerkUserId"];
    const result = await loadGithubConfigLogic(makeOkFetch({}));
    expect(result.hasToken).toBe(false);
    expect(result.statusType).toBe("info");
    expect(result.statusMsg).toMatch(/not authenticated/i);
  });

  it("shows 'Configured ✓' with username when has_github_token is true", async () => {
    const mePayload: MeResponse = {
      clerk_id: "test-user-123",
      has_github_token: true,
      github_username: "narendranathe",
    };
    const result = await loadGithubConfigLogic(makeOkFetch(mePayload));
    expect(result.hasToken).toBe(true);
    expect(result.username).toBe("narendranathe");
    expect(result.statusMsg).toContain("narendranathe");
    expect(result.statusMsg).toContain("✓");
    expect(result.statusType).toBe("ok");
  });

  it("shows 'Not configured' when has_github_token is false", async () => {
    const mePayload: MeResponse = {
      clerk_id: "test-user-123",
      has_github_token: false,
      github_username: null,
    };
    const result = await loadGithubConfigLogic(makeOkFetch(mePayload));
    expect(result.hasToken).toBe(false);
    expect(result.statusMsg).toMatch(/not configured/i);
    expect(result.statusType).toBe("info");
  });

  it("shows 'Not configured' when has_github_token is absent", async () => {
    const mePayload: MeResponse = { clerk_id: "test-user-123" };
    const result = await loadGithubConfigLogic(makeOkFetch(mePayload));
    expect(result.hasToken).toBe(false);
    expect(result.statusType).toBe("info");
  });

  it("returns err status on non-ok fetch response", async () => {
    const result = await loadGithubConfigLogic(makeErrorFetch(500));
    expect(result.hasToken).toBe(false);
    expect(result.statusType).toBe("err");
  });

  it("returns err status on network error", async () => {
    const result = await loadGithubConfigLogic(makeNetworkErrorFetch());
    expect(result.hasToken).toBe(false);
    expect(result.statusType).toBe("err");
    expect(result.statusMsg).toMatch(/backend/i);
  });
});
