import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export type Discovery = { schema_version: "supervisor_discovery_v1"; controller_port: number;
  solver_git_sha: string; control_origin: string; token: string };
type Status = { schema_version: "supervisor_ui_v1"; controller_port: number; solver_git_sha: string;
  enabled: boolean; status: string; binding_matches: boolean; starts: number; max_starts: number;
  next_start_at?: number; process?: { pid: number; identity: string }; observed_at_utc?: string;
  last_tick_utc?: string; service_observed_at_utc: string; last_error?: string };
const labels: Record<string, string> = {
  DISABLED: "自動復旧は無効", ARMED: "自動復旧は有効・確認待ち", PROCESS_PRESENT: "管理プロセスの生存を確認",
  STARTING: "起動記録を保存・結果確認中", STARTED: "管理サーバーを起動・確認待ち", BACKOFF: "再起動の待機時間中",
  HOLD_PROCESS_UNKNOWN: "プロセスを確認できず保留", HOLD_MULTIPLE_PROCESSES: "複数の管理プロセスを検出・保留",
  HOLD_PORT_OCCUPIED: "ポートの使用者を確認できず保留", HOLD_QUEUE_OWNED: "キューが使用中のため保留",
  BLOCKED_RESTART_BUDGET: "再起動回数の上限に達して停止", BLOCKED_BINDING_CHANGED: "固定設定・監督コードが変わったため停止",
  BLOCKED_PREFLIGHT: "起動前検査で停止", BLOCKED_START_OUTCOME_UNKNOWN: "前回の起動結果が不明のため停止",
  IDLE_NO_PENDING_WORK: "残りジョブがないため自動復旧を終了",
};
const stamp = (value?: string) => value ? new Date(value).toLocaleString("ja-JP") : "未確認";

export async function discovery(origin: string): Promise<Discovery | null> {
  const target = new URL(origin || window.location.origin);
  const response = await fetch(`${origin}/supervisor-control-${target.port || 80}.json`, { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("操作サービスの登録情報を取得できません");
  const data = await response.json() as Discovery;
  const endpoint = new URL(data.control_origin);
  if (data.schema_version !== "supervisor_discovery_v1" || data.controller_port !== Number(target.port || 80)
      || endpoint.protocol !== "http:" || endpoint.hostname !== "127.0.0.1" || endpoint.pathname !== "/"
      || endpoint.search || endpoint.hash || endpoint.username || endpoint.password || !endpoint.port
      || typeof data.token !== "string" || data.token.length < 32) {
    throw new Error("操作サービスと監視先の対応が一致しません");
  }
  return data;
}

async function request(info: Discovery, action: "status" | "enable" | "disable"): Promise<Status> {
  const response = await fetch(`${info.control_origin}/${action}`, {
    method: action === "status" ? "GET" : "POST", cache: "no-store",
    headers: { "X-Supervisor-Token": info.token }, signal: AbortSignal.timeout(25000),
  });
  const data = await response.json() as Status & { error?: string };
  if (!response.ok) throw new Error(data.error || "操作サービスに接続できません");
  if (data.schema_version !== "supervisor_ui_v1" || data.controller_port !== info.controller_port
      || data.solver_git_sha !== info.solver_git_sha) throw new Error("異なる管理サーバーからの応答です");
  return data;
}

export default function ControllerRecovery({ origin = "", readOnly = false, controllerSha }: {
  origin?: string; readOnly?: boolean; controllerSha?: string;
}) {
  const client = useQueryClient();
  const key = ["controller-recovery", origin];
  const query = useQuery({ queryKey: key, queryFn: async () => {
    const info = await discovery(origin);
    if (!info) return null;
    if (controllerSha && controllerSha !== info.solver_git_sha) throw new Error("計算固定版と操作サービスの版が違います");
    return { info, status: await request(info, "status") };
  }, refetchInterval: 5000, retry: false, refetchOnWindowFocus: "always" });
  const mutation = useMutation({ mutationFn: async (action: "enable" | "disable") => {
    if (readOnly) throw new Error("別の監視先は閲覧専用です");
    // Refetch binding and nonce; a service restart invalidates the old session.
    const info = await discovery(origin);
    if (!info || (controllerSha && controllerSha !== info.solver_git_sha)) throw new Error("操作先を確認できません");
    await request(info, action);
  }, onSuccess: () => { void client.invalidateQueries({ queryKey: key }); } });
  const state = query.data?.status;
  const unconfirmed = query.isError || query.isFetching && !query.data;
  return <section className="panel" aria-label="管理サーバーの自動復旧">
    <h2>管理サーバーの自動復旧</h2>
    <p className="subtle">対象：{origin || window.location.origin} ／ シナリオに共通の管理機能</p>
    {query.isPending && <p>状態を確認中…</p>}
    {query.data === null && <p>この管理サーバーには操作サービスが登録されていません。</p>}
    {query.isError && <p role="alert">現在状態を確認できません：{query.error.message}。計算停止とは限りません。</p>}
    {state && <>
      <p><strong>{unconfirmed ? "現在状態は未確認（以下は前回値）" : labels[state.status] || state.status}</strong>
        {!unconfirmed && ` ／ 自動復旧：${state.enabled ? "有効" : "無効"}`}</p>
      <p>自動起動 {state.starts}/{state.max_starts}回 ／ 管理PID {state.process?.pid ?? "未確認"}
        {state.status === "BACKOFF" && state.next_start_at && ` ／ 次回確認 ${stamp(new Date(state.next_start_at * 1000).toISOString())}`}</p>
      {state.last_error && <p role="alert">監督処理で確認エラー：{state.last_error}。詳細を確認してください。</p>}
      <p className="subtle">監督の確認：{stamp(state.last_tick_utc)} ／ 画面取得：{stamp(state.service_observed_at_utc)}</p>
      <div className="actions">
        <button disabled={readOnly || unconfirmed || mutation.isPending || state.enabled || !state.binding_matches || state.status.startsWith("BLOCKED")}
          onClick={() => mutation.mutate("enable")}>自動復旧を有効にする</button>
        <button disabled={readOnly || unconfirmed || mutation.isPending || !state.enabled}
          onClick={() => mutation.mutate("disable")}>自動復旧を無効にする</button>
        <button disabled={query.isFetching} onClick={() => { void query.refetch(); }}>復旧状態を更新</button>
      </div>
      <details><summary>復旧の条件と詳細</summary>
        <p>状態コード：{state.status} ／ 計算固定版：{state.solver_git_sha}</p>
        <p>管理サーバーの停止が確認できた場合だけ、同じ固定版・キューを起動します。状態不明なら保留し、最大3回で打ち切ります。</p>
        <p>新しい計算試行は作りません。復旧した管理サーバーは、既存キューの待機ジョブの割当を再開します。</p>
        <p>「無効にする」は自動復旧だけを止めます。管理サーバー・バスの計算・結果回収を終了する操作ではありません。</p>
        <p>BLOCKEDは元の記録を確認する必要があります。この画面から回数上限や不明な起動記録を消すことはできません。</p>
      </details>
    </>}
    {readOnly && <p>別の監視先は閲覧専用です。<a href={`${origin}/#cluster`} target="_blank" rel="noreferrer">対象の画面を開いて操作</a>してください。</p>}
    {mutation.isPending && <p role="status">操作を適用中…</p>}
    {mutation.isSuccess && <p role="status">操作を適用しました。復旧状態を確認してください。</p>}
    {mutation.isError && <p role="alert">{mutation.error.message}</p>}
  </section>;
}
