import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Check, Play } from "lucide-react";
import {
  api,
  post,
  strings,
  type Job,
  type Overview,
  type Prepared,
  type Row,
} from "../api";
import { ErrorBox } from "./common";
import { FieldGrid } from "./Fields";
import type { Configuration } from "./SettingsPanel";
import type { ClusterWorkers } from "./ClusterPanel";

function workerRoleAllowsProfile(worker: ClusterWorkers["workers"][number], noGurobi: boolean): boolean {
  return noGurobi
    ? worker.job_role === "both" || worker.job_role === "alns_only"
    : worker.job_role === "both" || worker.job_role === "gurobi_only";
}

function workerAllowsProfile(worker: ClusterWorkers["workers"][number], noGurobi: boolean): boolean {
  const ready = noGurobi ? worker.can_run_no_gurobi : worker.can_run_optimization;
  return workerRoleAllowsProfile(worker, noGurobi) && ready === true;
}

export function executionControls(value: Row): Row {
  const names: Record<string, string> = {
    solverMode: "mode",
    executionProfile: "execution_profile",
    timeLimitSeconds: "time_limit_seconds",
    timeStepMin: "time_step_min",
    mipGap: "mip_gap",
    randomSeed: "random_seed",
    alnsIterations: "alns_iterations",
    noImprovementLimit: "no_improvement_limit",
    destroyFraction: "destroy_fraction",
    stage1Stage2CandidateLimit: "stage1_stage2_candidate_limit",
    stage1CompositionSearchRadius: "stage1_composition_search_radius",
    stage1BevFrontierEnabled: "stage1_bev_frontier_enabled",
    stage1BevFrontierMinCount: "stage1_bev_frontier_min_count",
    stage1BevFrontierMaxCount: "stage1_bev_frontier_max_count",
    stage1BevFrontierTargetTimeLimitSeconds:
      "stage1_bev_frontier_target_time_limit_seconds",
    integratedActualCostObjective: "integrated_actual_cost_objective",
    integratedEvUtilizationMode: "integrated_ev_utilization_mode",
    integratedActualCostUpperBoundJpy: "integrated_actual_cost_upper_bound_jpy",
    integratedActualCostUpperBoundDeltaRatio:
      "integrated_actual_cost_upper_bound_delta_ratio",
    co2EmissionsCapKg: "co2_emissions_cap_kg",
  };
  return Object.fromEntries(
    Object.entries(names)
      .filter(([key]) => value[key] !== undefined)
      .map(([key, target]) => [target, value[key]]),
  );
}
export default function RunPanel({
  id,
  data,
  revision,
  blocked,
}: {
  id: string;
  data: Overview;
  revision: number;
  blocked: boolean;
}) {
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: ["configuration", id],
    queryFn: () => api<Configuration>(`/desktop/scenarios/${id}/configuration`),
  });
  const [formal, setFormal] = useState(false);
  const [method, setMethod] = useState("optimize");
  const [destination, setDestination] = useState("standalone");
  const [minimumRamGb, setMinimumRamGb] = useState(16);
  const workers = useQuery({
    queryKey: ["cluster-workers"],
    queryFn: () => api<ClusterWorkers>("/cluster/workers"),
  });
  const [rolling, setRolling] = useState(true);
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [preparedRevision, setPreparedRevision] = useState("");
  const [jobId, setJobId] = useState(
    localStorage.getItem("ev-job-" + id) ?? "",
  );
  const [observed, setObserved] = useState<Row>({
    current_time: "12:00",
    actual_soc: {},
    actual_bess_soc_kwh: {},
    actual_location_node_id: {},
    delays: [],
    updated_pv_profile: [],
  });
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: !!jobId,
    queryFn: ({ signal }) =>
      api<Job>(`/jobs/${encodeURIComponent(jobId)}`, { signal }),
    refetchInterval: (query) =>
      query.state.data &&
      ["completed", "failed", "cancelled"].includes(query.state.data.status)
        ? false
        : 2000,
  });
  const preflight = useQuery({
    queryKey: ["preflight"],
    enabled: formal || destination !== "standalone",
    queryFn: () => api<Row>("/research/git-preflight"),
    staleTime: 0,
  });
  const capabilities = useQuery({
    queryKey: ["capabilities", id],
    queryFn: () => api<Row>(`/scenarios/${id}/optimization/capabilities`),
  });
  const running = job.data
    ? ["running", "pending"].includes(job.data.status)
    : !!jobId && job.isPending;
  useEffect(() => {
    setPrepared(null);
  }, [revision]);
  useEffect(() => {
    if (job.data?.status === "completed")
      void client.invalidateQueries({ queryKey: ["overview", id] });
  }, [job.data?.status, client, id]);
  const value = settings.data?.values ?? {};
  const noGurobi = value.executionProfile === "alns_no_gurobi_v1";
  const selectedWorker = workers.data?.workers.find((worker) => worker.id === destination);
  const selectedWorkerAllowed = destination === "auto" || destination === "standalone" ||
    (selectedWorker !== undefined && workerAllowsProfile(selectedWorker, noGurobi));
  useEffect(() => {
    if (noGurobi) {
      setFormal(false);
      setRolling(false);
      setMethod("optimize");
    }
  }, [noGurobi]);
  const planningDays = Number(
    prepared?.planningDays ?? value.planningDays ?? 1,
  );
  const depots = strings(value.selectedDepotIds);
  const routes = strings(value.selectedRouteIds);
  const prepare = useMutation({
    mutationFn: async () => {
      const current = await api<Configuration>(
        `/desktop/scenarios/${id}/configuration`,
      );
      const overview = await api<Overview>(`/desktop/scenarios/${id}`);
      const result = await post<Prepared>(
        `/scenarios/${id}/simulation/prepare`,
        {
          selected_depot_ids: strings(current.values.selectedDepotIds),
          selected_route_ids: strings(current.values.selectedRouteIds),
          service_date: current.values.serviceDate,
          service_dates: current.values.serviceDates,
          simulation_settings: overview.settings,
        },
      );
      const after = await api<Configuration>(
        `/desktop/scenarios/${id}/configuration`,
      );
      return { result, after };
    },
    onSuccess: ({ result, after }) => {
      setPrepared(result);
      setPreparedRevision(after.revision);
      client.setQueryData(["configuration", id], after);
      void client.invalidateQueries({ queryKey: ["overview", id] });
    },
  });
  const run = useMutation({
    mutationFn: async () => {
      const current = await api<Configuration>(
        `/desktop/scenarios/${id}/configuration`,
      );
      if (current.revision !== preparedRevision) {
        setPrepared(null);
        throw new Error(
          "入力条件が変更されています。もう一度「入力を準備」を実行してください。",
        );
      }
      if (method === "simulate")
        return post<{ job_id: string }>(`/scenarios/${id}/simulation/run`, {
          prepared_input_id: prepared?.preparedInputId,
          source: "duties",
        });
      if (method === "optimize" && destination !== "standalone") {
        const submission = {
          scenario_id: id,
          worker_id: destination === "auto" ? null : destination,
          minimum_ram_gb: minimumRamGb,
          request: {
            ...executionControls(current.values),
            research_run: formal,
            prepared_input_id: prepared?.preparedInputId,
            run_hourly_rolling: rolling,
            run_profile: rolling
              ? "day_ahead_and_hourly_rolling"
              : "day_ahead_exploratory",
            rebuild_dispatch: false,
            use_existing_duties: false,
          },
        };
        const storageKey = `ev-cluster-submission-${id}`;
        const signature = JSON.stringify(submission);
        let previous: { signature?: string; key?: string } = {};
        try {
          const cached: unknown = JSON.parse(localStorage.getItem(storageKey) ?? "{}");
          if (cached && typeof cached === "object" && "signature" in cached && "key" in cached &&
              typeof cached.signature === "string" && typeof cached.key === "string") previous = { signature: cached.signature, key: cached.key };
        } catch { /* Invalid local cache is not an accepted job. */ }
        const key = previous.signature === signature && previous.key ? previous.key : crypto.randomUUID();
        localStorage.setItem(storageKey, JSON.stringify({ signature, key }));
        return post<{ job_id: string }>("/cluster/jobs", { ...submission, idempotency_key: key });
      }
      return post<{ job_id: string }>(
        `/scenarios/${id}/${method === "reoptimize" ? "reoptimize" : "run-optimization"}`,
        {
          ...executionControls(current.values),
          research_run: formal,
          prepared_input_id: prepared?.preparedInputId,
          ...(method === "reoptimize"
            ? observed
            : {
                run_hourly_rolling: rolling,
                run_profile: rolling
                  ? "day_ahead_and_hourly_rolling"
                  : "day_ahead_exploratory",
              }),
        },
      );
    },
    onSuccess: (result) => {
      setJobId(result.job_id);
      localStorage.setItem("ev-job-" + id, result.job_id);
    },
  });
  const busy =
    (running && (destination === "standalone" || method !== "optimize")) ||
    prepare.isPending ||
    run.isPending;
  return (
    <>
      <section className="panel">
        <div className="section-title">
          <h2>保存された条件で実行する</h2>
          <span className="badge">
            {depots.length} 営業所 / {routes.length} 路線パターン
          </span>
        </div>
        <div className="run-summary">
          <div>
            <small>期間</small>
            <strong>
              {String(value.serviceDate ?? "未設定")} から{" "}
              {String(value.planningDays ?? 1)} 日
            </strong>
          </div>
          <div>
            <small>最適化手法</small>
            <strong>{String(value.solverMode ?? "未設定")}</strong>
          </div>
          <div>
            <small>計算時間上限</small>
            <strong>{String(value.timeLimitSeconds ?? "—")} 秒</strong>
          </div>
          <div>
            <small>目標 gap</small>
            <strong>
              {typeof value.mipGap === "number"
                ? `${value.mipGap * 100}%`
                : "未設定"}
            </strong>
          </div>
        </div>
        <p className="subtle">
          条件の変更は「運行・計算設定」、車両・設備の変更は各画面から保存します。
        </p>
        {blocked && (
          <p className="warning">
            未保存の変更があります。保存または破棄してから実行してください。
          </p>
        )}
        <ErrorBox error={settings.error} />
      </section>
      <section className="panel">
        <h2>入力の準備と計算</h2>
        {noGurobi && <p className="warning">Gurobi非依存ALNS：単日・BESSなしの診断専用です。正式研究・時間別rolling・再最適化には使えません。手法をALNSに設定し、保存してから入力を準備してください。</p>}
        <p className="subtle">
          入力準備では、このシナリオの派生データを更新します。実行中はアプリを開いたままにしてください。
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run.mutate();
          }}
        >
          <fieldset disabled={busy || blocked}>
            <div className="form-grid">
              <label>
                実行する処理
                <select
                  value={method}
                  onChange={(e) => setMethod(e.target.value)}
                >
                  <option value="optimize">最適化</option>
                  <option value="simulate">
                    シミュレーション（保存された仕業）
                  </option>
                  <option value="reoptimize" disabled={noGurobi}>観測状態から再最適化</option>
                </select>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={formal}
                  disabled={method === "simulate" || noGurobi}
                  onChange={(e) => setFormal(e.target.checked)}
                />
                正式実行（clean commit 必須）
              </label>
              {method === "optimize" && (
                <label>
                  計算の配布先
                  <select
                    value={destination}
                    onChange={(event) => setDestination(event.target.value)}
                  >
                    <option value="standalone">このPCで通常実行</option>
                    <option value="auto">
                      分散キューで自動割当（clean commit 必須）
                    </option>
                    {workers.data?.workers
                      .filter((worker) => worker.enabled)
                      .map((worker) => {
                        const roleAllows = workerRoleAllowsProfile(worker, noGurobi);
                        const ready = noGurobi ? worker.can_run_no_gurobi : worker.can_run_optimization;
                        return (
                          <option key={worker.id} value={worker.id}
                            disabled={!workerAllowsProfile(worker, noGurobi)}>
                            {worker.name}（{roleAllows ? (ready ? "計算可能" : "準備待ち") : "担当外"}）
                          </option>
                        );
                      })}
                  </select>
                </label>
              )}
              {method === "optimize" && (
                <label className="check">
                  <input
                    type="checkbox"
                    checked={rolling}
                    disabled={noGurobi}
                    onChange={(e) => setRolling(e.target.checked)}
                  />
                  時間ごとのローリング運用も実行する
                </label>
              )}
              {method === "optimize" && destination !== "standalone" && (
                <label>
                  必要な空きRAM（GB）
                  <input type="number" min="1" step="1" required
                    value={minimumRamGb}
                    onChange={(event) => setMinimumRamGb(Number(event.target.value))} />
                </label>
              )}
            </div>
            {method === "reoptimize" && (
              <details open>
                <summary>観測した時刻・残量・遅延</summary>
                <FieldGrid
                  fields={[
                    {
                      key: "current_time",
                      label: "現在時刻（HH:MM）",
                      required: true,
                    },
                    {
                      key: "actual_soc",
                      label: "車両IDと実測SOC",
                      kind: "json",
                    },
                    {
                      key: "actual_bess_soc_kwh",
                      label: "営業所IDとBESS実測残量（kWh）",
                      kind: "json",
                    },
                    {
                      key: "actual_location_node_id",
                      label: "車両IDと現在位置",
                      kind: "json",
                    },
                    { key: "delays", label: "便IDと遅延分数", kind: "json" },
                    {
                      key: "updated_pv_profile",
                      label: "更新したPV予報",
                      kind: "json",
                    },
                  ]}
                  value={observed}
                  onChange={(key, next) =>
                    setObserved({ ...observed, [key]: next })
                  }
                />
              </details>
            )}
            <div className="actions">
              <button
                type="button"
                className="primary"
                disabled={!settings.data || !depots.length}
                onClick={() => prepare.mutate()}
              >
                <Check size={16} />
                {prepare.isPending ? "準備中…" : "1. 入力を準備"}
              </button>
              <button
                className="primary"
                disabled={
                  !prepared?.ready ||
                  !selectedWorkerAllowed ||
                  (formal && planningDays > 1 && method !== "simulate")
                }
              >
                <Play size={16} />
                {run.isPending ? "開始中…" : "2. 計算を開始"}
              </button>
            </div>
          </fieldset>
        </form>
        {method === "optimize" && (
          <div className={planningDays > 1 ? "warning" : "notice"}>
            <strong>
              {planningDays}日間 / {planningDays * 24}時間
            </strong>
            <p>
              {rolling
                ? `1時間ずつ運用するローリングを予定${planningDays * 24}回実行します。これは予定数で、完了数ではありません。`
                : "前日計画のみ実行します。ローリング運用は行いません。"}
            </p>
            {planningDays > 1 && (
              <p>
                複数日は診断実行です（MULTIDAY_RESEARCH_BLOCKED）。正式研究実行は開始できません。現在の週間キャンペーン専用設定の再現を保証するものではありません。
              </p>
            )}
          </div>
        )}
        <ErrorBox
          error={prepare.error ?? run.error ?? job.error ?? preflight.error}
        />
        {destination !== "standalone" && method === "optimize" && (
          <p className="notice">
            登録後は「分散計算」で進捗と成果物を確認できます。GurobiとRAMの設定を満たすPCがない場合は待機します。通信が切れた場合は状態を照合するまで実行枠を保持します。
          </p>
        )}
        {prepared && (
          <div className={prepared.ready ? "notice" : "warning"}>
            {prepared.ready ? "入力準備済み" : "入力が未成立"} ·{" "}
            {prepared.tripCount} 便 / {prepared.vehicleCount} 台 /{" "}
            {prepared.planningDays} 日
            {prepared.message && <p>{prepared.message}</p>}
            {prepared.warnings?.map((warning, i) => (
              <p key={i}>{warning}</p>
            ))}
          </div>
        )}
        {(formal || destination !== "standalone") && preflight.data && (
          <details>
            <summary>正式実行の事前確認</summary>
            <pre>{JSON.stringify(preflight.data, null, 2)}</pre>
          </details>
        )}
      </section>
      {job.data && (
        <section className="panel job">
          <div>
            <Activity size={18} />
            <strong>{job.data.status}</strong>
            <span>{job.data.progress}%</span>
          </div>
          <progress max={100} value={job.data.progress} />
          <p>{job.data.message}</p>
          {job.data.error && <p className="error">{job.data.error}</p>}
          <small>ジョブID: {job.data.job_id}</small>
          <details>
            <summary>ジョブの詳細</summary>
            <pre>{JSON.stringify(job.data, null, 2)}</pre>
          </details>
        </section>
      )}
      <details className="panel">
        <summary>計算機能・保存済み設定</summary>
        <pre>
          {JSON.stringify(
            { capabilities: capabilities.data, settings: data.settings },
            null,
            2,
          )}
        </pre>
      </details>
    </>
  );
}
