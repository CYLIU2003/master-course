// ── RouteEditorDrawer ─────────────────────────────────────────
// Editor drawer for creating / editing a route.
// Supports tabbed sections: basic info, stops/edges (future).

import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { EditorDrawer } from "@/features/common/EditorDrawer";
import { DrawerTabs } from "@/features/common/DrawerTabs";
import { useMasterUiStore } from "@/stores/master-ui-store";
import {
  useRoute,
  useCreateRoute,
  useUpdateRoute,
  useDeleteRoute,
} from "@/hooks";
import type { Route } from "@/types";
import type { CreateRouteRequest, UpdateRouteRequest } from "@/types/api";

interface Props {
  scenarioId: string;
  routeId: string | null;
  isCreate: boolean;
}

type FormData = {
  name: string;
  startStop: string;
  endStop: string;
  distanceKm: string;
  durationMin: string;
  color: string;
  enabled: boolean;
};

const EMPTY_FORM: FormData = {
  name: "",
  startStop: "",
  endStop: "",
  distanceKm: "0",
  durationMin: "0",
  color: "#3b82f6",
  enabled: true,
};

function routeToForm(r: Route): FormData {
  return {
    name: r.name,
    startStop: r.startStop,
    endStop: r.endStop,
    distanceKm: String(r.distanceKm),
    durationMin: String(r.durationMin),
    color: r.color || "#3b82f6",
    enabled: r.enabled,
  };
}

const TABS = [
  { key: "basic", label: "基本情報" },
  { key: "stops", label: "停留所" },
];

export function RouteEditorDrawer({ scenarioId, routeId, isCreate }: Props) {
  const { t } = useTranslation();
  const closeDrawer = useMasterUiStore((s) => s.closeDrawer);
  const setDirty = useMasterUiStore((s) => s.setDirty);
  const isDirty = useMasterUiStore((s) => s.isDirty);

  const { data: route } = useRoute(scenarioId, routeId ?? "");
  const createRoute = useCreateRoute(scenarioId);
  const updateRoute = useUpdateRoute(scenarioId, routeId ?? "");
  const deleteRoute = useDeleteRoute(scenarioId);

  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [activeTab, setActiveTab] = useState("basic");

  useEffect(() => {
    if (isCreate) {
      setForm(EMPTY_FORM);
    } else if (route) {
      setForm(routeToForm(route));
    }
  }, [route, isCreate]);

  const updateField = useCallback(
    <K extends keyof FormData>(key: K, value: FormData[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
      setDirty(true);
    },
    [setDirty],
  );

  const handleSave = () => {
    if (isCreate) {
      const req: CreateRouteRequest = {
        name: form.name || "新規路線",
        startStop: form.startStop,
        endStop: form.endStop,
        distanceKm: Number(form.distanceKm) || 0,
        durationMin: Number(form.durationMin) || 0,
        color: form.color,
        enabled: form.enabled,
      };
      createRoute.mutate(req, {
        onSuccess: () => closeDrawer(),
      });
    } else if (routeId) {
      const req: UpdateRouteRequest = {
        name: form.name,
        startStop: form.startStop,
        endStop: form.endStop,
        distanceKm: Number(form.distanceKm) || 0,
        durationMin: Number(form.durationMin) || 0,
        color: form.color,
        enabled: form.enabled,
      };
      updateRoute.mutate(req, {
        onSuccess: () => setDirty(false),
      });
    }
  };

  const handleDelete = () => {
    if (!routeId) return;
    if (!confirm(t("routes.delete_confirm", "この路線を削除しますか？"))) return;
    deleteRoute.mutate(routeId, {
      onSuccess: () => closeDrawer(),
    });
  };

  const isSaving = createRoute.isPending || updateRoute.isPending;

  return (
    <EditorDrawer
      open
      title={isCreate ? t("routes.create_title", "路線を追加") : form.name || "路線"}
      subtitle={routeId ?? undefined}
      onClose={closeDrawer}
      onSave={handleSave}
      onDelete={!isCreate && routeId ? handleDelete : undefined}
      isDirty={isDirty}
      isSaving={isSaving}
    >
      <DrawerTabs tabs={TABS} activeKey={activeTab} onChange={setActiveTab} />

      {activeTab === "basic" && (
        <div className="space-y-4">
          <Field label={t("routes.field_name", "路線名")}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => updateField("name", e.target.value)}
              className="field-input"
              placeholder="例: 鶴見線"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("routes.field_start", "始点")}>
              <input
                type="text"
                value={form.startStop}
                onChange={(e) => updateField("startStop", e.target.value)}
                className="field-input"
                placeholder="始点停留所"
              />
            </Field>
            <Field label={t("routes.field_end", "終点")}>
              <input
                type="text"
                value={form.endStop}
                onChange={(e) => updateField("endStop", e.target.value)}
                className="field-input"
                placeholder="終点停留所"
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("routes.field_distance", "距離 (km)")}>
              <input
                type="number"
                min="0"
                step="any"
                value={form.distanceKm}
                onChange={(e) => updateField("distanceKm", e.target.value)}
                className="field-input"
              />
            </Field>
            <Field label={t("routes.field_duration", "所要時間 (分)")}>
              <input
                type="number"
                min="0"
                value={form.durationMin}
                onChange={(e) => updateField("durationMin", e.target.value)}
                className="field-input"
              />
            </Field>
          </div>
          <Field label={t("routes.field_color", "表示色")}>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={form.color}
                onChange={(e) => updateField("color", e.target.value)}
                className="h-8 w-8 cursor-pointer rounded border border-border"
              />
              <input
                type="text"
                value={form.color}
                onChange={(e) => updateField("color", e.target.value)}
                className="field-input flex-1"
                placeholder="#3b82f6"
              />
            </div>
          </Field>
          <CheckboxField
            label={t("routes.field_enabled", "有効")}
            checked={form.enabled}
            onChange={(v) => updateField("enabled", v)}
          />
        </div>
      )}

      {activeTab === "stops" && (
        <div className="flex h-40 items-center justify-center text-xs text-slate-400">
          停留所・エッジ編集は Phase 2 で実装予定
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
