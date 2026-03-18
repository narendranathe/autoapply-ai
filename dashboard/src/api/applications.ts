import type { AxiosInstance } from "axios";

export type AppStatus =
  | "discovered"
  | "draft"
  | "tailored"
  | "applied"
  | "phone_screen"
  | "interview"
  | "offer"
  | "rejected";

export interface ApplicationRecord {
  id: string;
  company_name: string;
  role_title: string;
  job_url: string | null;
  platform: string | null;
  status: AppStatus;
  similarity_score: number | null;
  notes: string | null;
  created_at: string;
}

export interface ApplicationListResponse {
  items: ApplicationRecord[];
  total: number;
  page: number;
  per_page: number;
  has_next: boolean;
}

export interface FunnelStage {
  status: string;
  count: number;
  conversion_rate: number | null;
}

export interface FunnelResponse {
  total: number;
  funnel: FunnelStage[];
}

export async function fetchApplications(
  client: AxiosInstance,
  page = 1,
  perPage = 100,
): Promise<ApplicationListResponse> {
  const { data } = await client.get<ApplicationListResponse>("/applications", {
    params: { page, per_page: perPage },
  });
  return data;
}

export async function fetchFunnel(client: AxiosInstance): Promise<FunnelResponse> {
  const { data } = await client.get<FunnelResponse>("/applications/funnel");
  return data;
}

export async function patchApplicationStatus(
  client: AxiosInstance,
  id: string,
  status: AppStatus,
): Promise<ApplicationRecord> {
  const { data } = await client.patch<ApplicationRecord>(`/applications/${id}`, { status });
  return data;
}
