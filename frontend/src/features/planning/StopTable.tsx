import { useTranslation } from "react-i18next";
import { useStops } from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
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
        description={t("stops.no_stops_description", "ODPT からデータ一式を取り込んでください")}
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border bg-slate-50">
            <th className="px-3 py-2 text-xs font-medium text-slate-500">
              {t("stops.col_name", "停留所名")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500">
              {t("stops.col_code", "コード")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500">
              {t("stops.col_pole", "ポール番号")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">
              {t("stops.col_lat", "緯度")}
            </th>
            <th className="px-3 py-2 text-xs font-medium text-slate-500 text-right">
              {t("stops.col_lon", "経度")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {stops.map((stop) => (
            <tr key={stop.id} className="hover:bg-slate-50/50">
              <td className="px-3 py-2 font-medium text-slate-700">{stop.name}</td>
              <td className="px-3 py-2 text-xs text-slate-600">{stop.code || "-"}</td>
              <td className="px-3 py-2 text-xs text-slate-600">
                {stop.poleNumber || "-"}
              </td>
              <td className="px-3 py-2 text-right font-mono text-xs text-slate-600">
                {stop.lat ?? "-"}
              </td>
              <td className="px-3 py-2 text-right font-mono text-xs text-slate-600">
                {stop.lon ?? "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
