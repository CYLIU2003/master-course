import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  display,
  record,
  type Overview,
  type Page,
  type Row,
} from "../api";
import { ErrorBox, Pager } from "./common";

const names: Record<string, string> = {
  vehicle_gantt_rows: "車両ダイヤ（運行・待機・充電）",
  vehicle_soc_kwh_by_vehicle_slot: "車両SOC（kWh）",
  bess_soc_kwh_by_depot_slot: "BESS残量（kWh）",
  grid_to_bus_kwh_by_depot_slot: "系統→車両（kWh）",
  pv_to_bus_kwh_by_depot_slot: "PV→車両（kWh）",
  bess_to_bus_kwh_by_depot_slot: "BESS→車両（kWh）",
  pv_to_bess_kwh_by_depot_slot: "PV→BESS（kWh）",
  grid_to_bess_kwh_by_depot_slot: "系統→BESS（kWh）",
  pv_curtail_kwh_by_depot_slot: "PV抑制（kWh）",
  charging_schedule: "充電スケジュール",
  daily_cost_ledger: "日別費用明細",
  vehicle_cost_ledger: "車両別費用明細",
};
export function CostBars({ values }: { values: Row }) {
  const entries = Object.entries(values).filter(
    ([key, value]) =>
      typeof value === "number" &&
      Number.isFinite(value) &&
      key.endsWith("cost") &&
      key !== "total_cost",
  );
  const max = Math.max(
    1,
    ...entries.map(([, value]) => Math.abs(Number(value))),
  );
  return (
    <div className="cost-bars">
      {entries.map(([key, value]) => (
        <div key={key}>
          <span>{key}</span>
          <div>
            <i style={{ width: `${(Math.abs(Number(value)) / max) * 100}%` }} />
          </div>
          <strong>
            {Number(value).toLocaleString("ja-JP", {
              maximumFractionDigits: 2,
            })}{" "}
            円
          </strong>
        </div>
      ))}
    </div>
  );
}
export default function ResultDetails({
  id,
  data,
}: {
  id: string;
  data: Overview;
}) {
  const simulation = useQuery({
    queryKey: ["simulation-summary", id],
    queryFn: () =>
      api<{ available: boolean; source: string | null; values: Row }>(
        `/desktop/scenarios/${id}/simulation-summary`,
      ),
  });
  const artifacts = useQuery({
    queryKey: ["result-artifacts", id],
    enabled: data.result.available,
    queryFn: () =>
      api<{
        directory: string | null;
        items: { name: string; bytes: number }[];
        truncated: boolean;
      }>(`/desktop/scenarios/${id}/artifacts`),
  });
  const [name, setName] = useState("vehicle_soc_kwh_by_vehicle_slot");
  const [owner, setOwner] = useState("");
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["result-data", id, name, owner, offset],
    enabled: data.result.available,
    queryFn: () =>
      api<Page<Row> & { owners: string[]; source: string; scope: string }>(
        `/desktop/scenarios/${id}/result-data/${name}?owner=${encodeURIComponent(owner)}&offset=${offset}&limit=250`,
      ),
  });
  const points = (query.data?.items ?? [])
    .filter(
      (row) =>
        typeof row.value === "number" && typeof row.slot_index === "number",
    )
    .sort((a, b) => Number(a.slot_index) - Number(b.slot_index));
  const lowX = Math.min(...points.map((row) => Number(row.slot_index))),
    highX = Math.max(...points.map((row) => Number(row.slot_index)));
  const lowY = Math.min(0, ...points.map((row) => Number(row.value))),
    highY = Math.max(1, ...points.map((row) => Number(row.value)));
  const path = points
    .map(
      (row, i) =>
        `${i ? "L" : "M"}${55 + ((Number(row.slot_index) - lowX) / Math.max(highX - lowX, 1)) * 790},${225 - ((Number(row.value) - lowY) / (highY - lowY)) * 185}`,
    )
    .join(" ");
  const keys = Object.keys(query.data?.items[0] ?? {});
  return (
    <>
      <section className="panel">
        <h2>保存されたレポート・図表</h2>
        <ErrorBox error={artifacts.error} />
        <p className="subtle">
          既存のExcel・CSV・PDF・図を取得できます。元の成果物をそのまま扱います（1ファイル100
          MBまで）。
        </p>
        <details>
          <summary>
            出力ファイル · {artifacts.data?.items.length ?? 0} 件
          </summary>
          <p className="subtle">{artifacts.data?.directory ?? "出力先なし"}</p>
          <ul className="artifact-list">
            {artifacts.data?.items.map((file) => (
              <li key={file.name}>
                {file.bytes <= 100_000_000 ? (
                  <a
                    download
                    href={`/api/desktop/scenarios/${id}/artifacts/file?name=${encodeURIComponent(file.name)}`}
                  >
                    {file.name}
                  </a>
                ) : (
                  <span>{file.name}（取得上限を超えています）</span>
                )}
                <small>
                  {(file.bytes / 1024).toLocaleString("ja-JP", {
                    maximumFractionDigits: 1,
                  })}{" "}
                  KB
                </small>
              </li>
            ))}
          </ul>
          {artifacts.data?.truncated && (
            <p>
              先頭250ファイルを表示しています。残りは上記の出力フォルダーで確認できます。
            </p>
          )}
        </details>
      </section>
      <section className="panel">
        <h2>シミュレーションの結果</h2>
        <ErrorBox error={simulation.error} />
        {simulation.data?.available ? (
          <>
            <p className="subtle">
              保存された仕業のシミュレーション値です。最適化後の最終会計や研究採用とは別に確認します。
            </p>
            <div className="metrics">
              {[
                ["total_operating_cost", "運行費用（円）"],
                ["total_energy_cost", "エネルギー費用（円）"],
                ["total_co2_kg", "CO₂排出量（kg）"],
                ["served_task_ratio", "運行充足率"],
              ].map(([key, label]) => (
                <article key={key}>
                  <span>{label}</span>
                  <strong>{display(simulation.data.values[key])}</strong>
                </article>
              ))}
            </div>
            <details>
              <summary>費用の基準と検証値</summary>
              <pre>{JSON.stringify(simulation.data.values, null, 2)}</pre>
            </details>
          </>
        ) : (
          <p className="subtle">保存済みのシミュレーション結果はありません。</p>
        )}
      </section>
      <section className="panel">
        <h2>最適化計画の費用内訳</h2>
        <p className="subtle">
          保存された計画の費用項目です。最終会計は概要に表示された出典を確認してください。
        </p>
        <CostBars values={record(data.result.values.cost_breakdown)} />
      </section>
      <section className="panel">
        <div className="section-title">
          <h2>残量・電力・費用明細</h2>
          <span className="badge">保存されたソルバー計画</span>
        </div>
        <p className="subtle">
          計画値の表示です。実行済みローリング会計や物理検証の合格を意味しません。電源別フローは営業所・時間枠単位で表示します。
        </p>
        <div className="table-toolbar">
          <select
            aria-label="結果データ"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setOwner("");
              setOffset(0);
            }}
          >
            {Object.entries(names).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          {!!query.data?.owners.length && (
            <select
              aria-label="車両・営業所"
              value={owner}
              onChange={(e) => {
                setOwner(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">車両・営業所を選択</option>
              {query.data.owners.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          )}
          <Pager
            offset={offset}
            total={query.data?.total ?? 0}
            size={250}
            set={setOffset}
          />
        </div>
        <ErrorBox error={query.error} />
        {name === "vehicle_gantt_rows" && (
          <VehicleTimeline items={query.data?.items ?? []} />
        )}
        {points.length > 0 && (
          <svg
            className="series-chart"
            role="img"
            aria-label={`${names[name]} · ${owner}`}
            viewBox="0 0 900 270"
          >
            <line x1="55" y1="225" x2="845" y2="225" stroke="#a0b4ac" />
            <line x1="55" y1="40" x2="55" y2="225" stroke="#a0b4ac" />
            <text x="50" y="28">
              {highY.toFixed(1)} kWh
            </text>
            <text x="10" y="225">
              {lowY}
            </text>
            <text x="55" y="249">
              {lowX}
            </text>
            <text x="820" y="249">
              {highX}
            </text>
            <text x="400" y="263">
              時間枠インデックス
            </text>
            <path d={path} fill="none" stroke="#2c755b" strokeWidth="2.5" />
          </svg>
        )}
        <div className="detail-table">
          <table>
            <thead>
              <tr>
                {keys.map((key) => (
                  <th key={key}>{key}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {query.data?.items.map((row, i) => (
                <tr key={i}>
                  {keys.map((key) => (
                    <td key={key}>{display(row[key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!query.isFetching && !query.data?.items.length && (
          <p className="empty">
            {owner || !query.data?.owners.length
              ? "該当する保存済みデータはありません。"
              : "車両または営業所を選ぶと推移を表示します。"}
          </p>
        )}
        <small>出典: {query.data?.source ?? "未取得"} · 1ページ最大250件</small>
      </section>
    </>
  );
}

function clockMinutes(value: unknown): number | null {
  if (typeof value !== "string" || !/^\d+:\d{2}(:\d{2})?$/.test(value))
    return null;
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}
export function VehicleTimeline({ items }: { items: Row[] }) {
  const events = items
    .map((row) => ({
      row,
      start: clockMinutes(row.start_time ?? row.departure_time),
      end: clockMinutes(row.end_time ?? row.arrival_time),
    }))
    .filter(
      (event): event is { row: Row; start: number; end: number } =>
        event.start !== null && event.end !== null && event.end >= event.start,
    );
  if (!events.length) return null;
  const vehicles = [
    ...new Set(events.map((event) => String(event.row.vehicle_id))),
  ];
  const start = Math.min(...events.map((event) => event.start)),
    end = Math.max(...events.map((event) => event.end));
  const label = (minutes: number) =>
    `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
  return (
    <div className="timeline-scroll">
      <svg
        width="1100"
        height={70 + vehicles.length * 38}
        viewBox={`0 0 1100 ${70 + vehicles.length * 38}`}
        role="img"
        aria-label="保存された車両ダイヤ"
      >
        <text x="190" y="18">
          {label(start)}
        </text>
        <text x="1010" y="18">
          {label(end)}
        </text>
        {vehicles.map((vehicle, index) => (
          <g key={vehicle}>
            <text x="10" y={48 + index * 38}>
              {vehicle}
            </text>
            <line
              x1="190"
              x2="1060"
              y1={53 + index * 38}
              y2={53 + index * 38}
              stroke="#d7e2dc"
            />
          </g>
        ))}
        {events.map(({ row, start: a, end: b }, index) => {
          const state = String(row.state ?? row.event_type ?? "unknown");
          const color = /charg/.test(state)
            ? "#d39335"
            : /trip|service|running/.test(state)
              ? "#347a61"
              : /deadhead/.test(state)
                ? "#7086af"
                : "#b3c2bb";
          return (
            <rect
              key={index}
              x={190 + ((a - start) / Math.max(1, end - start)) * 870}
              y={32 + vehicles.indexOf(String(row.vehicle_id)) * 38}
              width={Math.max(2, ((b - a) / Math.max(1, end - start)) * 870)}
              height="24"
              rx="3"
              fill={color}
            >
              <title>
                {String(row.vehicle_id)} · {state} · {label(a)}〜{label(b)} ·{" "}
                {String(row.trip_id ?? row.route_id ?? "")}
              </title>
            </rect>
          );
        })}
      </svg>
      <p className="subtle">
        緑: 運行 / 黄: 充電 / 青: 回送 / 灰:
        待機など。表示中の最大250イベントを描画します。
      </p>
    </div>
  );
}
