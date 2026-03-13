import { api } from "./client";
import type {
  AppDataStatusResponse,
  AppStateResponse,
  ResearchDatasetsResponse,
} from "@/types";

export const appApi = {
  listDatasets: () => api.get<ResearchDatasetsResponse>("/app/datasets"),

  getDataStatus: (datasetId?: string) => {
    const query = datasetId
      ? `?datasetId=${encodeURIComponent(datasetId)}`
      : "";
    return api.get<AppDataStatusResponse>(`/app/data-status${query}`);
  },

  getAppState: (datasetId?: string) => {
    const query = datasetId
      ? `?datasetId=${encodeURIComponent(datasetId)}`
      : "";
    return api.get<AppStateResponse>(`/app-state${query}`);
  },
};

export const fetchAppState = () => appApi.getAppState();
