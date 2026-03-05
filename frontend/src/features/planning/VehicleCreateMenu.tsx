// ── VehicleCreateMenu ─────────────────────────────────────────
// When "Add Vehicle" is clicked, this menu appears in the drawer
// to let the user choose between EV bus or Engine bus before the
// actual form opens.

import { useTranslation } from "react-i18next";
import { useMasterUiStore } from "@/stores/master-ui-store";

export function VehicleCreateMenu() {
  const { t } = useTranslation();
  const openDrawer = useMasterUiStore((s) => s.openDrawer);
  const closeDrawer = useMasterUiStore((s) => s.closeDrawer);

  const handleSelect = (vehicleType: "ev_bus" | "engine_bus") => {
    openDrawer({ isCreate: true, vehicleType });
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
