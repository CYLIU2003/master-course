import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

type Stage = { completed: number; total: number; percent: number };
type Week = {
  week: string;
  status: string;
  status_label: string;
  prepared: boolean;
  strict_scope_audit_passed: boolean;
  prepared_input_id: string | null;
  prepared_input_sha256: string | null;
  scenario_id: string | null;
  job_id: string | null;
  worker_id: string | null;
  collected_sha256: string | null;
  audit_verified: boolean;
  error_code: string | null;
  error: string | null;
  warning_codes: string[];
  overnight: { next_service_date?: string; extra_slots?: number } | null;
};
type Progress = {
  schema_version: "monthly_campaign_progress_v1";
  campaign: string;
  generated_at_utc: string;
  git_sha: string | null;
  status: string;
  prepare_process: string;
  stages: { overall: Stage; prepare: Stage; solve: Stage; audit: Stage };
  campaign_stage: string | null;
  campaign_error: string | null;
  connection_status: string | null;
  failed_count: number;
  weeks: Week[];
  recent_log: string[];
  recent_errors: string[];
};

const campaignLabels: Record<string, string> = {
  NOT_STARTED: "未着手",
  WAITING: "次工程の開始待ち",
  RUNNING: "実行中",
  ERROR: "要対応",
  COMPLETED_DIAGNOSTIC: "診断処理完了",
};
const stageLabels: { key: keyof Progress["stages"]; label: string }[] = [
  { key: "overall", label: "全工程" },
  { key: "prepare", label: "入力準備" },
  { key: "solve", label: "計算" },
  { key: "audit", label: "成果物監査" },
];

function isStage(value: unknown): value is Stage {
  if (!value || typeof value !== "object") return false;
  const stage = value as Partial<Stage>;
  return (
    Number.isInteger(stage.completed) &&
    Number.isInteger(stage.total) &&
    Number.isInteger(stage.percent) &&
    stage.completed! >= 0 &&
    stage.total! > 0 &&
    stage.completed! <= stage.total! &&
    stage.percent! >= 0 &&
    stage.percent! <= 100
  );
}

function isProgress(value: unknown): value is Progress {
  if (!value || typeof value !== "object") return false;
  const data = value as Partial<Progress>;
  return (
    data.schema_version === "monthly_campaign_progress_v1" &&
    typeof data.campaign === "string" &&
    typeof data.generated_at_utc === "string" &&
    typeof data.status === "string" &&
    typeof data.prepare_process === "string" &&
    typeof data.failed_count === "number" &&
    !!data.stages &&
    stageLabels.every(({ key }) => isStage(data.stages?.[key])) &&
    Array.isArray(data.weeks) &&
    data.stages?.prepare.total === data.weeks.length &&
    data.stages?.overall.total === data.weeks.length * 3 &&
    Array.isArray(data.recent_log) &&
    Array.isArray(data.recent_errors) &&
    data.weeks.every((week) =>
      week && typeof week.week === "string" && typeof week.status === "string" &&
      typeof week.status_label === "string" && typeof week.prepared === "boolean" &&
      typeof week.audit_verified === "boolean",
    )
  );
}

async function readCampaignProgress(): Promise<Progress> {
  const response = await fetch("/campaign-progress.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`進捗記録を取得できません (HTTP ${response.status})`);
  const payload: unknown = await response.json();
  if (!isProgress(payload)) throw new Error("進捗記録の形式が一致しません");
  return payload;
}

function StageCard({ label, stage }: { label: string; stage: Stage }) {
  return (
    <div className="campaign-stage">
      <span>{label}</span>
      <strong>{stage.percent}%</strong>
      <progress value={stage.completed} max={stage.total} aria-label={`${label}の進捗`} />
      <small>{stage.completed} / {stage.total} 工程</small>
    </div>
  );
}

export default function CampaignProgress() {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, []);
  const progress = useQuery({
    queryKey: ["monthly-campaign-progress"],
    queryFn: readCampaignProgress,
    retry: false,
    refetchInterval: 5000,
  });
  const data = progress.data;
  const generated = data ? Date.parse(data.generated_at_utc) : NaN;
  const stale = !Number.isFinite(generated) || now - generated > 20_000;

  return (
    <section className="panel campaign-progress">
      <h2>渋24・月別12週の進捗</h2>
      <p className="subtle">
        各割合は完了した週・工程の件数です。実行中の1週について残り時間や内部探索の進捗率は推定しません。
      </p>
      {progress.isError && !data && (
        <p className="warning">進捗記録を表示できません。計算停止を意味しません。{String(progress.error)}</p>
      )}
      {data && (
        <>
          <div className="campaign-heading">
            <strong className={`campaign-status campaign-status-${data.status.toLowerCase()}`}>
              {campaignLabels[data.status] ?? data.status}
            </strong>
            <span>{data.campaign}</span>
            <small>固定コード {data.git_sha?.slice(0, 10) ?? "未記録"}</small>
          </div>
          {(stale || progress.isError) && (
            <p className="warning">
              進捗記録の更新が止まっています。最後の取得時点の値です。実行の生死はこの表示だけでは判断できません。
            </p>
          )}
          {data.campaign_error && <p className="error">全体の問題: {data.campaign_error}</p>}
          <div className="campaign-stages">
            {stageLabels.map(({ key, label }) => (
              <StageCard key={key} label={label} stage={data.stages[key]} />
            ))}
          </div>
          <p className="subtle">
            Prepareプロセス: {data.prepare_process} · 接続: {data.connection_status ?? "未記録"} ·
            エラー週: {data.failed_count} · 最終更新: {data.generated_at_utc}
          </p>
          <p className="subtle">
            「計算完了」と「成果物監査済み」は別です。全工程100%でも研究採用・大域最適性の証明にはなりません。
          </p>
          <div className="detail-table campaign-weeks">
            <table>
              <thead><tr>
                <th>対象週</th><th>状態</th><th>入力</th><th>計算</th><th>監査</th><th>配布先</th><th>詳しい記録</th>
              </tr></thead>
              <tbody>
                {data.weeks.map((week) => (
                  <tr key={week.week}>
                    <td>{week.week}</td>
                    <td><span className={`campaign-status campaign-status-${week.status.toLowerCase()}`}>
                      {week.status_label}
                    </span></td>
                    <td>{week.prepared ? "完了" : "—"}</td>
                    <td>{["COMPLETED", "AUDIT_FAILED"].includes(week.status) || week.audit_verified ? "完了" : "—"}</td>
                    <td>{week.audit_verified ? "確認済み" : "—"}</td>
                    <td>{week.worker_id ?? "—"}</td>
                    <td>
                      <details>
                        <summary>詳細</summary>
                        <dl className="campaign-details">
                          <dt>状態コード</dt><dd>{week.status}</dd>
                          <dt>入力監査</dt><dd>{week.strict_scope_audit_passed ? "通過" : "未通過・未実施"}</dd>
                          <dt>Prepared ID</dt><dd>{week.prepared_input_id ?? "未発行"}</dd>
                          <dt>入力 SHA-256</dt><dd>{week.prepared_input_sha256 ?? "未記録"}</dd>
                          <dt>シナリオ ID</dt><dd>{week.scenario_id ?? "未記録"}</dd>
                          <dt>ジョブ ID</dt><dd>{week.job_id ?? "未投入"}</dd>
                          <dt>成果物 SHA-256</dt><dd>{week.collected_sha256 ?? "未回収"}</dd>
                          <dt>翌朝の対象日</dt><dd>{week.overnight?.next_service_date ?? "未記録"}</dd>
                          <dt>翌朝の追加枠</dt><dd>{week.overnight?.extra_slots ?? "—"}</dd>
                          <dt>警告コード</dt><dd>{week.warning_codes?.join(", ") || "なし"}</dd>
                          <dt>エラーコード</dt><dd>{week.error_code ?? "なし"}</dd>
                          <dt>原因</dt><dd>{week.error ?? "記録なし"}</dd>
                        </dl>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(data.recent_errors.length > 0 || data.recent_log.length > 0) && (
            <details>
              <summary>直近のスクリプト記録</summary>
              {data.recent_errors.length > 0 && <pre className="error">{data.recent_errors.join("\n")}</pre>}
              <pre>{data.recent_log.join("\n")}</pre>
            </details>
          )}
        </>
      )}
    </section>
  );
}
