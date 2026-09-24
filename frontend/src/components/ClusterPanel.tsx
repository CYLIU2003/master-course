import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post } from "../api";
import { ErrorBox } from "./common";

import WorkerNodes, { type ClusterWorkers } from "./WorkerNodes";
import BatchProgress from "./BatchProgress";
export type { ClusterWorkers } from "./WorkerNodes";
type ClusterJob = {
  id: string;
  state: string;
  worker_id: string | null;
  error: string | null;
  execution_progress?: {
    percent: number;
    stage: string;
    message: string;
    observed_at: string;
    meaning: "pipeline_checkpoint_not_solver_gap";
  } | null;
  manifest: {
    kind: string;
    worker_id: string | null;
    retry_of: string | null;
    logical_job_id?: string;
    attempt_number?: number;
    execution_profile?: string;
    batch_id?: string;
    task_id?: string;
    batch_task_count?: number;
    summary?: {
      scenario_name: string;
      scenario_id?: string | null;
      planning_days: number;
      horizon_hours: number;
      service_dates: string[];
      expected_rolling_windows: number;
      research_status: string;
    };
  };
  result: {
    archive_sha256?: string;
    cluster_admission?: string;
    result?: {
      message?: string;
      metadata?: {
        solver_usage?: {
          counts_complete: boolean;
          environment_starts: number;
          optimize_calls: number;
        };
      };
    };
  } | null;
  created_at: string;
};

const monitorPortKey = "ev-cluster-monitor-port";

function isValidMonitorPort(value: string): boolean {
  const port = Number(value);
  return !value || (Number.isInteger(port) && port >= 1 && port <= 65535);
}

export default function ClusterPanel({ scenarioId }: { scenarioId?: string }) {
  const client = useQueryClient();
  const [monitorPort, setMonitorPort] = useState(() => {
    const saved = sessionStorage.getItem(monitorPortKey);
    return saved && isValidMonitorPort(saved) ? saved : window.location.port;
  });
  const validPort = isValidMonitorPort(monitorPort);
  const monitorOrigin =
    validPort && monitorPort && monitorPort !== window.location.port
      ? `${window.location.protocol}//${window.location.hostname}:${monitorPort}`
      : "";
  const remoteMonitor = !!monitorOrigin;
  const workersKey = remoteMonitor
    ? ["cluster-workers", monitorOrigin]
    : ["cluster-workers"];
  const jobsKey = remoteMonitor ? ["cluster-jobs", monitorOrigin] : ["cluster-jobs"];
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, []);
  const [selected, setSelected] = useState("");
  const [jobScope, setJobScope] = useState<"scenario" | "all">(
    scenarioId && !remoteMonitor ? "scenario" : "all",
  );
  const [probe, setProbe] = useState<unknown>(null);
  const workers = useQuery({
    queryKey: workersKey,
    queryFn: () =>
      api<ClusterWorkers>("/cluster/workers", { cache: "no-store" }, monitorOrigin),
    enabled: validPort,
    refetchInterval: 4000,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  const jobs = useQuery({
    queryKey: jobsKey,
    queryFn: () =>
      api<ClusterJob[]>("/cluster/jobs", { cache: "no-store" }, monitorOrigin),
    enabled: validPort,
    refetchInterval: 3000,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  const importWorkers = useMutation({
    mutationFn: async (file: File) =>
      post("/cluster/workers/import", JSON.parse(await file.text())),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: workersKey });
    },
  });
  const detail = useQuery({
    queryKey: ["cluster-job", monitorOrigin, selected],
    queryFn: () =>
      api<unknown>(`/cluster/jobs/${encodeURIComponent(selected)}`, {
        cache: "no-store",
      }, monitorOrigin),
    enabled: !!selected && validPort,
    refetchInterval: 3000,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  const action = useMutation({
    mutationFn: async ({
      path,
      isProbe,
    }: {
      path: string;
      isProbe?: boolean;
    }) => {
      const result = await post<unknown>(path, {});
      if (isProbe) setProbe(result);
    },
    onSuccess: () => {
      void client.invalidateQueries({
        predicate: (query) => String(query.queryKey[0]).startsWith("cluster-"),
      });
    },
  });
  const visibleJobs =
    scenarioId && jobScope === "scenario"
      ? (jobs.data ?? []).filter(
          (job) => job.manifest.summary?.scenario_id === scenarioId,
        )
      : (jobs.data ?? []);
  const visibleSelected = visibleJobs.some((job) => job.id === selected);
  const refreshStopped = [workers, jobs].some(
    (query) =>
      query.isError ||
      (query.dataUpdatedAt > 0 && now - query.dataUpdatedAt > 15000),
  );
  return (
    <>
      {jobScope === "all" && <BatchProgress jobs={jobs.data ?? []} />}
      <section className="panel">
        <h2>分散計算</h2>
        {(window.location.protocol === "http:" ||
          window.location.protocol === "https:") && (
          <label>
            監視先ポート（このPC）
            <input
              type="number"
              min={1}
              max={65535}
              value={monitorPort}
              onChange={(event) => {
                const value = event.target.value;
                setMonitorPort(value);
                setSelected("");
                setProbe(null);
                if (value !== window.location.port) setJobScope("all");
                if (isValidMonitorPort(value) && value !== window.location.port)
                  sessionStorage.setItem(monitorPortKey, value);
                else sessionStorage.removeItem(monitorPortKey);
              }}
            />
          </label>
        )}
        {!validPort && <p className="warning">1〜65535のポートを入力してください。</p>}
        {remoteMonitor && (
          <p className="notice">
            別の監視先は閲覧専用です。操作は{" "}
            <a href={`${monitorOrigin}/#cluster`} target="_blank" rel="noreferrer">
              その監視画面
            </a>
            で行ってください。
          </p>
        )}
        {refreshStopped && (
          <p className="warning">
            画面の状態更新が止まっています。これは従機の停止を意味しません。再接続すると保存済みの実行状態を確認できます。
          </p>
        )}
        <p>
          「実行」画面で入力を準備し、配布先を選んで登録します。独立したケースを各PCへ割り当てます。
        </p>
        <p className="subtle">
          計算完了と研究上の採用判定は別です。結果は元シナリオへ上書きせず、ジョブごとの成果物として保存します。
        </p>
        <p>
          Gurobi実行枠: 通常実行・分散の合計{" "}
          {workers.data?.reserved_gurobi_slots ?? "—"}、 WLS解放待ち{" "}
          {workers.data?.cooling_gurobi_slots ?? 0}、 外部計算予約{" "}
          {workers.data?.external_gurobi_slots ?? 0} / 合計{" "}
          {workers.data?.global_gurobi_slots ?? "—"}
        </p>
        <p className="subtle">
          各PCの空きメモリ・CPU負荷・同条件の実測時間を使って割り当てます。通信が切れた実行の枠は、終了確認まで保持します。
        </p>
        <ErrorBox
          error={
            workers.error ??
            jobs.error ??
            action.error ??
            detail.error ??
            importWorkers.error
          }
        />
        <label>
          端末設定を取り込む（親機内で保存）
          <input
            type="file"
            accept="application/json,.json"
            disabled={importWorkers.isPending || remoteMonitor}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) importWorkers.mutate(file);
              event.target.value = "";
            }}
          />
        </label>
        <h3>全シナリオ共通の計算端末</h3>
        <WorkerNodes
          data={workers.data}
          pending={action.isPending || remoteMonitor}
          onAction={(path) => action.mutate({ path })}
        />
        {probe != null && (
          <details open>
            <summary>接続確認結果（ライセンスの有効性は未検証）</summary>
            <pre>{JSON.stringify(probe, null, 2)}</pre>
          </details>
        )}
      </section>
      <section className="panel">
        <h2>キューと実行履歴</h2>
        <p className="subtle">
          接続先: {remoteMonitor ? new URL(monitorOrigin).host : window.location.host || "ローカル"} · ジョブ最終更新:{" "}
          {jobs.dataUpdatedAt
            ? new Date(jobs.dataUpdatedAt).toLocaleTimeString("ja-JP")
            : "取得中"}
        </p>
        {scenarioId && (
          <label>
            表示するジョブ
            <select
              value={jobScope}
              onChange={(event) => {
                setJobScope(event.target.value as "scenario" | "all");
                setSelected("");
              }}
            >
              <option value="scenario">選択中のシナリオ</option>
              <option value="all">全シナリオ・診断</option>
            </select>
          </label>
        )}
        <div className="run-summary">
          {[
            ["待機", ["QUEUED"]],
            ["実行・回収中", ["STAGING", "RUNNING", "COLLECTING"]],
            ["要確認", ["LOST", "FAILED", "BLOCKED"]],
            ["計算完了", ["COMPLETED"]],
          ].map(([label, states]) => (
            <div key={String(label)}>
              <small>{label}</small>
              <strong>
                {visibleJobs.filter((job) => states.includes(job.state)).length}
              </strong>
            </div>
          ))}
        </div>
        <p className="subtle">
          QUEUED は利用可能な枠待ち、LOST は状態不明です。LOST
          は枠を保持します。「結果を照合」で子機の終了を確認してください。
        </p>
        <p className="subtle">
          ジョブの割合は子機が保存した処理工程の到達点です。求解器内部の探索率、残り時間、最適性gapではありません。
          通信断では最後に確認できた値として表示します。
        </p>
        {jobs.isSuccess && !visibleJobs.length && (
          <p>
            {scenarioId && jobScope === "scenario"
              ? "このシナリオの登録タスクはありません。"
              : "登録されたタスクはありません。"}
          </p>
        )}
        <div className="detail-table">
          <table>
            <thead>
              <tr>
                <th>タスク</th>
                <th>配布先</th>
                <th>対象期間・運用</th>
                <th>状態</th>
                <th>工程進捗</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {[...visibleJobs].reverse().map((job) => (
                <tr key={job.id}>
                  <td>
                    <button onClick={() => setSelected(job.id)}>
                      {job.id.slice(0, 8)}
                    </button>
                    <br />
                    {job.manifest.kind}
                    <br />
                    <small>
                      試行 {job.manifest.attempt_number ?? 1} ·{" "}
                      {job.manifest.execution_profile === "alns_no_gurobi_v1"
                        ? "Gurobiなし"
                        : "既存手法"}
                    </small>
                    <br />
                    <small>{job.created_at}</small>
                  </td>
                  <td>
                    {job.worker_id ?? job.manifest.worker_id ?? "自動割当"}
                  </td>
                  <td>
                    {job.manifest.summary ? (
                      <>
                        <strong>
                          {job.manifest.summary.scenario_name ||
                            "最適化シナリオ"}
                        </strong>
                        <br />
                        {job.manifest.summary.service_dates[0] ??
                          "日付未設定"}{" "}
                        ～ {job.manifest.summary.service_dates.at(-1) ?? "—"}
                        <br />
                        {job.manifest.summary.planning_days}日間 /{" "}
                        {job.manifest.summary.horizon_hours}時間
                        <br />
                        ローリング予定{" "}
                        {job.manifest.summary.expected_rolling_windows}回<br />
                        <small>
                          {job.manifest.summary.research_status ===
                          "MULTIDAY_RESEARCH_BLOCKED"
                            ? "複数日・研究採用は未対応"
                            : "研究採用は別途判定"}
                        </small>
                      </>
                    ) : (
                      job.manifest.kind === "optimization"
                        ? "シナリオ情報なし"
                        : "接続・成果物転送の診断"
                    )}
                  </td>
                  <td>
                    {job.state}
                    {job.state === "COMPLETED" && (
                      <small>（研究採用を意味しません）</small>
                    )}
                    {job.result?.cluster_admission ===
                      "FENCED_BEFORE_LAUNCH" && (
                      <small>（子機で未開始と確認済み）</small>
                    )}
                    {job.result?.result?.message && (
                      <p
                        className={
                          job.result.result.message.includes(
                            "terminal_soc_balance_failed",
                          )
                            ? "warning"
                            : "subtle"
                        }
                      >
                        {job.result.result.message.includes(
                          "terminal_soc_balance_failed",
                        )
                          ? "期末SOCの条件未達（診断結果）"
                          : job.result.result.message}
                      </p>
                    )}
                    {job.result?.result?.metadata?.solver_usage && (
                      <small>
                        {job.result.result.metadata.solver_usage.counts_complete
                          ? `Gurobi Env ${job.result.result.metadata.solver_usage.environment_starts}回 / 求解 ${job.result.result.metadata.solver_usage.optimize_calls}回`
                          : "Gurobi利用回数の記録は不完全です"}
                      </small>
                    )}
                    {job.error && <p className="error">{job.error}</p>}
                  </td>
                  <td>
                    {job.execution_progress ? (
                      <>
                        <strong>{job.execution_progress.percent}%</strong>
                        <progress
                          value={job.execution_progress.percent}
                          max={100}
                          aria-label={`${job.id}の処理工程進捗`}
                        />
                        <small>
                          {job.execution_progress.stage || "工程未記録"}
                        </small>
                        {job.execution_progress.message && (
                          <small>{job.execution_progress.message}</small>
                        )}
                        <small>
                          {job.state === "LOST"
                            ? "最後に確認した値 · "
                            : "確認日時 · "}
                          {job.execution_progress.observed_at}
                        </small>
                      </>
                    ) : (
                      <small>
                        {job.state === "QUEUED"
                          ? "0% · 実行待ち"
                          : "子機から工程報告なし"}
                      </small>
                    )}
                  </td>
                  <td>
                    {["QUEUED", "RUNNING", "LOST"].includes(job.state) && (
                      <button
                        disabled={action.isPending || remoteMonitor}
                        onClick={() =>
                          action.mutate({
                            path: `/cluster/jobs/${job.id}/cancel`,
                          })
                        }
                      >
                        {job.state === "QUEUED"
                          ? "登録取消"
                          : "このタスクを停止"}
                      </button>
                    )}
                    {job.state === "LOST" && (
                      <button
                        disabled={action.isPending || remoteMonitor}
                        onClick={() =>
                          action.mutate({
                            path: `/cluster/jobs/${job.id}/reconcile`,
                          })
                        }
                      >
                        結果を照合
                      </button>
                    )}
                    {["FAILED", "BLOCKED", "CANCELLED"].includes(job.state) && (
                      <button
                        disabled={action.isPending || remoteMonitor}
                        onClick={() =>
                          action.mutate({
                            path: `/cluster/jobs/${job.id}/retry`,
                          })
                        }
                      >
                        新しいIDで再試行
                      </button>
                    )}
                    {!!job.result?.archive_sha256 && (
                      <a
                        href={`${monitorOrigin}/api/cluster/jobs/${job.id}/artifacts`}
                        download
                      >
                        成果物ZIP
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selected && visibleSelected && (
          <details open>
            <summary>ジョブ詳細・状態遷移・成果物ハッシュ</summary>
            <pre>{JSON.stringify(detail.data, null, 2)}</pre>
          </details>
        )}
      </section>
    </>
  );
}
