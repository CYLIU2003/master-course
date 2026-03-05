// ── VehicleEditorDrawer ───────────────────────────────────────
// Editor drawer for creating / editing a vehicle.
// Handles both BEV (ev_bus) and ICE (engine_bus) forms via
// discriminated sections.

import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { EditorDrawer } from "@/features/common/EditorDrawer";
import { DrawerTabs } from "@/features/common/DrawerTabs";
import { useMasterUiStore } from "@/stores/master-ui-store";
import {
  useVehicle,
  useCreateVehicle,
  useUpdateVehicle,
  useDeleteVehicle,
} from "@/hooks";
import type { Vehicle } from "@/types";
import type { CreateVehicleRequest, UpdateVehicleRequest } from "@/types/api";

interface Props {
  scenarioId: string;
  vehicleId: string | null;
  isCreate: boolean;
  vehicleType: "ev_bus" | "engine_bus" | null;
  depotId: string | null;
}

type FormData = {
  modelName: string;
  capacityPassengers: string;
  // BEV fields
  batteryKwh: string;
  energyConsumptionEv: string;
  chargePowerKw: string;
  minSoc: string;
  maxSoc: string;
  // ICE fields
  fuelTankL: string;
  energyConsumptionIce: string;
  // Common
  acquisitionCost: string;
  enabled: boolean;
};

const EMPTY_FORM: FormData = {
  modelName: "",
  capacityPassengers: "70",
  batteryKwh: "",
  energyConsumptionEv: "1.2",
  chargePowerKw: "",
  minSoc: "0.2",
  maxSoc: "0.9",
  fuelTankL: "",
  energyConsumptionIce: "",
  acquisitionCost: "0",
  enabled: true,
};

function vehicleToForm(v: Vehicle): FormData {
  return {
    modelName: v.modelName,
    capacityPassengers: String(v.capacityPassengers),
    batteryKwh: v.batteryKwh != null ? String(v.batteryKwh) : "",
    energyConsumptionEv: v.type === "BEV" ? String(v.energyConsumption) : "",
    chargePowerKw: v.chargePowerKw != null ? String(v.chargePowerKw) : "",
    minSoc: v.minSoc != null ? String(v.minSoc) : "",
    maxSoc: v.maxSoc != null ? String(v.maxSoc) : "",
    fuelTankL: v.fuelTankL != null ? String(v.fuelTankL) : "",
    energyConsumptionIce: v.type === "ICE" ? String(v.energyConsumption) : "",
    acquisitionCost: String(v.acquisitionCost),
    enabled: v.enabled,
  };
}

/** Determine the power type for the API: BEV or ICE */
function resolveApiType(
  vehicleType: "ev_bus" | "engine_bus" | null,
  existingVehicle?: Vehicle,
): "BEV" | "ICE" {
  if (vehicleType === "ev_bus") return "BEV";
  if (vehicleType === "engine_bus") return "ICE";
  return existingVehicle?.type ?? "BEV";
}

export function VehicleEditorDrawer({
  scenarioId,
  vehicleId,
  isCreate,
  vehicleType,
  depotId,
}: Props) {
  const { t } = useTranslation();
  const closeDrawer = useMasterUiStore((s) => s.closeDrawer);
  const setDirty = useMasterUiStore((s) => s.setDirty);
  const isDirty = useMasterUiStore((s) => s.isDirty);

  const { data: vehicle } = useVehicle(scenarioId, vehicleId ?? "");
  const createVehicle = useCreateVehicle(scenarioId);
  const updateVehicle = useUpdateVehicle(scenarioId, vehicleId ?? "");
  const deleteVehicle = useDeleteVehicle(scenarioId);

  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [activeTab, setActiveTab] = useState("basic");

  const apiType = resolveApiType(vehicleType, vehicle ?? undefined);
  const isEv = apiType === "BEV";

  useEffect(() => {
    if (isCreate) {
      setForm(EMPTY_FORM);
    } else if (vehicle) {
      setForm(vehicleToForm(vehicle));
    }
  }, [vehicle, isCreate]);

  const updateField = useCallback(
    <K extends keyof FormData>(key: K, value: FormData[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
      setDirty(true);
    },
    [setDirty],
  );

  const handleSave = () => {
    const energyConsumption = isEv
      ? Number(form.energyConsumptionEv) || 0
      : Number(form.energyConsumptionIce) || 0;

    if (isCreate) {
      if (!depotId) return; // safety
      const req: CreateVehicleRequest = {
        depotId,
        type: apiType,
        modelName: form.modelName || "新規車両",
        capacityPassengers: Number(form.capacityPassengers) || 70,
        batteryKwh: isEv ? (Number(form.batteryKwh) || null) : null,
        fuelTankL: !isEv ? (Number(form.fuelTankL) || null) : null,
        energyConsumption,
        chargePowerKw: isEv ? (Number(form.chargePowerKw) || null) : null,
        minSoc: isEv ? (Number(form.minSoc) || null) : null,
        maxSoc: isEv ? (Number(form.maxSoc) || null) : null,
        acquisitionCost: Number(form.acquisitionCost) || 0,
        enabled: form.enabled,
      };
      createVehicle.mutate(req, {
        onSuccess: () => closeDrawer(),
      });
    } else if (vehicleId) {
      const req: UpdateVehicleRequest = {
        type: apiType,
        modelName: form.modelName,
        capacityPassengers: Number(form.capacityPassengers) || 70,
        batteryKwh: isEv ? (Number(form.batteryKwh) || null) : null,
        fuelTankL: !isEv ? (Number(form.fuelTankL) || null) : null,
        energyConsumption,
        chargePowerKw: isEv ? (Number(form.chargePowerKw) || null) : null,
        minSoc: isEv ? (Number(form.minSoc) || null) : null,
        maxSoc: isEv ? (Number(form.maxSoc) || null) : null,
        acquisitionCost: Number(form.acquisitionCost) || 0,
        enabled: form.enabled,
      };
      updateVehicle.mutate(req, {
        onSuccess: () => setDirty(false),
      });
    }
  };

  const handleDelete = () => {
    if (!vehicleId) return;
    if (!confirm(t("vehicles.delete_confirm", "この車両を削除しますか？"))) return;
    deleteVehicle.mutate(vehicleId, {
      onSuccess: () => closeDrawer(),
    });
  };

  const isSaving = createVehicle.isPending || updateVehicle.isPending;

  const tabs = isEv
    ? [
        { key: "basic", label: "基本情報" },
        { key: "ev", label: "EV仕様" },
        { key: "cost", label: "コスト" },
      ]
    : [
        { key: "basic", label: "基本情報" },
        { key: "engine", label: "エンジン仕様" },
        { key: "cost", label: "コスト" },
      ];

  const typeLabel = isEv ? "EV バス" : "エンジンバス";
  const title = isCreate
    ? t("vehicles.create_title", `${typeLabel}を追加`)
    : form.modelName || "車両";

  return (
    <EditorDrawer
      open
      title={title}
      subtitle={vehicleId ?? typeLabel}
      onClose={closeDrawer}
      onSave={handleSave}
      onDelete={!isCreate && vehicleId ? handleDelete : undefined}
      isDirty={isDirty}
      isSaving={isSaving}
    >
      <DrawerTabs tabs={tabs} activeKey={activeTab} onChange={setActiveTab} />

      {activeTab === "basic" && (
        <div className="space-y-4">
          <Field label={t("vehicles.field_model", "車両名/モデル名")}>
            <input
              type="text"
              value={form.modelName}
              onChange={(e) => updateField("modelName", e.target.value)}
              className="field-input"
              placeholder="例: BYD K9"
            />
          </Field>
          <Field label={t("vehicles.field_capacity", "乗客定員")}>
            <input
              type="number"
              min="1"
              value={form.capacityPassengers}
              onChange={(e) => updateField("capacityPassengers", e.target.value)}
              className="field-input"
            />
          </Field>
          <CheckboxField
            label={t("vehicles.field_enabled", "有効")}
            checked={form.enabled}
            onChange={(v) => updateField("enabled", v)}
          />
        </div>
      )}

      {activeTab === "ev" && isEv && (
        <div className="space-y-4">
          <Field label={t("vehicles.field_battery", "バッテリー容量 (kWh)")}>
            <input
              type="number"
              min="0"
              step="any"
              value={form.batteryKwh}
              onChange={(e) => updateField("batteryKwh", e.target.value)}
              className="field-input"
              placeholder="例: 300"
            />
          </Field>
          <Field label={t("vehicles.field_ev_consumption", "電力消費量 (kWh/km)")}>
            <input
              type="number"
              min="0"
              step="any"
              value={form.energyConsumptionEv}
              onChange={(e) => updateField("energyConsumptionEv", e.target.value)}
              className="field-input"
              placeholder="例: 1.2"
            />
          </Field>
          <Field label={t("vehicles.field_charge_power", "最大充電出力 (kW)")}>
            <input
              type="number"
              min="0"
              step="any"
              value={form.chargePowerKw}
              onChange={(e) => updateField("chargePowerKw", e.target.value)}
              className="field-input"
              placeholder="例: 150"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("vehicles.field_min_soc", "最低SOC")}>
              <input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={form.minSoc}
                onChange={(e) => updateField("minSoc", e.target.value)}
                className="field-input"
                placeholder="0.2"
              />
            </Field>
            <Field label={t("vehicles.field_max_soc", "最高SOC")}>
              <input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={form.maxSoc}
                onChange={(e) => updateField("maxSoc", e.target.value)}
                className="field-input"
                placeholder="0.9"
              />
            </Field>
          </div>
        </div>
      )}

      {activeTab === "engine" && !isEv && (
        <div className="space-y-4">
          <Field label={t("vehicles.field_fuel_tank", "燃料タンク容量 (L)")}>
            <input
              type="number"
              min="0"
              step="any"
              value={form.fuelTankL}
              onChange={(e) => updateField("fuelTankL", e.target.value)}
              className="field-input"
              placeholder="例: 200"
            />
          </Field>
          <Field label={t("vehicles.field_ice_consumption", "燃費 (L/km)")}>
            <input
              type="number"
              min="0"
              step="any"
              value={form.energyConsumptionIce}
              onChange={(e) => updateField("energyConsumptionIce", e.target.value)}
              className="field-input"
              placeholder="例: 0.35"
            />
          </Field>
        </div>
      )}

      {activeTab === "cost" && (
        <div className="space-y-4">
          <Field label={t("vehicles.field_cost", "取得価格 (円)")}>
            <input
              type="number"
              min="0"
              value={form.acquisitionCost}
              onChange={(e) => updateField("acquisitionCost", e.target.value)}
              className="field-input"
              placeholder="例: 30000000"
            />
          </Field>
        </div>
      )}
    </EditorDrawer>
  );
}

// ── Local field helpers ──────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">
        {label}
      </span>
      {children}
    </label>
  );
}

function CheckboxField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-500"
      />
      <span className="text-xs font-medium text-slate-600">{label}</span>
    </label>
  );
}
