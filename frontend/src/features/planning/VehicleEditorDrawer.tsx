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
  useCreateVehicleBatch,
  useUpdateVehicle,
  useDeleteVehicle,
  useDuplicateVehicle,
  useDuplicateVehicleBatch,
  useVehicleTemplates,
  useCreateVehicleTemplate,
  useUpdateVehicleTemplate,
  useDeleteVehicleTemplate,
} from "@/hooks";
import type { Vehicle, VehicleTemplate } from "@/types";
import type {
  CreateVehicleRequest,
  UpdateVehicleRequest,
  CreateVehicleTemplateRequest,
  UpdateVehicleTemplateRequest,
} from "@/types/api";

interface Props {
  scenarioId: string;
  vehicleId: string | null;
  isCreate: boolean;
  vehicleType: "ev_bus" | "engine_bus" | null;
  templateId: string | null;
  depotId: string | null;
}

type FormData = {
  quantity: string;
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
  quantity: "1",
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
    quantity: "1",
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

function templateToForm(template: VehicleTemplate): FormData {
  return {
    quantity: "1",
    modelName: template.modelName,
    capacityPassengers: String(template.capacityPassengers),
    batteryKwh: template.batteryKwh != null ? String(template.batteryKwh) : "",
    energyConsumptionEv:
      template.type === "BEV" ? String(template.energyConsumption) : "",
    chargePowerKw:
      template.chargePowerKw != null ? String(template.chargePowerKw) : "",
    minSoc: template.minSoc != null ? String(template.minSoc) : "",
    maxSoc: template.maxSoc != null ? String(template.maxSoc) : "",
    fuelTankL: template.fuelTankL != null ? String(template.fuelTankL) : "",
    energyConsumptionIce:
      template.type === "ICE" ? String(template.energyConsumption) : "",
    acquisitionCost: String(template.acquisitionCost),
    enabled: template.enabled,
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
  templateId,
  depotId,
}: Props) {
  const { t } = useTranslation();
  const closeDrawer = useMasterUiStore((s) => s.closeDrawer);
  const selectVehicle = useMasterUiStore((s) => s.selectVehicle);
  const setDirty = useMasterUiStore((s) => s.setDirty);
  const isDirty = useMasterUiStore((s) => s.isDirty);

  const { data: vehicle } = useVehicle(scenarioId, vehicleId ?? "");
  const { data: templatesData } = useVehicleTemplates(scenarioId);
  const createVehicle = useCreateVehicle(scenarioId);
  const createVehicleBatch = useCreateVehicleBatch(scenarioId);
  const updateVehicle = useUpdateVehicle(scenarioId, vehicleId ?? "");
  const deleteVehicle = useDeleteVehicle(scenarioId);
  const duplicateVehicle = useDuplicateVehicle(scenarioId);
  const duplicateVehicleBatch = useDuplicateVehicleBatch(
    scenarioId,
    vehicleId ?? "",
  );
  const createVehicleTemplate = useCreateVehicleTemplate(scenarioId);

  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [activeTab, setActiveTab] = useState("basic");
  const [selectedTemplateId, setSelectedTemplateId] = useState(templateId ?? "");
  const [templateName, setTemplateName] = useState("");
  const [duplicateQuantity, setDuplicateQuantity] = useState("1");

  const updateVehicleTemplate = useUpdateVehicleTemplate(
    scenarioId,
    selectedTemplateId || "",
  );
  const deleteVehicleTemplate = useDeleteVehicleTemplate(scenarioId);

  const templates = templatesData?.items ?? [];

  const apiType = resolveApiType(vehicleType, vehicle ?? undefined);
  const isEv = apiType === "BEV";
  const applicableTemplates = templates.filter((item) => item.type === apiType);
  const initialTemplate = templates.find((item) => item.id === templateId) ?? null;
  const selectedTemplate =
    applicableTemplates.find((item) => item.id === selectedTemplateId) ?? null;

  useEffect(() => {
    setSelectedTemplateId(templateId ?? "");
  }, [templateId]);

  useEffect(() => {
    setDuplicateQuantity("1");
  }, [vehicleId]);

  useEffect(() => {
    if (!isCreate && vehicle) {
      setForm(vehicleToForm(vehicle));
      setTemplateName(vehicle.modelName ? `${vehicle.modelName} template` : "");
    }
  }, [vehicle, isCreate]);

  useEffect(() => {
    if (!isCreate) return;
    if (!templateId) {
      setForm(EMPTY_FORM);
      setTemplateName("");
      return;
    }
    if (!initialTemplate) return;
    setForm(templateToForm(initialTemplate));
    setTemplateName(initialTemplate.name);
  }, [isCreate, templateId, initialTemplate]);

  const updateField = useCallback(
    <K extends keyof FormData>(key: K, value: FormData[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
      setDirty(true);
    },
    [setDirty],
  );

  const buildCreateVehicleRequest = useCallback((): CreateVehicleRequest => {
    const energyConsumption = isEv
      ? Number(form.energyConsumptionEv) || 0
      : Number(form.energyConsumptionIce) || 0;

    return {
      depotId: depotId ?? "",
      type: apiType,
      modelName: form.modelName || t("vehicles.default_vehicle_name", "新規車両"),
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
  }, [apiType, depotId, form, isEv, t]);

  const buildTemplateRequest = useCallback((): CreateVehicleTemplateRequest => {
    const createRequest = buildCreateVehicleRequest();
    return {
      name:
        templateName.trim() ||
        form.modelName ||
        t("vehicles.default_template_name", "新規テンプレート"),
      type: createRequest.type,
      modelName: createRequest.modelName,
      capacityPassengers: createRequest.capacityPassengers,
      batteryKwh: createRequest.batteryKwh,
      fuelTankL: createRequest.fuelTankL,
      energyConsumption: createRequest.energyConsumption,
      chargePowerKw: createRequest.chargePowerKw,
      minSoc: createRequest.minSoc,
      maxSoc: createRequest.maxSoc,
      acquisitionCost: createRequest.acquisitionCost,
      enabled: createRequest.enabled,
    };
  }, [buildCreateVehicleRequest, form.modelName, t, templateName]);

  const handleApplyTemplate = () => {
    if (!selectedTemplate) return;
    setForm(templateToForm(selectedTemplate));
    setTemplateName(selectedTemplate.name);
    setDirty(true);
  };

  const handleTemplateSelectionChange = (value: string) => {
    setSelectedTemplateId(value);
    const matched = applicableTemplates.find((item) => item.id === value) ?? null;
    setTemplateName(matched?.name ?? "");
  };

  const handleSave = () => {
    const baseReq = buildCreateVehicleRequest();

    if (isCreate) {
      if (!depotId) return; // safety
      const quantity = Math.max(1, Number(form.quantity) || 1);
      if (quantity > 1) {
        createVehicleBatch.mutate(
          {
            ...baseReq,
            quantity,
          },
          {
            onSuccess: () => {
              setDirty(false);
              closeDrawer();
            },
          },
        );
      } else {
        createVehicle.mutate(baseReq, {
          onSuccess: () => {
            setDirty(false);
            closeDrawer();
          },
        });
      }
    } else if (vehicleId) {
      const req: UpdateVehicleRequest = {
        type: apiType,
        modelName: baseReq.modelName,
        capacityPassengers: baseReq.capacityPassengers,
        batteryKwh: baseReq.batteryKwh,
        fuelTankL: baseReq.fuelTankL,
        energyConsumption: baseReq.energyConsumption,
        chargePowerKw: baseReq.chargePowerKw,
        minSoc: baseReq.minSoc,
        maxSoc: baseReq.maxSoc,
        acquisitionCost: baseReq.acquisitionCost,
        enabled: baseReq.enabled,
      };
      updateVehicle.mutate(req, {
        onSuccess: () => setDirty(false),
      });
    }
  };

  const handleCreateTemplate = () => {
    createVehicleTemplate.mutate(buildTemplateRequest(), {
      onSuccess: (createdTemplate) => {
        setSelectedTemplateId(createdTemplate.id);
        setTemplateName(createdTemplate.name);
      },
    });
  };

  const handleUpdateTemplate = () => {
    if (!selectedTemplateId) return;
    const payload: UpdateVehicleTemplateRequest = buildTemplateRequest();
    updateVehicleTemplate.mutate(payload, {
      onSuccess: (updatedTemplate) => {
        setTemplateName(updatedTemplate.name);
      },
    });
  };

  const handleDeleteTemplate = () => {
    if (!selectedTemplateId) return;
    if (
      !confirm(
        t("vehicles.template_delete_confirm", "このテンプレートを削除しますか？"),
      )
    ) {
      return;
    }
    deleteVehicleTemplate.mutate(selectedTemplateId, {
      onSuccess: () => {
        setSelectedTemplateId("");
        setTemplateName("");
      },
    });
  };

  const handleDelete = () => {
    if (!vehicleId) return;
    if (!confirm(t("vehicles.delete_confirm", "この車両を削除しますか？"))) return;
    deleteVehicle.mutate(vehicleId, {
      onSuccess: () => closeDrawer(),
    });
  };

  const handleDuplicate = () => {
    if (!vehicleId) return;
    duplicateVehicle.mutate(vehicleId, {
      onSuccess: (created) => {
        setDirty(false);
        selectVehicle(created.id);
      },
    });
  };

  const handleDuplicateBatch = () => {
    if (!vehicleId) return;
    duplicateVehicleBatch.mutate(
      {
        quantity: Math.max(1, Number(duplicateQuantity) || 1),
      },
      {
        onSuccess: () => {
          setDuplicateQuantity("1");
        },
      },
    );
  };

  const isSaving =
    createVehicle.isPending ||
    createVehicleBatch.isPending ||
    updateVehicle.isPending;
  const isTemplateBusy =
    createVehicleTemplate.isPending ||
    updateVehicleTemplate.isPending ||
    deleteVehicleTemplate.isPending;

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
      onDuplicate={!isCreate && vehicleId ? handleDuplicate : undefined}
      isDirty={isDirty}
      isSaving={isSaving}
    >
      <DrawerTabs tabs={tabs} activeKey={activeTab} onChange={setActiveTab} />

      {activeTab === "basic" && (
        <div className="space-y-4">
          {(isCreate || applicableTemplates.length > 0) && (
            <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-slate-700">
                  {t("vehicles.template_apply", "テンプレート適用")}
                </span>
                {selectedTemplate && (
                  <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-slate-500">
                    {selectedTemplate.name}
                  </span>
                )}
              </div>
              <div className="flex gap-2">
                <select
                  value={selectedTemplateId}
                  onChange={(e) => handleTemplateSelectionChange(e.target.value)}
                  className="field-input"
                >
                  <option value="">
                    {t("vehicles.template_select_placeholder", "テンプレートを選択")}
                  </option>
                  {applicableTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleApplyTemplate}
                  disabled={!selectedTemplate}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("vehicles.template_apply_button", "適用")}
                </button>
              </div>
            </div>
          )}

          {isCreate && (
            <Field label={t("vehicles.field_quantity", "導入台数")}>
              <input
                type="number"
                min="1"
                value={form.quantity}
                onChange={(e) => updateField("quantity", e.target.value)}
                className="field-input"
              />
            </Field>
          )}

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

          {!isCreate && vehicleId && (
            <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
              <p className="mb-1 text-xs font-medium text-slate-700">
                {t("vehicles.duplicate_many", "同じ仕様を複数台複製")}
              </p>
              <p className="mb-3 text-xs text-slate-500">
                {t(
                  "vehicles.duplicate_many_help",
                  "現在の車両仕様と路線許可をそのままコピーして追加します。",
                )}
              </p>
              <div className="flex gap-2">
                <input
                  type="number"
                  min="1"
                  value={duplicateQuantity}
                  onChange={(e) => setDuplicateQuantity(e.target.value)}
                  className="field-input max-w-28"
                />
                <button
                  type="button"
                  onClick={handleDuplicateBatch}
                  disabled={duplicateVehicleBatch.isPending}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {duplicateVehicleBatch.isPending
                    ? t("vehicles.duplicate_many_running", "複製中...")
                    : t("vehicles.duplicate_many_button", "複数台複製")}
                </button>
              </div>
            </div>
          )}
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

          <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-xs font-medium text-slate-700">
                {t("vehicles.template_manage", "テンプレート管理")}
              </p>
              <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-slate-500">
                {applicableTemplates.length}
              </span>
            </div>

            <div className="space-y-3">
              <div className="flex gap-2">
                <select
                  value={selectedTemplateId}
                  onChange={(e) => handleTemplateSelectionChange(e.target.value)}
                  className="field-input"
                >
                  <option value="">
                    {t("vehicles.template_manage_placeholder", "編集するテンプレートを選択")}
                  </option>
                  {applicableTemplates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleApplyTemplate}
                  disabled={!selectedTemplate}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("vehicles.template_apply_button", "適用")}
                </button>
              </div>

              <input
                type="text"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                className="field-input"
                placeholder={t("vehicles.template_name_placeholder", "例: 標準EV 300kWh")}
              />

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleCreateTemplate}
                  disabled={isTemplateBusy}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {createVehicleTemplate.isPending
                    ? t("vehicles.template_saving", "保存中...")
                    : t("vehicles.template_save_button", "新規保存")}
                </button>
                <button
                  type="button"
                  onClick={handleUpdateTemplate}
                  disabled={!selectedTemplateId || isTemplateBusy}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {updateVehicleTemplate.isPending
                    ? t("vehicles.template_updating", "更新中...")
                    : t("vehicles.template_update_button", "上書き更新")}
                </button>
                <button
                  type="button"
                  onClick={handleDeleteTemplate}
                  disabled={!selectedTemplateId || isTemplateBusy}
                  className="rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {deleteVehicleTemplate.isPending
                    ? t("vehicles.template_deleting", "削除中...")
                    : t("vehicles.template_delete_button", "テンプレート削除")}
                </button>
              </div>

              {applicableTemplates.length === 0 && (
                <p className="text-xs text-slate-500">
                  {t(
                    "vehicles.templates_empty",
                    "車両編集画面からテンプレートを保存すると、ここからすぐ適用できます。",
                  )}
                </p>
              )}
            </div>
          </div>
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
