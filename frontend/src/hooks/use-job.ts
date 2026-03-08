import { useQuery } from "@tanstack/react-query";
import { jobsApi } from "@/api/jobs";

export const jobKeys = {
  detail: (jobId: string) => ["jobs", jobId] as const,
};

export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: jobId ? jobKeys.detail(jobId) : ["jobs", "idle"],
    queryFn: () => jobsApi.get(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 1000;
    },
  });
}
