/**
 * Tests for useTabNavigation hook.
 *
 * NOTE: @testing-library/react is NOT currently in package.json.
 * To run these tests, add a test runner (e.g. vitest) and
 * @testing-library/react-hooks (or @testing-library/react >=13).
 *
 * Dependency install command:
 *   npm install -D vitest @testing-library/react @testing-library/user-event jsdom
 *
 * These tests are written in the Vitest/Jest style and serve as the
 * RED phase of the red-green-refactor cycle. They will not run until
 * the test infrastructure is wired up.
 */

import { useTabNavigation, DEFAULT_TAB } from "../useTabNavigation";
import type { Tab } from "../useTabNavigation";

// ---------------------------------------------------------------------------
// Minimal renderHook shim — replace with @testing-library/react once installed
// ---------------------------------------------------------------------------
function renderHook<T>(hook: () => T): { result: { current: T } } {
  // This shim will throw at runtime once the real hook throws "not implemented".
  // After GREEN phase, wire up vitest + @testing-library/react to run properly.
  const result = { current: hook() };
  return { result };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useTabNavigation", () => {
  it("initialises with the default tab ('resumes')", () => {
    const { result } = renderHook(() => useTabNavigation());
    expect(result.current.tab).toBe(DEFAULT_TAB);
    expect(result.current.tab).toBe("resumes");
  });

  it("initialises with a custom initial tab when provided", () => {
    const { result } = renderHook(() => useTabNavigation("questions"));
    expect(result.current.tab).toBe("questions");
  });

  it("setTab updates the active tab", () => {
    const { result } = renderHook(() => useTabNavigation());
    // Initial state
    expect(result.current.tab).toBe("resumes");
    // Change to 'fields'
    result.current.setTab("fields");
    expect(result.current.tab).toBe("fields");
  });

  it("setTab accepts all valid Tab values", () => {
    const allTabs: Tab[] = ["resumes", "fields", "questions", "history", "prep", "cover"];
    for (const t of allTabs) {
      const { result } = renderHook(() => useTabNavigation());
      result.current.setTab(t);
      expect(result.current.tab).toBe(t);
    }
  });
});
