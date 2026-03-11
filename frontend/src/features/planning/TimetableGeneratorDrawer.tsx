// ── TimetableGeneratorDrawer ──────────────────────────────────
// Interval-based trip generator.
// Generates equally-spaced trips between start_time and end_time
// at interval_min minutes and appends them to the scenario timetable.

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { EditorDrawer } from "@/features/common/EditorDrawer";
import { useUpdateTimetable } from "@/hooks";
import { scenarioApi } from "@/api/scenario";
import type { TimetableRow } from "@/types";

// ── helpers ───────────────────────────────────────────────────

/** Parse "HH:MM" → total minutes (supports values ≥ 24:00) */
function parseHHMM(s: string): number {
  const [h, m] = s.split(":").map(Number);
  return h * 60 + (m || 0);
}

/** Format total minutes → "HH:MM" (supports values ≥ 24:00) */
function formatHHMM(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

interface GeneratorForm {
  route_id: string;
  service_id: string;
  direction: "outbound" | "inbound";
  origin: string;
  destination: string;
  start_time: string;
  end_time: string;
  interval_min: number;
  trip_duration_min: number;
  distance_km: number;
  allowed_vehicle_types: string;
}

const EMPTY_FORM: GeneratorForm = {
  route_id: "",
  service_id: "WEEKDAY",
  direction: "outbound",
  origin: "",
  destination: "",
  start_time: "06:00",
  end_time: "22:00",
  interval_min: 20,
  trip_duration_min: 60,
  distance_km: 0,
  allowed_vehicle_types: "BEV;ICE",
};

function generateRows(form: GeneratorForm, startIndex: number): TimetableRow[] {
  const startMin = parseHHMM(form.start_time);
  const endMin = parseHHMM(form.end_time);
  const avt = form.allowed_vehicle_types
    .split(/[;,]/)
    .map((s) => s.trim())
    .filter(Boolean);

  const rows: TimetableRow[] = [];
  let dep = startMin;
  let idx = startIndex;

  while (dep <= endMin) {
    rows.push({
      route_id: form.route_id,
      service_id: form.service_id,
      direction: form.direction,
      trip_index: idx++,
      origin: form.origin,
      destination: form.destination,
      departure: formatHHMM(dep),
      arrival: formatHHMM(dep + form.trip_duration_min),
      distance_km: form.distance_km,
      allowed_vehicle_types: avt.length > 0 ? avt : ["BEV", "ICE"],
    });
    dep += form.interval_min;
  }
  return rows;
}

// ── Props ─────────────────────────────────────────────────────

interface Props {
  open: boolean;
  scenarioId: string;
  defaultServiceId: string;
  existingRowCount: number;
  onClose: () => void;
}

// ── Component ─────────────────────────────────────────────────

export function TimetableGeneratorDrawer({
  open,
  scenarioId,
  defaultServiceId,
  existingRowCount,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const updateTimetable = useUpdateTimetable(scenarioId);

  const [form, setForm] = useState<GeneratorForm>(() => ({
    ...EMPTY_FORM,
    service_id: defaultServiceId,
  }));

  function set<K extends keyof GeneratorForm>(key: K, val: GeneratorForm[K]) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  const preview = generateRows(form, existingRowCount);

  async function handleSave() {
    const current = await scenarioApi.getTimetable(scenarioId);
    const updated = [...(current.items ?? []), ...preview];
    updateTimetable.mutate({ rows: updated }, { onSuccess: onClose });
  }

  const isDirty =
    form.route_id !== EMPTY_FORM.route_id ||
    form.origin !== EMPTY_FORM.origin ||
    form.destination !== EMPTY_FORM.destination;

  return (
    <EditorDrawer
      open={open}
      title={t("timetable.generate_title")}
      subtitle={`${preview.length} trips will be generated`}
      onClose={onClose}
      onSave={handleSave}
      isDirty={isDirty}
      isSaving={updateTimetable.isPending}
      width="w-[520px]"
    >
      <div className="flex flex-col gap-4 p-4">
        {/* Route & service */}
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-slate-600">{t("timetable.col_route")}</span>
            <input
              className="rounded border border-border px-2 py-1 text-xs"
              value={form.route_id}
              placeholder="e.g. R01"
              onChange={(e) => set("route_id", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-slate-600">{t("timetable.col_service_id")}</span>
            <select
              className="rounded border border-border px-2 py-1 text-xs"
              value={form.service_id}
              onChange={(e) => set("service_id", e.target.value)}
            >
              <option value="WEEKDAY">WEEKDAY</option>
              <option value="SAT">SAT</option>
              <option value="SAT_HOL">SAT_HOL</option>
              <option value="SUN_HOL">SUN_HOL</option>
            </select>
          </label>
        </div>

        {/* Direction */}
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-semibold text-slate-600">{t("timetable.col_dir")}</span>
          <select
            className="rounded border border-border px-2 py-1 text-xs"
            value={form.direction}
            onChange={(e) =>
              set("direction", e.target.value as "outbound" | "inbound")
            }
          >
            <option value="outbound">outbound</option>
            <option value="inbound">inbound</option>
          </select>
        </label>

        {/* Origin / Destination */}
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-slate-600">{t("timetable.col_origin")}</span>
            <input
              className="rounded border border-border px-2 py-1 text-xs"
              value={form.origin}
              placeholder="Stop A"
              onChange={(e) => set("origin", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-slate-600">{t("timetable.col_dest")}</span>
            <input
              className="rounded border border-border px-2 py-1 text-xs"
              value={form.destination}
              placeholder="Stop B"
              onChange={(e) => set("destination", e.target.value)}
            />
          </label>
        </div>

        {/* Timing */}
        <div className="grid grid-cols-3 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-slate-600">Start time</span>
            <input
              className="rounded border border-border px-2 py-1 font-mono text-xs"
              value={form.start_time}
              placeholder="HH:MM"
              onChange={(e) => set("start_time", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-slate-600">End time</span>
            <input
              className="rounded border border-border px-2 py-1 font-mono text-xs"
              value={form.end_time}
              placeholder="HH:MM"
              onChange={(e) => set("end_time", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-slate-600">Interval (min)</span>
            <input
              type="number"
              min={1}
              className="rounded border border-border px-2 py-1 text-xs"
              value={form.interval_min}
              onChange={(e) => set("interval_min", parseInt(e.target.value) || 20)}
            />
          </label>
        </div>

        {/* Trip duration & distance */}
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-slate-600">Trip duration (min)</span>
            <input
              type="number"
              min={1}
              className="rounded border border-border px-2 py-1 text-xs"
              value={form.trip_duration_min}
              onChange={(e) =>
                set("trip_duration_min", parseInt(e.target.value) || 60)
              }
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-slate-600">{t("timetable.col_dist")}</span>
            <input
              type="number"
              min={0}
              step={0.1}
              className="rounded border border-border px-2 py-1 text-xs"
              value={form.distance_km}
              onChange={(e) =>
                set("distance_km", parseFloat(e.target.value) || 0)
              }
            />
          </label>
        </div>

        {/* Allowed vehicle types */}
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-semibold text-slate-600">
            {t("timetable.col_vehicle_types")} (semicolon-separated)
          </span>
          <input
            className="rounded border border-border px-2 py-1 text-xs"
            value={form.allowed_vehicle_types}
            placeholder="BEV;ICE"
            onChange={(e) => set("allowed_vehicle_types", e.target.value)}
          />
        </label>

        {/* Preview summary */}
        <div className="rounded-lg border border-border bg-surface-sunken p-3 text-xs text-slate-600">
          <span className="font-semibold">{t("timetable.generate")}:</span>{" "}
          {preview.length > 0 ? (
            <>
              <span className="text-primary-700 font-semibold">{preview.length}</span> trips
              {preview.length > 0 && (
                <span className="ml-2 text-slate-400">
                  ({preview[0]?.departure} → {preview[preview.length - 1]?.departure})
                </span>
              )}
            </>
          ) : (
            <span className="text-slate-400">0 trips (check start/end/interval)</span>
          )}
        </div>
      </div>
    </EditorDrawer>
  );
}
