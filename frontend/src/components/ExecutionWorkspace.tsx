import { useState } from "react";
import type { Overview } from "../api";
import RunPanel from "./RunPanel";
import ExecutionProgress from "./ExecutionProgress";
import ClusterPanel from "./ClusterPanel";
import LabConsole from "./LabConsole";

/** Reuse preparation and submission contracts; navigation never submits a job. */
export default function ExecutionWorkspace({ id, data, revision = 0, blocked = false, onChoose, onNavigate, onSelect }: {
  id?: string; data?: Overview; revision?: number; blocked?: boolean;
  onChoose: () => void; onNavigate: (page: string) => void; onSelect: (id: string) => void;
}) {
  const [source, setSource] = useState<"scenario" | "lab">("scenario");
  const [showJobs, setShowJobs] = useState(false);
  return <>
    <section className="panel" aria-label="実行対象の選択">
      <h2>実行開始・進捗</h2>
      <p>対象を選び、保存した設定を確認してから入力準備・計算開始へ進みます。</p>
      <p>操作先：{window.location.origin} ／ 対象：<strong>{data?.meta.name ?? "シナリオ未選択"}</strong></p>
      <div className="actions">
        <button aria-pressed={source === "scenario"} onClick={() => setSource("scenario")}>シナリオから開始</button>
        <button aria-pressed={source === "lab"} onClick={() => setSource("lab")}>研究室の依頼から選ぶ</button>
        <button disabled={blocked} onClick={onChoose}>実行対象のシナリオを選ぶ</button>
        <button disabled={!id} onClick={() => onNavigate("settings")}>設定を確認・保存</button>
        <button disabled={!id} onClick={() => onNavigate("periods")}>登録した代表週・期間を確認</button>
      </div>
      {blocked && <p role="alert">未保存の変更があります。設定画面で保存または元に戻すと開始できます。</p>}
    </section>
    {source === "scenario" && (id && data ? <>
      <p className="warning">下の開始ボタンは「保存された条件」の対象期間を実行します。登録済みの12代表週を一括開始するボタンではありません。進行中の週は下の進捗で確認できます。</p>
      <RunPanel id={id} data={data} revision={revision} blocked={blocked} />
    </> : <p>「実行対象のシナリオを選ぶ」から選択してください。研究室の依頼はシナリオ未選択でも確認できます。</p>)}
    {source === "lab" && <LabConsole intakeOnly readOnly={blocked} onSelectScenario={scenario => {
      onSelect(scenario); setSource("scenario");
    }} />}
    <LabConsole resultsOnly scenarioId={id} />
    <p className="subtle">月別比較は回収後の再検算・図表復旧を含みます。下の実行記録は原試行の失敗もそのまま残すため、件数・状態が異なる場合があります。</p>
    <ExecutionProgress scenarioId={id} />
    <section className="panel">
      <h2>ジョブ・PC・待機理由の詳細</h2>
      <p>入力準備、配布、配車・充電求解、毎時運用、回収・検算を区別します。割合は保存済み工程の割合で、残り時間や最適性の証明ではありません。</p>
      <button aria-expanded={showJobs} onClick={() => setShowJobs(!showJobs)}>{showJobs ? "ジョブ一覧を閉じる" : "ジョブ一覧と機器・エラー詳細を開く"}</button>
    </section>
    {showJobs && <ClusterPanel scenarioId={id} />}
  </>;
}
