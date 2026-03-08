import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { fetchMaybeJson } from "@/api/client";
import { scenarioApi } from "@/api/scenario";
import { depotApi, routeApi, stopApi } from "@/api/master-data";
import { depotKeys, routeKeys, stopKeys } from "@/hooks/use-master-data";
import { scenarioKeys } from "@/hooks";
import { useBootStore } from "@/stores/boot-store";
import { useTabWarmStore } from "@/stores/tab-warm-store";
import { measureAsyncStep } from "@/utils/perf/measureAsyncStep";

const BOOT_STEPS = [
  { id: "context", label: "App context 読込", weight: 5 },
  { id: "cache", label: "Scenario cache 確認", weight: 10 },
  { id: "master", label: "基本マスタ読込", weight: 15 },
  { id: "timetable", label: "時刻表 summary 構築", weight: 30 },
  { id: "explorer", label: "Explorer index 準備", weight: 20 },
  { id: "tabs", label: "タブ prewarm", weight: 20 },
] as const;

interface Props {
  scenarioId: string | null;
}

export function AppBootstrapManager({ scenarioId }: Props) {
  const queryClient = useQueryClient();
  const start = useBootStore((state) => state.start);
  const updateStep = useBootStore((state) => state.updateStep);
  const complete = useBootStore((state) => state.complete);
  const fail = useBootStore((state) => state.fail);
  const reset = useBootStore((state) => state.reset);
  const setTabStatus = useTabWarmStore((state) => state.setTabStatus);
  const resetWarmTabs = useTabWarmStore((state) => state.reset);

  useEffect(() => {
    if (!scenarioId) {
      reset();
      resetWarmTabs();
      return;
    }
    const currentScenarioId = scenarioId;

    let cancelled = false;

    async function run() {
      start(currentScenarioId, BOOT_STEPS.map((step) => ({ ...step })));
      resetWarmTabs();
      setTabStatus("planning", "warming", "営業所・車両・路線 summary を準備中");
      setTabStatus("timetable", "warming", "時刻表 summary を準備中");
      setTabStatus("dispatch", "warming", "dispatch scope を準備中");
      setTabStatus("explorer", "warming", "Explorer overview を準備中");
      try {
        updateStep("context", {
          status: "running",
          progress: 20,
          detailMessage: "app/context を読込中",
        });
        await measureAsyncStep("boot:context", () => fetchMaybeJson("/api/app/context"));
        if (cancelled) return;
        updateStep("context", { status: "success", progress: 100 });

        updateStep("cache", {
          status: "running",
          progress: 20,
          detailMessage: "scenario detail と dispatch scope を確認中",
        });
        await measureAsyncStep("boot:cache", async () => {
          await Promise.all([
            queryClient.ensureQueryData({
              queryKey: scenarioKeys.detail(currentScenarioId),
              queryFn: async () => scenarioApi.get(currentScenarioId),
            }),
            queryClient.ensureQueryData({
              queryKey: scenarioKeys.dispatchScope(currentScenarioId),
              queryFn: async () => scenarioApi.getDispatchScope(currentScenarioId),
            }),
          ]);
        });
        if (cancelled) return;
        updateStep("cache", { status: "success", progress: 100 });

        updateStep("master", {
          status: "running",
          progress: 20,
          detailMessage: "depots / routes / stops を先読み中",
        });
        await measureAsyncStep("boot:master", async () => {
          await Promise.all([
            queryClient.ensureQueryData({
              queryKey: depotKeys.all(currentScenarioId),
              queryFn: () => depotApi.list(currentScenarioId),
            }),
            queryClient.ensureQueryData({
              queryKey: routeKeys.all(currentScenarioId),
              queryFn: () => routeApi.list(currentScenarioId),
            }),
            queryClient.ensureQueryData({
              queryKey: stopKeys.all(currentScenarioId),
              queryFn: () => stopApi.list(currentScenarioId),
            }),
          ]);
        });
        if (cancelled) return;
        updateStep("master", { status: "success", progress: 100 });
        setTabStatus("planning", "ready", "基本マスタの先読みが完了");

        updateStep("timetable", {
          status: "running",
          progress: 20,
          detailMessage: "timetable / stop-timetable summary を構築中",
        });
        await measureAsyncStep("boot:timetable", async () => {
          await Promise.all([
            queryClient.ensureQueryData({
              queryKey: scenarioKeys.timetableSummary(currentScenarioId),
              queryFn: () => scenarioApi.getTimetableSummary(currentScenarioId),
            }),
            queryClient.ensureQueryData({
              queryKey: scenarioKeys.stopTimetablesSummary(currentScenarioId),
              queryFn: () => scenarioApi.getStopTimetablesSummary(currentScenarioId),
            }),
          ]);
        });
        if (cancelled) return;
        updateStep("timetable", { status: "success", progress: 100 });
        setTabStatus("timetable", "ready", "時刻表 summary の先読みが完了");

        updateStep("explorer", {
          status: "running",
          progress: 20,
          detailMessage: "public-data overview を読込中",
        });
        await measureAsyncStep("boot:explorer", () =>
          fetchMaybeJson(`/api/scenarios/${currentScenarioId}/explorer/overview?operator=tokyu`),
        );
        if (cancelled) return;
        updateStep("explorer", { status: "success", progress: 100 });
        setTabStatus("explorer", "ready", "Explorer overview の先読みが完了");

        updateStep("tabs", {
          status: "running",
          progress: 40,
          detailMessage: "各タブの lightweight cache を確定中",
          currentCount: 3,
          totalCount: 3,
        });
        setTabStatus("dispatch", "ready", "dispatch scope の準備が完了");
        if (cancelled) return;
        updateStep("tabs", { status: "success", progress: 100 });
        complete();
      } catch (error) {
        if (!cancelled) {
          fail(error instanceof Error ? error.message : String(error));
          setTabStatus("planning", "error", "起動時の先読みで失敗");
          setTabStatus("timetable", "error", "起動時の先読みで失敗");
          setTabStatus("dispatch", "error", "起動時の先読みで失敗");
          setTabStatus("explorer", "error", "起動時の先読みで失敗");
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [
    complete,
    fail,
    queryClient,
    reset,
    resetWarmTabs,
    scenarioId,
    setTabStatus,
    start,
    updateStep,
  ]);

  return null;
}
