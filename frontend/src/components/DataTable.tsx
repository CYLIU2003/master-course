import { useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { api, display, type Page, type Row } from "../api";
import { ErrorBox, Pager } from "./common";
const tableNames: Record<string, string> = {
  timetable_rows: "時刻表",
  routes: "路線パターン",
  vehicle_templates: "車両テンプレート",
  depots: "営業所",
  vehicles: "車両",
  chargers: "充電器",
  stops: "停留所",
  trips: "トリップ",
  duties: "仕業",
  blocks: "ブロック",
};
const columns: Record<string, string[]> = {
  timetable_rows: [
    "trip_id",
    "route_id",
    "service_id",
    "departure",
    "arrival",
    "distance_km",
    "operator_id",
  ],
  routes: ["id", "name", "routeCode", "distanceKm"],
  vehicles: ["id", "modelName", "type", "depotId", "batteryKwh", "enabled"],
  vehicle_templates: ["id", "name", "type", "batteryKwh"],
  depots: ["id", "name"],
  stops: ["id", "name"],
};
const columnLabels: Record<string, string> = {
  id: "ID",
  name: "名称",
  trip_id: "便 ID",
  route_id: "系統 ID",
  service_id: "日区分",
  departure: "出発",
  arrival: "到着",
  distance_km: "距離 (km)",
  operator_id: "事業者 ID",
  routeCode: "系統名",
  distanceKm: "距離 (km)",
  type: "車種",
  depotId: "営業所",
  batteryCapacityKWh: "電池容量 (kWh)",
  batteryKwh: "電池容量 (kWh)",
  modelName: "車両モデル",
  enabled: "使用可",
};
export default function DataTable({
  id,
  fixed,
  selected,
  onSelection,
  onEdit,
}: {
  id: string;
  fixed?: string;
  selected?: string[];
  onSelection?: (ids: string[]) => void;
  onEdit?: (row: Row) => void;
}) {
  const [name, setName] = useState(fixed ?? "timetable_rows");
  const [offset, setOffset] = useState(0);
  const [service, setService] = useState("");
  const viewport = useRef<HTMLDivElement>(null);
  const data = useQuery({
    queryKey: ["table", id, name, offset, service],
    queryFn: ({ signal }) =>
      api<Page<Row>>(
        `/desktop/scenarios/${id}/tables/${name}?offset=${offset}&limit=250${service ? "&service_id=" + encodeURIComponent(service) : ""}`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });
  const rows = data.data?.items ?? [];
  const keys = [
    ...(onEdit ? ["__edit"] : []),
    ...(columns[name] ?? Object.keys(rows[0] ?? {}).slice(0, 8)),
  ];
  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => viewport.current,
    estimateSize: () => 42,
    overscan: 6,
  });
  function page(n: number) {
    setOffset(n);
    viewport.current?.scrollTo({ top: 0 });
  }
  return (
    <section className="data-panel">
      <div className="table-toolbar">
        <div>
          {fixed ? (
            <h3>{tableNames[name]}</h3>
          ) : (
            <select
              aria-label="データ種類"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                page(0);
              }}
            >
              {Object.entries(tableNames).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          )}
          {name === "timetable_rows" && (
            <select
              aria-label="運行日区分"
              value={service}
              onChange={(e) => {
                setService(e.target.value);
                page(0);
              }}
            >
              <option value="">すべての日区分</option>
              <option>WEEKDAY</option>
              <option>SAT</option>
              <option>SUN_HOL</option>
            </select>
          )}
        </div>
        <Pager
          offset={offset}
          total={data.data?.total ?? 0}
          size={250}
          set={page}
        />
      </div>
      <ErrorBox error={data.error} />
      <div className="table-status">
        {data.isFetching
          ? "読み込み中…"
          : `1ページ最大250件 · 表示中 ${rows.length.toLocaleString()} 件`}
      </div>
      <div
        className="table-scroll"
        ref={viewport}
        role="table"
        aria-label={tableNames[name]}
        aria-rowcount={data.data?.total ?? 0}
      >
        <div
          className="table-head"
          role="row"
          style={{
            minWidth: 140 * (keys.length + (onSelection ? 1 : 0)),
            gridTemplateColumns: `repeat(${keys.length + (onSelection ? 1 : 0)}, minmax(140px, 1fr))`,
          }}
        >
          {onSelection && <div role="columnheader">選択</div>}
          {keys.map((key) => (
            <div key={key} role="columnheader">
              {key === "__edit" ? "操作" : (columnLabels[key] ?? key)}
            </div>
          ))}
        </div>
        <div
          style={{
            height: virtual.getTotalSize(),
            position: "relative",
            minWidth: 140 * (keys.length + (onSelection ? 1 : 0)),
          }}
        >
          {virtual.getVirtualItems().map((item) => {
            const row = rows[item.index];
            const rowId = String(row.id ?? row.route_id ?? "");
            return (
              <div
                className="table-row"
                role="row"
                aria-rowindex={offset + item.index + 2}
                key={item.key}
                style={{
                  height: item.size,
                  transform: `translateY(${item.start}px)`,
                  gridTemplateColumns: `repeat(${keys.length + (onSelection ? 1 : 0)}, minmax(140px, 1fr))`,
                }}
              >
                {onSelection && (
                  <div role="cell">
                    <input
                      type="checkbox"
                      aria-label={`${display(row.name)}を選択`}
                      checked={selected?.includes(rowId) ?? false}
                      disabled={data.isPlaceholderData || !rowId}
                      onChange={(e) =>
                        onSelection(
                          e.target.checked
                            ? [...(selected ?? []), rowId]
                            : (selected ?? []).filter(
                                (value) => value !== rowId,
                              ),
                        )
                      }
                    />
                  </div>
                )}
                {keys.map((key) => (
                  <div role="cell" key={key} title={display(row[key])}>
                    {key === "__edit" ? (
                      <button
                        type="button"
                        disabled={data.isPlaceholderData}
                        onClick={() => onEdit?.(row)}
                      >
                        編集
                      </button>
                    ) : (
                      display(row[key])
                    )}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
        {!data.isPending && !rows.length && (
          <p className="empty">該当するデータはありません。</p>
        )}
      </div>
    </section>
  );
}
