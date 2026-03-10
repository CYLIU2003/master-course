import { useEffect, useState } from "react";
import { useBootStore } from "@/stores/boot-store";

export function BootSplashOverlay() {
  const status = useBootStore((state) => state.status);
  const displayMode = useBootStore((state) => state.displayMode);
  const progress = useBootStore((state) => state.progress);
  const steps = useBootStore((state) => state.steps);
  const errorMessage = useBootStore((state) => state.errorMessage);
  const [shouldRender, setShouldRender] = useState(false);
  const [isClosing, setIsClosing] = useState(false);

  useEffect(() => {
    let timeoutId: number | undefined;
    if (displayMode === "restore" && status !== "error") {
      setShouldRender(false);
      setIsClosing(false);
      return undefined;
    }
    if (status === "running" || status === "error") {
      setShouldRender(true);
      setIsClosing(false);
      return;
    }
    if (status === "ready" && progress >= 100) {
      setShouldRender(true);
      setIsClosing(true);
      timeoutId = window.setTimeout(() => {
        setShouldRender(false);
        setIsClosing(false);
      }, 420);
      return () => {
        window.clearTimeout(timeoutId);
      };
    }
    if (status === "idle") {
      setShouldRender(false);
      setIsClosing(false);
    }
    return undefined;
  }, [displayMode, progress, status]);

  if (!shouldRender) {
    return null;
  }

  const activeStep = steps.find((step) => step.status === "running")
    ?? steps.find((step) => step.status === "error")
    ?? steps.find((step) => step.status === "pending")
    ?? steps.at(-1);

  return (
    <div
      className={`pointer-events-none fixed inset-0 z-[80] flex items-center justify-center bg-[radial-gradient(circle_at_top,#e0f2fe_0%,#f8fafc_45%,#e2e8f0_100%)] backdrop-blur-sm transition-opacity duration-300 ${
        isClosing ? "opacity-0" : "opacity-100"
      }`}
    >
      <div
        className={`pointer-events-auto w-full max-w-2xl rounded-[28px] border border-slate-200/80 bg-white/90 p-8 shadow-2xl transition-all duration-300 ${
          isClosing ? "translate-y-2 scale-[0.985]" : "translate-y-0 scale-100"
        }`}
      >
        <div className="flex items-start justify-between gap-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">
              Boot Pipeline
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-900">
              {activeStep?.label ?? "Initializing"}
            </h2>
            <p className="mt-2 text-sm text-slate-500">
              {activeStep?.detailMessage ?? "サービスと軽量インデックスを段階起動しています。"}
            </p>
          </div>
          <div className="relative flex h-16 w-16 items-center justify-center rounded-full border border-slate-200 bg-slate-50">
            <div className="absolute inset-2 animate-pulse rounded-full border border-sky-200" />
            <span className="text-sm font-semibold text-slate-700">{progress}%</span>
          </div>
        </div>
        <div className="mt-6 h-3 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-[linear-gradient(90deg,#0f766e,#0284c7,#38bdf8)] transition-[width] duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="mt-6 grid gap-3 md:grid-cols-2">
          {steps.map((step) => (
            <div key={step.id} className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-3">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="font-medium text-slate-700">{step.label}</span>
                <span className="font-mono text-slate-500">
                  {step.currentCount != null && step.totalCount != null
                    ? `${step.currentCount}/${step.totalCount}`
                    : `${step.progress}%`}
                </span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white">
                <div
                  className={`h-full rounded-full transition-[width] duration-300 ${
                    step.status === "error"
                      ? "bg-rose-500"
                      : step.status === "success"
                        ? "bg-emerald-500"
                        : "bg-sky-500"
                  }`}
                  style={{ width: `${step.progress}%` }}
                />
              </div>
              {step.detailMessage && (
                <p className="mt-2 text-[11px] text-slate-500">{step.detailMessage}</p>
              )}
            </div>
          ))}
        </div>
        {errorMessage && (
          <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {errorMessage}
          </div>
        )}
      </div>
    </div>
  );
}
