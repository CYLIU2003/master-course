import { api } from "./client";
import type { AppDataStatusResponse, ResearchDatasetsResponse } from "@/types";

export const appApi = {
  listDatasets: () => api.get<ResearchDatasetsResponse>("/app/datasets"),

  getDataStatus: (datasetId?: string) => {
    const query = datasetId
      ? `?datasetId=${encodeURIComponent(datasetId)}`
      : "";
    return api.get<AppDataStatusResponse>(`/app/data-status${query}`);
  },
};
