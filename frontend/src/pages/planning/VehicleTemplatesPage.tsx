import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  PageSection,
  LoadingBlock,
  ErrorBlock,
  EmptyState,
} from "@/features/common";
import {
  useCreateVehicleBatch,
  useCreateVehicleTemplate,
  useDeleteVehicleTemplate,
  useDepots,
  useUpdateVehicleTemplate,
  useVehicleTemplates,
} from "@/hooks";
import type { VehicleTemplate } from "@/types";
import type {
  CreateVehicleBatchRequest,
  CreateVehicleTemplateRequest,
  UpdateVehicleTemplateRequest,
} from "@/types/api";

type TemplateFormState = {
  name: string;
  type: "BEV" | "ICE";
  modelName: string;
  capacityPassengers: string;
  batteryKwh: string;
  fuelTankL: string;
  energyConsumption: string;
  chargePowerKw: string;
  minSoc: string;
  maxSoc: string;
  acquisitionCost: string;
  enabled: boolean;
};

const EMPTY_FORM: TemplateFormState = {
  name: "",
  type: "BEV",
  modelName: "",
  capacityPassengers: "70",
  batteryKwh: "",
  fuelTankL: "",
  energyConsumption: "1.2",
  chargePowerKw: "",
  minSoc: "0.2",
  maxSoc: "0.9",
  acquisitionCost: "0",
  enabled: true,
};

function templateToForm(template: VehicleTemplate): TemplateFormState {
  return {
    name: template.name,
    type: template.type,
    modelName: template.modelName,
    capacityPassengers: String(template.capacityPassengers),
    batteryKwh: template.batteryKwh != null ? String(template.batteryKwh) : "",
    fuelTankL: template.fuelTankL != null ? String(template.fuelTankL) : "",
    energyConsumption: String(template.energyConsumption),
    chargePowerKw: template.chargePowerKw != null ? String(template.chargePowerKw) : "",
    minSoc: template.minSoc != null ? String(template.minSoc) : "",
    maxSoc: template.maxSoc != null ? String(template.maxSoc) : "",
    acquisitionCost: String(template.acquisitionCost),
    enabled: template.enabled,
  };
}

export function VehicleTemplatesPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data, isLoading, error } = useVehicleTemplates(scenarioId!);
  const { data: depotsData } = useDepots(scenarioId!);
  const createTemplate = useCreateVehicleTemplate(scenarioId!);
  const deleteTemplate = useDeleteVehicleTemplate(scenarioId!);
  const createVehicleBatch = useCreateVehicleBatch(scenarioId!);

  const templates = data?.items ?? [];
  const depots = depotsData?.items ?? [];

  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [form, setForm] = useState<TemplateFormState>(EMPTY_FORM);
  const [targetDepotId, setTargetDepotId] = useState("");
  const [quantity, setQuantity] = useState("1");

  const selectedTemplate = useMemo(
    () => templates.find((item) => item.id === selectedTemplateId) ?? null,
    [selectedTemplateId, templates],
  );
  const updateTemplate = useUpdateVehicleTemplate(scenarioId!, selectedTemplateId ?? "");

  useEffect(() => {
    if (!depots.length || targetDepotId) {
      return;
    }
    setTargetDepotId(depots[0].id);
  }, [depots, targetDepotId]);

  useEffect(() => {
    if (!templates.length) {
      setSelectedTemplateId(null);
      setForm(EMPTY_FORM);
      return;
    }
    if (selectedTemplateId && templates.some((item) => item.id === selectedTemplateId)) {
      return;
    }
    setSelectedTemplateId(templates[0].id);
  }, [selectedTemplateId, templates]);

  useEffect(() => {
    if (!selectedTemplate) {
      return;
    }
    setForm(templateToForm(selectedTemplate));
  }, [selectedTemplate]);

  if (isLoading) {
    return <LoadingBlock message={t("vehicles.templates_loading", "テンプレートを読み込み中...")} />;
  }
  if (error) {
    return <ErrorBlock message={error.message} />;
  }

  const buildTemplatePayload = (): CreateVehicleTemplateRequest => ({
    name: form.name.trim() || form.modelName || t("vehicles.default_template_name", "新規テンプレート"),
    type: form.type,
    modelName: form.modelName.trim() || t("vehicles.default_vehicle_name", "新規車両"),
    capacityPassengers: Number(form.capacityPassengers) || 70,
    batteryKwh: form.type === "BEV" ? Number(form.batteryKwh) || null : null,
    fuelTankL: form.type === "ICE" ? Number(form.fuelTankL) || null : null,
    energyConsumption: Number(form.energyConsumption) || 0,
    chargePowerKw: form.type === "BEV" ? Number(form.chargePowerKw) || null : null,
    minSoc: form.type === "BEV" ? Number(form.minSoc) || null : null,
    maxSoc: form.type === "BEV" ? Number(form.maxSoc) || null : null,
    acquisitionCost: Number(form.acquisitionCost) || 0,
    enabled: form.enabled,
  });

  const handleCreateNew = () => {
    setSelectedTemplateId(null);
    setForm(EMPTY_FORM);
  };

  const handleSaveNew = () => {
    createTemplate.mutate(buildTemplatePayload(), {
      onSuccess: (created) => {
        setSelectedTemplateId(created.id);
      },
    });
  };

  const handleUpdate = () => {
    if (!selectedTemplateId) {
      return;
    }
    updateTemplate.mutate(buildTemplatePayload() as UpdateVehicleTemplateRequest);
  };

  const handleDelete = () => {
    if (!selectedTemplateId) {
      return;
    }
    if (!confirm(t("vehicles.template_delete_confirm", "このテンプレートを削除しますか？"))) {
      return;
    }
    deleteTemplate.mutate(selectedTemplateId, {
      onSuccess: () => {
        setSelectedTemplateId(null);
        setForm(EMPTY_FORM);
      },
    });
  };

  const handleCreateVehicles = () => {
    if (!selectedTemplate || !targetDepotId) {
      return;
    }
    const payload = buildTemplatePayload();
    const request: CreateVehicleBatchRequest = {
      depotId: targetDepotId,
      type: payload.type,
      modelName: payload.modelName,
      capacityPassengers: payload.capacityPassengers,
      batteryKwh: payload.batteryKwh,
      fuelTankL: payload.fuelTankL,
      energyConsumption: payload.energyConsumption,
      chargePowerKw: payload.chargePowerKw,
      minSoc: payload.minSoc,
      maxSoc: payload.maxSoc,
      acquisitionCost: payload.acquisitionCost,
      enabled: payload.enabled,
      quantity: Math.max(1, Number(quantity) || 1),
    };
    createVehicleBatch.mutate(request);
  };

  return (
    <PageSection
      title={t("vehicles.template_manage", "テンプレート管理")}
      description={t(
        "vehicles.template_manage_page_description",
        "車両テンプレートの作成・更新・削除と、テンプレートからの一括作成を行います。",
      )}
      actions={
        <button
          type="button"
          onClick={handleCreateNew}
          className="rounded border border-border px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          {t("vehicles.template_new", "新規テンプレート")}
        </button>
      }
    >
      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="rounded-xl border border-border bg-white">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <p className="text-sm font-semibold text-slate-800">
              {t("vehicles.templates_section", "保存済みテンプレート")}
            </p>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">
              {templates.length}
            </span>
          </div>
          {templates.length === 0 ? (
            <div className="p-4">
              <EmptyState
                title={t("vehicles.templates_empty_title", "テンプレートがありません")}
                description={t(
                  "vehicles.templates_empty",
                  "テンプレートを作成すると、車両追加時にすぐ適用できます。",
                )}
              />
            </div>
          ) : (
            <div className="divide-y divide-border">
              {templates.map((template) => {
                const active = template.id === selectedTemplateId;
                return (
                  <button
                    key={template.id}
                    type="button"
                    onClick={() => setSelectedTemplateId(template.id)}
                    className={`w-full px-4 py-3 text-left transition-colors ${
                      active ? "bg-primary-50/70" : "hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-slate-800">{template.name}</p>
                        <p className="text-xs text-slate-500">{template.modelName || "-"}</p>
                      </div>
                      <span
                        className={`rounded border px-2 py-0.5 text-[11px] font-medium ${
                          template.type === "BEV"
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                            : "border-amber-200 bg-amber-50 text-amber-700"
                        }`}
                      >
                        {template.type}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-white p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  {selectedTemplateId
                    ? t("vehicles.template_edit", "テンプレート編集")
                    : t("vehicles.template_create", "テンプレート作成")}
                </p>
                <p className="text-xs text-slate-500">
                  {t(
                    "vehicles.template_edit_help",
                    "VehicleCreateMenu では適用のみ行い、作成・更新・削除はこの画面で管理します。",
                  )}
                </p>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <Field label={t("vehicles.template_name", "テンプレート名")}>
                <input
                  value={form.name}
                  onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                  className="field-input"
                />
              </Field>
              <Field label={t("vehicles.col_type", "種別")}>
                <select
                  value={form.type}
                  onChange={(e) => setForm((prev) => ({ ...prev, type: e.target.value as "BEV" | "ICE" }))}
                  className="field-input"
                >
                  <option value="BEV">BEV</option>
                  <option value="ICE">ICE</option>
                </select>
              </Field>
              <Field label={t("vehicles.field_model", "車両名/モデル名")}>
                <input
                  value={form.modelName}
                  onChange={(e) => setForm((prev) => ({ ...prev, modelName: e.target.value }))}
                  className="field-input"
                />
              </Field>
              <Field label={t("vehicles.field_capacity", "乗客定員")}>
                <input
                  type="number"
                  min="1"
                  value={form.capacityPassengers}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, capacityPassengers: e.target.value }))
                  }
                  className="field-input"
                />
              </Field>
              {form.type === "BEV" ? (
                <>
                  <Field label={t("vehicles.field_battery", "バッテリー容量 (kWh)")}>
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={form.batteryKwh}
                      onChange={(e) => setForm((prev) => ({ ...prev, batteryKwh: e.target.value }))}
                      className="field-input"
                    />
                  </Field>
                  <Field label={t("vehicles.field_charge_power", "最大充電出力 (kW)")}>
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={form.chargePowerKw}
                      onChange={(e) =>
                        setForm((prev) => ({ ...prev, chargePowerKw: e.target.value }))
                      }
                      className="field-input"
                    />
                  </Field>
                  <Field label={t("vehicles.field_min_soc", "最低SOC")}>
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.01"
                      value={form.minSoc}
                      onChange={(e) => setForm((prev) => ({ ...prev, minSoc: e.target.value }))}
                      className="field-input"
                    />
                  </Field>
                  <Field label={t("vehicles.field_max_soc", "最高SOC")}>
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.01"
                      value={form.maxSoc}
                      onChange={(e) => setForm((prev) => ({ ...prev, maxSoc: e.target.value }))}
                      className="field-input"
                    />
                  </Field>
                </>
              ) : (
                <Field label={t("vehicles.field_fuel_tank", "燃料タンク容量 (L)")}>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={form.fuelTankL}
                    onChange={(e) => setForm((prev) => ({ ...prev, fuelTankL: e.target.value }))}
                    className="field-input"
                  />
                </Field>
              )}
              <Field
                label={
                  form.type === "BEV"
                    ? t("vehicles.field_ev_consumption", "電力消費量 (kWh/km)")
                    : t("vehicles.field_ice_consumption", "燃費 (L/km)")
                }
              >
                <input
                  type="number"
                  min="0"
                  step="any"
                  value={form.energyConsumption}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, energyConsumption: e.target.value }))
                  }
                  className="field-input"
                />
              </Field>
              <Field label={t("vehicles.field_cost", "取得価格 (円)")}>
                <input
                  type="number"
                  min="0"
                  value={form.acquisitionCost}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, acquisitionCost: e.target.value }))
                  }
                  className="field-input"
                />
              </Field>
            </div>

            <label className="mt-3 flex items-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm((prev) => ({ ...prev, enabled: e.target.checked }))}
                className="h-4 w-4 rounded border-slate-300 text-primary-600"
              />
              {t("vehicles.field_enabled", "有効")}
            </label>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleSaveNew}
                disabled={createTemplate.isPending}
                className="rounded bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
              >
                {createTemplate.isPending
                  ? t("vehicles.template_saving", "保存中...")
                  : t("vehicles.template_save_button", "新規保存")}
              </button>
              <button
                type="button"
                onClick={handleUpdate}
                disabled={!selectedTemplateId || updateTemplate.isPending}
                className="rounded border border-border px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {updateTemplate.isPending
                  ? t("vehicles.template_updating", "更新中...")
                  : t("vehicles.template_update_button", "上書き更新")}
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={!selectedTemplateId || deleteTemplate.isPending}
                className="rounded border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                {deleteTemplate.isPending
                  ? t("vehicles.template_deleting", "削除中...")
                  : t("vehicles.template_delete_button", "テンプレート削除")}
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-border bg-white p-4">
            <p className="text-sm font-semibold text-slate-800">
              {t("vehicles.template_create_many", "このテンプレートで N 台作成")}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {t(
                "vehicles.template_create_many_help",
                "選択中のテンプレート内容をそのまま使って、指定営業所へ複数台の車両を作成します。",
              )}
            </p>
            <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_140px_auto]">
              <Field label={t("vehicles.target_depot", "作成先営業所")}>
                <select
                  value={targetDepotId}
                  onChange={(e) => setTargetDepotId(e.target.value)}
                  className="field-input"
                >
                  {depots.map((depot) => (
                    <option key={depot.id} value={depot.id}>
                      {depot.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t("vehicles.field_quantity", "導入台数")}>
                <input
                  type="number"
                  min="1"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  className="field-input"
                />
              </Field>
              <div className="flex items-end">
                <button
                  type="button"
                  onClick={handleCreateVehicles}
                  disabled={!selectedTemplate || !targetDepotId || createVehicleBatch.isPending}
                  className="w-full rounded border border-border px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  {createVehicleBatch.isPending
                    ? t("vehicles.creating_many", "作成中...")
                    : t("vehicles.template_create_many_button", "車両を作成")}
                </button>
              </div>
            </div>
            {depots.length === 0 && (
              <p className="mt-3 text-xs text-amber-700">
                {t(
                  "vehicles.template_create_many_no_depot",
                  "車両を作成する前に営業所を1件以上登録してください。",
                )}
              </p>
            )}
          </div>
        </div>
      </div>
    </PageSection>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  );
}
