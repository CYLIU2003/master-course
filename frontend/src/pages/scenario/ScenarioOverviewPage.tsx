import { Link, useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useScenario, useDeleteScenario } from "@/hooks";
import { PageSection, LoadingBlock, ErrorBlock } from "@/features/common";
import { isIncompleteArtifactError } from "@/api/client";

export function ScenarioOverviewPage() {
  const { t } = useTranslation();
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { data: scenario, isLoading, error } = useScenario(scenarioId!);

  if (isLoading) return <LoadingBlock />;

  if (error && isIncompleteArtifactError(error)) {
    return (
      <IncompleteArtifactBanner
        scenarioId={scenarioId!}
        message={error.message}
      />
    );
  }

  if (error) return <ErrorBlock message={error.message} />;
  if (!scenario) return null;

  return (
    <div>
      <PageSection title={scenario.name} description={scenario.description}>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <InfoCard label="Operator" value={scenario.operatorId} />
          <InfoCard label="Dataset" value={scenario.datasetId ?? "tokyu_core"} />
          <InfoCard label="Dataset Version" value={scenario.datasetVersion ?? "unknown"} />
          <InfoCard label="Random Seed" value={String(scenario.randomSeed ?? 42)} />
          <InfoCard label={t("scenarios.mode")} value={scenario.mode} />
          <InfoCard label={t("scenarios.status")} value={scenario.status} />
          <InfoCard label={t("scenarios.created")} value={scenario.createdAt} />
          <InfoCard label={t("scenarios.updated")} value={scenario.updatedAt} />
        </div>
        {scenario.datasetStatus?.warning ? (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {scenario.datasetStatus.warning}
          </div>
        ) : null}
      </PageSection>

      <PageSection
        title={t("scenarios.pipeline_progress")}
        description={t("scenarios.pipeline_description")}
      >
        <div className="grid gap-3 md:grid-cols-3">
          <QuickLinkCard
            title="Step 2 Setup"
            description="Depots, routes, fleet, charging, and solver parameters."
            to={`/scenarios/${scenario.id}/planning`}
          />
          <QuickLinkCard
            title="Step 3 Execute"
            description="Build dispatch artifacts, run simulation, and launch optimization."
            to={`/scenarios/${scenario.id}/simulation`}
          />
          <QuickLinkCard
            title="Step 4 Results"
            description="Review duties, KPI, and reproducibility metadata."
            to={`/scenarios/${scenario.id}/results/dispatch`}
          />
        </div>
      </PageSection>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-sm font-medium text-slate-700 truncate">
        {value}
      </p>
    </div>
  );
}

function QuickLinkCard({
  title,
  description,
  to,
}: {
  title: string;
  description: string;
  to: string;
}) {
  return (
    <Link
      to={to}
      className="rounded-lg border border-border bg-surface-raised p-4 text-left transition hover:border-primary-200 hover:bg-primary-50/40"
    >
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      <p className="mt-1 text-xs text-slate-500">{description}</p>
    </Link>
  );
}

function IncompleteArtifactBanner({
  scenarioId,
  message,
}: {
  scenarioId: string;
  message: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const deleteMutation = useDeleteScenario();

  async function handleDelete() {
    if (
      !window.confirm(
        t(
          "scenarios.incomplete_delete_confirm",
          "このシナリオを削除して一覧に戻りますか？",
        ),
      )
    ) {
      return;
    }
    try {
      await deleteMutation.mutateAsync(scenarioId);
      navigate("/scenarios");
    } catch {
      // Delete itself failed — navigate away regardless so the UI doesn't stay stuck
      navigate("/scenarios");
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-6">
        {/* Icon row */}
        <div className="flex items-start gap-3">
          <span className="mt-0.5 text-xl text-amber-500" aria-hidden>
            ⚠️
          </span>
          <div className="flex-1">
            <h2 className="text-base font-semibold text-amber-900">
              {t(
                "scenarios.incomplete_title",
                "シナリオの保存が中断されました",
              )}
            </h2>
            <p className="mt-1 text-sm text-amber-800">
              {t(
                "scenarios.incomplete_description",
                "前回の保存処理が途中で中断されたため、このシナリオは使用できない状態です。シナリオを削除して再作成してください。",
              )}
            </p>
            {/* Technical detail (collapsed-style) */}
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-amber-700 hover:text-amber-900">
                {t("common.technical_detail", "技術的な詳細")}
              </summary>
              <pre className="mt-2 overflow-auto rounded bg-amber-100 px-3 py-2 text-xs text-amber-800">
                {message}
              </pre>
            </details>
          </div>
        </div>

        {/* Action row */}
        <div className="mt-5 flex items-center gap-3">
          <button
            type="button"
            onClick={() => void handleDelete()}
            disabled={deleteMutation.isPending}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            {deleteMutation.isPending
              ? t("common.deleting", "削除中…")
              : t("scenarios.delete_and_back", "削除して一覧に戻る")}
          </button>
          <button
            type="button"
            onClick={() => navigate("/scenarios")}
            className="rounded-md border border-amber-300 bg-white px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-50"
          >
            {t("common.back_to_list", "一覧に戻る")}
          </button>
        </div>
      </div>
    </div>
  );
}
