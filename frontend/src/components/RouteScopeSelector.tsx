import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Page, type Row } from "../api";
import { ErrorBox } from "./common";

type RouteOption = {
  id: string;
  name: string;
  family: string;
  familyLabel: string;
  direction: string;
  depot: string;
};

const PAGE_SIZE = 250;
const MAX_ROUTES = 10_000;

function routeText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function toRoute(row: Row): RouteOption {
  const id = routeText(row.id);
  if (!id) throw new Error("路線パターンにIDがありません。入力データを確認してください。");
  const code = routeText(row.routeFamilyCode) || routeText(row.routeCode);
  const family = code ? code.normalize("NFKC") : "系統未設定";
  const start = routeText(row.startStop);
  const end = routeText(row.endStop);
  return {
    id,
    name: routeText(row.routeLabel) || routeText(row.name) || [start, end].filter(Boolean).join(" → ") || id,
    family,
    familyLabel: routeText(row.routeFamilyLabel) || code || "系統未設定",
    direction: routeText(row.canonicalDirection) || routeText(row.direction),
    depot: routeText(row.depotId),
  };
}

async function loadRoutes(id: string, signal: AbortSignal): Promise<RouteOption[]> {
  const path = `/desktop/scenarios/${encodeURIComponent(id)}/tables/routes`;
  const first = await api<Page<Row>>(`${path}?offset=0&limit=${PAGE_SIZE}`, { signal });
  if (first.offset !== 0 || first.total < 0)
    throw new Error("路線一覧の先頭ページが不正です。再読み込みしてください。");
  if (first.total > MAX_ROUTES) throw new Error(`路線が${MAX_ROUTES}件を超えます。入力を分割して確認してください。`);
  const rows = [...first.items];
  for (let offset = PAGE_SIZE; offset < first.total; offset += PAGE_SIZE) {
    const page = await api<Page<Row>>(`${path}?offset=${offset}&limit=${PAGE_SIZE}`, { signal });
    if (page.total !== first.total || page.offset !== offset)
      throw new Error("路線一覧が読込中に変わりました。再読み込みしてください。");
    rows.push(...page.items);
  }
  if (rows.length !== first.total) throw new Error("路線一覧が途中で欠けました。再読み込みしてください。");
  const routes = rows.map(toRoute);
  if (new Set(routes.map((route) => route.id)).size !== routes.length)
    throw new Error("路線パターンIDが重複しています。入力データを確認してください。");
  return routes;
}

export default function RouteScopeSelector({
  id, selected, onSelection,
}: {
  id: string;
  selected: string[];
  onSelection: (ids: string[]) => void;
}) {
  const [filter, setFilter] = useState("");
  const catalog = useQuery({
    queryKey: ["route-catalog", id],
    queryFn: ({ signal }) => loadRoutes(id, signal),
  });
  const routes = catalog.data ?? [];
  const groups = useMemo(() => {
    const grouped = new Map<string, { label: string; routes: RouteOption[] }>();
    for (const route of routes) {
      const current = grouped.get(route.family) ?? { label: route.familyLabel, routes: [] };
      current.routes.push(route);
      grouped.set(route.family, current);
    }
    return [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right, "ja"));
  }, [routes]);
  const known = new Set(routes.map((route) => route.id));
  const unknown = catalog.isSuccess ? selected.filter((routeId) => !known.has(routeId)) : [];
  const selectedSet = new Set(selected);
  const needle = filter.trim().normalize("NFKC").toLocaleLowerCase();

  function toggle(ids: string[], checked: boolean) {
    const next = new Set(selected);
    for (const routeId of ids) checked ? next.add(routeId) : next.delete(routeId);
    onSelection([...next]);
  }

  return (
    <section className="route-scope" aria-label="計算対象の系統と路線パターン">
      <div className="route-scope-toolbar">
        <div>
          <h3>計算対象の系統・路線パターン</h3>
          <p className="subtle">系統全体を選ぶか、方向・経由地ごとのパターンを選べます。保存後に入力準備をやり直してください。</p>
        </div>
        <label>系統・行先を検索
          <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="例：渋24、成城学園前" />
        </label>
      </div>
      <ErrorBox error={catalog.error} />
      {catalog.isPending && <p>路線一覧を読み込み中…</p>}
      {catalog.isSuccess && <p>{selected.filter((routeId) => known.has(routeId)).length} / {routes.length} パターンを選択中</p>}
      {unknown.length > 0 && <p className="warning">現行の路線一覧にない選択IDが{unknown.length}件あります。入力とシナリオの出典を確認してください。</p>}
      {catalog.isSuccess && !routes.length && <p className="warning">このシナリオに路線がありません。固定データの取込み後に選択してください。</p>}
      <div className="route-scope-groups">
        {groups.map(([family, group]) => {
          const visible = group.routes.filter((route) =>
            !needle || [family, group.label, route.name, route.id, route.direction, route.depot]
              .some((value) => value.normalize("NFKC").toLocaleLowerCase().includes(needle)));
          if (!visible.length) return null;
          const ids = group.routes.map((route) => route.id);
          const checked = ids.every((routeId) => selectedSet.has(routeId));
          return <details key={family} className="route-scope-group" open={Boolean(needle)}>
            <summary>{group.label} <small>{ids.filter((routeId) => selectedSet.has(routeId)).length} / {ids.length} パターン</small></summary>
            <label className="route-scope-all">
              <input type="checkbox" aria-label={`${group.label}の全パターン`} checked={checked}
                onChange={(event) => toggle(ids, event.target.checked)} />
              この系統の全パターン
            </label>
            <button type="button" className="route-scope-only" disabled={unknown.length > 0}
              onClick={() => onSelection(ids)}>
              この系統だけを対象にする
            </button>
            {visible.map((route) => <label key={route.id} className="route-scope-pattern">
              <input type="checkbox" aria-label={`${route.name}を計算対象にする`}
                checked={selectedSet.has(route.id)} onChange={(event) => toggle([route.id], event.target.checked)} />
              <span>{route.name}<small>{[route.direction, route.depot, route.id].filter(Boolean).join(" · ")}</small></span>
            </label>)}
          </details>;
        })}
      </div>
    </section>
  );
}
