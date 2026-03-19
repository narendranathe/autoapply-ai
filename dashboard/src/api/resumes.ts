import type { AxiosInstance } from "axios";

export interface ResumeRecord {
  id: string;
  filename: string;
  file_type: string;
  version_tag?: string | null;
  target_company?: string | null;
  target_role?: string | null;
  is_base_template?: boolean;
  created_at: string;
  file_hash?: string | null;
}

export async function fetchResumes(client: AxiosInstance): Promise<ResumeRecord[]> {
  const { data } = await client.get<ResumeRecord[]>("/vault/resumes");
  return data;
}

export async function downloadResume(client: AxiosInstance, id: string): Promise<Blob> {
  const { data } = await client.get(`/vault/resumes/${id}/download`, { responseType: "blob" });
  return data;
}

export async function uploadResume(client: AxiosInstance, formData: FormData): Promise<ResumeRecord> {
  const { data } = await client.post<ResumeRecord>("/vault/resumes/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}
