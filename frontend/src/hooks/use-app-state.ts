import { useQuery } from "@tanstack/react-query";
import { fetchAppState } from "@/api/app";

export type AppReadinessState =
  | "no-seed"
  | "seed-only"
  | "built-ready"
  | "integrity-error"
  | "incomplete";

export interface AppStateResult {
  readiness: AppReadinessState;
  seedReady: boolean;
  builtReady: boolean;
  datasetId: string | null;
  datasetVersion: string | null;
  missingArtifacts: string[];
  integrityError: string | null;
  isLoading: boolean;
}

function deriveReadiness(data: {
  seed_ready: boolean;
  built_ready: boolean;
  missing_artifacts: string[];
  integrity_error: string | null;
}): AppReadinessState {
  if (!data.seed_ready) return "no-seed";
  if (data.integrity_error) return "integrity-error";
  if ((data.missing_artifacts ?? []).length > 0) return "incomplete";
  if (!data.built_ready) return "seed-only";
  return "built-ready";
}

export function useAppState(): AppStateResult {
  const { data, isLoading } = useQuery({
    queryKey: ["app-state"],
    queryFn: fetchAppState,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  if (isLoading || !data) {
    return {
      readiness: "seed-only",
      seedReady: false,
      builtReady: false,
      datasetId: null,
      datasetVersion: null,
      missingArtifacts: [],
      integrityError: null,
      isLoading: true,
    };
  }

  return {
    readiness: deriveReadiness({
      seed_ready: Boolean(data.seed_ready),
      built_ready: Boolean(data.built_ready),
      missing_artifacts: [...(data.missing_artifacts ?? [])],
      integrity_error: (data.integrity_error ?? null) as string | null,
    }),
    seedReady: Boolean(data.seed_ready),
    builtReady: Boolean(data.built_ready),
    datasetId: data.dataset_id ?? null,
    datasetVersion: data.dataset_version ?? null,
    missingArtifacts: [...(data.missing_artifacts ?? [])],
    integrityError: (data.integrity_error ?? null) as string | null,
    isLoading: false,
  };
}
