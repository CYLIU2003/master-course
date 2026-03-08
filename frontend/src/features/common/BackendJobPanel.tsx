import type { Job } from "@/types";

interface Props {
  job?: Job | null;
  className?: string;
}

export function BackendJobPanel({ job, className }: Props) {
  if (!job) {
    return null;
  }

  const stage = typeof job.metadata?.stage === "string" ? job.metadata.stage : null;

  return (
    <div className={`rounded-lg border border-border bg-surface-raised p-4 ${className ?? ""}`}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Backend job
          </div>
          <div className="text-sm font-semibold text-slate-800">
            {stage ? `${stage} / ${job.status}` : job.status}
          </div>
          <div className="mt-1 text-xs text-slate-500">{job.message || job.job_id}</div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-semibold text-slate-800">{job.progress}%</div>
          <div className="text-[11px] text-slate-500">{job.job_id}</div>
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full transition-[width] duration-300 ${
            job.status === "failed"
              ? "bg-rose-500"
              : job.status === "completed"
                ? "bg-emerald-500"
                : "bg-sky-500"
          }`}
          style={{ width: `${job.progress}%` }}
        />
      </div>
      {job.error && (
        <div className="mt-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {job.error}
        </div>
      )}
    </div>
  );
}
