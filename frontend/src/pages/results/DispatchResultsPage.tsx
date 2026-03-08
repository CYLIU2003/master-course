import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useDispatchPlan, useDutyValidation } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";

export function DispatchResultsPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: plan, isLoading, error } = useDispatchPlan(scenarioId!);
  const { data: validation } = useDutyValidation(scenarioId!);

  if (isLoading) {
    return <LoadingBlock message={t("dispatch_results.description")} />;
  }
  if (error && !error.message.includes("404")) {
    return <ErrorBlock message={error.message} />;
  }
  if (!plan) {
    return (
      <PageSection title={t("dispatch_results.title")} description={t("dispatch_results.description")}>
        <EmptyState
          title={t("dispatch_results.placeholder")}
          description="Build dispatch plan を実行すると summary が表示されます。"
        />
      </PageSection>
    );
  }

  const invalidCount = (validation?.items ?? []).filter((item) => !item.valid).length;
  const planCount = plan.total_plans ?? 0;

  return (
    <PageSection title={t("dispatch_results.title")} description={t("dispatch_results.description")}>
      <div className="grid gap-3 md:grid-cols-4">
        <StatCard label="Plans" value={planCount} />
        <StatCard label="Blocks" value={plan.total_blocks} />
        <StatCard label="Duties" value={plan.total_duties} />
        <StatCard label="Invalid duties" value={invalidCount} tone={invalidCount > 0 ? "danger" : "ok"} />
      </div>
      <div className="mt-4 rounded-lg border border-border bg-white">
        <div className="border-b border-border px-4 py-3 text-sm font-semibold text-slate-700">
          Vehicle type summary
        </div>
        <div className="divide-y divide-border">
          {plan.plans.map((item) => (
            <div key={item.plan_id} className="flex items-center justify-between px-4 py-3 text-sm">
              <div>
                <div className="font-medium text-slate-800">{item.vehicle_type}</div>
                <div className="text-xs text-slate-500">{item.plan_id}</div>
              </div>
              <div className="flex gap-4 text-xs text-slate-500">
                <span>{item.blocks.length} blocks</span>
                <span>{item.duties.length} duties</span>
                <span>{item.charging_plan.length} charging slots</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </PageSection>
  );
}

function StatCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number | string;
  tone?: "default" | "ok" | "danger";
}) {
  const toneClass =
    tone === "danger" ? "text-rose-600" : tone === "ok" ? "text-emerald-600" : "text-slate-800";
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
