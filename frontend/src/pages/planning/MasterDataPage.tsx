// ── MasterDataPage ────────────────────────────────────────────
// Main "営業所・車両・路線" page.
// 3 sub-tabs (depots / vehicles / routes)
// 3 view modes (table / map / node)
// 3-pane layout: left filter | center content | right drawer

import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMasterUiStore } from "@/stores/master-ui-store";
import { ThreePaneLayout } from "@/features/common/ThreePaneLayout";
import { MasterDataHeader } from "./MasterDataHeader";
import { MasterDataTabs } from "./MasterDataTabs";
import { MasterLeftPanel } from "./MasterLeftPanel";
import { MasterCenterPanel } from "./MasterCenterPanel";
import { MasterEditorDrawerHost } from "./MasterEditorDrawerHost";

export function MasterDataPage() {
  const { scenarioId } = useParams<{ scenarioId: string }>();
  const { t } = useTranslation();

  if (!scenarioId) return null;

  return (
    <div className="flex h-full flex-col">
      {/* Header + Tabs + Mode switch */}
      <MasterDataHeader scenarioId={scenarioId} />
      <MasterDataTabs />

      {/* 3-pane body */}
      <ThreePaneLayout
        left={<MasterLeftPanel scenarioId={scenarioId} />}
        center={<MasterCenterPanel scenarioId={scenarioId} />}
        right={<MasterEditorDrawerHost scenarioId={scenarioId} />}
      />
    </div>
  );
}
