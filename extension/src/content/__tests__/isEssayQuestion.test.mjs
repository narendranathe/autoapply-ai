/**
 * Tests for isEssayQuestion / NON_QUESTION_PATTERNS / MIN_ESSAY_LABEL_LENGTH.
 *
 * Imports directly from the pure sibling module `../essay-detection.ts`,
 * which has no browser side effects. Node strips TS types via
 * --experimental-strip-types (Node 22+).
 *
 * Run:
 *   cd extension && npm test
 *   # or: node --test --experimental-strip-types src/content/__tests__/isEssayQuestion.test.mjs
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  isEssayQuestion,
  NON_QUESTION_PATTERNS,
  MIN_ESSAY_LABEL_LENGTH,
} from "../essay-detection.ts";

test("MIN_ESSAY_LABEL_LENGTH is 15", () => {
  assert.equal(MIN_ESSAY_LABEL_LENGTH, 15);
});

test("NON_QUESTION_PATTERNS is a case-insensitive RegExp", () => {
  assert.ok(NON_QUESTION_PATTERNS instanceof RegExp);
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
