import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, put } from "../api";
import { ErrorBox } from "./common";

type Attempt = { id: string; state: string; prepared: boolean; verified: boolean;
  observed_at?: string; stale?: boolean; job_id?: string; worker?: string; error?: string;
  source_git_sha?: string; placement?: unknown[]; failure_detail?: unknown };
type Period = { id: string; label: string; start: string; days: number; end?: string; attempts?: Attempt[] };
type Plan = { revision: number; periods: Period[]; progress: { prepared: number; verified: number } };
const labels: Record<string, string> = { RUNNING: "実行中", QUEUED: "待機中", FAILED: "エラー",
  COMPLETED: "計算終了（検算状況を確認）", VERIFIED: "検算完了", UNKNOWN: "状態不明",
  NOT_STARTED: "未開始", PREPARING: "入力準備中" };

export default function PeriodPlans({ id, onDirty }: { id: string; onDirty: (dirty: boolean) => void }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<Period[] | null>(null);
  const [revision, setRevision] = useState(0);
  const [start, setStart] = useState("");
  const [days, setDays] = useState(7);
  const query = useQuery({ queryKey: ["periods", id],
    queryFn: ({ signal }) => api<Plan>(`/desktop/scenarios/${id}/periods`, { signal, cache: "no-store" }),
    refetchInterval: 15000 });
  const save = useMutation({ mutationFn: () => put<Plan>(`/desktop/scenarios/${id}/periods`, {
    revision, periods: (draft ?? []).map(({ id: key, label, start: date, days: count }) => ({ id: key, label, start: date, days: count })) }),
    onSuccess: (data) => { client.setQueryData(["periods", id], data); setDraft(null); onDirty(false); } });
  const edit = (periods: Period[]) => { if (draft === null) setRevision(query.data?.revision ?? 0); setDraft(periods); onDirty(true); };
  const periods = draft ?? query.data?.periods ?? [];
  return <section className="card">
    <h2>このシナリオの期間別計画</h2>
    <p>共通の車両・設備・路線をひとつのシナリオで管理し、各月の代表週などをここに登録します。各期間内のSOCは連続、期間同士は独立した実験です。</p>
    <p>入力準備 {query.data?.progress.prepared ?? 0}% ／ 検算完了 {query.data?.progress.verified ?? 0}%（{periods.length}期間）。計画の登録だけでは計算を開始しません。</p>
    {query.error && <ErrorBox error={query.error} />}
    {save.error && <ErrorBox error={save.error} />}
    <div className="toolbar">
      <label>開始日 <input aria-label="期間開始日" type="date" value={start} onChange={e => setStart(e.target.value)} /></label>
      <label>日数 <input aria-label="期間日数" type="number" min={1} max={366} value={days} onChange={e => setDays(Number(e.target.value))} /></label>
      <button disabled={!query.data || !start || days < 1 || days > 366 || !Number.isInteger(days)} onClick={() => {
        edit([...periods, { id: crypto.randomUUID(), label: `${start}から${days}日間`, start, days }]); setStart("");
      }}>期間を追加</button>
      <button disabled={draft === null || save.isPending} onClick={() => save.mutate()}>計画を保存</button>
      <button disabled={draft === null || save.isPending} onClick={() => { setDraft(null); onDirty(false); }}>編集を戻す</button>
    </div>
    <p>週次実行スクリプトへの出力は7日間の計画に対応しています。他の日数は登録できますが、対応する実行経路の確認が必要です。</p>
    <table><thead><tr><th>期間名</th><th>対象期間</th><th>状態</th><th>詳細・履歴</th></tr></thead>
      <tbody>{periods.map((period, index) => {
        const latest = period.attempts?.at(-1);
        return <tr key={period.id}><td><input aria-label={`期間名 ${index+1}`} value={period.label} onChange={e => edit(periods.map(p => p.id === period.id ? { ...p, label: e.target.value } : p))} /></td>
          <td>{period.start} ～ {period.end ?? `${period.days}日間`}</td>
          <td>{query.error ? "取得失敗・状態不明" : latest ? labels[latest.state] ?? latest.state : "計画のみ"}{latest?.verified && "／検算済み"}</td>
          <td><details><summary>実行記録 {period.attempts?.length ?? 0}件</summary>
            {period.attempts?.map(attempt => <pre key={attempt.id}>{JSON.stringify(attempt, null, 2)}</pre>)}
          </details>{!period.attempts?.length && <button onClick={() => edit(periods.filter(p => p.id !== period.id))}>計画から削除</button>}</td></tr>;
      })}</tbody></table>
    {!periods.length && <p>まだ期間がありません。1つのシナリオに複数の週を追加できます。</p>}
  </section>;
}
