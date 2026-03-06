// ── VehicleCreateMenu ─────────────────────────────────────────
// When "Add Vehicle" is clicked, this menu appears in the drawer
// to let the user choose between EV bus or Engine bus before the
// actual form opens.

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useVehicleTemplates } from "@/hooks";
import { useMasterUiStore } from "@/stores/master-ui-store";

interface Props {
  scenarioId: string;
}

export function VehicleCreateMenu({ scenarioId }: Props) {
  const { t } = useTranslation();
  const { data } = useVehicleTemplates(scenarioId);
  const openDrawer = useMasterUiStore((s) => s.openDrawer);
  const closeDrawer = useMasterUiStore((s) => s.closeDrawer);
  const templates = data?.items ?? [];

  const handleSelect = (vehicleType: "ev_bus" | "engine_bus") => {
    openDrawer({ isCreate: true, vehicleType });
  };

  const handleTemplateSelect = (templateId: string, type: "BEV" | "ICE") => {
    openDrawer({
      isCreate: true,
      vehicleType: type === "BEV" ? "ev_bus" : "engine_bus",
      vehicleTemplateId: templateId,
    });
  };

  return (
    <div className="w-[480px] shrink-0 flex flex-col border-l border-border bg-surface-raised">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-800">
          {t("vehicles.create_choose_type", "車両タイプを選択")}
        </h3>
        <button
          onClick={closeDrawer}
          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          aria-label="Close"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Type cards */}
      <div className="flex-1 p-4 space-y-3">
        <TypeCard
          title={t("vehicles.type_ev", "EV バス")}
          description={t(
            "vehicles.type_ev_desc",
            "バッテリー電気バス。充電設備・SOC管理が必要です。",
          )}
          badgeColor="bg-green-50 text-green-700 border-green-200"
          onClick={() => handleSelect("ev_bus")}
        />
        <TypeCard
          title={t("vehicles.type_engine", "エンジンバス")}
          description={t(
            "vehicles.type_engine_desc",
            "ディーゼル・ガソリン・CNG等の内燃機関バス。",
          )}
          badgeColor="bg-amber-50 text-amber-700 border-amber-200"
          onClick={() => handleSelect("engine_bus")}
        />

        <div className="pt-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-700">
              {t("vehicles.templates_section", "保存済みテンプレート")}
            </p>
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">
                {templates.length}
              </span>
              <Link
                to={`/scenarios/${scenarioId}/vehicle-templates`}
                className="text-[11px] font-medium text-primary-700 hover:text-primary-800"
              >
                {t("vehicles.template_manage_link", "管理")}
              </Link>
            </div>
          </div>

          {templates.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 px-3 py-2 text-xs text-slate-500">
              {t(
                "vehicles.templates_empty",
                "車両編集画面からテンプレートを保存すると、ここからすぐ適用できます。",
              )}
            </p>
          ) : (
            <div className="space-y-2">
              {templates.map((template) => (
                <button
                  key={template.id}
                  onClick={() => handleTemplateSelect(template.id, template.type)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-left transition-colors hover:border-primary-300 hover:bg-primary-50/30"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-slate-700">
                        {template.name}
                      </p>
                      <p className="text-xs text-slate-500">
                        {template.modelName || t("vehicles.field_model", "車両名/モデル名")}
                      </p>
                    </div>
                    <span
                      className={`rounded border px-2 py-0.5 text-[11px] font-medium ${
                        template.type === "BEV"
                          ? "border-green-200 bg-green-50 text-green-700"
                          : "border-amber-200 bg-amber-50 text-amber-700"
                      }`}
                    >
                      {template.type}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TypeCard({
  title,
  description,
  badgeColor,
  onClick,
}: {
  title: string;
  description: string;
  badgeColor: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full rounded-lg border border-border p-4 text-left transition-colors hover:border-primary-300 hover:bg-primary-50/30"
    >
      <span
        className={`mb-2 inline-block rounded border px-2 py-0.5 text-xs font-medium ${badgeColor}`}
      >
        {title}
      </span>
      <p className="text-xs text-slate-500">{description}</p>
    </button>
  );
}
