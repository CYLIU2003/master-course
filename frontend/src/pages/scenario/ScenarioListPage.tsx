import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useScenarios, useCreateScenario, useDeleteScenario } from "@/hooks";
import { LoadingBlock, ErrorBlock, EmptyState } from "@/features/common";
import { formatDate } from "@/utils/format";
import { appApi } from "@/api/app";
import { scenarioApi } from "@/api/scenario";
import { useUIStore } from "@/stores/ui-store";

type EditingState = {
  id: string;
  name: string;
};

const DATASET_DISPLAY_NAMES: Record<string, string> = {
  tokyu_core: "Tokyu Core (4 depots)",
  tokyu_dispatch_ready: "Tokyu Dispatch Ready (4 depots)",
  tokyu_full: "Tokyu Full (all depots)",
};

const DATASET_SCENARIO_TITLES: Record<string, string> = {
  tokyu_core: "Tokyu Core",
  tokyu_dispatch_ready: "Tokyu Dispatch Ready",
  tokyu_full: "Tokyu Full",
};

function humanizeDatasetId(datasetId: string): string {
  return String(datasetId)
    .split("_")
    .map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : part))
    .join(" ");
}

function datasetDisplayName(datasetId: string): string {
  return DATASET_DISPLAY_NAMES[datasetId] ?? humanizeDatasetId(datasetId);
}

function datasetScenarioTitle(datasetId: string): string {
  return DATASET_SCENARIO_TITLES[datasetId] ?? humanizeDatasetId(datasetId);
}

export function ScenarioListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useScenarios();
  const { data: datasetsData, error: datasetsError } = useQuery({
    queryKey: ["app", "datasets"],
    queryFn: appApi.listDatasets,
  });
  const createMutation = useCreateScenario();
  const deleteMutation = useDeleteScenario();
  const [editing, setEditing] = useState<EditingState | null>(null);
  const [isSavingName, setIsSavingName] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [selectedScenarioIds, setSelectedScenarioIds] = useState<string[]>([]);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [bulkDeleteError, setBulkDeleteError] = useState<string | null>(null);
  const activatingScenarioId = useUIStore((s) => s.activatingScenarioId);
  const setActivatingScenarioId = useUIStore((s) => s.setActivatingScenarioId);

  const scenarios = useMemo(() => data?.items ?? [], [data?.items]);
  const datasets = datasetsData?.items ?? [];
  const defaultDatasetId = datasetsData?.defaultDatasetId ?? "tokyu_core";
  const orderedDatasets = [...datasets].sort((a, b) => {
    if (a.datasetId === defaultDatasetId) return -1;
    if (b.datasetId === defaultDatasetId) return 1;
    return a.datasetId.localeCompare(b.datasetId);
  });
  const datasetNameById = useMemo(
    () =>
      new Map(
        orderedDatasets.map((dataset) => [
          dataset.datasetId,
          datasetDisplayName(dataset.datasetId),
        ]),
      ),
    [orderedDatasets],
  );
  const selectedScenarioSet = useMemo(
    () => new Set(selectedScenarioIds),
    [selectedScenarioIds],
  );
  const allScenariosSelected =
    scenarios.length > 0 && selectedScenarioIds.length === scenarios.length;
  const actionsLocked = activatingScenarioId !== null || isBulkDeleting;

  const saveRenameDisabled =
    !editing ||
    isSavingName ||
    editing.name.trim().length === 0 ||
    scenarios.every(
      (scenario) =>
        scenario.id !== editing.id || scenario.name.trim() === editing.name.trim(),
    );

  useEffect(() => {
    const validIds = new Set(scenarios.map((scenario) => scenario.id));
    setSelectedScenarioIds((prev) => prev.filter((id) => validIds.has(id)));
  }, [scenarios]);

  if (isLoading) return <LoadingBlock message={t("scenarios.loading")} />;
  if (error) return <ErrorBlock message={error.message} />;

  async function activateAndOpen(scenarioId: string) {
    if (activatingScenarioId === scenarioId) {
      return;
    }
    setActivatingScenarioId(scenarioId);
    try {
      await scenarioApi.activate(scenarioId);
      navigate(`/scenarios/${scenarioId}/planning`);
    } finally {
      setActivatingScenarioId(null);
    }
  }

  async function createFromDataset(datasetId: string) {
    const created = await createMutation.mutateAsync({
      name: `${datasetScenarioTitle(datasetId)} Scenario ${scenarios.length + 1}`,
      description: "",
      mode: "mode_B_resource_assignment",
      datasetId,
      randomSeed: 42,
    });
    await activateAndOpen(created.id);
  }

  function startRename(scenarioId: string, currentName: string) {
    setRenameError(null);
    setEditing({ id: scenarioId, name: currentName });
  }

  function cancelRename() {
    setRenameError(null);
    setEditing(null);
  }

  async function submitRename() {
    if (!editing) {
      return;
    }
    const nextName = editing.name.trim();
    if (!nextName) {
      setRenameError("表示名を入力してください。");
      return;
    }

    setRenameError(null);
    setIsSavingName(true);
    try {
      await scenarioApi.update(editing.id, { name: nextName });
      await queryClient.invalidateQueries({ queryKey: ["scenarios"] });
      setEditing(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : "表示名の更新に失敗しました。";
      setRenameError(message);
    } finally {
      setIsSavingName(false);
    }
  }

  function toggleScenarioSelection(scenarioId: string) {
    setBulkDeleteError(null);
    setSelectedScenarioIds((prev) =>
      prev.includes(scenarioId)
        ? prev.filter((id) => id !== scenarioId)
        : [...prev, scenarioId],
    );
  }

  function toggleAllScenarios() {
    setBulkDeleteError(null);
    if (allScenariosSelected) {
      setSelectedScenarioIds([]);
      return;
    }
    setSelectedScenarioIds(scenarios.map((scenario) => scenario.id));
  }

  async function deleteSelectedScenarios() {
    const ids = [...selectedScenarioIds];
    if (!ids.length) {
      return;
    }
    const confirmMessage =
      ids.length === 1
        ? t("scenarios.delete_confirm", {
            name: scenarios.find((scenario) => scenario.id === ids[0])?.name ?? ids[0],
          })
        : `Delete ${ids.length} scenarios?`;
    if (!window.confirm(confirmMessage)) {
      return;
    }

    setBulkDeleteError(null);
    setIsBulkDeleting(true);
    try {
      const results = await Promise.allSettled(
        ids.map((scenarioId) => scenarioApi.delete(scenarioId)),
      );
      const failedIds = results.flatMap((result, index) =>
        result.status === "rejected" ? [ids[index]] : [],
      );
      await queryClient.invalidateQueries({ queryKey: ["scenarios"] });
      if (failedIds.length > 0) {
        setSelectedScenarioIds(failedIds);
        setBulkDeleteError(`${failedIds.length} scenario(s) could not be deleted.`);
      } else {
        setSelectedScenarioIds([]);
      }
    } finally {
      setIsBulkDeleting(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">東急バス研究ケース</h1>
        <p className="mt-1 text-sm text-slate-500">
          Step 1: 事前に用意した Tokyu dataset を選択し、シナリオを作成または開きます。
        </p>
      </div>

      {editing ? (
        <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-60 flex-1 text-sm">
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                シナリオ表示名
              </div>
              <input
                type="text"
                value={editing.name}
                onChange={(event) =>
                  setEditing((prev) =>
                    prev ? { ...prev, name: event.target.value } : prev,
                  )
                }
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700"
                placeholder="表示名"
              />
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void submitRename()}
                disabled={saveRenameDisabled}
                className="rounded-md bg-primary-600 px-3 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
              >
                {isSavingName ? "保存中..." : "表示名を保存"}
              </button>
              <button
                type="button"
                onClick={cancelRename}
                disabled={isSavingName}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                キャンセル
              </button>
            </div>
          </div>
          {renameError ? (
            <div className="mt-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {renameError}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mb-8 grid gap-4 md:grid-cols-2">
        {orderedDatasets.map((dataset) => (
          <section
            key={dataset.datasetId}
            className="rounded-xl border border-border bg-surface-raised p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  {datasetDisplayName(dataset.datasetId)}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-500">{dataset.datasetId}</p>
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
                disabled={createMutation.isPending || actionsLocked}
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
        <div>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface-raised px-3 py-2">
            <div className="text-xs text-slate-600">
              {selectedScenarioIds.length > 0
                ? `${selectedScenarioIds.length} selected`
                : "Select scenarios to delete multiple at once"}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={toggleAllScenarios}
                disabled={actionsLocked}
                className="rounded border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {allScenariosSelected ? "Clear all" : "Select all"}
              </button>
              <button
                type="button"
                onClick={() => setSelectedScenarioIds([])}
                disabled={actionsLocked || selectedScenarioIds.length === 0}
                className="rounded border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Clear selected
              </button>
              <button
                type="button"
                onClick={() => void deleteSelectedScenarios()}
                disabled={
                  actionsLocked ||
                  deleteMutation.isPending ||
                  selectedScenarioIds.length === 0
                }
                className="rounded border border-rose-300 bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-50"
              >
                {isBulkDeleting ? "Deleting..." : "Delete selected"}
              </button>
            </div>
          </div>

          {bulkDeleteError ? (
            <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {bulkDeleteError}
            </div>
          ) : null}

          <ul className="space-y-2">
            {scenarios.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between rounded-lg border border-border bg-surface-raised px-4 py-3 hover:border-primary-200"
              >
                <div className="flex min-w-0 flex-1 items-start gap-3 text-left">
                  <input
                    type="checkbox"
                    checked={selectedScenarioSet.has(s.id)}
                    onChange={() => toggleScenarioSelection(s.id)}
                    disabled={actionsLocked || deleteMutation.isPending}
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-primary-600"
                  />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-800">{s.name}</p>
                    <p className="mt-0.5 truncate text-xs text-slate-400">
                      {datasetNameById.get(s.datasetId ?? defaultDatasetId) ??
                        datasetDisplayName(s.datasetId ?? defaultDatasetId)}
                      {" "}
                      ({s.datasetId ?? defaultDatasetId}) &middot; {s.mode} &middot; {s.status} &middot; {formatDate(s.updatedAt)}
                    </p>
                  </div>
                </div>
                <div className="ml-3 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void activateAndOpen(s.id)}
                    disabled={actionsLocked}
                    className="rounded-md border border-primary-200 px-3 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-50 disabled:opacity-50"
                  >
                    {activatingScenarioId === s.id
                      ? t("common.loading", "読込中")
                      : t("common.open", "開く")}
                  </button>
                  <button
                    type="button"
                    onClick={() => startRename(s.id, s.name)}
                    disabled={actionsLocked || isSavingName}
                    className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                  >
                    表示名を編集
                  </button>
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      if (confirm(t("scenarios.delete_confirm", { name: s.name })))
                        deleteMutation.mutate(s.id);
                    }}
                    disabled={actionsLocked}
                    className="text-xs text-red-400 hover:text-red-600"
                  >
                    {t("common.delete")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
