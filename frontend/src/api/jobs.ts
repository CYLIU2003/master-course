import { api } from "./client";
import type { JobResponse } from "@/types";

export const jobsApi = {
  get: (jobId: string) => api.get<JobResponse>(`/jobs/${jobId}`),
};
