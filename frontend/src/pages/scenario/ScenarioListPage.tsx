import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useScenarios, useCreateScenario, useDeleteScenario } from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { formatDate } from "@/utils/format";

export function ScenarioListPage() {
  const { t } = useTranslation();
  const { data, isLoading, error } = useScenarios();
  const createMutation = useCreateScenario();
  const deleteMutation = useDeleteScenario();

  if (isLoading) return <LoadingBlock message={t("scenarios.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  const scenarios = data?.items ?? [];

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800">{t("scenarios.title")}</h1>
        <button
          onClick={() =>
            createMutation.mutate({
              name: `Scenario ${scenarios.length + 1}`,
              description: "",
              mode: "mode_B_resource_assignment",
            })
          }
          disabled={createMutation.isPending}
          className="rounded-md bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {createMutation.isPending ? t("scenarios.creating") : t("scenarios.new_scenario")}
        </button>
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
              <Link
                to={`/scenarios/${s.id}`}
                className="flex-1"
              >
                <p className="text-sm font-medium text-slate-800">{s.name}</p>
                <p className="text-xs text-slate-400">
                  {s.mode} &middot; {s.status} &middot; {formatDate(s.updatedAt)}
                </p>
              </Link>
              <button
                onClick={(e) => {
                  e.preventDefault();
                  if (confirm(t("scenarios.delete_confirm", { name: s.name })))
                    deleteMutation.mutate(s.id);
                }}
                className="ml-3 text-xs text-red-400 hover:text-red-600"
              >
                {t("common.delete")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
