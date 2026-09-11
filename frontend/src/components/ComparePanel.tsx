import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  display,
  record,
  type Overview,
  type Page,
  type Scenario,
} from "../api";
import { ErrorBox, Pager } from "./common";

export default function ComparePanel({ data }: { data: Overview }) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState("");
  const list = useQuery({
    queryKey: ["scenarios", "compare", search, offset],
    queryFn: () =>
      api<Page<Scenario>>(
        `/desktop/scenarios?q=${encodeURIComponent(search)}&offset=${offset}&limit=50`,
      ),
  });
  const comparison = useQuery({
    queryKey: ["overview", selected],
    enabled: !!selected,
    queryFn: () => api<Overview>(`/desktop/scenarios/${selected}`),
  });
  const other = comparison.data;
  const metrics = [
    "solver_status",
    "objective_value",
    "final_accounting_total_cost_jpy",
    "final_accounting_source",
    "mip_gap",
    "solve_time_seconds",
    "summary.trip_count_served",
    "summary.trip_count_unserved",
    "summary.vehicle_count_used",
    "simulation_summary.total_co2_kg",
    "simulation_summary.peak_demand_kw",
  ];
  const changes = other
    ? [
        ...new Set([
          ...Object.keys(data.settings),
          ...Object.keys(other.settings),
        ]),
      ].filter(
        (key) =>
          JSON.stringify(data.settings[key]) !==
          JSON.stringify(other.settings[key]),
      )
    : [];
  return (
    <section className="panel">
      <h2>シナリオを比較する</h2>
      <p className="subtle">
        現在のシナリオをAとして、保存された別の結果をBに選びます。差分だけで因果効果とは判断しません。
      </p>
      <div className="table-toolbar">
        <input
          placeholder="比較するシナリオを検索"
          aria-label="比較シナリオ検索"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
          }}
        />
        <select
          aria-label="比較対象B"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
        >
          <option value="">Bを選択</option>
          {list.data?.items
            .filter((row) => row.id !== data.meta.id)
            .map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
        </select>
        <Pager
          offset={offset}
          total={list.data?.total ?? 0}
          size={50}
          set={setOffset}
        />
      </div>
      <ErrorBox error={list.error ?? comparison.error} />
      {other && (
        <>
          <div className="detail-table">
            <table>
              <thead>
                <tr>
                  <th>項目</th>
                  <th>A · {data.meta.name}</th>
                  <th>B · {other.meta.name}</th>
                  <th>B − A</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map((key) => {
                  const a = data.result.values[key],
                    b = other.result.values[key];
                  return (
                    <tr key={key}>
                      <th>{key}</th>
                      <td>{display(a)}</td>
                      <td>{display(b)}</td>
                      <td>
                        {typeof a === "number" && typeof b === "number"
                          ? (b - a).toLocaleString("ja-JP", {
                              maximumFractionDigits: 6,
                            })
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <h3>研究採用の判定</h3>
          <p>
            A:{" "}
            {display(
              record(data.result.values.solution_validity)
                .research_acceptance_status,
            )}{" "}
            / B:{" "}
            {display(
              record(other.result.values.solution_validity)
                .research_acceptance_status,
            )}
          </p>
          <details open>
            <summary>異なる入力条件 · {changes.length} 項目</summary>
            <div className="detail-table">
              <table>
                <thead>
                  <tr>
                    <th>設定</th>
                    <th>A</th>
                    <th>B</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((key) => (
                    <tr key={key}>
                      <th>{key}</th>
                      <td>{display(data.settings[key])}</td>
                      <td>{display(other.settings[key])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>営業所・路線選択も別に確認してください。</p>
            <pre>
              {JSON.stringify({ A: data.scope, B: other.scope }, null, 2)}
            </pre>
          </details>
        </>
      )}
    </section>
  );
}
