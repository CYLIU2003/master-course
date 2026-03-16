// ── MasterDataPage ────────────────────────────────────────────
// Main "営業所・車両・路線" page.
// 3 sub-tabs (depots / vehicles / routes)
// 3 view modes (table / map / node)
// 3-pane layout: left filter | center content | right drawer

import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { ThreePaneLayout } from "@/features/common/ThreePaneLayout";
import { useTabWarmStore } from "@/stores/tab-warm-store";
import { MasterDataHeader } from "./MasterDataHeader";
import { MasterDataTabs } from "./MasterDataTabs";
import { MasterLeftPanel } from "./MasterLeftPanel";
import { MasterCenterPanel } from "./MasterCenterPanel";
import { MasterEditorDrawerHost } from "./MasterEditorDrawerHost";

export function MasterDataPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const setTabStatus = useTabWarmStore((state) => state.setTabStatus);

  useEffect(() => {
    if (!scenarioId) {
      return;
    }
    const planningStatus = useTabWarmStore.getState().tabs.planning.status;
    if (planningStatus !== "ready") {
      setTabStatus("planning", "ready", "master data を表示中");
    }
  }, [scenarioId, setTabStatus]);

  if (!scenarioId) return null;

  return (
    <div className="flex min-h-0 flex-col">
      {/* Header + Tabs + Mode switch */}
      <MasterDataHeader scenarioId={scenarioId} />
      <MasterDataTabs />

      {/* 3-pane body */}
      <div className="min-h-0 flex-1">
        <ThreePaneLayout
          left={<MasterLeftPanel scenarioId={scenarioId} />}
          center={<MasterCenterPanel scenarioId={scenarioId} />}
          right={<MasterEditorDrawerHost scenarioId={scenarioId} />}
        />
      </div>
    </div>
  );
}
