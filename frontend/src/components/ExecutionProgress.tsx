import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import "./ExecutionProgress.css";

type Execution = { phase: string; observed_at: string; rolling_saved: number; rolling_feasible: number;
  chain_accepted: boolean; last_step: string | null;
  native: { file: string; updated_at: string; metrics: { solver_seconds?: number; barrier_iteration?: number; stage_gap_percent?: number }; lines: string[] } | null };
type Case = { parent: string; campaign: string; week: string; state: string; worker: string | null;
  prepared: boolean; verified: boolean; job_id: string | null; solver_git_sha: string; observed_at: string;
  connection: string; started_at: string | null; expected_windows: number | null; trip_count: number | null;
  error: string | null; probe_error?: string; execution: Execution | null;
  license?: { global_gurobi_slots: number; external_gurobi_slots: number; reserved_gurobi_slots: number; cooling_gurobi_slots: number };
  placement: { worker: string; reasons: string[]; readiness_reasons: string[]; available_ram_gb?: number; required_ram_gb?: number }[] };
type Detail = { schema_version: "execution_detail_v1"; observed_at: string; cases: Case[]; errors: { operation: string; error: string }[] };
const phases: Record<string, string> = { MODEL_BUILD: "数理モデルの構築", STAGE1: "配車を求解中（Stage 1）",
  STAGE2: "充電計画を求解中（Stage 2）", ROLLING: "毎時の運用計算", FINALIZING: "会計・出力を作成中" };
const states: Record<string, string> = { PREPARING: "入力を準備中", NOT_PREPARED: "入力準備待ち", QUEUED: "PC・ライセンスの空き待ち",
  STAGING: "子機へ配布中", RUNNING: "計算中（詳細を確認中）", COLLECTING: "成果物を回収中", COMPLETED: "計算終了・検算を確認",
  VERIFIED: "検算・集計済み", FAILED: "失敗", BLOCKED: "開始条件で停止", CANCELLED: "取消済み",
  LOST: "通信不明・同じ試行を照合中", STATE_UNKNOWN: "状態不明", FAILED_OR_UNVERIFIED: "失敗または未検算",
  PREPARE_OR_SUBMIT_FAILED: "入力準備・投入に失敗" };
const reasons: Record<string, string> = { INSUFFICIENT_OR_UNKNOWN_RAM: "空きRAM不足・未確認", WORKER_SLOTS_RESERVED: "別の計算を実行中",
  GUROBI_REQUIRES_32GB_INSTALLED_RAM: "Gurobiは搭載RAM 32GB以上が必要（不足・未確認）",
  CPU_BUSY: "CPU使用率が高い", AC_POWER_REQUIRED: "AC電源未確認", INSUFFICIENT_OR_UNKNOWN_CPU_THREADS: "CPU枠不足",
  GUROBI_LICENSE_UNAVAILABLE: "Gurobiライセンスを利用できません" };
const stamp = (s?: string | null) => s ? new Date(s).toLocaleString("ja-JP") : "未確認";
export default function ExecutionProgress({ scenarioId, origin = "" }: { scenarioId?: string; origin?: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(timer); }, []);
  const query = useQuery({ queryKey: ["execution-detail", origin], queryFn: async () => {
    const r = await fetch(`${origin}/execution-detail.json`, { cache: "no-store" });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json() as Detail;
    if (d.schema_version !== "execution_detail_v1" || !Array.isArray(d.cases) || !Array.isArray(d.errors) || !Number.isFinite(Date.parse(d.observed_at))) throw new Error("進捗データの形式不一致");
    return d;
  }, refetchInterval: 10000, retry: false });
  const data = query.data;
  if (!data && !query.error) return null;
  const stale = !!query.error || !data || now - Date.parse(data.observed_at) > 120000 || Date.parse(data.observed_at) - now > 30000;
  const rows = data?.cases.filter(c => !scenarioId || c.parent === scenarioId) ?? [];
  return <section className="panel" aria-label="計算の詳細進捗">
    <h2>計算の詳細進捗</h2>
    <p>入力準備 {rows.filter(c => c.prepared).length}/{rows.length}週 ／ 計算終了 {rows.filter(c => ["COMPLETED", "VERIFIED"].includes(c.state)).length}/{rows.length}週 ／ 検算・集計 {rows.filter(c => c.verified).length}/{rows.length}週</p>
    <p>30秒ごとに読取・画面は10秒ごとに更新。取得時刻：{stamp(data?.observed_at)} <button onClick={() => void query.refetch()}>進捗を更新</button></p>
    <p>工程と保存済みの窓数を表示します。求解の残り時間・全体の最適性は、この進捗率からは分かりません。</p>
    {stale && <p role="alert">更新が途切れています。以下は最後の記録で、現在の実行状態は不明です。</p>}
    {data?.errors.map(e => <p role="alert" key={e.operation}>{e.operation}：取得失敗（{e.error}）。計算失敗とは別です。</p>)}
    <div className="execution-progress-list">{rows.map(c => {
        const ex = c.execution;
        const live = !stale && c.connection === "CONNECTED" && (c.state !== "RUNNING" || !ex || (now - Date.parse(ex.observed_at) < 120000 && now - Date.parse(ex.observed_at) >= -30000));
        const phase = c.verified ? "検算・集計済み" : live && c.state === "RUNNING" && ex ? phases[ex.phase] ?? ex.phase : states[c.state] ?? c.state;
        const n = ex?.rolling_feasible ?? 0, total = c.expected_windows;
        return <article className="execution-progress-case" key={`${c.campaign}-${c.week}`} aria-label={`${c.week}の計算進捗`}>
          <div className="execution-progress-overview"><div><h3>{c.week} 開始週</h3><p>{!live && "最終記録："}{phase}</p></div>
            <div><small>担当PC</small><p>{c.worker ?? "未割当"}</p></div>
            <div><small>毎時の計算</small><p>{ex && total ? <><progress aria-label={`${c.week}の保存済み可行窓`} value={Math.min(n, total)} max={total}/><br/>{n}/{total}窓（{(100*n/total).toFixed(1)}%）<br/><small>保存済み可行窓。週全体の検算は別。</small></> : "未取得・未着手"}</p></div></div>
          {c.error && <p role="alert">{reasons[c.error] ?? c.error}</p>}{c.probe_error && <p>{c.probe_error}</p>}
          <details><summary>工程・求解・待機理由を見る</summary>
            <ol><li>入力準備：{c.prepared ? "完了" : "未完了"}（対象便 {c.trip_count ?? "未取得"}）</li>
              <li>配車・充電：{phase}</li><li>毎時計算：保存 {ex?.rolling_saved ?? "未取得"}窓／チェーン検査 {ex?.chain_accepted ? "通過" : "未確認"}</li>
              <li>回収・検算・集計：{c.verified ? "完了" : "未完了"}</li></ol>
            <p>投入時刻：{stamp(c.started_at)} ／ 詳細読取：{stamp(ex?.observed_at)}</p>
            {ex?.native && <><p>直近ログ：{ex.native.file} ／ 更新 {stamp(ex.native.updated_at)}</p>
              <p>求解器の経過 {ex.native.metrics.solver_seconds ?? "未取得"}秒 ／ barrier反復 {ex.native.metrics.barrier_iteration ?? "該当なし"} ／ この求解のgap {ex.native.metrics.stage_gap_percent == null ? "未取得" : `${ex.native.metrics.stage_gap_percent}%`}（週全体のgapではありません）</p>
              <pre>{ex.native.lines.join("\n")}</pre></>}
            {c.state === "QUEUED" && <><p>PC要件を満たしていても共有ライセンス使用中・解放待ちなら待機します。</p>
              {c.license && <p>Gurobi：全{c.license.global_gurobi_slots}枠／使用・予約{c.license.reserved_gurobi_slots}／解放待ち{c.license.cooling_gurobi_slots}／外部予約{c.license.external_gurobi_slots}</p>}
              {c.placement.map(p => <p key={p.worker}>{p.worker}：{[...p.reasons, ...p.readiness_reasons].map(r => reasons[r] ?? r).join("、") || "PC資源要件内"}（空き {p.available_ram_gb?.toFixed(1) ?? "不明"}GB／要求 {p.required_ram_gb ?? "不明"}GB）</p>)}</>}
            <p>試行ID：{c.job_id ?? "未投入"}<br/>計算コード：{c.solver_git_sha}<br/>実験：{c.campaign}</p>
          </details></article>;
      })}</div>
  </section>;
}
