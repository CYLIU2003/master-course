import { useAppState, type AppReadinessState } from "./use-app-state";

export interface ScenarioRunReadiness {
  canRun: boolean;
  reason: string | null;
  readiness: AppReadinessState;
}

const READINESS_MESSAGES: Record<AppReadinessState, string | null> = {
  "built-ready": null,
  "no-seed": "Seed data failed to load. Check data/seed/tokyu/.",
  "seed-only": "Built dataset not found. Run data-prep first.",
  "integrity-error":
    "Built dataset integrity check failed. Regenerate with data-prep.",
  incomplete: "Some built artifacts are missing. Regenerate with data-prep.",
};

export function useScenarioRunReadiness(): ScenarioRunReadiness {
  const { readiness } = useAppState();
  const canRun = readiness === "built-ready";
  return {
    canRun,
    reason: READINESS_MESSAGES[readiness],
    readiness,
  };
}
