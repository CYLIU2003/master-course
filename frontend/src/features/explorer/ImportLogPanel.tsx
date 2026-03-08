import { useImportJobStore } from "@/stores/import-job-store";

interface Props {
  jobId?: string | null;
}

export function ImportLogPanel({ jobId }: Props) {
  const activeJobId = useImportJobStore((state) => state.activeJobId);
  const jobs = useImportJobStore((state) => state.jobs);
  const targetJob = jobs[jobId ?? activeJobId ?? ""];

  if (!targetJob || targetJob.logs.length === 0) {
    return null;
  }

  return (
    <div className="rounded-xl border border-border bg-surface-raised p-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-semibold text-slate-800">Import Logs</p>
        <span className="text-xs text-slate-500">{targetJob.logs.length} entries</span>
      </div>
      <div className="max-h-56 space-y-2 overflow-auto">
        {targetJob.logs.map((log) => (
          <div key={`${log.ts}-${log.message}`} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span
                className={`font-semibold uppercase tracking-wide ${
                  log.level === "error"
                    ? "text-rose-600"
                    : log.level === "warn"
                      ? "text-amber-600"
                      : "text-slate-500"
                }`}
              >
                {log.level}
              </span>
              <span className="font-mono text-slate-400">{log.ts}</span>
            </div>
            <p className="mt-1 text-slate-700">{log.message}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
