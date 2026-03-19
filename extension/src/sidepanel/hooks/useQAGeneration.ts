import { useCallback, useEffect, useRef, useState } from "react";
import type { PageContext } from "../../shared/types";
import { vaultApi, type SimilarAnswer } from "../../shared/api";
import { getFreshProviders } from "./useProviders";
import { workHistoryApi } from "../../shared/api";

// ── Draft persistence helpers (sessionStorage, keyed by job URL) ────────────

function draftKey(jobUrl: string | undefined, suffix: string): string {
  const base = jobUrl ? btoa(jobUrl).slice(0, 32) : "nojob";
  return `aap_drafts_${base}_${suffix}`;
}

function loadDraftSession<T>(jobUrl: string | undefined, suffix: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(draftKey(jobUrl, suffix));
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch { return fallback; }
}

function saveDraftSession(jobUrl: string | undefined, suffix: string, value: unknown): void {
  try {
    sessionStorage.setItem(draftKey(jobUrl, suffix), JSON.stringify(value));
  } catch { /* storage full — ignore */ }
}

export interface UseQAGenerationResult {
  answerDrafts: Record<string, string[]>;
  setAnswerDrafts: React.Dispatch<React.SetStateAction<Record<string, string[]>>>;
  selectedAnswers: Record<string, number>;
  setSelectedAnswers: React.Dispatch<React.SetStateAction<Record<string, number>>>;
  savingAnswer: string | null;
  generatingAnswer: string | null;
  draftProviders: Record<string, string[]>;
  setDraftProviders: React.Dispatch<React.SetStateAction<Record<string, string[]>>>;
  savedAnswerIds: Record<string, string>;
  generationErrors: Record<string, string>;
  memoryAnswers: Record<string, SimilarAnswer[]>;
  setMemoryAnswers: React.Dispatch<React.SetStateAction<Record<string, SimilarAnswer[]>>>;
  editedTexts: Record<string, string>;
  setEditedTexts: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  trimmingAnswer: string | null;
  copiedAllAnswers: boolean;
  setCopiedAllAnswers: React.Dispatch<React.SetStateAction<boolean>>;
  workHistoryText: string;
  promptTemplates: Record<string, string>;
  // Handlers
  handleGenerateAnswers: (questionId: string, questionText: string, category: string, isRegenerate?: boolean, maxLength?: number) => Promise<void>;
  handleSaveAnswer: (questionId: string, questionText: string, category: string) => Promise<void>;
  handleUseMemoryAnswer: (questionId: string, questionText: string, category: string, memory: SimilarAnswer) => void;
  handleTrimAnswer: (questionId: string, maxLength: number) => Promise<void>;
  persistDrafts: () => void;
}

export function useQAGeneration(
  context: PageContext,
  tab: string,
  promptTemplates: Record<string, string>
): UseQAGenerationResult {
  const jobUrl = context.jobUrl;

  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string[]>>(
    () => loadDraftSession(jobUrl, "answerDrafts", {})
  );
  const [selectedAnswers, setSelectedAnswers] = useState<Record<string, number>>(
    () => loadDraftSession(jobUrl, "selectedAnswers", {})
  );
  const [savingAnswer, setSavingAnswer] = useState<string | null>(null);
  const [generatingAnswer, setGeneratingAnswer] = useState<string | null>(null);
  const [draftProviders, setDraftProviders] = useState<Record<string, string[]>>(
    () => loadDraftSession(jobUrl, "draftProviders", {})
  );
  const [savedAnswerIds, setSavedAnswerIds] = useState<Record<string, string>>({});
  const [generationErrors, setGenerationErrors] = useState<Record<string, string>>({});
  const [memoryAnswers, setMemoryAnswers] = useState<Record<string, SimilarAnswer[]>>({});
  const [editedTexts, setEditedTexts] = useState<Record<string, string>>(
    () => loadDraftSession(jobUrl, "editedTexts", {})
  );
  const [trimmingAnswer, setTrimmingAnswer] = useState<string | null>(null);
  const [copiedAllAnswers, setCopiedAllAnswers] = useState(false);
  const [workHistoryText, setWorkHistoryText] = useState<string>("");

  useEffect(() => {
    workHistoryApi
      .getText()
      .then((res) => {
        if (res.text) setWorkHistoryText(res.text);
      })
      .catch(() => {}); // silently fail
  }, []);

  // Fetch "From Memory" similar answers whenever questions change
  useEffect(() => {
    if (context.openQuestions.length === 0) return;
    context.openQuestions.forEach((q) => {
      vaultApi
        .getSimilarAnswers({ questionText: q.questionText, questionCategory: q.category, topK: 3 })
        .then((res) => {
          if (res.answers.length > 0) {
            setMemoryAnswers((prev) => ({ ...prev, [q.questionId]: res.answers }));
          }
        })
        .catch(() => {}); // silently fail
    });
  }, [context.openQuestions]);

  const workHistoryRef = useRef(workHistoryText);
  workHistoryRef.current = workHistoryText;

  // Track which question IDs have been auto-triggered so we only fire once per question
  const autoTriggeredRef = useRef<Set<string>>(new Set());

  // Auto-generate when Q&A tab is active and new questions appear
  useEffect(() => {
    if (tab !== "questions") return;
    if (context.openQuestions.length === 0) return;
    const currentWorkHistory = workHistoryRef.current;

    context.openQuestions.forEach((q) => {
      if (autoTriggeredRef.current.has(q.questionId)) return;
      autoTriggeredRef.current.add(q.questionId);

      setGeneratingAnswer(q.questionId);
      setGenerationErrors((prev) => { const n = { ...prev }; delete n[q.questionId]; return n; });

      getFreshProviders().then((freshProviders) => {
        if (freshProviders.length === 0) {
          autoTriggeredRef.current.delete(q.questionId);
          setGeneratingAnswer((cur) => cur === q.questionId ? null : cur);
          setGenerationErrors((prev) => ({ ...prev, [q.questionId]: "No API key found. Open Settings → enter any Groq or Gemini key → Save LLM Settings." }));
          return;
        }
        return vaultApi.generateAnswers({
          questionText: q.questionText,
          questionCategory: q.category,
          companyName: context.company,
          roleTitle: context.roleTitle,
          jdText: context.jdText ?? "",
          workHistoryText: currentWorkHistory,
          maxLength: q.maxLength,
          providers: freshProviders,
          categoryInstructions: promptTemplates[q.category] || promptTemplates["custom"],
        }).then((res) => {
          if (!res.drafts?.length) {
            setGenerationErrors((prev) => ({ ...prev, [q.questionId]: "All providers failed — check your API keys in Settings." }));
            return;
          }
          setAnswerDrafts((prev) => ({ ...prev, [q.questionId]: res.drafts }));
          setSelectedAnswers((prev) => ({ ...prev, [q.questionId]: 0 }));
          setEditedTexts((prev) => ({ ...prev, [q.questionId]: res.drafts[0] ?? "" }));
          if (res.draft_providers?.length) {
            setDraftProviders((prev) => ({ ...prev, [q.questionId]: res.draft_providers! }));
          } else {
            setGenerationErrors((prev) => ({ ...prev, [q.questionId]: "⚠ LLM fallback used — placeholder answers shown. Check your API keys." }));
          }
        }).catch((e) => {
          autoTriggeredRef.current.delete(q.questionId);
          setGenerationErrors((prev) => ({ ...prev, [q.questionId]: e instanceof Error ? e.message : "Generation failed" }));
        }).finally(() => {
          setGeneratingAnswer((cur) => cur === q.questionId ? null : cur);
        });
      });
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, context.openQuestions]);

  const handleGenerateAnswers = useCallback(async (
    questionId: string,
    questionText: string,
    category: string,
    isRegenerate = false,
    maxLength?: number
  ) => {
    const freshProviders = await getFreshProviders();
    if (freshProviders.length === 0) {
      setGenerationErrors((prev) => ({ ...prev, [questionId]: "No API key found. Open Settings → enter any Groq or Gemini key → Save LLM Settings." }));
      return;
    }
    if (isRegenerate) {
      if (savedAnswerIds[questionId]) {
        vaultApi.recordFeedback({ answerId: savedAnswerIds[questionId], feedback: "regenerated" }).catch(() => {});
      }
      setAnswerDrafts((prev) => { const n = { ...prev }; delete n[questionId]; return n; });
      setDraftProviders((prev) => { const n = { ...prev }; delete n[questionId]; return n; });
      setEditedTexts((prev) => { const n = { ...prev }; delete n[questionId]; return n; });
    }
    setGeneratingAnswer(questionId);
    setGenerationErrors((prev) => { const n = { ...prev }; delete n[questionId]; return n; });
    try {
      const res = await vaultApi.generateAnswers({
        questionText,
        questionCategory: category,
        companyName: context.company,
        roleTitle: context.roleTitle,
        jdText: context.jdText ?? "",
        workHistoryText: workHistoryRef.current,
        maxLength,
        providers: freshProviders,
        categoryInstructions: promptTemplates[category] || promptTemplates["custom"],
      });
      if (!res.drafts?.length) {
        setGenerationErrors((prev) => ({ ...prev, [questionId]: "All providers failed — check your API keys in Settings." }));
        return;
      }
      setAnswerDrafts((prev) => ({ ...prev, [questionId]: res.drafts }));
      setSelectedAnswers((prev) => ({ ...prev, [questionId]: 0 }));
      setEditedTexts((prev) => ({ ...prev, [questionId]: res.drafts[0] ?? "" }));
      if (res.draft_providers?.length) {
        setDraftProviders((prev) => ({ ...prev, [questionId]: res.draft_providers! }));
      } else {
        setGenerationErrors((prev) => ({ ...prev, [questionId]: "⚠ LLM fallback used — showing placeholder answers. Check your API keys." }));
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Generation failed";
      setGenerationErrors((prev) => ({ ...prev, [questionId]: msg }));
    } finally {
      setGeneratingAnswer(null);
    }
  }, [context.company, context.roleTitle, context.jdText, promptTemplates, savedAnswerIds]);

  const handleSaveAnswer = useCallback(async (questionId: string, questionText: string, category: string) => {
    const idx = selectedAnswers[questionId] ?? 0;
    const originalDraft = answerDrafts[questionId]?.[idx] ?? "";
    const finalText = (editedTexts[questionId] ?? originalDraft).trim();
    if (!finalText) return;

    const wasEdited = finalText !== originalDraft.trim();

    setSavingAnswer(questionId);
    try {
      const saved = await vaultApi.saveAnswer({
        questionText,
        questionCategory: category,
        answerText: finalText,
        companyName: context.company,
        roleTitle: context.roleTitle,
        llmProviderUsed: draftProviders[questionId]?.[0],
      });
      setSavedAnswerIds((prev) => ({ ...prev, [questionId]: saved.answer_id }));
      vaultApi.recordFeedback({
        answerId: saved.answer_id,
        feedback: wasEdited ? "edited" : "used_as_is",
        editedAnswer: wasEdited ? finalText : undefined,
      }).catch(() => {});
      chrome.runtime.sendMessage({ type: "FILL_ANSWER", payload: { questionId, text: finalText } });
    } finally {
      setSavingAnswer(null);
    }
  }, [selectedAnswers, answerDrafts, editedTexts, context.company, context.roleTitle, draftProviders]);

  const handleUseMemoryAnswer = useCallback((questionId: string, questionText: string, category: string, memory: SimilarAnswer) => {
    vaultApi.recordFeedback({ answerId: memory.answer_id, feedback: "used_as_is" }).catch(() => {});
    vaultApi.saveAnswer({
      questionText,
      questionCategory: category,
      answerText: memory.answer_text,
      companyName: context.company,
      roleTitle: context.roleTitle,
    }).catch(() => {});
    chrome.runtime.sendMessage({ type: "FILL_ANSWER", payload: { questionId, text: memory.answer_text } });
  }, [context.company, context.roleTitle]);

  const handleTrimAnswer = useCallback(async (questionId: string, maxLength: number) => {
    const currentText = editedTexts[questionId] ?? answerDrafts[questionId]?.[selectedAnswers[questionId] ?? 0] ?? "";
    if (!currentText || currentText.length <= maxLength) return;
    setTrimmingAnswer(questionId);
    try {
      const freshProviders = await getFreshProviders();
      const res = await vaultApi.trimAnswer({ answerText: currentText, maxChars: maxLength, providers: freshProviders });
      setEditedTexts((prev) => ({ ...prev, [questionId]: res.trimmed }));
    } catch { /* silently ignore */ } finally {
      setTrimmingAnswer(null);
    }
  }, [editedTexts, answerDrafts, selectedAnswers]);

  const persistDrafts = useCallback(() => {
    saveDraftSession(jobUrl, "answerDrafts", answerDrafts);
    saveDraftSession(jobUrl, "selectedAnswers", selectedAnswers);
    saveDraftSession(jobUrl, "draftProviders", draftProviders);
    saveDraftSession(jobUrl, "editedTexts", editedTexts);
  }, [jobUrl, answerDrafts, selectedAnswers, draftProviders, editedTexts]);

  return {
    answerDrafts,
    setAnswerDrafts,
    selectedAnswers,
    setSelectedAnswers,
    savingAnswer,
    generatingAnswer,
    draftProviders,
    setDraftProviders,
    savedAnswerIds,
    generationErrors,
    memoryAnswers,
    setMemoryAnswers,
    editedTexts,
    setEditedTexts,
    trimmingAnswer,
    copiedAllAnswers,
    setCopiedAllAnswers,
    workHistoryText,
    promptTemplates,
    handleGenerateAnswers,
    handleSaveAnswer,
    handleUseMemoryAnswer,
    handleTrimAnswer,
    persistDrafts,
  };
}
