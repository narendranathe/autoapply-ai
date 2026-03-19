import { useCallback, useEffect, useState } from "react";
import { vaultApi } from "../../shared/api";

export interface RagDocument {
  source_filename: string;
  doc_type: string;
  chunk_count: number;
  has_dense_embeddings: boolean;
  created_at: string;
}

export interface UseRagDocsResult {
  ragDocContent: string;
  setRagDocContent: React.Dispatch<React.SetStateAction<string>>;
  ragDocType: "resume" | "work_history";
  setRagDocType: React.Dispatch<React.SetStateAction<"resume" | "work_history">>;
  ragDocFilename: string;
  setRagDocFilename: React.Dispatch<React.SetStateAction<string>>;
  uploadingRagDoc: boolean;
  ragUploadResult: string;
  ragUploadError: string;
  ragDocList: RagDocument[];
  ragDocsLoaded: boolean;
  loadRagDocs: () => Promise<void>;
  handleUploadRagDoc: () => Promise<void>;
  handleDeleteRagDoc: (filename: string) => Promise<void>;
}

export function useRagDocs(): UseRagDocsResult {
  const [ragDocContent, setRagDocContent] = useState<string>("");
  const [ragDocType, setRagDocType] = useState<"resume" | "work_history">("resume");
  const [ragDocFilename, setRagDocFilename] = useState<string>("resume.md");
  const [uploadingRagDoc, setUploadingRagDoc] = useState(false);
  const [ragUploadResult, setRagUploadResult] = useState<string>("");
  const [ragUploadError, setRagUploadError] = useState<string>("");
  const [ragDocList, setRagDocList] = useState<RagDocument[]>([]);
  const [ragDocsLoaded, setRagDocsLoaded] = useState(false);

  const loadRagDocs = useCallback(async () => {
    try {
      const res = await vaultApi.listDocuments();
      setRagDocList(res.documents);
      setRagDocsLoaded(true);
    } catch {
      setRagDocsLoaded(true);
    }
  }, []);

  // Auto-load RAG docs on mount
  useEffect(() => {
    loadRagDocs();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleUploadRagDoc = useCallback(async () => {
    if (!ragDocContent.trim()) {
      setRagUploadError("Paste your markdown content first.");
      return;
    }
    setUploadingRagDoc(true);
    setRagUploadError("");
    setRagUploadResult("");
    try {
      const res = await vaultApi.uploadMarkdownDoc({
        content: ragDocContent,
        docType: ragDocType,
        sourceFilename: ragDocFilename || `${ragDocType}.md`,
      });
      setRagUploadResult(`✓ ${res.message}`);
      setRagDocContent("");
      await loadRagDocs();
    } catch (err) {
      setRagUploadError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploadingRagDoc(false);
    }
  }, [ragDocContent, ragDocType, ragDocFilename, loadRagDocs]);

  const handleDeleteRagDoc = useCallback(async (filename: string) => {
    try {
      await vaultApi.deleteDocument(filename);
      setRagDocList((prev) => prev.filter((d) => d.source_filename !== filename));
    } catch {
      /* ignore */
    }
  }, []);

  return {
    ragDocContent,
    setRagDocContent,
    ragDocType,
    setRagDocType,
    ragDocFilename,
    setRagDocFilename,
    uploadingRagDoc,
    ragUploadResult,
    ragUploadError,
    ragDocList,
    ragDocsLoaded,
    loadRagDocs,
    handleUploadRagDoc,
    handleDeleteRagDoc,
  };
}
