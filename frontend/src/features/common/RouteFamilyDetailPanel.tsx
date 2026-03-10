import type { RouteFamilyDetail } from "@/types";
import { getRouteVariantLabel } from "@/features/planning/route-family-display";

interface RouteFamilyDetailPanelProps {
  detail: RouteFamilyDetail;
  onClose?: () => void;
  contextLabel?: string;
}

export function RouteFamilyDetailPanel({
  detail,
  onClose,
  contextLabel,
}: RouteFamilyDetailPanelProps) {
  return (
    <div className="rounded-lg border border-border bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-mono text-slate-500">
            {detail.routeFamilyCode}
          </div>
          <h3 className="text-sm font-semibold text-slate-800">
            {detail.routeFamilyLabel}
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            variants {detail.summary.variantCount} / main {detail.summary.mainVariantCount} / linked {detail.summary.aggregatedLinkState}
            {contextLabel ? ` / ${contextLabel}` : ""}
          </p>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            Close
          </button>
        )}
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded border border-slate-100 bg-slate-50 p-3">
          <div className="text-xs font-medium text-slate-600">Canonical Pair</div>
          <div className="mt-1 text-xs text-slate-700">
            {detail.canonicalMainPair
              ? `${detail.canonicalMainPair.outboundStartStop ?? "?"} -> ${detail.canonicalMainPair.outboundEndStop ?? "?"} / ${detail.canonicalMainPair.inboundStartStop ?? "?"} -> ${detail.canonicalMainPair.inboundEndStop ?? "?"}`
              : "not detected"}
          </div>
        </div>
        <div className="rounded border border-slate-100 bg-slate-50 p-3">
          <div className="text-xs font-medium text-slate-600">Timetable Diagnostics</div>
          <div className="mt-1 text-xs text-slate-700">
            trips linked {detail.timetableDiagnostics?.totalTripsLinked ?? 0} / stop timetable links {detail.timetableDiagnostics?.totalStopTimetableEntriesLinked ?? 0}
          </div>
        </div>
      </div>

      <div className="mt-3 rounded border border-slate-100 p-3">
        <div className="text-xs font-medium text-slate-600">Variants</div>
        <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {detail.variants.map((variant) => (
            <div key={variant.id} className="rounded border border-slate-100 bg-slate-50 p-2 text-xs">
              <div className="flex items-center gap-2">
                {variant.color && (
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ backgroundColor: variant.color }}
                  />
                )}
                <span className="font-medium text-slate-700">{variant.name}</span>
              </div>
              <div className="mt-1 text-slate-500">
                {getRouteVariantLabel(variant) ?? variant.routeVariantType ?? "unknown"}
              </div>
              <div className="mt-1 text-slate-500">
                {variant.startStop} - {variant.endStop} / {variant.tripCount ?? 0} trips
              </div>
            </div>
          ))}
        </div>
      </div>

      {!!detail.timetableDiagnostics?.warnings?.length && (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          {detail.timetableDiagnostics.warnings.join(" / ")}
        </div>
      )}
    </div>
  );
}
