import { useState } from "react";

export type WorkerNode = {
  id: string;
  name: string;
  host: string | null;
  ssh_user: string | null;
  tailscale_ip: string | null;
  transport: string;
  enabled: boolean;
  mode: string;
  status: string;
  slots: number;
  reserved: number;
  gurobi: boolean;
  ram_gb: number;
  tailscale_online: boolean | null;
  ssh_ready: boolean;
  environment_ready: boolean;
  can_run_optimization: boolean;
  can_run_no_gurobi?: boolean;
  can_run_diagnostic: boolean;
  readiness_reasons: string[];
  network_checked_at: string | null;
  last_seen_at: string | null;
  last_probe_at: string | null;
  last_error: string | null;
  probe_error_code?: string | null;
  probing: boolean;
  metrics_stale: boolean;
  active_jobs: { id: string; state: string }[];
  completed_jobs: number;
  failed_jobs: number;
  last_allocation?: {
    job_id: string;
    available_ram_gb: number | null;
    required_ram_gb: number;
    required_cpu_threads: number;
    ranking_basis: string;
    matching_history_count: number;
    median_worker_seconds: number | null;
  } | null;
  capability: {
    cpu_model?: string | null;
    ac_power?: boolean | null;
    battery_percent?: number | null;
    cpu_count?: number;
    cpu_percent?: number | null;
    ram_gb?: number | null;
    ram_free_gb?: number | null;
    disk_free_gb?: number | null;
    python?: string;
    gurobi_version?: number[];
    git?: { sha: string; dirty: boolean };
    gurobi_license_checked?: boolean;
  };
};
export type ClusterWorkers = {
  workers: WorkerNode[];
  global_gurobi_slots: number;
  external_gurobi_slots?: number;
  reserved_gurobi_slots: number;
  cooling_gurobi_slots?: number;
  license_reservations?: { id: string; state: string; release_after: number | null }[];
};

const stateLabels: Record<string, string> = {
  READY: "計算可能",
  BUSY: "実行枠を使用中",
  OFFLINE: "オフライン",
  UNKNOWN: "未確認",
  TAILSCALE_ONLINE: "Tailscale接続・SSH未確認",
  SSH_READY: "SSH接続・計算準備待ち",
  DISABLED: "割当無効",
  DRAINING: "新規割当停止",
  ERROR: "確認エラー",
};
function timeLabel(value: string | null) {
  return value ? new Date(value).toLocaleString("ja-JP") : "未確認";
}
function metric(value: number | null | undefined, suffix: string) {
  return value == null ? "未確認" : `${value.toFixed(1)} ${suffix}`;
}

export default function WorkerNodes({
  data,
  pending,
  onAction,
}: {
  data?: ClusterWorkers;
  pending: boolean;
  onAction: (path: string) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const nodes = data?.workers ?? [];
  const visible = nodes.filter(
    (node) =>
      `${node.name} ${node.tailscale_ip ?? ""}`
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (filter === "all" ||
        (filter === "ready"
          ? node.can_run_optimization
          : filter === "busy"
            ? node.reserved > 0
            : !node.can_run_optimization && node.reserved === 0)),
  );
  return (
    <>
      <div className="run-summary">
        <div>
          <small>登録端末</small>
          <strong>{nodes.length} 台</strong>
        </div>
        <div>
          <small>Tailscaleオンライン（子機）</small>
          <strong>
            {nodes.filter((node) => node.tailscale_online === true).length} /{" "}
            {nodes.filter((node) => node.transport === "ssh").length}
          </strong>
        </div>
        <div>
          <small>計算可能</small>
          <strong>
            {
              nodes.filter(
                (node) =>
                  node.can_run_optimization && node.reserved < node.slots,
              ).length
            }{" "}
            台
          </strong>
        </div>
        <div>
          <small>実行枠を使用中</small>
          <strong>{nodes.filter((node) => node.reserved > 0).length} 台</strong>
        </div>
      </div>
      <div className="node-filters">
        <label>
          計算ノードを検索
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="PC名・Tailscale IP"
          />
        </label>
        <label>
          表示
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="all">すべて</option>
            <option value="ready">計算可能</option>
            <option value="busy">実行枠を使用中</option>
            <option value="attention">準備・確認が必要</option>
          </select>
        </label>
      </div>
      <p className="subtle">
        Tailscaleは約5秒、SSH・計算環境は約30秒間隔で確認します。失敗時は間隔を延ばします。期限切れの確認結果では割り当てません。端末の割当停止では、実行中の計算は継続します。
      </p>
      <div className="worker-grid">
        {visible.map((node) => (
          <article className="worker-card" key={node.id} aria-label={node.name}>
            <div className="section-title">
              <h3>{node.name}</h3>
              <span
                className={`node-state node-state-${node.status.toLowerCase()}`}
              >
                {stateLabels[node.status] ?? node.status}
              </span>
            </div>
            <p className="subtle">
              {node.transport === "local"
                ? "親機・ローカル実行"
                : `${node.tailscale_ip ?? node.host} · ${node.ssh_user ?? "SSH設定のユーザー"}`}
            </p>
            <div className="node-checks">
              <span>
                Tailscale:{" "}
                {node.transport === "local"
                  ? "対象外"
                  : node.tailscale_online == null
                    ? "不明"
                    : node.tailscale_online
                      ? "オンライン"
                      : "オフライン"}
              </span>
              <span>
                SSH:{" "}
                {node.transport === "local"
                  ? "対象外"
                  : node.ssh_ready
                    ? "接続済み"
                    : "未確認"}
              </span>
              <span>
                計算環境: {node.environment_ready ? "一致" : "準備待ち"}
              </span>
            </div>
            <dl className="node-metrics">
              <div>
                <dt>CPU使用率</dt>
                <dd>
                  {node.capability.cpu_model && <small>{node.capability.cpu_model}<br /></small>}
                  {metric(node.capability.cpu_percent, "%")} /{" "}
                  {node.capability.cpu_count ?? "—"}論理コア
                </dd>
              </div>
              <div>
                <dt>RAM空き / 総量</dt>
                <dd>
                  {metric(node.capability.ram_free_gb, "GB")} /{" "}
                  {metric(node.capability.ram_gb, "GB")}
                </dd>
              </div>
              <div>
                <dt>ディスク空き</dt>
                <dd>{metric(node.capability.disk_free_gb, "GB")}</dd>
              </div>
              <div>
                <dt>実行枠</dt>
                <dd>
                  {node.reserved} / {node.slots} · 完了{node.completed_jobs} /
                  失敗{node.failed_jobs}
                </dd>
              </div>
            </dl>
            {node.capability.ac_power !== undefined && (
              <p className="subtle">電源: {node.capability.ac_power === null ? "未確認" : node.capability.ac_power ? "AC接続" : "バッテリー駆動"}</p>
            )}
            {node.last_allocation && (
              <details>
                <summary>直近の割当根拠</summary>
                <p>必要RAM {metric(node.last_allocation.required_ram_gb, "GB")} / 割当時の余裕 {metric(node.last_allocation.available_ram_gb, "GB")}。
                  {node.last_allocation.ranking_basis === "comparable_worker_runtime"
                    ? ` 同条件の実測${node.last_allocation.matching_history_count}件、中央値${metric(node.last_allocation.median_worker_seconds, "秒")}で選択。`
                    : " 現在の負荷とメモリ余裕で選択。同条件の速度比較は未確認です。"}
                  研究のthreads・時間上限は変更しません。</p>
              </details>
            )}
            {node.metrics_stale && (
              <small>環境・負荷情報は未確認、または期限切れです。</small>
            )}
            <p className="subtle">
              最終環境確認: {timeLabel(node.last_probe_at)}
              <br />
              最終Tailscale確認: {timeLabel(node.network_checked_at)}
            </p>
            {node.active_jobs.map((job) => (
              <p key={job.id}>
                実行タスク: {job.id.slice(0, 8)} · {job.state}
              </p>
            ))}
            {!!node.readiness_reasons.length && (
              <details>
                <summary>
                  計算開始までの確認事項（{node.readiness_reasons.length}）
                </summary>
                <ul>
                  {node.readiness_reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </details>
            )}
            {node.last_error && (
              <p className="node-error">
                {node.probe_error_code && <strong>{node.probe_error_code}: </strong>}
                {node.last_error.includes("Permission denied")
                  ? "SSH認証に失敗しました。公開鍵とログインユーザーを確認してください。"
                  : node.last_error}
              </p>
            )}
            <div className="actions">
              <button
                disabled={pending || node.probing}
                onClick={() => onAction(`/cluster/workers/${node.id}/probe`)}
              >
                {node.probing ? "確認中…" : "接続確認"}
              </button>
              {node.mode === "active" ? (
                <>
                  <button
                    disabled={pending}
                    onClick={() =>
                      onAction(`/cluster/workers/${node.id}/drain`)
                    }
                  >
                    新規割当停止
                  </button>
                  <button
                    disabled={pending}
                    onClick={() =>
                      onAction(`/cluster/workers/${node.id}/disable`)
                    }
                  >
                    無効化
                  </button>
                </>
              ) : (
                <button
                  disabled={pending}
                  onClick={() => onAction(`/cluster/workers/${node.id}/enable`)}
                >
                  割当を有効化
                </button>
              )}
              <button
                disabled={
                  pending ||
                  !node.can_run_diagnostic ||
                  node.reserved >= node.slots
                }
                onClick={() =>
                  onAction(`/cluster/workers/${node.id}/diagnostic`)
                }
              >
                診断タスクを配布
              </button>
            </div>
            <details>
              <summary>環境の詳細</summary>
              <p>
                Python {node.capability.python ?? "未確認"} / Gurobi{" "}
                {node.capability.gurobi_version?.join(".") ?? "未確認"}
              </p>
              <p>
                Gurobi利用枠: {node.gurobi ? "設定済み" : "未設定"}
                （定期確認ではライセンスを消費しません）
              </p>
              <p>
                コード: {node.capability.git?.sha.slice(0, 12) ?? "未確認"}
                {node.capability.git?.dirty ? " / 未コミット変更あり" : ""}
              </p>
            </details>
          </article>
        ))}
      </div>
      {data && !visible.length && <p>該当する計算ノードはありません。</p>}
    </>
  );
}
