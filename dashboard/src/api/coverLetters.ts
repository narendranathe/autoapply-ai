import type { AxiosInstance } from "axios";

export interface CoverLetter {
  id: string;
  company_name?: string | null;
  role_title?: string | null;
  content: string;
  created_at: string;
}

export async function fetchCoverLetters(client: AxiosInstance): Promise<CoverLetter[]> {
  const { data } = await client.get<CoverLetter[]>("/vault/cover-letters");
  return data;
}
