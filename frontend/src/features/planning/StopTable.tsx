import { useTranslation } from "react-i18next";
import { useStops } from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState, VirtualizedList } from "@/features/common";
import type { Stop } from "@/types";

interface Props {
  scenarioId: string;
}

export function StopTable({ scenarioId }: Props) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useStops(scenarioId);

  if (isLoading) return <LoadingBlock message={t("stops.loading", "停留所を読み込み中...")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const stops: Stop[] = data?.items ?? [];

  if (stops.length === 0) {
    return (
      <EmptyState
        title={t("stops.no_stops", "停留所がありません")}
        description={t(
          "stops.no_stops_description",
          "ODPT または GTFS からデータ一式を取り込んでください",
        )}
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <div className="grid grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr_0.8fr] border-b border-border bg-slate-50 text-left text-sm">
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("stops.col_name", "停留所名")}</div>
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("stops.col_code", "コード")}</div>
        <div className="px-3 py-2 text-xs font-medium text-slate-500">{t("stops.col_pole", "ポール番号")}</div>
        <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("stops.col_lat", "緯度")}</div>
        <div className="px-3 py-2 text-right text-xs font-medium text-slate-500">{t("stops.col_lon", "経度")}</div>
      </div>
      <VirtualizedList
        items={stops}
        height={560}
        itemHeight={42}
        className="bg-white"
        perfLabel="master-stops-table"
        getKey={(stop) => stop.id}
        renderItem={(stop) => (
          <div className="grid h-full grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr_0.8fr] border-b border-border px-0 text-sm hover:bg-slate-50/50">
            <div className="px-3 py-2 font-medium text-slate-700">{stop.name}</div>
            <div className="px-3 py-2 text-xs text-slate-600">{stop.code || "-"}</div>
            <div className="px-3 py-2 text-xs text-slate-600">{stop.poleNumber || "-"}</div>
            <div className="px-3 py-2 text-right font-mono text-xs text-slate-600">{stop.lat ?? "-"}</div>
            <div className="px-3 py-2 text-right font-mono text-xs text-slate-600">{stop.lon ?? "-"}</div>
          </div>
        )}
      />
    </div>
  );
}
