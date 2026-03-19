import axios from "axios";
import { useMemo } from "react";
import { useSafeAuth } from "../components/ProtectedRoute";

const BASE_URL = import.meta.env.VITE_API_URL ?? "https://autoapply-ai-api.fly.dev/api/v1";

export function useApiClient() {
  const { getToken } = useSafeAuth();

  return useMemo(() => {
    const client = axios.create({ baseURL: BASE_URL });
    client.interceptors.request.use(async (config) => {
      const token = await getToken?.();
      if (token) config.headers.Authorization = `Bearer ${token}`;
      return config;
    });
    return client;
  }, [getToken]);
}
