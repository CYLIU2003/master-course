import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Check, Play } from "lucide-react";
import {
  api,
  post,
  record,
  strings,
  type Job,
  type Overview,
  type Prepared,
} from "../api";
import DataTable from "./DataTable";
import { ErrorBox } from "./common";
export default function RunPanel({ id, data }: { id: string; data: Overview }) {
  const [depots, setDepots] = useState(
    strings(record(data.scope.depotSelection).depotIds),
  );
  const [routes, setRoutes] = useState(
    strings(record(data.scope.routeSelection).includeRouteIds).length
      ? strings(record(data.scope.routeSelection).includeRouteIds)
      : strings(record(data.scope.routeSelection).routeIds),
  );
  const [date, setDate] = useState(
    String(data.settings.service_date ?? "2025-05-12"),
  );
  const [days, setDays] = useState(Number(data.settings.planning_days ?? 1));
  const [mode, setMode] = useState(
    String(data.settings.solver_mode ?? "phase3_two_stage"),
  );
  const [limit, setLimit] = useState(
    Number(data.settings.time_limit_seconds ?? 300),
  );
  const [formal, setFormal] = useState(false);
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [jobId, setJobId] = useState(
    localStorage.getItem("ev-job-" + id) ?? "",
  );
  const [selectionTable, setSelectionTable] = useState("depots");
  const client = useQueryClient();
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: !!jobId,
    queryFn: ({ signal }) =>
      api<Job>(`/jobs/${encodeURIComponent(jobId)}`, { signal }),
    refetchInterval: (query) =>
      query.state.data &&
      ["completed", "failed"].includes(query.state.data.status)
        ? false
        : 2000,
  });
  const running = job.data
    ? ["running", "pending"].includes(job.data.status)
    : !!jobId && job.isPending;
  useEffect(() => {
    if (job.data?.status === "completed")
      void client.invalidateQueries({ queryKey: ["overview", id] });
  }, [job.data?.status, client, id]);
  useEffect(() => {
    setPrepared(null);
  }, [depots, routes, date, days, mode, limit]);
  const prepare = useMutation({
    mutationFn: () => {
      const serviceDates = Array.from({ length: days }, (_, index) => {
        const day = new Date(date + "T00:00:00Z");
        day.setUTCDate(day.getUTCDate() + index);
        return day.toISOString().slice(0, 10);
      });
      return post<Prepared>(`/scenarios/${id}/simulation/prepare`, {
        selected_depot_ids: depots,
        selected_route_ids: routes,
        service_date: date,
        service_dates: serviceDates,
        simulation_settings: {
          ...data.settings,
          solver_mode: mode,
          time_limit_seconds: limit,
          service_date: date,
          service_dates: serviceDates,
          planning_days: days,
        },
      });
    },
    onSuccess: (value) => {
      setPrepared(value);
      void client.invalidateQueries({ queryKey: ["overview", id] });
    },
  });
  const run = useMutation({
    mutationFn: () =>
      post<{ job_id: string }>(`/scenarios/${id}/run-optimization`, {
        mode,
        research_run: formal,
        prepared_input_id: prepared?.preparedInputId,
        time_limit_seconds: limit,
        run_hourly_rolling: true,
      }),
    onSuccess: (value) => {
      setJobId(value.job_id);
      localStorage.setItem("ev-job-" + id, value.job_id);
    },
  });
  const busy = running || prepare.isPending || run.isPending;
  return (
    <>
      <section className="panel">
        <div className="section-title">
          <h2>01　対象と条件</h2>
          <span className="badge">
            {depots.length} 営業所 / {routes.length} 系統選択
          </span>
        </div>
        <fieldset disabled={busy}>
          <div className="form-grid">
            <label>
              開始日
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
            <label>
              対象日数
              <input
                type="number"
                min={1}
                max={7}
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
              />
            </label>
            <label>
              ソルバー
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="phase3_two_stage">Phase 3 · 二段階</option>
                <option value="phase4_integrated">Phase 4 · 統合</option>
                <option value="mode_milp_only">MILP</option>
                <option value="mode_alns_only">ALNS</option>
                <option value="mode_hybrid">Hybrid</option>
              </select>
            </label>
            <label>
              時間制限（秒）
              <input
                type="number"
                min={1}
                max={86400}
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
              />
            </label>
          </div>
          <p className="subtle">
            複数日は日付別時刻表・PV
            の入力契約を満たす必要があります。継承した充電・SOC・料金設定は下に表示します。
          </p>
          <div className="selection-tools">
            <button
              className={selectionTable === "depots" ? "active" : ""}
              onClick={() => setSelectionTable("depots")}
            >
              営業所を選択
            </button>
            <button
              className={selectionTable === "routes" ? "active" : ""}
              onClick={() => setSelectionTable("routes")}
            >
              系統を選択
            </button>
            <span>系統が未選択の場合は、保存済みの範囲設定を使用します。</span>
          </div>
          <DataTable
            key={selectionTable}
            id={id}
            fixed={selectionTable}
            selected={selectionTable === "depots" ? depots : routes}
            onSelection={selectionTable === "depots" ? setDepots : setRoutes}
          />
          <details>
            <summary>継承する設定・対象 ID</summary>
            <pre>
              {JSON.stringify(
                { depots, routes, settings: data.settings },
                null,
                2,
              )}
            </pre>
          </details>
        </fieldset>
      </section>
      <section className="panel">
        <h2>02　入力の準備と実行</h2>
        <p className="subtle">
          Prepare
          はこのシナリオの入力と派生データを更新します。実行中はアプリを開いたままにしてください。
        </p>
        <div className="actions">
          <button
            className="primary"
            disabled={
              busy ||
              !depots.length ||
              !date ||
              !Number.isInteger(days) ||
              days < 1 ||
              days > 7 ||
              limit < 1
            }
            onClick={() => prepare.mutate()}
          >
            <Check size={16} />
            {prepare.isPending ? "準備中…" : "入力を準備"}
          </button>
          <label className="check">
            <input
              type="checkbox"
              checked={formal}
              disabled={busy}
              onChange={(e) => setFormal(e.target.checked)}
            />
            正式実行（clean commit 必須）
          </label>
          <button
            className="primary"
            disabled={busy || !prepared?.ready}
            onClick={() => run.mutate()}
          >
            <Play size={16} /> {run.isPending ? "開始中…" : "最適化を実行"}
          </button>
        </div>
        <ErrorBox error={prepare.error ?? run.error ?? job.error} />
        {prepared && (
          <div className={prepared.ready ? "notice" : "warning"}>
            {prepared.ready ? "入力準備済み" : "入力が未成立"} ·{" "}
            {prepared.tripCount} trips / {prepared.vehicleCount} vehicles /{" "}
            {prepared.planningDays} 日
            {prepared.message && <p>{prepared.message}</p>}
            {prepared.warnings?.map((warning, i) => (
              <p key={i}>{warning}</p>
            ))}
          </div>
        )}
        {job.data && (
          <div className="job">
            <div>
              <Activity size={18} />
              <strong>{job.data.status}</strong>
              <span>{job.data.progress}%</span>
            </div>
            <progress max={100} value={job.data.progress} />
            <p>{job.data.message}</p>
            {job.data.error && <p className="error">{job.data.error}</p>}
            <small>
              ジョブ ID: {job.data.job_id} ·
              再起動後も状態を確認できます。実行自体は再開されません。
            </small>
          </div>
        )}
      </section>
    </>
  );
}
