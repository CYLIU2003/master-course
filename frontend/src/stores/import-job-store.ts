import { create } from "zustand";

export type ImportJobStatus = "idle" | "running" | "success" | "error";
export type ImportStageStatus = "pending" | "running" | "success" | "error";

export interface ImportJobStage {
  id: string;
  label: string;
  weight: number;
  progress: number;
  status: ImportStageStatus;
  currentCount?: number;
  totalCount?: number;
  message?: string;
}

export interface ImportJobLog {
  ts: string;
  level: "info" | "warn" | "error";
  message: string;
}

export interface ImportJob {
  jobId: string;
  source: "odpt" | "gtfs" | "system";
  label: string;
  status: ImportJobStatus;
  overallProgress: number;
  currentStage: string;
  stages: ImportJobStage[];
  logs: ImportJobLog[];
  errorMessage?: string;
  startedAt: string;
  endedAt?: string;
}

interface ImportJobState {
  activeJobId: string | null;
  jobs: Record<string, ImportJob>;
  startJob: (job: {
    jobId: string;
    source: ImportJob["source"];
    label: string;
    stages: Array<Pick<ImportJobStage, "id" | "label" | "weight">>;
  }) => void;
  updateStage: (
    jobId: string,
    stageId: string,
    patch: Partial<Omit<ImportJobStage, "id" | "label" | "weight">>,
  ) => void;
  appendLog: (jobId: string, log: Omit<ImportJobLog, "ts"> & { ts?: string }) => void;
  completeJob: (jobId: string, message?: string) => void;
  failJob: (jobId: string, message: string) => void;
  dismissJob: (jobId: string) => void;
}

function computeProgress(stages: ImportJobStage[]): number {
  const totalWeight = stages.reduce((sum, stage) => sum + stage.weight, 0);
  if (totalWeight <= 0) {
    return 0;
  }
  const weighted = stages.reduce(
    (sum, stage) => sum + (Math.max(0, Math.min(100, stage.progress)) / 100) * stage.weight,
    0,
  );
  return Math.round((weighted / totalWeight) * 100);
}

function currentStageLabel(stages: ImportJobStage[]): string {
  return stages.find((stage) => stage.status === "running")?.label
    ?? stages.find((stage) => stage.status === "error")?.label
    ?? stages.find((stage) => stage.status !== "success")?.label
    ?? stages.at(-1)?.label
    ?? "";
}

export const useImportJobStore = create<ImportJobState>((set) => ({
  activeJobId: null,
  jobs: {},
  startJob: ({ jobId, source, label, stages }) =>
    set((state) => ({
      activeJobId: jobId,
      jobs: {
        ...state.jobs,
        [jobId]: {
          jobId,
          source,
          label,
          status: "running",
          overallProgress: 0,
          currentStage: stages[0]?.label ?? "",
          stages: stages.map((stage, index) => ({
            ...stage,
            progress: index === 0 ? 5 : 0,
            status: index === 0 ? "running" : "pending",
          })),
          logs: [],
          startedAt: new Date().toISOString(),
        },
      },
    })),
  updateStage: (jobId, stageId, patch) =>
    set((state) => {
      const current = state.jobs[jobId];
      if (!current) {
        return state;
      }
      const stages = current.stages.map((stage) => {
        if (stage.id !== stageId) {
          return stage;
        }
        const next = { ...stage, ...patch };
        if (next.status === "success" && next.progress < 100) {
          next.progress = 100;
        }
        return next;
      });
      return {
        jobs: {
          ...state.jobs,
          [jobId]: {
            ...current,
            stages,
            overallProgress: computeProgress(stages),
            currentStage: currentStageLabel(stages),
          },
        },
      };
    }),
  appendLog: (jobId, log) =>
    set((state) => {
      const current = state.jobs[jobId];
      if (!current) {
        return state;
      }
      return {
        jobs: {
          ...state.jobs,
          [jobId]: {
            ...current,
            logs: [
              {
                ts: log.ts ?? new Date().toISOString(),
                level: log.level,
                message: log.message,
              },
              ...current.logs,
            ].slice(0, 40),
          },
        },
      };
    }),
  completeJob: (jobId, message) =>
    set((state) => {
      const current = state.jobs[jobId];
      if (!current) {
        return state;
      }
      const stages = current.stages.map((stage) => ({
        ...stage,
        status: "success" as const,
        progress: 100,
      }));
      const logs: ImportJobLog[] = message
        ? [{ ts: new Date().toISOString(), level: "info" as const, message }, ...current.logs].slice(0, 40)
        : current.logs;
      const nextJob: ImportJob = {
        ...current,
        status: "success",
        stages,
        overallProgress: 100,
        currentStage: stages.at(-1)?.label ?? current.currentStage,
        endedAt: new Date().toISOString(),
        logs,
      };
      return {
        activeJobId: state.activeJobId,
        jobs: {
          ...state.jobs,
          [jobId]: nextJob,
        },
      };
    }),
  failJob: (jobId, message) =>
    set((state) => {
      const current = state.jobs[jobId];
      if (!current) {
        return state;
      }
      const logs: ImportJobLog[] = [
        { ts: new Date().toISOString(), level: "error" as const, message },
        ...current.logs,
      ].slice(0, 40);
      const nextJob: ImportJob = {
        ...current,
        status: "error",
        errorMessage: message,
        endedAt: new Date().toISOString(),
        logs,
      };
      return {
        activeJobId: state.activeJobId,
        jobs: {
          ...state.jobs,
          [jobId]: nextJob,
        },
      };
    }),
  dismissJob: (jobId) =>
    set((state) => {
      const nextJobs = { ...state.jobs };
      delete nextJobs[jobId];
      return {
        activeJobId: state.activeJobId === jobId ? null : state.activeJobId,
        jobs: nextJobs,
      };
    }),
}));
