import { create } from "zustand";

export type BootStepStatus = "pending" | "running" | "success" | "error";
export type BootStatus = "idle" | "running" | "ready" | "error";

export interface BootStep {
  id: string;
  label: string;
  weight: number;
  status: BootStepStatus;
  progress: number;
  detailMessage?: string;
  currentCount?: number;
  totalCount?: number;
  startedAt?: string;
  endedAt?: string;
}

interface BootState {
  scenarioId: string | null;
  status: BootStatus;
  progress: number;
  steps: BootStep[];
  errorMessage: string | null;
  start: (scenarioId: string, steps: Array<Pick<BootStep, "id" | "label" | "weight">>) => void;
  updateStep: (
    stepId: string,
    patch: Partial<Omit<BootStep, "id" | "label" | "weight">>,
  ) => void;
  complete: () => void;
  fail: (message: string) => void;
  reset: () => void;
}

function computeWeightedProgress(steps: BootStep[]): number {
  const totalWeight = steps.reduce((sum, step) => sum + step.weight, 0);
  if (totalWeight <= 0) {
    return 0;
  }
  const completed = steps.reduce(
    (sum, step) => sum + step.weight * Math.max(0, Math.min(100, step.progress)) / 100,
    0,
  );
  return Math.round((completed / totalWeight) * 100);
}

export const useBootStore = create<BootState>((set) => ({
  scenarioId: null,
  status: "idle",
  progress: 0,
  steps: [],
  errorMessage: null,
  start: (scenarioId, steps) =>
    set({
      scenarioId,
      status: "running",
      progress: 0,
      errorMessage: null,
      steps: steps.map((step) => ({
        ...step,
        status: "pending",
        progress: 0,
      })),
    }),
  updateStep: (stepId, patch) =>
    set((state) => {
      const steps = state.steps.map((step) => {
        if (step.id !== stepId) {
          return step;
        }
        const next = { ...step, ...patch };
        if (next.status === "running" && !next.startedAt) {
          next.startedAt = new Date().toISOString();
        }
        if ((next.status === "success" || next.status === "error") && !next.endedAt) {
          next.endedAt = new Date().toISOString();
        }
        if (next.status === "success" && next.progress < 100) {
          next.progress = 100;
        }
        return next;
      });
      return {
        steps,
        progress: computeWeightedProgress(steps),
      };
    }),
  complete: () =>
    set((state) => {
      const steps = state.steps.map((step) =>
        step.status === "success"
          ? step
          : {
              ...step,
              status: "success" as const,
              progress: 100,
              endedAt: step.endedAt ?? new Date().toISOString(),
            },
      );
      return {
        status: "ready",
        steps,
        progress: 100,
      };
    }),
  fail: (message) =>
    set((state) => ({
      status: "error",
      errorMessage: message,
      progress: computeWeightedProgress(state.steps),
    })),
  reset: () =>
    set({
      scenarioId: null,
      status: "idle",
      progress: 0,
      steps: [],
      errorMessage: null,
    }),
}));
