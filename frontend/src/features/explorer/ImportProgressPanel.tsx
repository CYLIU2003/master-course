import { useMemo } from "react";
import { useImportJobStore } from "@/stores/import-job-store";

interface Props {
  jobId?: string | null;
  className?: string;
}

export function ImportProgressPanel({ jobId, className }: Props) {
  const activeJobId = useImportJobStore((state) => state.activeJobId);
  const jobs = useImportJobStore((state) => state.jobs);
  const targetJob = jobs[jobId ?? activeJobId ?? ""];

  const stages = useMemo(() => targetJob?.stages ?? [], [targetJob]);

  if (!targetJob) {
    return null;
  }

  return (
    <div className={`rounded-xl border border-border bg-surface-raised p-4 ${className ?? ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Import Job
          </p>
          <p className="text-sm font-semibold text-slate-800">{targetJob.label}</p>
          <p className="text-xs text-slate-500">
            {targetJob.currentStage || "待機中"} / {targetJob.status}
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-semibold text-slate-800">{targetJob.overallProgress}%</div>
          <div className="text-xs text-slate-500">{targetJob.source.toUpperCase()}</div>
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-[linear-gradient(90deg,#0f766e,#14b8a6,#99f6e4)] transition-[width] duration-300"
          style={{ width: `${targetJob.overallProgress}%` }}
        />
      </div>
      <div className="mt-3 space-y-2">
        {stages.map((stage) => (
          <div key={stage.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="font-medium text-slate-700">{stage.label}</span>
              <span className="font-mono text-slate-500">
                {stage.currentCount != null && stage.totalCount != null
                  ? `${stage.currentCount}/${stage.totalCount}`
                  : `${stage.progress}%`}
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full rounded-full transition-[width] duration-300 ${
                  stage.status === "error"
                    ? "bg-rose-500"
                    : stage.status === "success"
                      ? "bg-emerald-500"
                      : "bg-sky-500"
                }`}
                style={{ width: `${stage.progress}%` }}
              />
            </div>
            {stage.message && (
              <p className="mt-1 text-[11px] text-slate-500">{stage.message}</p>
            )}
          </div>
        ))}
      </div>
      {targetJob.errorMessage && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {targetJob.errorMessage}
        </div>
      )}
    </div>
  );
}
