type BatchJob = {
  id: string;
  state: string;
  worker_id: string | null;
  error: string | null;
  created_at: string;
  manifest: {
    batch_id?: string;
    task_id?: string;
    batch_task_count?: number;
    attempt_number?: number;
    summary?: { scenario_name: string };
  };
  execution_progress?: {
    percent: number;
    stage: string;
    message: string;
    observed_at: string;
  } | null;
};

const failedStates = new Set(["FAILED", "BLOCKED", "CANCELLED", "LOST"]);

function latestTasks(jobs: BatchJob[]): BatchJob[] {
  const byTask = new Map<string, BatchJob>();
  for (const job of jobs) {
    const task = job.manifest.task_id;
    if (!task) continue;
    const previous = byTask.get(task);
    if (
      !previous ||
      (job.manifest.attempt_number ?? 1) >
        (previous.manifest.attempt_number ?? 1) ||
      ((job.manifest.attempt_number ?? 1) ===
        (previous.manifest.attempt_number ?? 1) &&
        job.created_at > previous.created_at)
    ) {
      byTask.set(task, job);
    }
  }
  return [...byTask.values()].sort((a, b) =>
    (a.manifest.task_id ?? "").localeCompare(b.manifest.task_id ?? ""),
  );
}

export default function BatchProgress({ jobs }: { jobs: BatchJob[] }) {
  const groups = new Map<string, BatchJob[]>();
  for (const job of jobs) {
    if (!job.manifest.batch_id) continue;
    const group = groups.get(job.manifest.batch_id) ?? [];
    group.push(job);
    groups.set(job.manifest.batch_id, group);
  }
  if (!groups.size) return null;
  return (
    <section className="panel">
      <h2>分散バッチの進捗</h2>
      <p className="subtle">
        割合は宣言したタスク数に対する、成果物を回収・検証できた件数です。
        実行中の求解率や研究採用率ではありません。再試行は同じタスクとして数えます。
      </p>
      {[...groups.entries()].map(([batchId, rows]) => {
        const tasks = latestTasks(rows);
        const total = rows[0].manifest.batch_task_count ?? tasks.length;
        const verified = tasks.filter(
          (job) => job.state === "COMPLETED",
        ).length;
        const errors = tasks.filter((job) =>
          failedStates.has(job.state),
        ).length;
        const percent = total > 0 ? Math.round((verified * 100) / total) : 0;
        return (
          <details key={batchId} className="campaign-progress">
            <summary>
              {batchId} · {percent}% · 回収確認 {verified}/{total} · 要確認{" "}
              {errors}
            </summary>
            <progress
              value={verified}
              max={total}
              aria-label={`${batchId}の成果物回収進捗`}
            />
            <p className="subtle">
              登録済み {tasks.length}/{total} · 計算中{" "}
              {
                tasks.filter((job) =>
                  ["STAGING", "RUNNING", "COLLECTING"].includes(job.state),
                ).length
              }{" "}
              · 状態不明 {tasks.filter((job) => job.state === "LOST").length}
            </p>
            <div className="detail-table">
              <table>
                <thead>
                  <tr>
                    <th>タスク</th>
                    <th>シナリオ</th>
                    <th>状態</th>
                    <th>配布先</th>
                    <th>子機の工程</th>
                    <th>原因</th>
                  </tr>
                </thead>
                <tbody>
                  {tasks.map((job) => (
                    <tr key={job.id}>
                      <td>
                        {job.manifest.task_id}
                        <br />
                        <small>
                          試行 {job.manifest.attempt_number ?? 1} ·{" "}
                          {job.id.slice(0, 8)}
                        </small>
                      </td>
                      <td>{job.manifest.summary?.scenario_name ?? "—"}</td>
                      <td>{job.state}</td>
                      <td>{job.worker_id ?? "未割当"}</td>
                      <td>
                        {job.execution_progress
                          ? `${job.execution_progress.percent}% · ${job.execution_progress.stage || "工程未記録"}${job.state === "LOST" ? "（最終確認値）" : ""}`
                          : "報告なし"}
                      </td>
                      <td>{job.error ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        );
      })}
    </section>
  );
}
