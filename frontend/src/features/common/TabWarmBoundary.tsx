import type { ReactNode } from "react";
import type { WarmTabKey } from "@/stores/tab-warm-store";
import { useTabWarmStore } from "@/stores/tab-warm-store";

interface Props {
  tab: WarmTabKey;
  title: string;
  children: ReactNode;
}

export function TabWarmBoundary({ tab, title, children }: Props) {
  const state = useTabWarmStore((store) => store.tabs[tab]);

  if (state.status === "warming" || state.status === "idle") {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center p-6">
        <div className="w-full max-w-xl rounded-[24px] border border-slate-200 bg-[linear-gradient(135deg,#f8fafc,#e0f2fe)] p-8 shadow-sm">
          <div className="flex items-center gap-4">
            <div className="relative h-12 w-12 shrink-0 rounded-full border border-sky-200 bg-white">
              <div className="absolute inset-2 animate-pulse rounded-full border border-sky-300" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-800">{title}</p>
              <p className="mt-1 text-sm text-slate-500">
                {state.detail ?? "このタブの lightweight cache を準備しています。"}
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="m-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {state.detail ?? `${title} の準備でエラーが発生しました。`}
      </div>
    );
  }

  return <>{children}</>;
}
