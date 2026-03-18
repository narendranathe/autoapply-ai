/**
 * detection-patterns.ts — Shared field and question-category pattern tables.
 *
 * Single source of truth imported by both detector.ts and floatingPanel.ts.
 * Eliminates the constant duplication that previously existed between the two
 * content scripts.
 */

import type { FieldType, QuestionCategory } from "./types";

// ── Field detection patterns ────────────────────────────────────────────────

export const FIELD_PATTERNS: Array<{ type: FieldType; patterns: RegExp[] }> = [
  { type: "first_name", patterns: [/first[_\s-]?name/i, /fname/i, /given[_\s-]?name/i] },
  { type: "last_name",  patterns: [/last[_\s-]?name/i, /lname/i, /family[_\s-]?name/i, /surname/i] },
  { type: "full_name",  patterns: [/^name$/i, /full[_\s-]?name/i, /your[_\s-]?name/i] },
  { type: "email",      patterns: [/email/i] },
  { type: "phone",      patterns: [/phone/i, /mobile/i, /tel/i, /cell/i] },
  { type: "address",    patterns: [/address/i, /street/i] },
  { type: "city",       patterns: [/^city$/i, /city[_\s]?name/i] },
  { type: "state",      patterns: [/\bstate\b/i, /province/i, /region/i] },
  { type: "zip",        patterns: [/zip/i, /postal/i, /postcode/i] },
  { type: "country",    patterns: [/country/i, /nation/i, /reside\b/i, /resident/i, /united states/i] },
  { type: "us_resident", patterns: [/reside in the u\.?s/i, /us resident/i, /live in the (us|united states)/i] },
  { type: "linkedin",   patterns: [/linkedin/i] },
  { type: "github",     patterns: [/github/i] },
  { type: "portfolio",  patterns: [/portfolio/i, /personal[_\s-]?site/i, /personal[_\s-]?web/i] },
  { type: "website",    patterns: [/^website$/i, /web[_\s-]?site/i, /personal[_\s-]?url/i] },
  { type: "degree",     patterns: [/\bdegree\b/i, /education level/i, /highest.*degree/i, /level.*education/i, /\beducation\b/i] },
  { type: "skills",     patterns: [/skill/i] },
  { type: "years_experience", patterns: [/years.+experience/i, /experience.+years/i, /yoe/i] },
  { type: "salary",     patterns: [/salary/i, /compensation/i, /pay[_\s-]?expectation/i] },
  { type: "sponsorship", patterns: [/sponsor/i, /visa/i, /work[_\s-]?auth/i, /authorized.+work/i, /immigration/i, /h-?1b/i, /require.*employment/i] },
  { type: "demographic", patterns: [/race/i, /ethnicity/i, /gender/i, /veteran/i, /disability/i, /hispanic/i, /latino/i, /pronoun/i] },
];

// ── Question category patterns ──────────────────────────────────────────────

export const QUESTION_CATEGORY_PATTERNS: Array<{ category: QuestionCategory; patterns: RegExp[] }> = [
  { category: "cover_letter", patterns: [/cover.?letter/i, /letter of interest/i, /motivation letter/i] },
  { category: "why_company", patterns: [/why.+(want|interested|join|work|here|company)/i, /what draws you/i, /why do you want to work/i] },
  { category: "why_hire", patterns: [/why (should|hire|choose|best candidate)/i, /what makes you (unique|stand out)/i, /why are you the right/i] },
  { category: "about_yourself", patterns: [/tell us about yourself/i, /introduce yourself/i, /walk us through/i, /about yourself/i] },
  { category: "strength", patterns: [/strength/i, /excel at/i, /best at/i, /what are you good at/i] },
  { category: "weakness", patterns: [/weakness/i, /area.+improvement/i, /struggle with/i, /grow.+professionally/i] },
  { category: "challenge", patterns: [/challenge/i, /difficult situation/i, /obstacle/i, /failure/i, /overcame/i, /tough problem/i] },
  { category: "leadership", patterns: [/led|lead/i, /leadership/i, /managed a team/i, /team lead/i, /mentor/i] },
  { category: "conflict", patterns: [/conflict/i, /disagreement/i, /difficult coworker/i, /colleague/i, /difficult person/i] },
  { category: "motivation", patterns: [/motivat/i, /passion/i, /what drives/i, /inspires you/i] },
  { category: "five_years", patterns: [/5 years|five years/i, /career goal/i, /long.term/i, /see yourself/i, /where do you see/i] },
  { category: "impact", patterns: [/proud of/i, /biggest accomplishment/i, /greatest achievement/i, /most proud/i] },
  { category: "fit", patterns: [/align.+value/i, /culture/i, /what do you know about us/i, /research.+company/i, /our mission/i] },
  { category: "sponsorship", patterns: [/sponsor/i, /visa/i, /work authorization/i] },
];
