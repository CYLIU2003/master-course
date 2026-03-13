import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useScenarios, useCreateScenario, useDeleteScenario } from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { formatDate } from "@/utils/format";
import { appApi } from "@/api/app";
import { fetchMaybeJson } from "@/api/client";

export function ScenarioListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, isLoading, error } = useScenarios();
  const { data: datasetsData, error: datasetsError } = useQuery({
    queryKey: ["app", "datasets"],
    queryFn: appApi.listDatasets,
  });
  const createMutation = useCreateScenario();
  const deleteMutation = useDeleteScenario();

  if (isLoading) return <LoadingBlock message={t("scenarios.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const scenarios = data?.items ?? [];
  const datasets = datasetsData?.items ?? [];
  const defaultDatasetId = datasetsData?.defaultDatasetId ?? "tokyu_core";
  const orderedDatasets = [...datasets].sort((a, b) => {
    if (a.datasetId === defaultDatasetId) return -1;
    if (b.datasetId === defaultDatasetId) return 1;
    return a.datasetId.localeCompare(b.datasetId);
  });

  async function activateAndOpen(scenarioId: string) {
    await fetchMaybeJson(`/api/scenarios/${scenarioId}/activate`, { method: "POST" });
    navigate(`/scenarios/${scenarioId}/planning`);
  }

  async function createFromDataset(datasetId: string) {
    const created = await createMutation.mutateAsync({
      name: `${datasetId === "tokyu_core" ? "Tokyu Core" : "Tokyu Full"} Scenario ${scenarios.length + 1}`,
      description: "",
      mode: "mode_B_resource_assignment",
      datasetId,
      randomSeed: 42,
    });
    await activateAndOpen(created.id);
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Tokyu Bus Research Cases</h1>
        <p className="mt-1 text-sm text-slate-500">
          Step 1: choose a prepared Tokyu dataset, then open or create a scenario.
        </p>
      </div>

      <div className="mb-8 grid gap-4 md:grid-cols-2">
        {orderedDatasets.map((dataset) => (
          <section
            key={dataset.datasetId}
            className="rounded-xl border border-border bg-surface-raised p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-800">{dataset.datasetId}</p>
                <p className="mt-1 text-xs text-slate-500">{dataset.description}</p>
              </div>
              <span
                className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                  dataset.builtAvailable
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-amber-50 text-amber-700"
                }`}
              >
                {dataset.builtAvailable ? "built ready" : "seed only"}
              </span>
            </div>
            <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
              <div>dataset version: {dataset.datasetVersion}</div>
              <div>depots: {dataset.includedDepots.join(", ")}</div>
            </div>
            {dataset.warning ? (
              <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
                {dataset.warning}
              </p>
            ) : null}
            <div className="mt-4 flex items-center justify-between">
              <p className="text-[11px] text-slate-500">
                random seed defaults to `42` and can be changed in the scenario.
              </p>
              <button
                onClick={() => void createFromDataset(dataset.datasetId)}
                disabled={createMutation.isPending}
                className="rounded-md bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
              >
                {createMutation.isPending ? t("scenarios.creating") : "Create"}
              </button>
            </div>
          </section>
        ))}
        {datasetsError ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700 md:col-span-2">
            {datasetsError.message}
          </div>
        ) : null}
      </div>

      {scenarios.length === 0 ? (
        <EmptyState
          title={t("scenarios.no_scenarios")}
          description={t("scenarios.create_first")}
        />
      ) : (
        <ul className="space-y-2">
          {scenarios.map((s) => (
            <li
              key={s.id}
              className="flex items-center justify-between rounded-lg border border-border bg-surface-raised px-4 py-3 hover:border-primary-200"
            >
              <div className="flex-1 text-left">
                <p className="text-sm font-medium text-slate-800">{s.name}</p>
                <p className="text-xs text-slate-400">
                  {s.datasetId ?? "tokyu_core"} &middot; {s.mode} &middot; {s.status} &middot; {formatDate(s.updatedAt)}
                </p>
              </div>
              <div className="ml-3 flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => void activateAndOpen(s.id)}
                  className="rounded-md border border-primary-200 px-3 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-50"
                >
                  {t("common.open", "開く")}
                </button>
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    if (confirm(t("scenarios.delete_confirm", { name: s.name })))
                      deleteMutation.mutate(s.id);
                  }}
                  className="text-xs text-red-400 hover:text-red-600"
                >
                  {t("common.delete")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
