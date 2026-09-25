import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ExecutionProgress from "./ExecutionProgress";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function show(stale = false, failed = false) {
  const stamp = new Date(Date.now() - (stale ? 300000 : 0)).toISOString();
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    schema_version: "execution_detail_v1", observed_at: stamp, errors: [], cases: [{
      parent: "p", campaign: "campaign", week: "2025-02-03", state: failed ? "FAILED" : "RUNNING", worker: "worker32",
      prepared: true, verified: false, job_id: "same-attempt", solver_git_sha: "frozen", connection: "CONNECTED", expected_windows: 175,
      error: failed ? "GUROBI_LICENSE_UNAVAILABLE" : null, placement: [], execution: failed ? null : {
        phase: "ROLLING", observed_at: stamp, rolling_saved: 25, rolling_feasible: 24, chain_accepted: false, native: null }
    }] })))));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ExecutionProgress scenarioId="p"/></QueryClientProvider>);
}
it("shows actual rolling counts and separates weekly verification", async () => {
  show();
  expect(await screen.findByText("24/175窓（13.7%）")).toBeTruthy();
  expect(screen.getByText(/検算・集計 0\/1週/)).toBeTruthy();
  expect(screen.getByText("毎時の運用計算")).toBeTruthy();
});
it("marks stale snapshots as last known instead of live", async () => {
  show(true);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("現在の実行状態は不明"));
  expect(screen.getByText(/最終記録/)).toBeTruthy();
});
it("shows license failure without counting it as successful computation", async () => {
  show(false, true);
  expect(await screen.findByText("Gurobiライセンスを利用できません")).toBeTruthy();
  expect(screen.getByText(/計算終了 0\/1週/)).toBeTruthy();
});
