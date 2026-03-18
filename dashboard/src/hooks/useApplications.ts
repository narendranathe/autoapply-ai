import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "./useApiClient";
import {
  fetchApplications,
  fetchFunnel,
  patchApplicationStatus,
  type AppStatus,
  type ApplicationListResponse,
} from "../api/applications";

const QUERY_KEY = ["applications"] as const;
const FUNNEL_KEY = ["applications-funnel"] as const;

export function useApplications() {
  const client = useApiClient();
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => fetchApplications(client),
  });
}

export function useFunnel() {
  const client = useApiClient();
  return useQuery({
    queryKey: FUNNEL_KEY,
    queryFn: () => fetchFunnel(client),
  });
}

export function useUpdateStatus() {
  const client = useApiClient();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: AppStatus }) =>
      patchApplicationStatus(client, id, status),

    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: QUERY_KEY });
      const previous = qc.getQueryData<ApplicationListResponse>(QUERY_KEY);

      qc.setQueryData<ApplicationListResponse>(QUERY_KEY, (old) => {
        if (!old) return old;
        return {
          ...old,
          items: old.items.map((app) => (app.id === id ? { ...app, status } : app)),
        };
      });

      return { previous };
    },

    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) {
        qc.setQueryData(QUERY_KEY, ctx.previous);
      }
    },

    onSettled: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      qc.invalidateQueries({ queryKey: FUNNEL_KEY });
    },
  });
}
