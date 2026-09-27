import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { discovery, type Discovery } from "./ControllerRecovery";
import type { ClusterWorkers, WorkerNode } from "./WorkerNodes";

type Attachment = { name: string; size: number; sha256: string };
type RequestForm = { schema_version: "lab_request_v1"; request_id: string; requester: string; project: string;
  title: string; workload: "thesis_scenario" | "python" | "other"; solver: "gurobi" | "no_gurobi" | "other";
  memory_gib: number; threads: number; time_limit_minutes: number; license_basis: string;
  instructions: string; scenario_id: string; attachments: Attachment[] };
type Report = { revision: string; parent: string; observed_at_utc: string; included: number; declared: number;
  complete: boolean; cases: { week: string; state: string; included: boolean; original_state?: string; total_cost_jpy?: number }[] };
type Lab = { schema_version: "lab_console_v1"; controller_port: number; solver_git_sha: string; inventory_port: number | null;
  requests: { request: RequestForm; state: string; received_at: string; sha256: string; solver_submitted: false }[]; report: Report | null };

function blankRequest(): RequestForm {
  return { schema_version: "lab_request_v1", request_id: crypto.randomUUID(), requester: "", project: "", title: "",
    workload: "thesis_scenario", solver: "other", memory_gib: 8, threads: 2, time_limit_minutes: 60,
    license_basis: "未確認（受付後に利用者・ライセンス条件を確認）", instructions: "", scenario_id: "", attachments: [] };
}

async function labFetch(info: Discovery, path: string, body?: unknown): Promise<Response> {
  const response = await fetch(`${info.control_origin}/lab${path}`, { method: body === undefined ? "GET" : "POST",
    cache: "no-store", signal: AbortSignal.timeout(15000),
    headers: { "X-Supervisor-Token": info.token, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) throw new Error((await response.json() as { error?: string }).error || "受付サービスに接続できません");
  return response;
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function workerIdentity(worker: WorkerNode): string {
  return worker.transport === "local" ? "local" : worker.tailscale_ip || worker.host || `unverified:${worker.id}`;
}

function FleetInventory({ port, current, origin, currentUnconfirmed }: { port: number; current?: ClusterWorkers; origin: string; currentUnconfirmed: boolean }) {
  const target = new URL(origin || window.location.origin); target.port = String(port);
  const registryOrigin = target.origin;
  const query = useQuery({ queryKey: ["lab-worker-inventory", registryOrigin], queryFn: () =>
    api<ClusterWorkers>("/cluster/workers", { cache: "no-store", signal: AbortSignal.timeout(10000) }, registryOrigin),
    refetchInterval: 15000, retry: false });
  const registered = query.data?.workers ?? [];
  const local = new Map((current?.workers ?? []).map(w => [workerIdentity(w), w]));
  return <section id="lab-inventory" className="panel" aria-label="研究室の全端末台帳">
    <h2>研究室の全端末台帳</h2>
    <p>登録 {query.data ? registered.length : "未確認"}台（親機 {query.data ? registered.filter(w => w.transport === "local").length : "未確認"}台・子機 {query.data ? registered.filter(w => w.transport !== "local").length : "未確認"}台）
      ／ この計算サーバーの対象 {current?.workers.length ?? "未確認"}台</p>
    <p className="subtle">全台帳：{registryOrigin} ／ 今回の計算：{origin || window.location.origin}。台帳への登録と、今回の計算に投入できる状態は別です。</p>
    {query.isError && <p role="alert">全台帳の現在状態は未確認です。表示は前回値の場合があります：{query.error.message}</p>}
    <p>Gurobiは32GB以上・認証済みの端末に限定します。台数分のライセンス枠があるという意味ではありません。小容量機は対応済みの非Gurobi処理・検算等の候補です。</p>
    <p><a href={`${registryOrigin}/#cluster`} target="_blank" rel="noreferrer">全台帳の管理画面を開く</a>（別サーバーへの投入は、現在の予約・ライセンスとの競合確認が必要です）</p>
    <details open><summary>全端末の所在・RAM・割当状況</summary><div className="detail-table"><table>
      <thead><tr><th>PC</th><th>RAM / 空き [GiB]</th><th>今回の割当</th><th>台帳側の接続・環境</th></tr></thead>
      <tbody>{registered.map(w => {
        const active = local.get(workerIdentity(w));
        const c = (active ?? w).capability;
        const mode = !current || currentUnconfirmed ? "今回の割当情報は未確認（RAM等は前回値の場合あり）" : !active ? "今回の計算設定の対象外" : active.mode === "disabled" ? "割当無効"
          : active.mode === "draining" ? "新規割当停止" : active.reserved > 0 ? "実行枠を使用中（状態照合を含む）" : "割当候補・実投入時に判定";
        return <tr key={w.id}><td>{w.name}<br /><small>{w.transport === "local" ? "親機" : "子機"} · {w.tailscale_ip || w.host}</small></td>
          <td>{(c.installed_ram_gb ?? c.ram_gb)?.toFixed(1) ?? "未確認"} / {c.ram_free_gb?.toFixed(1) ?? "未確認"}
            {(active ?? w).metrics_stale && <small>（前回値）</small>}</td>
          <td>{mode}{active?.active_jobs.map(j => <small key={j.id}>{j.id.slice(0, 8)} · {j.state}</small>)}
            {active?.readiness_reasons.map(reason => <small key={reason}>{reason}</small>)}</td>
          <td>{query.isError ? "未確認" : w.status}<br />{w.readiness_reasons.join(" / ") || "台帳側の追加理由なし"}
            <small>確認：{w.last_probe_at ? new Date(w.last_probe_at).toLocaleString("ja-JP") : "未確認"}</small></td></tr>;
      })}</tbody></table></div></details>
  </section>;
}

export default function LabConsole({ origin = "", readOnly = false, controllerSha, workers, scenarioId, workersUnconfirmed = false }: {
  origin?: string; readOnly?: boolean; controllerSha?: string; workers?: ClusterWorkers; scenarioId?: string; workersUnconfirmed?: boolean;
}) {
  const client = useQueryClient();
  const key = ["lab-console", origin, controllerSha];
  const [form, setForm] = useState<RequestForm>(blankRequest);
  const [fileError, setFileError] = useState("");
  const [preview, setPreview] = useState<{ revision: string; src: string } | null>(null);
  const query = useQuery({ queryKey: key, queryFn: async () => {
    const info = await discovery(origin);
    if (!info) return null;
    if (controllerSha && info.solver_git_sha !== controllerSha) throw new Error("操作先の計算版が一致しません");
    const response = await labFetch(info, "");
    const data = await response.json() as Lab;
    if (data.schema_version !== "lab_console_v1" || data.controller_port !== info.controller_port || data.solver_git_sha !== info.solver_git_sha
        || !Array.isArray(data.requests)) throw new Error("受付サービスの登録先が一致しません");
    return { info, data };
  }, refetchInterval: 15000, retry: false });
  const submit = useMutation({ mutationFn: async (body: unknown) => {
    if (readOnly) throw new Error("対象の計算画面から操作してください");
    const info = await discovery(origin);
    if (!info || (controllerSha && info.solver_git_sha !== controllerSha)) throw new Error("受付先を確認できません");
    await labFetch(info, "/requests", body);
  }, onSuccess: () => { void client.invalidateQueries({ queryKey: key }); setForm(blankRequest()); } });
  const download = useMutation({ mutationFn: async ({ name, show = false }: { name: string; show?: boolean }) => {
    const report = query.data?.data.report;
    const info = await discovery(origin);
    if (!report || !info || info.solver_git_sha !== query.data?.info.solver_git_sha) throw new Error("結果の参照先を確認できません");
    const blob = await (await labFetch(info, `/report/${report.revision}/${name}`)).blob();
    if (show) {
      const reader = new FileReader(); reader.onload = () => setPreview({ revision: report.revision, src: String(reader.result) }); reader.readAsDataURL(blob);
    } else saveBlob(blob, name);
  } });
  const data = query.data?.data;
  const report = data?.report && (!scenarioId || data.report.parent === scenarioId) ? data.report : null;
  const disabled = readOnly || query.isError || !data || submit.isPending;
  return <>
    {data?.inventory_port && <FleetInventory port={data.inventory_port} current={workers} origin={origin} currentUnconfirmed={workersUnconfirmed} />}
    {report && <section id="lab-results" className="panel" aria-label="検算済みの月別比較">
      <h2>検算済みの月別比較：{report.included} / {report.declared}週</h2>
      {query.isError && <p role="alert">集計の現在状態は未確認です。以下は前回取得した結果です。</p>}
      <p>{report.complete ? "比較対象の集計が揃いました。" : "途中結果です。未完了週は費用比較に含めません。"} 正式研究採用・統合最適性とは別判定です。</p>
      <p className="subtle">集計更新：{new Date(report.observed_at_utc).toLocaleString("ja-JP")} ／ 計算版 {data?.solver_git_sha.slice(0, 8)}</p>
      <div className="detail-table"><table><thead><tr><th>代表週</th><th>検算・集計</th><th>費用 [円 / 週＋最終翌朝]</th></tr></thead>
        <tbody>{report.cases.map(c => <tr key={c.week}><td>{c.week}</td><td>{c.state === "REPORTING_RECOVERED" ? "図表失敗を修復・再検算済み（元試行は失敗）" : c.included ? "検算・集計済み" : `集計待ち (${c.state})`}</td>
          <td>{c.included && c.total_cost_jpy != null ? c.total_cost_jpy.toLocaleString("ja-JP", { maximumFractionDigits: 2 }) : "未確定"}</td></tr>)}</tbody></table></div>
      <div className="actions"><button disabled={query.isError || download.isPending} onClick={() => download.mutate({ name: "monthly_cost.png", show: true })}>費用グラフを表示</button>
        {["report.md", "weekly_summary.csv", "daily_summary.csv", "experiment_index.csv"].map(name => <button key={name} disabled={query.isError || download.isPending} onClick={() => download.mutate({ name })}>{name}を保存</button>)}</div>
      {preview?.revision === report.revision && <img src={preview.src} alt="検算済み代表週の費用比較" style={{ maxWidth: "100%" }} />}
      {download.isError && <p role="alert">{download.error.message}</p>}
    </section>}
    <section id="lab-intake" className="panel" aria-label="研究室の計算依頼受付">
      <h2>研究室の計算依頼受付</h2>
      <p>他のメンバーの依頼を親機に保存します。受付は求解の投入ではありません。入力・実行環境・RAM・利用者本人のライセンスを確認後、対応済みのシナリオは既存の「実行」画面からPrepareして投入します。</p>
      <p>任意のPython・他ソルバーの依頼は要対応として受け付けます。ファイル本体の転送やコード実行は行いません。APIキー・秘密鍵・ライセンスキーは入力しないでください。</p>
      {query.isError && <p role="alert">現在の受付・結果状態は未確認です：{query.error.message}</p>}
      {query.data === null && <p>受付サービス未登録。管理者による設置が必要です。</p>}
      <details><summary>依頼を作成・取り込む</summary>
        <form onSubmit={event => { event.preventDefault(); submit.mutate(form); }}>
          {([['requester', '依頼者'], ['project', '研究テーマ'], ['title', 'タスク名'], ['scenario_id', '既存シナリオID（任意）']] as const).map(([field, label]) =>
            <label key={field}>{label}<input value={form[field]} required={field !== 'scenario_id'} maxLength={field === 'title' ? 200 : field === 'project' ? 160 : 100} onChange={e => setForm({ ...form, [field]: e.target.value })} /></label>)}
          <label>実行形式<select value={form.workload} onChange={e => setForm({ ...form, workload: e.target.value as RequestForm['workload'] })}>
            <option value="thesis_scenario">この修論モデルのシナリオ</option><option value="python">別のPythonモデル（実行対応の確認が必要）</option><option value="other">その他（実行対応の確認が必要）</option></select></label>
          <label>ソルバー<select value={form.solver} onChange={e => setForm({ ...form, solver: e.target.value as RequestForm['solver'] })}>
            <option value="other">未確認・その他</option><option value="gurobi">Gurobi</option><option value="no_gurobi">Gurobiを使用しない</option></select></label>
          {([['memory_gib', '必要メモリ [GiB]', 256], ['threads', 'CPUスレッド数', 128], ['time_limit_minutes', '時間上限 [分]', 10080]] as const).map(([field, label, max]) =>
            <label key={field}>{label}<input type="number" required min={1} max={max} value={form[field]} onChange={e => setForm({ ...form, [field]: Number(e.target.value) })} /></label>)}
          <label>ライセンスの利用根拠（未確認可・キー不要）<textarea required maxLength={1000} value={form.license_basis} onChange={e => setForm({ ...form, license_basis: e.target.value })} /></label>
          <label>入力・実行方法・期待する成果物<textarea required maxLength={3000} value={form.instructions} onChange={e => setForm({ ...form, instructions: e.target.value })} /></label>
          <label>入力ファイルの照合情報を付ける（本体は送信しません、各32MiBまで）<input type="file" multiple onChange={async e => {
            const files = Array.from(e.target.files ?? []); setFileError("");
            try {
              if (files.length > 40 || files.some(f => f.size > 32 * 1024 * 1024)) throw new Error("40ファイル以内・各32MiB以内にしてください。大きい入力は別途共有して照合情報を記載してください。");
              const attachments: Attachment[] = [];
              for (const f of files) { const hash = await crypto.subtle.digest("SHA-256", await f.arrayBuffer());
                attachments.push({ name: f.name, size: f.size, sha256: Array.from(new Uint8Array(hash)).map(n => n.toString(16).padStart(2, "0")).join("") }); }
              setForm(previous => ({ ...previous, attachments }));
            } catch (error) { setFileError(String(error)); }
          }} /></label>
          <p>照合情報 {form.attachments.length}ファイル</p>
          <div className="actions"><button type="submit" disabled={disabled}>依頼を受付簿へ保存（計算は開始しません）</button>
            <button type="button" onClick={() => saveBlob(new Blob([JSON.stringify(form, null, 2)], { type: "application/json" }), `lab-request-${form.request_id}.json`)}>依頼JSONを保存</button></div>
        </form>
        <label>受け取った依頼JSONを登録<input type="file" accept=".json,application/json" disabled={disabled} onChange={async e => {
          const file = e.target.files?.[0]; e.target.value = ""; setFileError("");
          if (!file) return;
          try { if (file.size > 65536) throw new Error("依頼JSONは64KiB以内です"); submit.mutate(JSON.parse(await file.text()) as unknown); }
          catch (error) { setFileError(String(error)); }
        }} /></label>
      </details>
      {readOnly && <p>閲覧専用です。<a href={`${origin}/#cluster`}>対象の計算画面を開く</a>と受付できます。</p>}
      {fileError && <p role="alert">{fileError}</p>}{submit.isError && <p role="alert">{submit.error.message}</p>}
      {submit.isSuccess && <p role="status">受付簿へ保存しました。実行確認待ちです。求解ジョブは作成していません。</p>}
      <p>受付済み {data?.requests.length ?? "未確認"}件</p>
      {data?.requests.map(entry => <details key={entry.request.request_id}><summary>{entry.request.title} ／ {entry.request.requester} ／ 実行確認待ち</summary>
        <p>{entry.request.project} · {entry.request.solver} · {entry.request.memory_gib} GiB · {entry.request.threads} threads · {entry.request.time_limit_minutes}分</p>
        <p>{entry.request.instructions}</p><p>ライセンス申告：{entry.request.license_basis}（未検証）</p>
        <p>受付：{entry.received_at} · ID {entry.request.request_id}</p><p>依頼hash：{entry.sha256}</p>
        <button onClick={() => saveBlob(new Blob([JSON.stringify(entry.request, null, 2)], { type: "application/json" }), `lab-request-${entry.request.request_id}.json`)}>この依頼を保存</button>
      </details>)}
    </section>
  </>;
}
