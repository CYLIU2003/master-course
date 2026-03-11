import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { fetchMaybeJson } from "@/api/client";
import { scenarioApi } from "@/api/scenario";
import { depotApi } from "@/api/master-data";
import { depotKeys } from "@/hooks/use-master-data";
import { scenarioKeys } from "@/hooks";
import { useBootStore } from "@/stores/boot-store";
import { useTabWarmStore } from "@/stores/tab-warm-store";
import { measureAsyncStep } from "@/utils/perf/measureAsyncStep";

const BOOT_STEPS = [
  { id: "context", label: "App context 読込", weight: 5 },
  { id: "cache", label: "Scenario cache 確認", weight: 10 },
  { id: "master", label: "営業所 summary 読込", weight: 20 },
  { id: "timetable", label: "時刻表 summary 構築", weight: 35 },
  { id: "tabs", label: "タブ prewarm", weight: 30 },
] as const;

const BOOT_CACHE_KEY = "master-course:boot-manifest";

type BootCacheRecord = {
  scenarioId: string;
  manifestKey: string;
  warmedAt: string;
};

function readBootCache(): BootCacheRecord | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.sessionStorage.getItem(BOOT_CACHE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<BootCacheRecord>;
    if (
      typeof parsed.scenarioId !== "string"
      || typeof parsed.manifestKey !== "string"
      || typeof parsed.warmedAt !== "string"
    ) {
      return null;
    }
    return {
      scenarioId: parsed.scenarioId,
      manifestKey: parsed.manifestKey,
      warmedAt: parsed.warmedAt,
    };
  } catch {
    return null;
  }
}

function writeBootCache(record: BootCacheRecord) {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(BOOT_CACHE_KEY, JSON.stringify(record));
}

function clearBootCache() {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(BOOT_CACHE_KEY);
}

function buildBootManifestKey(
  scenarioId: string,
  scenarioDetail?: {
    feedContext?: {
      feedId?: string | null;
      snapshotId?: string | null;
      datasetId?: string | null;
      source?: string | null;
    } | null;
  } | null,
) {
  const feedContext = scenarioDetail?.feedContext ?? null;
  return JSON.stringify({
    scenarioId,
    feedId: feedContext?.feedId ?? null,
    snapshotId: feedContext?.snapshotId ?? null,
    datasetId: feedContext?.datasetId ?? null,
    source: feedContext?.source ?? null,
  });
}

interface Props {
  scenarioId: string | null;
}

export function AppBootstrapManager({ scenarioId }: Props) {
  const queryClient = useQueryClient();
  const start = useBootStore((state) => state.start);
  const updateStep = useBootStore((state) => state.updateStep);
  const setDisplayMode = useBootStore((state) => state.setDisplayMode);
  const setManifestKey = useBootStore((state) => state.setManifestKey);
  const complete = useBootStore((state) => state.complete);
  const fail = useBootStore((state) => state.fail);
  const reset = useBootStore((state) => state.reset);
  const setTabStatus = useTabWarmStore((state) => state.setTabStatus);
  const resetWarmTabs = useTabWarmStore((state) => state.reset);

  useEffect(() => {
    if (!scenarioId) {
      clearBootCache();
      reset();
      resetWarmTabs();
      return;
    }
    const currentScenarioId = scenarioId;
    const cachedManifest = readBootCache();
    const restoreCandidate = cachedManifest?.scenarioId === currentScenarioId;

    let cancelled = false;

    async function run() {
      start(
        currentScenarioId,
        BOOT_STEPS.map((step) => ({ ...step })),
        {
          displayMode: restoreCandidate ? "restore" : "full",
          manifestKey: cachedManifest?.manifestKey ?? null,
        },
      );
      resetWarmTabs();
      setTabStatus("planning", "warming", "営業所 summary を準備中");
      setTabStatus("timetable", "warming", "時刻表 summary を準備中");
      setTabStatus("dispatch", "warming", "dispatch scope を準備中");
      setTabStatus("explorer", "idle", "Explorer は開いた時だけ読込");
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
        const scenarioDetail = queryClient.getQueryData<{
          operatorId?: "tokyu" | "toei";
          feedContext?: {
            feedId?: string | null;
            snapshotId?: string | null;
            datasetId?: string | null;
            source?: string | null;
          } | null;
        }>(scenarioKeys.detail(currentScenarioId));
        const manifestKey = buildBootManifestKey(currentScenarioId, scenarioDetail);
        setManifestKey(manifestKey);
        if (!restoreCandidate || cachedManifest?.manifestKey !== manifestKey) {
          setDisplayMode("full");
        }
        const runMasterStep = async () => {
          updateStep("master", {
            status: "running",
            progress: 20,
            detailMessage: "depots のみ先読み中",
          });
          await measureAsyncStep("boot:master", async () => {
            await queryClient.ensureQueryData({
              queryKey: depotKeys.all(currentScenarioId),
              queryFn: () => depotApi.list(currentScenarioId),
            });
          });
          if (cancelled) {
            return;
          }
          updateStep("master", { status: "success", progress: 100 });
          setTabStatus("planning", "ready", "基本マスタの先読みが完了");
        };

        const runTimetableStep = async () => {
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
          if (cancelled) {
            return;
          }
          updateStep("timetable", { status: "success", progress: 100 });
          setTabStatus("timetable", "ready", "時刻表 summary の先読みが完了");
        };

        await Promise.all([runMasterStep(), runTimetableStep()]);
        if (cancelled) return;

        updateStep("tabs", {
          status: "running",
          progress: 40,
          detailMessage: "各タブの lightweight cache を確定中",
          currentCount: 2,
          totalCount: 2,
        });
        setTabStatus("dispatch", "ready", "dispatch scope の準備が完了");
        if (cancelled) return;
        updateStep("tabs", { status: "success", progress: 100 });
        complete();
        writeBootCache({
          scenarioId: currentScenarioId,
          manifestKey,
          warmedAt: new Date().toISOString(),
        });
      } catch (error) {
        if (!cancelled) {
          clearBootCache();
          fail(error instanceof Error ? error.message : String(error));
          setTabStatus("planning", "error", "起動時の先読みで失敗");
          setTabStatus("timetable", "error", "起動時の先読みで失敗");
          setTabStatus("dispatch", "error", "起動時の先読みで失敗");
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
    setDisplayMode,
    setManifestKey,
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
