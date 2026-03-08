import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import { useUIStore } from "@/stores/ui-store";
import { usePlanningDatasetStore } from "@/stores/planning-dataset-store";
import { PageSection } from "@/features/common";
import { DepotListPanel, DepotDetailPanel, RouteTable, VehicleRouteMatrix } from "@/features/planning";

export function MasterPlanningPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const selectedDepotId = useUIStore((s) => s.selectedDepotId);
  const [showAllRoutes, setShowAllRoutes] = useState(false);
  const setActiveDepotId = usePlanningDatasetStore((s) => s.setActiveDepotId);
  const setShowAllRoutesStore = usePlanningDatasetStore((s) => s.setShowAllRoutes);

  useEffect(() => {
    setActiveDepotId(selectedDepotId);
  }, [selectedDepotId, setActiveDepotId]);

  useEffect(() => {
    setShowAllRoutesStore(showAllRoutes);
  }, [showAllRoutes, setShowAllRoutesStore]);

  if (!scenarioId) return null;

  return (
    <div className="space-y-6">
      {/* Page title */}
      <div>
        <h1 className="text-lg font-semibold text-slate-800">
          {t("planning.title")}
        </h1>
        <p className="text-sm text-slate-500">
          {t("planning.description")}
        </p>
      </div>

      {/* Main 2-column layout: depot list + detail */}
      <div className="flex gap-4" style={{ minHeight: "400px" }}>
        {/* Left: Depot list */}
        <div className="w-56 shrink-0 rounded-lg border border-border bg-surface-raised">
          <DepotListPanel scenarioId={scenarioId} />
        </div>

        {/* Right: Depot detail or placeholder */}
        <div className="flex-1 rounded-lg border border-border bg-surface-raised">
          {selectedDepotId ? (
            <DepotDetailPanel
              scenarioId={scenarioId}
              depotId={selectedDepotId}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              {t("planning.select_depot")}
            </div>
          )}
        </div>
      </div>

      {/* Routes section (not depot-scoped) */}
      <PageSection
        title={t("planning.routes_title")}
        description={
          selectedDepotId && !showAllRoutes
            ? "Explorer で最後に確定した営業所に関係する route を優先表示しています。"
            : t("planning.routes_description")
        }
        actions={
          selectedDepotId ? (
            <label className="flex items-center gap-2 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={showAllRoutes}
                onChange={(e) => setShowAllRoutes(e.target.checked)}
              />
              すべて表示
            </label>
          ) : undefined
        }
      >
        <RouteTable
          scenarioId={scenarioId}
          depotId={selectedDepotId && !showAllRoutes ? selectedDepotId : undefined}
        />
      </PageSection>

      {/* Vehicle-Route permission matrix */}
      {selectedDepotId && (
        <PageSection
          title={t("planning.permissions_title")}
          description={t("planning.permissions_description")}
        >
          <VehicleRouteMatrix
            scenarioId={scenarioId}
            depotId={selectedDepotId}
          />
        </PageSection>
      )}
    </div>
  );
}
