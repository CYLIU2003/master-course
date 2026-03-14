import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { fetchMaybeJson } from "@/api/client";
import { scenarioApi } from "@/api/scenario";
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
      typeof parsed.scenarioId !== "string" ||
      typeof parsed.manifestKey !== "string" ||
      typeof parsed.warmedAt !== "string"
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
      datasetFingerprint?: string | null;
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
    datasetFingerprint: feedContext?.datasetFingerprint ?? null,
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
      setTabStatus("explorer", "ready", "Explorer はいつでも利用可能");
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
        await measureAsyncStep("boot:context", () =>
          fetchMaybeJson("/api/app/context"),
        );
        if (cancelled) return;
        updateStep("context", { status: "success", progress: 100 });

        updateStep("cache", {
          status: "running",
          progress: 20,
          detailMessage: "editor bootstrap を確認中",
        });
        await measureAsyncStep("boot:cache", async () => {
          const bootstrap = await queryClient.ensureQueryData({
            queryKey: scenarioKeys.editorBootstrap(currentScenarioId),
            queryFn: async () => scenarioApi.getEditorBootstrap(currentScenarioId),
          });
          queryClient.setQueryData(
            scenarioKeys.detail(currentScenarioId),
            bootstrap.scenario,
          );
          queryClient.setQueryData(
            scenarioKeys.dispatchScope(currentScenarioId),
            bootstrap.dispatchScope,
          );
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
        const manifestKey = buildBootManifestKey(
          currentScenarioId,
          scenarioDetail,
        );
        setManifestKey(manifestKey);
        if (!restoreCandidate || cachedManifest?.manifestKey !== manifestKey) {
          setDisplayMode("full");
        }
        updateStep("master", {
          status: "success",
          progress: 100,
          detailMessage: "planning page で必要になった時だけ読込",
        });
        setTabStatus("planning", "ready", "planning page 側の query で必要データを読込");

        updateStep("timetable", {
          status: "success",
          progress: 100,
          detailMessage: "timetable / rules は tab open 時に遅延読込",
        });
        setTabStatus("timetable", "idle", "時刻表タブを開いた時に読込");

        updateStep("tabs", {
          status: "success",
          progress: 100,
          detailMessage: "dispatch / explorer は必要時のみ読込",
          currentCount: 1,
          totalCount: 1,
        });
        setTabStatus("dispatch", "idle", "dispatch 系は実行系画面で遅延読込");
        setTabStatus("explorer", "ready", "Explorer は開いた時だけ読込");
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
          setTabStatus("explorer", "ready", "Explorer はいつでも利用可能");
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
