/**
 * Tests for the IframeFieldBridge postMessage allowlist (issue #101).
 *
 * Runner: node --test --experimental-strip-types (Node 22+, no extra deps).
 *   node --test --experimental-strip-types src/shared/__tests__/ats-origins.test.ts
 *
 * Covers:
 *   - isAllowedAtsOrigin() rejects "*", "null", and unknown origins
 *   - isAllowedAtsOrigin() accepts the 5 tracked Platforms (linkedin,
 *     greenhouse, lever, workday, indeed) and their known subdomains
 *   - Receiver-side handler drops messages whose origin is "*"
 *   - Sender-side helper refuses to post to a non-allowlisted iframe
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { isAllowedAtsOrigin, ATS_ORIGIN_PATTERNS } from "../ats-origins.ts";

describe("isAllowedAtsOrigin", () => {
  it("rejects wildcard '*'", () => {
    assert.equal(isAllowedAtsOrigin("*"), false);
  });

  it("rejects 'null' origin (sandboxed iframes / opaque origins)", () => {
    assert.equal(isAllowedAtsOrigin("null"), false);
  });

  it("rejects empty / nullish origins", () => {
    assert.equal(isAllowedAtsOrigin(""), false);
    assert.equal(isAllowedAtsOrigin(null), false);
    assert.equal(isAllowedAtsOrigin(undefined), false);
  });

  it("rejects look-alike attacker origins", () => {
    assert.equal(isAllowedAtsOrigin("https://linkedin.com.evil.com"), false);
    assert.equal(isAllowedAtsOrigin("https://evil.com/linkedin.com"), false);
    assert.equal(isAllowedAtsOrigin("https://greenhouse.io.attacker.net"), false);
    assert.equal(isAllowedAtsOrigin("https://notworkday.com"), false);
  });

  it("rejects arbitrary origins not in the allowlist", () => {
    assert.equal(isAllowedAtsOrigin("https://example.com"), false);
    assert.equal(isAllowedAtsOrigin("https://attacker.io"), false);
    assert.equal(isAllowedAtsOrigin("http://localhost:3000"), false);
  });

  it("accepts each of the 5 tracked Platforms at apex + subdomain", () => {
    const allowed = [
      "https://www.linkedin.com",
      "https://linkedin.com",
      "https://boards.greenhouse.io",
      "https://greenhouse.io",
      "https://jobs.lever.co",
      "https://lever.co",
      "https://wd5.myworkdayjobs.com",
      "https://company.myworkday.com",
      "https://workday.com",
      "https://www.indeed.com",
      "https://indeed.com",
    ];
    for (const origin of allowed) {
      assert.equal(isAllowedAtsOrigin(origin), true, `expected allowed: ${origin}`);
    }
  });

  it("covers all 5 tracked Platforms in the pattern list", () => {
    const haystack = ATS_ORIGIN_PATTERNS.map((re) => re.source).join("\n");
    for (const platform of ["linkedin", "greenhouse", "lever", "workday", "indeed"]) {
      assert.ok(haystack.includes(platform), `missing platform pattern: ${platform}`);
    }
  });
});

describe("IframeFieldBridge receiver", () => {
  function buildReceiver(): {
    handler: (e: { origin: string; data: unknown }) => void;
    processed: Array<{ origin: string; data: unknown }>;
  } {
    const processed: Array<{ origin: string; data: unknown }> = [];
    const handler = (e: { origin: string; data: unknown }): void => {
      if (!isAllowedAtsOrigin(e.origin)) return;
      const data = e.data as { type?: string } | null;
      if (data?.type !== "AAP_SCAN_FIELDS" && data?.type !== "AAP_FILL_FIELD") return;
      processed.push({ origin: e.origin, data });
    };
    return { handler, processed };
  }

  it("drops messages whose origin is '*'", () => {
    const { handler, processed } = buildReceiver();
    handler({ origin: "*", data: { type: "AAP_SCAN_FIELDS" } });
    assert.equal(processed.length, 0);
  });

  it("drops messages from non-allowlisted origins", () => {
    const { handler, processed } = buildReceiver();
    handler({ origin: "https://evil.com", data: { type: "AAP_FILL_FIELD", fieldId: "x", value: "y" } });
    handler({ origin: "https://linkedin.com.evil.com", data: { type: "AAP_SCAN_FIELDS" } });
    assert.equal(processed.length, 0);
  });

  it("processes messages from allowlisted ATS origins", () => {
    const { handler, processed } = buildReceiver();
    handler({ origin: "https://boards.greenhouse.io", data: { type: "AAP_SCAN_FIELDS" } });
    handler({ origin: "https://company.myworkday.com", data: { type: "AAP_FILL_FIELD", fieldId: "a", value: "b" } });
    assert.equal(processed.length, 2);
  });
});

describe("IframeFieldBridge sender", () => {
  function fakePostToIframe(
    iframe: { origin: string | null; postMessage: (msg: unknown, targetOrigin: string) => void },
    msg: unknown,
  ): { sent: boolean; targetOrigin: string | null } {
    const origin = iframe.origin;
    if (!origin || !isAllowedAtsOrigin(origin)) return { sent: false, targetOrigin: null };
    iframe.postMessage(msg, origin);
    return { sent: true, targetOrigin: origin };
  }

  it("does not post to an iframe whose origin is unknown / cross-origin", () => {
    const calls: Array<{ msg: unknown; targetOrigin: string }> = [];
    const result = fakePostToIframe(
      { origin: null, postMessage: (msg, targetOrigin) => calls.push({ msg, targetOrigin }) },
      { type: "AAP_SCAN_FIELDS" },
    );
    assert.equal(result.sent, false);
    assert.equal(calls.length, 0);
  });

  it("does not post to an iframe on a non-allowlisted origin", () => {
    const calls: Array<{ targetOrigin: string }> = [];
    const result = fakePostToIframe(
      { origin: "https://example.com", postMessage: (_m, targetOrigin) => calls.push({ targetOrigin }) },
      { type: "AAP_SCAN_FIELDS" },
    );
    assert.equal(result.sent, false);
    assert.equal(calls.length, 0);
  });

  it("never falls back to '*' even when origin resolution fails", () => {
    const calls: Array<string> = [];
    fakePostToIframe(
      { origin: null, postMessage: (_m, targetOrigin) => calls.push(targetOrigin) },
      { type: "AAP_FILL_FIELD", fieldId: "x", value: "y" },
    );
    assert.ok(!calls.includes("*"), "must never broadcast with targetOrigin '*'");
  });

  it("posts to the resolved ATS origin when allowlisted", () => {
    const calls: Array<{ targetOrigin: string }> = [];
    const result = fakePostToIframe(
      {
        origin: "https://wd5.myworkdayjobs.com",
        postMessage: (_m, targetOrigin) => calls.push({ targetOrigin }),
      },
      { type: "AAP_SCAN_FIELDS" },
    );
    assert.equal(result.sent, true);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].targetOrigin, "https://wd5.myworkdayjobs.com");
  });
});
