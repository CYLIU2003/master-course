import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox } from "./common";

type Stop = { id: string; name: string; lat: number | null; lon: number | null; coordinateSource?: string };
type Pattern = {
  id: string; name: string; routeCode: string; routeVariantType: string;
  direction: string; startStop: string; endStop: string; depotIds: string[];
  stopCount: number; stops: Stop[]; distanceKm: number | null;
  storedDistanceKm?: number | null;
  distanceSource: string; tripCount: number | null; source: string | null;
  tripCountsByDayType?: Record<string, number> | null;
  firstDepartureByDayType?: Record<string, string> | null;
  lastArrivalByDayType?: Record<string, string> | null;
  odptPatternId?: string | null;
  classificationConfidence?: number | null;
  classificationSource?: string | null;
  officialDepotReference?: { depotId: string; sourceUrl: string; sourceDate: string };
  officialDepotAmbiguity?: { reason: string; sourceUrls: string[] };
  officialServiceNotice?: { message: string; sourceUrl: string };
};
type Catalog = { depots: { id: string; name: string }[]; routes: Pattern[]; builtAt?: string | null; sourceSnapshotId?: string | null; officialReferenceCapturedAt?: string; officialReferenceStatus?: string };
const variantNames: Record<string, string> = {
  main: "本線", main_outbound: "本線・往路", main_inbound: "本線・復路",
  short_turn: "区間便", branch: "枝線", depot_out: "出庫便", depot_in: "入庫便",
  unknown: "未判定",
};
const directionNames: Record<string, string> = {
  outbound: "往路", inbound: "復路", circular: "循環", unknown: "未判定",
};

export default function RouteBrowser({ id, source = "scenario", selectedDepots, selectedRoutes, onScopeChange, onEdit }: {
  id: string;
  source?: "scenario" | "odpt" | "full";
  selectedDepots?: string[];
  selectedRoutes?: string[];
  onScopeChange?: (depots: string[], routes: string[]) => void;
  onEdit?: (routeId: string) => void;
}) {
  const [browseDepots, setBrowseDepots] = useState<string[]>([]);
  useEffect(() => setBrowseDepots([]), [id, source]);
  const data = useQuery({
    queryKey: ["route-catalog", id, source],
    queryFn: ({ signal }) => api<Catalog>(source === "odpt" ? "/desktop/route-catalog/odpt" : source === "full" ? "/desktop/route-catalog/full" : `/desktop/scenarios/${id}/route-catalog`, { signal }),
  });
  const catalog = data.data;
  const unassignedId = "__unassigned__";
  const hasDepotReference = (route: Pattern) => source === "odpt" && !!route.officialDepotReference;
  const depots = catalog ? [...catalog.depots, ...(!onScopeChange && catalog.routes.some((route) => !route.depotIds.length && !hasDepotReference(route)) ? [{ id: unassignedId, name: "所管未確認" }] : [])] : [];
  const belongsToDepot = (route: Pattern, depotId: string) => depotId === unassignedId
    ? !route.depotIds.length && !hasDepotReference(route)
    : route.depotIds.includes(depotId) || (hasDepotReference(route) && route.officialDepotReference?.depotId === depotId);
  const checkedDepots = onScopeChange ? (selectedDepots ?? []) : browseDepots;
  const checkedRoutes = selectedRoutes ?? [];
  const unassigned = catalog?.routes.filter((route) => !route.depotIds.length && !hasDepotReference(route)) ?? [];
  const referenceCount = catalog?.routes.filter((route) => !route.depotIds.length && hasDepotReference(route)).length ?? 0;

  function toggleDepot(depotId: string, checked: boolean) {
    const nextDepots = checked
      ? [...checkedDepots, depotId]
      : checkedDepots.filter((id) => id !== depotId);
    if (!onScopeChange) {
      setBrowseDepots(nextDepots);
      return;
    }
    const visibleIds = new Set(
      catalog?.routes.filter((route) => nextDepots.some((id) => belongsToDepot(route, id))).map((route) => route.id) ?? [],
    );
    const nextRoutes = checked
      ? [...new Set([...checkedRoutes, ...visibleIds])]
      : checkedRoutes.filter((id) => visibleIds.has(id));
    onScopeChange(nextDepots, nextRoutes);
  }

  function toggleRoutes(routeIds: string[], checked: boolean) {
    onScopeChange?.(
      checkedDepots,
      checked
        ? [...new Set([...checkedRoutes, ...routeIds])]
        : checkedRoutes.filter((id) => !routeIds.includes(id)),
    );
  }

  return (
    <section className="route-browser">
      <h3>営業所から路線を探す</h3>
      <p className="subtle">営業所にチェックを入れると、その所管系統を表示します。系統を開くと運行パターン、さらに停留所順と距離を確認できます。{onScopeChange && "対象範囲では営業所のチェックと同時に所属パターンも一括選択します。"}</p>
      {source === "odpt" && <p className="subtle">保存済みODPTスナップショットの全域路線です。ODPTに所管がない一部路線は、日付付き公式資料の参考所管で営業所別に表示します。パターン種別は保存済みの手動分類で、区間便・枝線の区別は未検証です。現在の運行を保証する情報ではありません。</p>}
      {source === "full" && <p className="subtle">別の保存済みGTFSスナップショットです。ODPTとは収録範囲・分類が異なり、現在の運行を保証する情報ではありません。</p>}
      <ErrorBox error={data.error} />
      {data.isPending && <p>路線情報を読み込み中…</p>}
      {catalog && <>
        {catalog.builtAt && <p className="subtle">データ構築日時: {catalog.builtAt}</p>}
        {catalog.sourceSnapshotId && <p className="subtle">元データのスナップショットID: {catalog.sourceSnapshotId}</p>}
        {source === "odpt" && catalog.officialReferenceCapturedAt && <p className="subtle">公式参考資料の確認日: {catalog.officialReferenceCapturedAt}。資料の日付は路線ごとに異なります。</p>}
        {source === "odpt" && catalog.officialReferenceStatus === "snapshot_mismatch" && <p className="route-warning">ODPTスナップショットが参考所管の照合対象と異なるため、参考所管を表示していません。</p>}
        {source !== "full" && catalog.routes.some((route) => typeof route.storedDistanceKm === "number" && route.storedDistanceKm <= 0) && <p className="route-warning">保存済み路線マスタに距離0のパターンが {catalog.routes.filter((route) => typeof route.storedDistanceKm === "number" && route.storedDistanceKm <= 0).length} 件あります。表示用の距離は最適化入力へ自動反映しません。</p>}
        <div className="route-depot-list">
          {depots.map((depot) => {
            const count = catalog.routes.filter((route) => belongsToDepot(route, depot.id)).length;
            return <label key={depot.id}>
              <input type="checkbox" checked={checkedDepots.includes(depot.id)} onChange={(event) => toggleDepot(depot.id, event.target.checked)} />
              {depot.name} <small>{count}パターン</small>
            </label>;
          })}
        </div>
        {!checkedDepots.length && <p className="empty">営業所を選ぶと路線が現れます。</p>}
        {checkedDepots.map((depotId) => {
          const depot = depots.find((item) => item.id === depotId);
          if (!depot) return null;
          const depotRoutes = catalog.routes.filter((route) => belongsToDepot(route, depotId));
          const families = new Map<string, Pattern[]>();
          for (const route of depotRoutes) {
            const family = route.routeCode || "系統未確認";
            families.set(family, [...(families.get(family) ?? []), route]);
          }
          return <details key={depotId} className="route-depot">
            <summary>{depot.name} · {families.size}系統 / {depotRoutes.length}パターン</summary>
            {!depotRoutes.length && <p className="empty">紐付く路線がありません。</p>}
            {[...families].sort(([a], [b]) => a.localeCompare(b, "ja")).map(([family, patterns]) =>
              <details key={family} className="route-family">
                <summary>{onScopeChange && <input type="checkbox" aria-label={`${depot.name} ${family}を選択`} checked={patterns.every((route) => checkedRoutes.includes(route.id))} onClick={(event) => event.stopPropagation()} onChange={(event) => toggleRoutes(patterns.map((route) => route.id), event.target.checked)} />}{family} · {patterns.length}パターン{patterns.some(hasDepotReference) ? "（公式参考所管）" : ""}</summary>
                {patterns.map((route) => <details key={route.id} className="route-pattern">
                  <summary>
                    {onScopeChange && <input type="checkbox" aria-label={`${route.name}を選択`} checked={checkedRoutes.includes(route.id)} onClick={(event) => event.stopPropagation()} onChange={(event) => toggleRoutes([route.id], event.target.checked)} />}
                    {route.startStop} → {route.endStop} · {variantNames[route.routeVariantType] ?? route.routeVariantType}{route.classificationSource === "manual_override" ? "（保存分類）" : ""} · {directionNames[route.direction] ?? route.direction}
                    <span>{route.distanceKm === null ? "距離未算出" : `${route.distanceKm.toFixed(2)} km`}</span>
                  </summary>
                  <div className="route-detail">
                    <p>{route.name}</p>
                    <p>停留所 {route.stopCount}件 · 収録便数合計 {route.tripCount ?? "未確認"} · 出典 {route.source ?? "未確認"}</p>
                    {route.officialDepotReference && <p>ODPT保存所管: 未割当。参考所管: {depot.name}（<a href={route.officialDepotReference.sourceUrl} target="_blank" rel="noopener noreferrer">東急バス公式資料</a>、資料日付 {route.officialDepotReference.sourceDate}）。表示専用の照合結果です。</p>}
                    {route.officialDepotAmbiguity && <p className="route-warning">所管の資料が一致しません: {route.officialDepotAmbiguity.reason} {route.officialDepotAmbiguity.sourceUrls.map((url, index) => <a key={url} href={url} target="_blank" rel="noopener noreferrer">資料{index + 1}</a>)}</p>}
                    {route.officialServiceNotice && <p className="route-warning">{route.officialServiceNotice.message} <a href={route.officialServiceNotice.sourceUrl} target="_blank" rel="noopener noreferrer">東急バス公式発表</a></p>}
                    {source === "odpt" && route.tripCount === 0 && <p className="route-warning">このパターンに収録された便はありません。運行状況を別途確認してください。</p>}
                    {route.odptPatternId && <p>ODPTパターンID: <code>{route.odptPatternId}</code></p>}
                    {route.classificationSource === "manual_override" && <p>運行パターン分類は保存済みの手動指定です。全パターンを正確に区別できているかは未検証です。</p>}
                    {route.classificationSource !== "manual_override" && route.classificationConfidence != null && <p>運行パターン分類は推定（信頼度 {Math.round(route.classificationConfidence * 100)}%）です。</p>}
                    {route.tripCountsByDayType && <p>日区分別: {Object.entries(route.tripCountsByDayType).map(([day, count]) => `${day} ${count}便`).join(" / ")}</p>}
                    {route.firstDepartureByDayType && <p>日区分別の始発: {Object.entries(route.firstDepartureByDayType).map(([day, time]) => `${day} ${time}`).join(" / ")}</p>}
                    {route.lastArrivalByDayType && <p>日区分別の最終到着: {Object.entries(route.lastArrivalByDayType).map(([day, time]) => `${day} ${time}`).join(" / ")}</p>}
                    <p>距離: {route.distanceKm === null ? "停留所列または座標が不足" : `${route.distanceKm.toFixed(6)} km（隣接停留所の直線距離の和。道路走行距離ではありません）`}</p>
                    {source !== "full" && route.storedDistanceKm !== undefined && <p>{source === "scenario" ? "シナリオに保存された距離" : "ODPT路線マスタの保存距離"}: {route.storedDistanceKm ?? "未設定"} km{typeof route.storedDistanceKm === "number" && route.storedDistanceKm <= 0 ? "（正式入力としては要修正）" : ""}</p>}
                    {route.distanceSource === "catalog_fast_stop_sequence_haversine_display_only" && <p className="route-warning">シナリオの停留所座標が不足したため、保存済みODPTカタログで補った表示専用値です。最適化入力の距離は変更していません。</p>}
                    {onEdit && <button type="button" onClick={() => onEdit(route.id)}>このパターンを編集</button>}
                    <ol>{route.stops.map((stop, index) => <li key={`${stop.id}-${index}`}>{stop.name} <small>{stop.lat === null || stop.lon === null ? "座標未確認" : `${stop.lat}, ${stop.lon}${stop.coordinateSource === "catalog_fast_display_only" ? "（補助カタログ）" : ""}`}</small></li>)}</ol>
                    {!route.stops.length && <p>停留所列がありません。</p>}
                  </div>
                </details>)}
              </details>,
            )}
          </details>;
        })}
        {source === "odpt" && referenceCount > 0 && <p className="subtle">ODPT保存所管が空のうち、公式資料の参考所管で表示: {referenceCount}パターン。保存データの所管は変更していません。</p>}
        {!!unassigned.length && <p className="route-warning">所管を確認できないパターン: {unassigned.length}件。「所管未確認」で閲覧できます。</p>}
      </>}
    </section>
  );
}
