/**
 * Pure helpers for classifying form field labels as open-ended essay questions.
 *
 * Lives in a side-effect-free module (no DOM, no chrome.runtime access) so it
 * can be imported by both the browser content script (detector.ts) and unit
 * tests that run under plain Node — no esbuild + vm scaffolding required.
 *
 * Spec reference: issue #122.
 */

/**
 * Labels matching this prefix regex are treated as contact/URL/metadata fields
 * rather than free-text essay prompts. Kept verbatim from the issue spec; see
 * follow-up issues for known false negatives (e.g. "Linker library experience"
 * matches `^link`) and word-boundary tightening.
 */
export const NON_QUESTION_PATTERNS =
  /^(url|website|link|linkedin|github|portfolio|email|phone|name|first\s?name|last\s?name|full\s?name|address|city|zip|country|salary|start\s?date)/i;

/**
 * Labels shorter than this are unlikely to be real essay prompts (typically
 * single-word inputs like "Name" / "City"). Spec-defined.
 */
export const MIN_ESSAY_LABEL_LENGTH = 15;

/**
 * Returns true if the given field label looks like an open-ended essay
 * prompt: long enough and not a known contact/URL field prefix.
 */
export function isEssayQuestion(label: string): boolean {
  const normalized = label.trim();
  if (normalized.length < MIN_ESSAY_LABEL_LENGTH) return false;
  if (NON_QUESTION_PATTERNS.test(normalized)) return false;
  return true;
}
