// ── VehicleEditorDrawer ───────────────────────────────────────
// Editor drawer for creating / editing a vehicle.
// Handles both BEV (ev_bus) and ICE (engine_bus) forms via
// discriminated sections.

import { useState, useEffect, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { EditorDrawer } from "@/features/common/EditorDrawer";
import { DrawerTabs } from "@/features/common/DrawerTabs";
import { useMasterUiStore } from "@/stores/master-ui-store";
import {
  useVehicle,
  useCreateVehicle,
  useCreateVehicleBatch,
  useDepotRoutePermissions,
  useDepots,
  useUpdateVehicle,
  useDeleteVehicle,
  useDuplicateVehicleBatch,
  useRoutes,
  useVehicleTemplates,
  useVehicleRoutePermissions,
} from "@/hooks";
import type { Vehicle, VehicleTemplate } from "@/types";
import type {
  CreateVehicleRequest,
  UpdateVehicleRequest,
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

const vehicleFormSchema = z
  .object({
    quantity: z.string().trim(),
    modelName: z.string().trim().min(1, "車両名/モデル名は必須です"),
    capacityPassengers: z.string().trim(),
    batteryKwh: z.string().trim(),
    energyConsumptionEv: z.string().trim(),
    chargePowerKw: z.string().trim(),
    minSoc: z.string().trim(),
    maxSoc: z.string().trim(),
    fuelTankL: z.string().trim(),
    energyConsumptionIce: z.string().trim(),
    acquisitionCost: z.string().trim(),
    enabled: z.boolean(),
  })
  .superRefine((value, ctx) => {
    const nonNegative = (raw: string, path: keyof FormData, label: string, integer: boolean = false) => {
      const parsed = Number(raw || "0");
      if (!Number.isFinite(parsed) || parsed < 0 || (integer && !Number.isInteger(parsed))) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: [path], message: `${label}は0以上の${integer ? "整数" : "数値"}で入力してください` });
      }
    };
    nonNegative(value.quantity, "quantity", "導入台数", true);
    nonNegative(value.capacityPassengers, "capacityPassengers", "乗客定員", true);
    nonNegative(value.acquisitionCost, "acquisitionCost", "取得費用");
  });

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
  const { data: depotsData } = useDepots(scenarioId);
  const { data: routesData } = useRoutes(scenarioId);
  const { data: depotRoutePermissionsData } = useDepotRoutePermissions(scenarioId);
  const { data: vehicleRoutePermissionsData } = useVehicleRoutePermissions(scenarioId);
  const { data: templatesData } = useVehicleTemplates(scenarioId);
  const createVehicle = useCreateVehicle(scenarioId);
  const createVehicleBatch = useCreateVehicleBatch(scenarioId);
  const updateVehicle = useUpdateVehicle(scenarioId, vehicleId ?? "");
  const deleteVehicle = useDeleteVehicle(scenarioId);
  const duplicateVehicleBatch = useDuplicateVehicleBatch(
    scenarioId,
    vehicleId ?? "",
  );

  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [activeTab, setActiveTab] = useState("basic");
  const [selectedTemplateId, setSelectedTemplateId] = useState(templateId ?? "");
  const [duplicateQuantity, setDuplicateQuantity] = useState("1");
  const [duplicateTargetDepotId, setDuplicateTargetDepotId] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  const templates = templatesData?.items ?? [];
  const depots = depotsData?.items ?? [];
  const routes = routesData?.items ?? [];
  const depotRoutePermissions = depotRoutePermissionsData?.items ?? [];
  const vehicleRoutePermissions = vehicleRoutePermissionsData?.items ?? [];

  const apiType = resolveApiType(vehicleType, vehicle ?? undefined);
  const isEv = apiType === "BEV";
  const applicableTemplates = templates.filter((item) => item.type === apiType);
  const initialTemplate = templates.find((item) => item.id === templateId) ?? null;
  const selectedTemplate =
    applicableTemplates.find((item) => item.id === selectedTemplateId) ?? null;
  const sourceVehicleRouteIds = useMemo(
    () =>
      vehicleId
        ? vehicleRoutePermissions
            .filter((item) => item.vehicleId === vehicleId && item.allowed)
            .map((item) => item.routeId)
        : [],
    [vehicleId, vehicleRoutePermissions],
  );
  const targetDepotPermissions = useMemo(
    () =>
      depotRoutePermissions.filter((item) => item.depotId === duplicateTargetDepotId),
    [depotRoutePermissions, duplicateTargetDepotId],
  );
  const targetDepotHasRouteRules = targetDepotPermissions.length > 0;
  const targetDepotAllowedRouteIds = useMemo(
    () => new Set(targetDepotPermissions.filter((item) => item.allowed).map((item) => item.routeId)),
    [targetDepotPermissions],
  );
  const routeNameById = useMemo(
    () =>
      new Map(
        routes.map((route) => [route.id, route.name || route.id] as const),
      ),
    [routes],
  );
  const duplicateRoutePreview = useMemo(() => {
    const kept = sourceVehicleRouteIds.filter(
      (routeId) => !targetDepotHasRouteRules || targetDepotAllowedRouteIds.has(routeId),
    );
    const dropped = targetDepotHasRouteRules
      ? sourceVehicleRouteIds.filter((routeId) => !targetDepotAllowedRouteIds.has(routeId))
      : [];
    return {
      kept,
      dropped,
      keptNames: kept.map((routeId) => routeNameById.get(routeId) ?? routeId),
      droppedNames: dropped.map((routeId) => routeNameById.get(routeId) ?? routeId),
    };
  }, [routeNameById, sourceVehicleRouteIds, targetDepotAllowedRouteIds, targetDepotHasRouteRules]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setSelectedTemplateId(templateId ?? "");
    });
    return () => window.cancelAnimationFrame(frame);
  }, [templateId]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setDuplicateQuantity("1");
      setDuplicateTargetDepotId(vehicle?.depotId ?? depotId ?? "");
    });
    return () => window.cancelAnimationFrame(frame);
  }, [vehicle?.depotId, vehicleId, depotId]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (!isCreate && vehicle) {
        setForm(vehicleToForm(vehicle));
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [vehicle, isCreate]);

  useEffect(() => {
    if (!isCreate) return undefined;
    const frame = window.requestAnimationFrame(() => {
      if (!templateId) {
        setForm(EMPTY_FORM);
        return;
      }
      if (!initialTemplate) return;
      setForm(templateToForm(initialTemplate));
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isCreate, templateId, initialTemplate]);

  const updateField = useCallback(
    <K extends keyof FormData>(key: K, value: FormData[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
      setValidationError(null);
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

  const handleApplyTemplate = () => {
    if (!selectedTemplate) return;
    setForm(templateToForm(selectedTemplate));
    setDirty(true);
  };

  const handleTemplateSelectionChange = (value: string) => {
    setSelectedTemplateId(value);
  };

  const handleSave = () => {
    const parsed = vehicleFormSchema.safeParse(form);
    if (!parsed.success) {
      setValidationError(parsed.error.issues[0]?.message ?? "入力内容を確認してください");
      setActiveTab("basic");
      return;
    }
    if (!depotId && isCreate) {
      setValidationError("営業所を選択してから車両を追加してください");
      return;
    }
    if (isEv) {
      const battery = Number(form.batteryKwh || "0");
      const chargePower = Number(form.chargePowerKw || "0");
      if (!Number.isFinite(battery) || battery <= 0) {
        setValidationError("EV バスは battery_kwh を正の数で入力してください");
        setActiveTab("ev");
        return;
      }
      if (!Number.isFinite(chargePower) || chargePower <= 0) {
        setValidationError("EV バスは charge_power_kw を正の数で入力してください");
        setActiveTab("ev");
        return;
      }
    } else {
      const fuelTank = Number(form.fuelTankL || "0");
      if (!Number.isFinite(fuelTank) || fuelTank <= 0) {
        setValidationError("エンジンバスは fuel_tank_l を正の数で入力してください");
        setActiveTab("engine");
        return;
      }
    }

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

  const handleDelete = () => {
    if (!vehicleId) return;
    if (!confirm(t("vehicles.delete_confirm", "この車両を削除しますか？"))) return;
    deleteVehicle.mutate(vehicleId, {
      onSuccess: () => closeDrawer(),
    });
  };

  const handleDuplicateBatch = () => {
    if (!vehicleId) return;
    duplicateVehicleBatch.mutate(
      {
        quantity: Math.max(1, Number(duplicateQuantity) || 1),
        targetDepotId: duplicateTargetDepotId || vehicle?.depotId,
      },
      {
        onSuccess: (response) => {
          setDuplicateQuantity("1");
          if (response.items[0]?.id) {
            selectVehicle(response.items[0].id);
          }
        },
      },
    );
  };

  const isSaving =
    createVehicle.isPending ||
    createVehicleBatch.isPending ||
    updateVehicle.isPending;

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

      {validationError && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {validationError}
        </div>
      )}

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
              <div className="mt-2 text-[11px] text-slate-500">
                <Link
                  to={`/scenarios/${scenarioId}/vehicle-templates`}
                  className="font-medium text-primary-700 hover:text-primary-800"
                >
                  {t("vehicles.template_manage_link", "テンプレート管理ページを開く")}
                </Link>
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
                  "複製先営業所で許可されている路線のみ引き継いで追加します。",
                )}
              </p>
              <div className="grid gap-2 sm:grid-cols-[120px_minmax(0,1fr)_auto]">
                <input
                  type="number"
                  min="1"
                  value={duplicateQuantity}
                  onChange={(e) => setDuplicateQuantity(e.target.value)}
                  className="field-input max-w-28"
                />
                <select
                  value={duplicateTargetDepotId}
                  onChange={(e) => setDuplicateTargetDepotId(e.target.value)}
                  className="field-input"
                >
                  {depots.map((depot) => (
                    <option key={depot.id} value={depot.id}>
                      {depot.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleDuplicateBatch}
                  disabled={duplicateVehicleBatch.isPending || !duplicateTargetDepotId}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {duplicateVehicleBatch.isPending
                    ? t("vehicles.duplicate_many_running", "複製中...")
                    : t("vehicles.duplicate_many_button", "複数台複製")}
                </button>
              </div>
              <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                <p className="font-medium text-slate-700">
                  {t("vehicles.duplicate_route_preview", "路線権限プレビュー")}
                </p>
                {!sourceVehicleRouteIds.length ? (
                  <p className="mt-1 text-slate-500">
                    {t(
                      "vehicles.duplicate_route_preview_empty",
                      "元車両に個別の route 権限がないため、追加の引き継ぎはありません。",
                    )}
                  </p>
                ) : !targetDepotHasRouteRules ? (
                  <p className="mt-1 text-slate-500">
                    {t(
                      "vehicles.duplicate_route_preview_unrestricted",
                      "複製先営業所に route 制限が未設定のため、現在の route 権限をそのまま引き継ぎます。",
                    )}
                  </p>
                ) : (
                  <div className="mt-2 grid gap-2 md:grid-cols-2">
                    <div className="rounded border border-emerald-100 bg-emerald-50/60 px-2 py-2">
                      <p className="font-medium text-emerald-800">
                        {t("vehicles.duplicate_route_preview_kept", "引き継ぐ route")}
                        {" "}
                        ({duplicateRoutePreview.kept.length})
                      </p>
                      <p className="mt-1 text-emerald-700">
                        {duplicateRoutePreview.keptNames.join(", ") ||
                          t("vehicles.duplicate_route_preview_none", "なし")}
                      </p>
                    </div>
                    <div className="rounded border border-amber-100 bg-amber-50/60 px-2 py-2">
                      <p className="font-medium text-amber-800">
                        {t("vehicles.duplicate_route_preview_dropped", "落ちる route")}
                        {" "}
                        ({duplicateRoutePreview.dropped.length})
                      </p>
                      <p className="mt-1 text-amber-700">
                        {duplicateRoutePreview.droppedNames.join(", ") ||
                          t("vehicles.duplicate_route_preview_none", "なし")}
                      </p>
                    </div>
                  </div>
                )}
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
