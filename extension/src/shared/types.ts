// Shared TypeScript types across background, content, and sidepanel

export type ExtensionMode = "idle" | "scout" | "apply";

export interface PageContext {
  mode: ExtensionMode;
  company: string;
  roleTitle: string;
  jobId?: string;
  jobUrl: string;
  platform: string; // linkedin | greenhouse | lever | workday | indeed | glassdoor | generic
  detectedFields: DetectedField[];
  openQuestions: DetectedQuestion[];
}

export interface DetectedField {
  fieldId: string;       // DOM element id / generated key
  fieldType: FieldType;
  label: string;
  currentValue: string;
  suggestedValue: string;
  confidence: number;    // 0.0–1.0
}

export type FieldType =
  | "first_name" | "last_name" | "full_name"
  | "email" | "phone"
  | "address" | "city" | "state" | "zip"
  | "linkedin" | "portfolio" | "website"
  | "resume_upload" | "cover_letter_upload"
  | "skills" | "years_experience" | "salary"
  | "sponsorship" | "demographic"
  | "unknown";

export interface DetectedQuestion {
  questionId: string;
  questionText: string;
  category: QuestionCategory;
  fieldType: "textarea" | "text";
  maxLength?: number;
}

export type QuestionCategory =
  | "why_company" | "why_hire" | "about_yourself"
  | "strength" | "weakness" | "challenge" | "leadership"
  | "conflict" | "motivation" | "five_years" | "impact"
  | "fit" | "sponsorship" | "custom";

export interface ResumeCard {
  resumeId: string;
  versionTag: string | null;
  filename: string;
  targetCompany: string | null;
  targetRole: string | null;
  atsScore: number | null;
  similarityScore: number;
  lastUsed: string | null;
  outcomes: string[];
  githubPath: string | null;
}

export interface ATSScoreResult {
  overallScore: number;
  keywordCoverage: number;
  skillsPresent: string[];
  skillsGap: string[];
  quantificationScore: number;
  experienceAlignment: number;
  mqCoverage: number;
  suggestions: string[];
  totalJdKeywords: number;
  matchedKeywords: number;
}

export interface AnswerDraft {
  text: string;
  wordCount: number;
  index: number;
}

export interface JobCard {
  company: string;
  role: string;
  url: string;
}

// Messages between content script ↔ background ↔ sidepanel
export type Message =
  | { type: "PAGE_CONTEXT_UPDATE"; payload: PageContext }
  | { type: "OPEN_SIDEPANEL" }
  | { type: "FILL_FIELD"; payload: { fieldId: string; value: string } }
  | { type: "FILL_ANSWER"; payload: { questionId: string; text: string } }
  | { type: "ATTACH_RESUME"; payload: { fieldId: string; pdfUrl: string } }
  | { type: "JOB_CARDS_UPDATE"; payload: JobCard[] }
  | { type: "GET_CONTEXT" }
  | { type: "CONTEXT_RESPONSE"; payload: PageContext | null };

// Offline sync queue entry
export interface OfflineEdit {
  id: string;
  versionTag: string;
  markdownContent: string;
  timestamp: number;
  synced: boolean;
}
