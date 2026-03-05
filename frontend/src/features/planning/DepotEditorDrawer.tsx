// ── DepotEditorDrawer ─────────────────────────────────────────
// Editor drawer for creating / editing a depot.

import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { EditorDrawer } from "@/features/common/EditorDrawer";
import { DrawerTabs } from "@/features/common/DrawerTabs";
import { useMasterUiStore } from "@/stores/master-ui-store";
import {
  useDepot,
  useCreateDepot,
  useUpdateDepot,
  useDeleteDepot,
} from "@/hooks";
import type { Depot } from "@/types";
import type { CreateDepotRequest, UpdateDepotRequest } from "@/types/api";

interface Props {
  scenarioId: string;
  depotId: string | null;
  isCreate: boolean;
}

type FormData = {
  name: string;
  location: string;
  lat: string;
  lon: string;
  normalChargerCount: string;
  normalChargerPowerKw: string;
  fastChargerCount: string;
  fastChargerPowerKw: string;
  hasFuelFacility: boolean;
  parkingCapacity: string;
  overnightCharging: boolean;
  notes: string;
};

const EMPTY_FORM: FormData = {
  name: "",
  location: "",
  lat: "",
  lon: "",
  normalChargerCount: "0",
  normalChargerPowerKw: "0",
  fastChargerCount: "0",
  fastChargerPowerKw: "0",
  hasFuelFacility: false,
  parkingCapacity: "0",
  overnightCharging: false,
  notes: "",
};

function depotToForm(depot: Depot): FormData {
  return {
    name: depot.name,
    location: depot.location,
    lat: depot.lat ? String(depot.lat) : "",
    lon: depot.lon ? String(depot.lon) : "",
    normalChargerCount: String(depot.normalChargerCount),
    normalChargerPowerKw: String(depot.normalChargerPowerKw),
    fastChargerCount: String(depot.fastChargerCount),
    fastChargerPowerKw: String(depot.fastChargerPowerKw),
    hasFuelFacility: depot.hasFuelFacility,
    parkingCapacity: String(depot.parkingCapacity),
    overnightCharging: depot.overnightCharging,
    notes: depot.notes,
  };
}

const TABS = [
  { key: "basic", label: "基本情報" },
  { key: "charging", label: "充電設備" },
  { key: "notes", label: "メモ" },
];

export function DepotEditorDrawer({ scenarioId, depotId, isCreate }: Props) {
  const { t } = useTranslation();
  const closeDrawer = useMasterUiStore((s) => s.closeDrawer);
  const setDirty = useMasterUiStore((s) => s.setDirty);
  const isDirty = useMasterUiStore((s) => s.isDirty);

  const { data: depot } = useDepot(scenarioId, depotId ?? "");
  const createDepot = useCreateDepot(scenarioId);
  const updateDepot = useUpdateDepot(scenarioId, depotId ?? "");
  const deleteDepot = useDeleteDepot(scenarioId);

  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [activeTab, setActiveTab] = useState("basic");

  // Populate form when depot data loads
  useEffect(() => {
    if (isCreate) {
      setForm(EMPTY_FORM);
    } else if (depot) {
      setForm(depotToForm(depot));
    }
  }, [depot, isCreate]);

  const updateField = useCallback(
    <K extends keyof FormData>(key: K, value: FormData[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
      setDirty(true);
    },
    [setDirty],
  );

  const handleSave = () => {
    if (isCreate) {
      const req: CreateDepotRequest = {
        name: form.name || "新規営業所",
        location: form.location,
        lat: form.lat ? Number(form.lat) : undefined,
        lon: form.lon ? Number(form.lon) : undefined,
        normalChargerCount: Number(form.normalChargerCount) || 0,
        normalChargerPowerKw: Number(form.normalChargerPowerKw) || 0,
        fastChargerCount: Number(form.fastChargerCount) || 0,
        fastChargerPowerKw: Number(form.fastChargerPowerKw) || 0,
        hasFuelFacility: form.hasFuelFacility,
        parkingCapacity: Number(form.parkingCapacity) || 0,
        overnightCharging: form.overnightCharging,
        notes: form.notes,
      };
      createDepot.mutate(req, {
        onSuccess: () => closeDrawer(),
      });
    } else if (depotId) {
      const req: UpdateDepotRequest = {
        name: form.name,
        location: form.location,
        lat: form.lat ? Number(form.lat) : undefined,
        lon: form.lon ? Number(form.lon) : undefined,
        normalChargerCount: Number(form.normalChargerCount) || 0,
        normalChargerPowerKw: Number(form.normalChargerPowerKw) || 0,
        fastChargerCount: Number(form.fastChargerCount) || 0,
        fastChargerPowerKw: Number(form.fastChargerPowerKw) || 0,
        hasFuelFacility: form.hasFuelFacility,
        parkingCapacity: Number(form.parkingCapacity) || 0,
        overnightCharging: form.overnightCharging,
        notes: form.notes,
      };
      updateDepot.mutate(req, {
        onSuccess: () => {
          setDirty(false);
        },
      });
    }
  };

  const handleDelete = () => {
    if (!depotId) return;
    if (!confirm(t("depots.delete_confirm", "この営業所を削除しますか？"))) return;
    deleteDepot.mutate(depotId, {
      onSuccess: () => closeDrawer(),
    });
  };

  const isSaving = createDepot.isPending || updateDepot.isPending;

  return (
    <EditorDrawer
      open
      title={isCreate ? t("depots.create_title", "営業所を追加") : form.name || "営業所"}
      subtitle={depotId ?? undefined}
      onClose={closeDrawer}
      onSave={handleSave}
      onDelete={!isCreate && depotId ? handleDelete : undefined}
      isDirty={isDirty}
      isSaving={isSaving}
    >
      <DrawerTabs tabs={TABS} activeKey={activeTab} onChange={setActiveTab} />

      {activeTab === "basic" && (
        <div className="space-y-4">
          <Field label={t("depots.field_name", "名前")}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => updateField("name", e.target.value)}
              className="field-input"
              placeholder="営業所名"
            />
          </Field>
          <Field label={t("depots.field_location", "住所")}>
            <input
              type="text"
              value={form.location}
              onChange={(e) => updateField("location", e.target.value)}
              className="field-input"
              placeholder="住所"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("depots.field_lat", "緯度")}>
              <input
                type="number"
                step="any"
                value={form.lat}
                onChange={(e) => updateField("lat", e.target.value)}
                className="field-input"
                placeholder="35.6812"
              />
            </Field>
            <Field label={t("depots.field_lon", "経度")}>
              <input
                type="number"
                step="any"
                value={form.lon}
                onChange={(e) => updateField("lon", e.target.value)}
                className="field-input"
                placeholder="139.7671"
              />
            </Field>
          </div>
          <Field label={t("depots.field_parking", "駐車台数")}>
            <input
              type="number"
              min="0"
              value={form.parkingCapacity}
              onChange={(e) => updateField("parkingCapacity", e.target.value)}
              className="field-input"
            />
          </Field>
          <CheckboxField
            label={t("depots.field_fuel", "燃料設備あり")}
            checked={form.hasFuelFacility}
            onChange={(v) => updateField("hasFuelFacility", v)}
          />
        </div>
      )}

      {activeTab === "charging" && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("depots.field_normal_count", "普通充電器数")}>
              <input
                type="number"
                min="0"
                value={form.normalChargerCount}
                onChange={(e) => updateField("normalChargerCount", e.target.value)}
                className="field-input"
              />
            </Field>
            <Field label={t("depots.field_normal_power", "普通充電出力 (kW)")}>
              <input
                type="number"
                min="0"
                step="any"
                value={form.normalChargerPowerKw}
                onChange={(e) => updateField("normalChargerPowerKw", e.target.value)}
                className="field-input"
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("depots.field_fast_count", "急速充電器数")}>
              <input
                type="number"
                min="0"
                value={form.fastChargerCount}
                onChange={(e) => updateField("fastChargerCount", e.target.value)}
                className="field-input"
              />
            </Field>
            <Field label={t("depots.field_fast_power", "急速充電出力 (kW)")}>
              <input
                type="number"
                min="0"
                step="any"
                value={form.fastChargerPowerKw}
                onChange={(e) => updateField("fastChargerPowerKw", e.target.value)}
                className="field-input"
              />
            </Field>
          </div>
          <CheckboxField
            label={t("depots.field_overnight", "夜間充電")}
            checked={form.overnightCharging}
            onChange={(v) => updateField("overnightCharging", v)}
          />
        </div>
      )}

      {activeTab === "notes" && (
        <div className="space-y-4">
          <Field label={t("depots.field_notes", "メモ")}>
            <textarea
              value={form.notes}
              onChange={(e) => updateField("notes", e.target.value)}
              rows={6}
              className="field-input resize-none"
              placeholder="自由記述メモ"
            />
          </Field>
        </div>
      )}
    </EditorDrawer>
  );
}

// ── Shared field components (local) ──────────────────────────

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
