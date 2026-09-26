import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ExecutionProgress from "./ExecutionProgress";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("keeps current failures visible and separates older terminal records", async () => {
  const stamp = new Date().toISOString();
  const base = {parent:"p",campaign:"old",week:"2025-01-06",state:"FAILED",worker:"pc",prepared:true,verified:false,
    job_id:"old-job",solver_git_sha:"old-sha",connection:"CONNECTED",started_at:stamp,observed_at:stamp,
    expected_windows:174,trip_count:1704,error:"old failure",execution:null,placement:[]};
  vi.stubGlobal("fetch",vi.fn(() => Promise.resolve(new Response(JSON.stringify({schema_version:"execution_detail_v1",observed_at:stamp,errors:[],cases:[base,
    {...base,campaign:"new",week:"2025-02-03",job_id:"new-job",solver_git_sha:"new-sha",error:"current failure"},
    {...base,week:"2025-03-03",state:"LOST",error:null}
  ]})))));
  render(<QueryClientProvider client={new QueryClient()}><ExecutionProgress controllerSha="new-sha"/></QueryClientProvider>);
  expect(await screen.findByText("current failure")).toBeTruthy();
  expect(screen.getByText(/入力準備 2\/2週/)).toBeTruthy();
  const old = screen.getByText("old failure").closest("details");
  expect(old?.open).toBe(false);
  expect(old?.textContent).toContain("今回の失敗ではありません");
  expect(screen.getByText("通信不明・同じ試行を照合中")).toBeTruthy();
});
function show(stale = false, failed = false, memory = false) {
  const stamp = new Date(Date.now() - (stale ? 300000 : 0)).toISOString();
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    schema_version: "execution_detail_v1", observed_at: stamp, errors: [], cases: [{
      parent: "p", campaign: "campaign", week: "2025-02-03", state: failed ? "FAILED" : "RUNNING", worker: "worker32",
      prepared: true, verified: false, job_id: "same-attempt", solver_git_sha: "frozen", connection: "CONNECTED", expected_windows: 175,
      error: failed ? "GUROBI_LICENSE_UNAVAILABLE" : null, placement: [], memory_budget_gib: 16, execution: failed ? null : {
        phase: "ROLLING", observed_at: stamp, rolling_saved: 25, rolling_feasible: 24, chain_accepted: false, native: null,
        memory: memory ? {status:"OBSERVED",working_set_gib:7.125,peak_working_set_gib:9.25,private_commit_gib:10.5} : {status:"UNKNOWN"} }
    }] })))));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ExecutionProgress scenarioId="p"/></QueryClientProvider>);
}
it("shows process memory and budget separately without adding RAM and commit", async () => {
  show(false, false, true);
  const row = await screen.findByLabelText("計算プロセスのメモリ");
  expect(row.textContent).toContain("使用中RAM 7.13 GiB");
  expect(row.textContent).toContain("起動後のRAM最大 9.25 GiB");
  expect(row.textContent).toContain("専用コミット 10.50 GiB ／ 計算予算 16 GiB");
  expect(row.textContent).toContain("合算しません");
});
it("labels old memory as a last observation", async () => {
  show(true, false, true);
  expect(await screen.findByText("メモリの最終記録")).toBeTruthy();
  expect(screen.queryByText("メモリ実測")).toBeNull();
});
it("does not turn inaccessible memory into zero", async () => {
  show();
  expect((await screen.findByLabelText("計算プロセスのメモリ")).textContent).toContain("メモリ未取得（UNKNOWN）");
});
it("shows actual rolling counts and separates weekly verification", async () => {
  show();
  expect(await screen.findByText("24/175窓（13.7%）")).toBeTruthy();
  expect(screen.getByText(/検算・集計 0\/1週/)).toBeTruthy();
  expect(screen.getByText("毎時の運用計算")).toBeTruthy();
});
it("marks stale snapshots as last known instead of live", async () => {
  show(true);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("現在の実行状態は不明"));
  expect(screen.getByText(/^最終記録：/)).toBeTruthy();
});
it("shows license failure without counting it as successful computation", async () => {
  show(false, true);
  expect(await screen.findByText("Gurobiライセンスを利用できません")).toBeTruthy();
  expect(screen.getByText(/計算終了 0\/1週/)).toBeTruthy();
});

it("shows queued memory and license cause without opening details", async () => {
  const stamp = new Date().toISOString();
  const row = { parent:"p", campaign:"new", week:"2025-02-03", state:"QUEUED", worker:null,
    prepared:true, verified:false, job_id:"new", solver_git_sha:"new", connection:"CONNECTED", observed_at:stamp,
    started_at:stamp, expected_windows:174, trip_count:1704, error:null, execution:null,
    license:{global_gurobi_slots:2,reserved_gurobi_slots:0,cooling_gurobi_slots:0,external_gurobi_slots:0},
    placement:[{worker:"pc32",reasons:["INSUFFICIENT_OR_UNKNOWN_RAM"],readiness_reasons:[],required_ram_gb:16,
      physical_free_ram_gb:19,system_reserve_gb:4,available_ram_gb:15,machine_memory_budget_gib:16,commit_available_gb:24}] };
  vi.stubGlobal("fetch",vi.fn(() => Promise.resolve(new Response(JSON.stringify({schema_version:"execution_detail_v1",observed_at:stamp,errors:[],
    cases:[{...row,campaign:"old",state:"FAILED",started_at:"2026-01-01T00:00:00Z",error:"old failure"},row]})))));
  render(<QueryClientProvider client={new QueryClient()}><ExecutionProgress/></QueryClientProvider>);
  expect(await screen.findByText("求解はまだ始まっていません")).toBeTruthy();
  expect(screen.getByRole("status").textContent).toContain("計算予算 16 GiB");
  expect(screen.getByRole("status").textContent).toContain("現在の空きRAM 19.0 GiB");
  expect(screen.queryByText("old failure")).toBeNull();
  expect(screen.getByText(/入力準備 1\/1週/)).toBeTruthy();
});
