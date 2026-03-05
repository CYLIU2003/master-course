// ── RouteNodeGraphPanel ───────────────────────────────────────
// Placeholder for the Phase 2 SVG-based node graph editor.
// Will contain the full canvas with stop nodes, edges, and
// distance editing.

import { useTranslation } from "react-i18next";

interface Props {
  scenarioId: string;
}

export function RouteNodeGraphPanel({ scenarioId: _scenarioId }: Props) {
  const { t } = useTranslation();

  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <div className="mb-2 text-2xl text-slate-300">
          <svg
            className="mx-auto h-12 w-12"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
            />
          </svg>
        </div>
        <p className="text-sm font-medium text-slate-500">
          {t("routes.node_graph_placeholder", "ノードグラフエディタ")}
        </p>
        <p className="mt-1 text-xs text-slate-400">
          Phase 2 で実装予定
        </p>
      </div>
    </div>
  );
}
