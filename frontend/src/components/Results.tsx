import { ArrowRight } from "lucide-react";
import { display, gate, record, strings, type Overview } from "../api";
export default function Results({ data }: { data: Overview }) {
  const values = data.result.values;
  const validity = record(values.solution_validity);
  const stats = [
    ["timetableRowCount", "時刻表"],
    ["routeCount", "路線パターン"],
    ["tripCount", "トリップ"],
    ["dutyCount", "仕業"],
  ];
  return (
    <>
      <div className="metrics">
        {stats.map(([key, label]) => (
          <article key={key}>
            <span>{label}</span>
            <strong>
              {typeof data.stats[key] === "number"
                ? Number(data.stats[key]).toLocaleString()
                : "—"}
            </strong>
            <small>保存済み入力の集計</small>
          </article>
        ))}
      </div>
      <section className="panel">
        <div className="section-title">
          <h2>最適化結果の確認</h2>
          <span className="badge">
            {data.result.available
              ? display(values.result_class)
              : "保存済み結果なし"}
          </span>
        </div>
        <p className="subtle">
          実行終了と研究上の採用は別の判定です。未確認の項目は合格として扱いません。
        </p>
        <div className="gates">
          {[
            ["ソルバー", display(values.solver_status)],
            [
              "物理検証",
              gate(
                validity.physical_schedule_validation_status ??
                  validity.physical_validation_status,
              ),
            ],
            ["研究採用", gate(validity.research_acceptance_status)],
            ["研究用コスト", gate(validity.research_kpi_eligible)],
          ].map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        <div className="cost-line">
          <div>
            <span>最終会計（JPY）</span>
            <strong>
              {typeof values.final_accounting_total_cost_jpy === "number"
                ? values.final_accounting_total_cost_jpy.toLocaleString(
                    "ja-JP",
                    { maximumFractionDigits: 6 },
                  )
                : "未確定"}
            </strong>
          </div>
          <p>出典: {display(values.final_accounting_source)}</p>
        </div>
        {strings(validity.blocking_reasons)
          .concat(strings(validity.research_blocking_reasons))
          .map((reason, i) => (
            <p className="warning" key={i}>
              {reason}
            </p>
          ))}
        <details>
          <summary>保存された検証値・出典を確認</summary>
          <pre>{JSON.stringify(values, null, 2)}</pre>
        </details>
      </section>
      <section className="panel next">
        <div>
          <h2>入力条件を確認して、診断へ</h2>
          <p>
            「運行・計算設定」で対象範囲と日付を設定し、「実行」へ進めます。既存の結果を残す場合は、先にシナリオを複製してください。
          </p>
        </div>
        <ArrowRight />
      </section>
    </>
  );
}
