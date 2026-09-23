import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ClusterPanel from "./ClusterPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("keeps a completed task's SOC rejection and solver usage visible", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.endsWith("/workers")
              ? { workers: [], global_gurobi_slots: 2 }
              : [
                  {
                    id: "completed-diagnostic",
                    state: "COMPLETED",
                    worker_id: "pc",
                    created_at: "2026-09-23",
                    manifest: {
                      kind: "optimization",
                      execution_profile: "alns_no_gurobi_v1",
                    },
                    result: {
                      result: {
                        message:
                          "Optimization complete (terminal_soc_balance_failed).",
                        metadata: {
                          solver_usage: {
                            counts_complete: true,
                            environment_starts: 0,
                            optimize_calls: 0,
                          },
                        },
                      },
                    },
                  },
                ],
          ),
        ),
      ),
    ),
  );
  render(
    <QueryClientProvider client={client}>
      <ClusterPanel />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("期末SOCの条件未達（診断結果）")).toBeTruthy();
  expect(screen.getByText("Gurobi Env 0回 / 求解 0回")).toBeTruthy();
  expect(screen.getByText("（研究採用を意味しません）")).toBeTruthy();
  client.clear();
});

it("keeps cached running jobs visible when UI refresh fails and cancels only the selected attempt", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["cluster-workers"], {
    workers: [],
    global_gurobi_slots: 2,
    external_gurobi_slots: 0,
    reserved_gurobi_slots: 1,
  });
  client.setQueryData(
    ["cluster-jobs"],
    [
      {
        id: "owned-attempt",
        state: "RUNNING",
        worker_id: "pc",
        manifest: {
          kind: "optimization",
          attempt_number: 2,
          execution_profile: "alns_no_gurobi_v1",
        },
        created_at: "2026-09-23",
      },
    ],
  );
  const fetch = vi.fn((url: string, options?: RequestInit) =>
    options?.method === "POST"
      ? Promise.resolve(
          new Response(JSON.stringify({ cancel_requested: true })),
        )
      : Promise.reject(new TypeError("connection lost")),
  );
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider client={client}>
      <ClusterPanel />
    </QueryClientProvider>,
  );
  expect(
    await screen.findByText(/これは従機の停止を意味しません/),
  ).toBeTruthy();
  expect(screen.getByText("RUNNING")).toBeTruthy();
  expect(screen.getByText(/試行 2 · Gurobiなし/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "このタスクを停止" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([url, options]) =>
          url === "/api/cluster/jobs/owned-attempt/cancel" &&
          options?.method === "POST",
      ),
    ).toBe(true),
  );
  expect(screen.getByText("RUNNING")).toBeTruthy();
  client.clear();
});

it("shows the weekly period and planned windows separately from research acceptance", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.endsWith("/workers")
              ? {
                  workers: [],
                  global_gurobi_slots: 2,
                  external_gurobi_slots: 1,
                  reserved_gurobi_slots: 0,
                }
              : [
                  {
                    id: "weekly-job",
                    state: "COMPLETED",
                    worker_id: "pc2",
                    created_at: "2026-09-22",
                    result: {},
                    manifest: {
                      kind: "optimization",
                      summary: {
                        scenario_name: "週間診断",
                        planning_days: 7,
                        horizon_hours: 168,
                        service_dates: ["2025-05-12", "2025-05-18"],
                        expected_rolling_windows: 168,
                        research_status: "MULTIDAY_RESEARCH_BLOCKED",
                      },
                    },
                  },
                ],
          ),
          { status: 200 },
        ),
      ),
    ),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ClusterPanel />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("週間診断")).toBeTruthy();
  expect(screen.getByText(/ローリング予定 168回/)).toBeTruthy();
  expect(screen.getByText("診断用・週間研究採用は未対応")).toBeTruthy();
  expect(screen.getByText("（研究採用を意味しません）")).toBeTruthy();
  expect(screen.getByText(/外部計算予約 1 \/ 合計 2/)).toBeTruthy();
});
