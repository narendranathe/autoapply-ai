/**
 * Tests for isEssayQuestion / NON_QUESTION_PATTERNS / MIN_ESSAY_LABEL_LENGTH.
 *
 * Test infrastructure: node --test (built-in) + esbuild (already a transitive
 * dep of vite, available in node_modules) + node:vm.
 *
 * detector.ts runs browser-only side effects at module load (chrome.runtime,
 * MutationObserver, document.body, history.pushState patching, etc.), so we
 * bundle it with esbuild into a CJS string and execute it inside a vm context
 * pre-populated with minimal stubs. The exports we care about are pure
 * functions and constants — they work fine under stubbed globals.
 *
 * Run:
 *   cd extension && node --test src/content/__tests__/isEssayQuestion.test.mjs
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import * as esbuild from "esbuild";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const detectorPath = path.resolve(__dirname, "../detector.ts");

async function loadDetectorExports() {
  const result = await esbuild.build({
    entryPoints: [detectorPath],
    bundle: true,
    format: "cjs",
    platform: "neutral",
    write: false,
    logLevel: "silent",
  });
  const code = result.outputFiles[0].text;

  const noopEl = {
    addEventListener: () => {},
    removeEventListener: () => {},
    querySelector: () => null,
    querySelectorAll: () => [],
    getAttribute: () => null,
    appendChild: () => {},
  };
  const sandbox = {
    module: { exports: {} },
    exports: {},
    require: () => ({}),
    console,
    setTimeout, clearTimeout, setInterval, clearInterval,
    document: {
      addEventListener: () => {},
      querySelector: () => null,
      querySelectorAll: () => [],
      getElementById: () => null,
      createElement: () => noopEl,
      title: "",
      body: null,
    },
    window: { addEventListener: () => {}, location: { href: "" } },
    history: { pushState: () => {}, replaceState: () => {} },
    chrome: {
      runtime: {
        onMessage: { addListener: () => {} },
        sendMessage: () => Promise.resolve(),
      },
    },
    MutationObserver: function MutationObserver() { return { observe: () => {} }; },
    HTMLElement: function HTMLElement() {},
    HTMLInputElement: function HTMLInputElement() {},
    HTMLTextAreaElement: function HTMLTextAreaElement() {},
    HTMLSelectElement: function HTMLSelectElement() {},
    Event: function Event() {},
    InputEvent: function InputEvent() {},
    DataTransfer: function DataTransfer() {},
    File: function File() {},
    fetch: () => Promise.resolve({}),
  };
  sandbox.window.self = sandbox.window;
  sandbox.window.top = sandbox.window;
  sandbox.globalThis = sandbox;

  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);

  return sandbox.module.exports;
}

const detector = await loadDetectorExports();
const { isEssayQuestion, NON_QUESTION_PATTERNS, MIN_ESSAY_LABEL_LENGTH } = detector;

test("MIN_ESSAY_LABEL_LENGTH is 15", () => {
  assert.equal(MIN_ESSAY_LABEL_LENGTH, 15);
});

test("NON_QUESTION_PATTERNS is a RegExp", () => {
  // Built in a separate vm context, so instanceof fails — duck-type instead.
  assert.equal(typeof NON_QUESTION_PATTERNS.test, "function");
  assert.equal(typeof NON_QUESTION_PATTERNS.source, "string");
  assert.equal(NON_QUESTION_PATTERNS.flags, "i");
});

// ── Positive cases: real essay questions ─────────────────────────────────────

test("essay: 'Why do you want to work here?' is an essay question", () => {
  assert.equal(isEssayQuestion("Why do you want to work here?"), true);
});

test("essay: 'Tell us about a project you are proud of.' is an essay question", () => {
  assert.equal(isEssayQuestion("Tell us about a project you are proud of."), true);
});

test("essay: 'Describe a time you led a team through change.' is an essay question", () => {
  assert.equal(isEssayQuestion("Describe a time you led a team through change."), true);
});

test("essay: 'What interests you about this role?' is an essay question", () => {
  assert.equal(isEssayQuestion("What interests you about this role?"), true);
});

test("essay: 'How would you approach scaling our platform?' is an essay question", () => {
  assert.equal(isEssayQuestion("How would you approach scaling our platform?"), true);
});

// ── Negative cases: contact / URL / name / metadata fields ───────────────────

test("non-question: 'LinkedIn Profile URL' is not an essay question", () => {
  assert.equal(isEssayQuestion("LinkedIn Profile URL"), false);
});

test("non-question: 'Name' is not an essay question (too short)", () => {
  assert.equal(isEssayQuestion("Name"), false);
});

test("non-question: 'First Name' is not an essay question", () => {
  assert.equal(isEssayQuestion("First Name"), false);
});

test("non-question: 'Last Name' is not an essay question", () => {
  assert.equal(isEssayQuestion("Last Name"), false);
});

test("non-question: 'Full Name' is not an essay question", () => {
  assert.equal(isEssayQuestion("Full Name"), false);
});

test("non-question: 'Email Address' is not an essay question", () => {
  assert.equal(isEssayQuestion("Email Address"), false);
});

test("non-question: 'Phone Number' is not an essay question", () => {
  assert.equal(isEssayQuestion("Phone Number"), false);
});

test("non-question: 'GitHub Profile URL' is not an essay question", () => {
  assert.equal(isEssayQuestion("GitHub Profile URL"), false);
});

test("non-question: 'Portfolio Website' is not an essay question", () => {
  assert.equal(isEssayQuestion("Portfolio Website"), false);
});

test("non-question: 'Website' is not an essay question", () => {
  assert.equal(isEssayQuestion("Website"), false);
});

test("non-question: 'Address Line 1' is not an essay question", () => {
  assert.equal(isEssayQuestion("Address Line 1"), false);
});

test("non-question: 'City' is not an essay question (too short)", () => {
  assert.equal(isEssayQuestion("City"), false);
});

test("non-question: 'Zip Code' is not an essay question", () => {
  assert.equal(isEssayQuestion("Zip Code"), false);
});

test("non-question: 'Country of Residence' is not an essay question", () => {
  assert.equal(isEssayQuestion("Country of Residence"), false);
});

test("non-question: 'Salary Expectations' is not an essay question", () => {
  assert.equal(isEssayQuestion("Salary Expectations"), false);
});

test("non-question: 'Start Date' is not an essay question", () => {
  assert.equal(isEssayQuestion("Start Date"), false);
});

// ── Length edge cases ────────────────────────────────────────────────────────

test("length: label shorter than MIN_ESSAY_LABEL_LENGTH is rejected", () => {
  assert.equal(isEssayQuestion("Too short"), false);
});

test("length: whitespace is trimmed before length check", () => {
  assert.equal(isEssayQuestion("   Name   "), false);
});

test("length: label exactly MIN_ESSAY_LABEL_LENGTH passes when not a contact field", () => {
  const label = "Cover your story"; // 16 chars, doesn't match NON_QUESTION_PATTERNS
  assert.ok(label.length >= MIN_ESSAY_LABEL_LENGTH);
  assert.equal(isEssayQuestion(label), true);
});
