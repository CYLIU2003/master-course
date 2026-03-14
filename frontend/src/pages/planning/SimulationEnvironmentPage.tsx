import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  PageSection,
} from "@/features/common";
import { useScenario } from "@/hooks";

export function SimulationEnvironmentPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: scenario, isLoading, error } = useScenario(scenarioId ?? "");

  if (!scenarioId) return null;
  if (isLoading) {
    return <LoadingBlock message={t("simulation_env.description")} />;
  }
  if (error) {
    return <ErrorBlock message={error.message} />;
  }

  const overlay = scenario?.scenarioOverlay;
  if (!overlay) {
    return (
      <PageSection
        title={t("simulation_env.title")}
        description={t("simulation_env.description")}
      >
        <EmptyState
          title="Scenario overlay 未設定"
          description="Simulation prepare を実行すると、料金・CO2・solver 設定がここに表示されます。"
        />
      </PageSection>
    );
  }

  const touSummary = overlay.cost_coefficients.tou_pricing.length
    ? overlay.cost_coefficients.tou_pricing
        .map(
          (band) =>
            `${band.start_hour}-${band.end_hour}: ${band.price_per_kwh.toFixed(1)} 円/kWh`,
        )
        .join(" / ")
    : "未設定";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-800">
          {t("simulation_env.title")}
        </h1>
        <p className="text-sm text-slate-500">
          {t("simulation_env.description")}
        </p>
      </div>

      <PageSection title="Fleet & Scope" description="Builder で選択された車両・営業所・路線の現在値です。">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <FieldCard label="BEV 台数" value={String(overlay.fleet.n_bev)} />
          <FieldCard label="ICE 台数" value={String(overlay.fleet.n_ice)} />
          <FieldCard label="営業所数" value={String(overlay.depot_ids.length)} />
          <FieldCard label="路線数" value={String(overlay.route_ids.length)} />
        </div>
      </PageSection>

      <PageSection title="Charging" description="デポ上限制約と充電設備パラメータです。">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <FieldCard
            label="充電器同時使用数"
            value={formatOptional(overlay.charging_constraints.max_simultaneous_sessions)}
          />
          <FieldCard
            label="充電出力上限"
            value={formatKw(overlay.charging_constraints.charger_power_limit_kw)}
          />
          <FieldCard
            label="デポ受電上限"
            value={formatKw(overlay.charging_constraints.depot_power_limit_kw)}
          />
          <FieldCard
            label="overnight"
            value={
              overlay.charging_constraints.overnight_window_start &&
              overlay.charging_constraints.overnight_window_end
                ? `${overlay.charging_constraints.overnight_window_start} - ${overlay.charging_constraints.overnight_window_end}`
                : "未設定"
            }
          />
        </div>
      </PageSection>

      <PageSection title="Costs & CO2" description="constant の思想に合わせて持ち上げた料金・排出係数です。">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <FieldCard
            label="買電単価"
            value={formatYenPerKwh(overlay.cost_coefficients.grid_flat_price_per_kwh)}
          />
          <FieldCard
            label="売電単価"
            value={formatYenPerKwh(overlay.cost_coefficients.grid_sell_price_per_kwh)}
          />
          <FieldCard
            label="需要料金"
            value={formatYenPerKw(overlay.cost_coefficients.demand_charge_cost_per_kw)}
          />
          <FieldCard
            label="軽油単価"
            value={`${overlay.cost_coefficients.diesel_price_per_l.toFixed(1)} 円/L`}
          />
          <FieldCard
            label="系統 CO2"
            value={`${overlay.cost_coefficients.grid_co2_kg_per_kwh.toFixed(3)} kg/kWh`}
          />
          <FieldCard
            label="CO2 価格"
            value={`${overlay.cost_coefficients.co2_price_per_kg.toFixed(1)} 円/kg`}
          />
          <FieldCard
            label="PV 有効"
            value={overlay.cost_coefficients.pv_enabled ? "Yes" : "No"}
          />
          <FieldCard
            label="PV scale"
            value={overlay.cost_coefficients.pv_scale.toFixed(2)}
          />
        </div>
        <div className="mt-4 rounded-lg border border-border bg-white p-4">
          <div className="text-xs font-medium text-slate-500">TOU pricing</div>
          <div className="mt-1 text-sm text-slate-700">{touSummary}</div>
        </div>
      </PageSection>

      <PageSection title="Solver" description="最適化モードと緩和設定です。">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <FieldCard label="Solver mode" value={overlay.solver_config.mode} />
          <FieldCard label="Objective mode" value={overlay.solver_config.objective_mode} />
          <FieldCard
            label="Allow partial"
            value={overlay.solver_config.allow_partial_service ? "Yes" : "No"}
          />
          <FieldCard
            label="Unserved penalty"
            value={`${overlay.solver_config.unserved_penalty.toFixed(0)} 円`}
          />
          <FieldCard
            label="Time limit"
            value={`${overlay.solver_config.time_limit_seconds}s`}
          />
          <FieldCard label="MIP gap" value={overlay.solver_config.mip_gap.toString()} />
          <FieldCard
            label="ALNS iter"
            value={overlay.solver_config.alns_iterations.toString()}
          />
          <FieldCard label="Random seed" value={String(scenario?.randomSeed ?? "-")} />
        </div>
      </PageSection>
    </div>
  );
}

function FieldCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 text-sm font-medium text-slate-700">{value}</p>
    </div>
  );
}

function formatOptional(value: number | null | undefined): string {
  return value == null ? "未設定" : String(value);
}

function formatKw(value: number | null | undefined): string {
  return value == null ? "未設定" : `${value.toFixed(1)} kW`;
}

function formatYenPerKwh(value: number | null | undefined): string {
  return value == null ? "未設定" : `${value.toFixed(1)} 円/kWh`;
}

function formatYenPerKw(value: number | null | undefined): string {
  return value == null ? "未設定" : `${value.toFixed(1)} 円/kW`;
}
