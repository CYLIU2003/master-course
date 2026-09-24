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
  sessionStorage.removeItem("ev-cluster-monitor-port");
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
  expect(screen.queryByRole("link", { name: "成果物ZIP" })).toBeNull();
  client.clear();
});

it("marks a fenced attempt as never started without offering a nonexistent archive", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(
    url.endsWith("/workers")
      ? { workers: [], global_gurobi_slots: 2 }
      : [{ id: "fenced", state: "BLOCKED", worker_id: "pc", created_at: "2026-09-23",
           manifest: { kind: "optimization" },
           result: { cluster_admission: "FENCED_BEFORE_LAUNCH" } }],
  )))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ClusterPanel /></QueryClientProvider>);
  expect(await screen.findByText("（子機で未開始と確認済み）")).toBeTruthy();
  expect(screen.queryByRole("link", { name: "成果物ZIP" })).toBeNull();
  expect(screen.getByRole("button", { name: "新しいIDで再試行" })).toBeTruthy();
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
  expect(screen.getByText("複数日・研究採用は未対応")).toBeTruthy();
  expect(screen.getByText("（研究採用を意味しません）")).toBeTruthy();
  expect(screen.getByText(/外部計算予約 1 \/ 合計 2/)).toBeTruthy();
});

it("shows the selected scenario's live jobs and can switch to all jobs", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const job = (id: string, scenarioId: string, name: string, state: string) => ({
    id,
    state,
    worker_id: null,
    created_at: "2026-09-24",
    manifest: {
      kind: "optimization",
      summary: {
        scenario_id: scenarioId,
        scenario_name: name,
        planning_days: 1,
        horizon_hours: 24,
        service_dates: ["2026-09-24"],
        expected_rolling_windows: 24,
        research_status: "SEPARATE_ACCEPTANCE_REQUIRED",
      },
    },
  });
  const first = job("job-first", "scenario-a", "Scenario A", "QUEUED");
  const second = job("job-second", "scenario-b", "Scenario B", "RUNNING");
  client.setQueryData(["cluster-jobs"], [first, second]);
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.endsWith("/workers")
              ? { workers: [], global_gurobi_slots: 2 }
              : [first, second],
          ),
        ),
      ),
    ),
  );
  render(
    <QueryClientProvider client={client}>
      <ClusterPanel scenarioId="scenario-a" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Scenario A")).toBeTruthy();
  expect(screen.queryByText("Scenario B")).toBeNull();
  client.setQueryData(["cluster-jobs"], [
    { ...first, state: "RUNNING" },
    second,
  ]);
  await waitFor(() => expect(screen.getByText("RUNNING")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("表示するジョブ"), {
    target: { value: "all" },
  });
  expect(screen.getByText("Scenario B")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("表示するジョブ"), {
    target: { value: "scenario" },
  });
  expect(screen.queryByText("Scenario B")).toBeNull();
  client.clear();
});

it("switches to another local controller's queue without enabling remote actions", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const fetch = vi.fn((url: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          url.endsWith("/workers")
            ? { workers: [], global_gurobi_slots: 2 }
            : [
                {
                  id: url.startsWith("http") ? "remote-job" : "local-job",
                  state: "QUEUED",
                  worker_id: null,
                  created_at: "2026-09-24",
                  manifest: {
                    kind: "optimization",
                    summary: {
                      scenario_id: url.startsWith("http")
                        ? "scenario-b"
                        : "scenario-a",
                      scenario_name: url.startsWith("http")
                        ? "Remote Scenario"
                        : "Local Scenario",
                      planning_days: 1,
                      horizon_hours: 24,
                      service_dates: ["2026-09-24"],
                      expected_rolling_windows: 0,
                      research_status: "SEPARATE_ACCEPTANCE_REQUIRED",
                    },
                  },
                },
              ],
        ),
      ),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const { rerender } = render(
    <QueryClientProvider client={client}>
      <ClusterPanel scenarioId="scenario-a" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Local Scenario")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("監視先ポート（このPC）"), {
    target: { value: "8890" },
  });
  expect(await screen.findByText("Remote Scenario")).toBeTruthy();
  expect(screen.queryByText("Local Scenario")).toBeNull();
  expect(screen.getByRole("button", { name: "登録取消" }).hasAttribute("disabled")).toBe(true);
  expect(
    fetch.mock.calls.some(([url]) =>
      String(url).startsWith("http://localhost:8890/api/cluster/jobs"),
    ),
  ).toBe(true);
  expect(sessionStorage.getItem("ev-cluster-monitor-port")).toBe("8890");
  rerender(
    <QueryClientProvider client={client}>
      <ClusterPanel key="next-scenario" scenarioId="scenario-b" />
    </QueryClientProvider>,
  );
  expect(
    (screen.getByLabelText("監視先ポート（このPC）") as HTMLInputElement).value,
  ).toBe("8890");
  expect(screen.getByText("Remote Scenario")).toBeTruthy();
  client.clear();
});

it("shows reusable per-attempt checkpoints and marks disconnected values as last known", async () => {
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
                    id: "job-a",
                    state: "RUNNING",
                    worker_id: "pc-a",
                    created_at: "2026-09-24",
                    manifest: {
                      kind: "optimization",
                      summary: {
                        scenario_name: "渋24",
                        service_dates: [],
                        planning_days: 1,
                        horizon_hours: 24,
                        expected_rolling_windows: 0,
                      },
                    },
                    execution_progress: {
                      percent: 55,
                      stage: "solve",
                      message: "Running optimizer",
                      observed_at: "2026-09-24T01:00:00Z",
                      meaning: "pipeline_checkpoint_not_solver_gap",
                    },
                  },
                  {
                    id: "job-b",
                    state: "LOST",
                    worker_id: "pc-b",
                    created_at: "2026-09-24",
                    manifest: {
                      kind: "optimization",
                      summary: {
                        scenario_name: "渋21",
                        service_dates: [],
                        planning_days: 1,
                        horizon_hours: 24,
                        expected_rolling_windows: 0,
                      },
                    },
                    execution_progress: {
                      percent: 25,
                      stage: "build_canonical",
                      message: "Building problem",
                      observed_at: "2026-09-24T00:00:00Z",
                      meaning: "pipeline_checkpoint_not_solver_gap",
                    },
                  },
                ],
          ),
        ),
      ),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ClusterPanel />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("渋24")).toBeTruthy();
  expect(screen.getByText("渋21")).toBeTruthy();
  expect(screen.getByText("55%")).toBeTruthy();
  expect(screen.getByText("25%")).toBeTruthy();
  expect(
    screen.getByText(/最後に確認した値 · 2026-09-24T00:00:00Z/),
  ).toBeTruthy();
  expect(
    screen.getByText(/求解器内部の探索率、残り時間、最適性gapではありません/),
  ).toBeTruthy();
  client.clear();
});

it("shows the selected scenario's live jobs and can switch to all jobs", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const job = (id: string, scenarioId: string, name: string, state: string) => ({
    id,
    state,
    worker_id: null,
    created_at: "2026-09-24",
    manifest: {
      kind: "optimization",
      summary: {
        scenario_id: scenarioId,
        scenario_name: name,
        planning_days: 1,
        horizon_hours: 24,
        service_dates: ["2026-09-24"],
        expected_rolling_windows: 24,
        research_status: "SEPARATE_ACCEPTANCE_REQUIRED",
      },
    },
  });
  const first = job("job-first", "scenario-a", "Scenario A", "QUEUED");
  const second = job("job-second", "scenario-b", "Scenario B", "RUNNING");
  client.setQueryData(["cluster-jobs"], [first, second]);
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.endsWith("/workers")
              ? { workers: [], global_gurobi_slots: 2 }
              : [first, second],
          ),
        ),
      ),
    ),
  );
  render(
    <QueryClientProvider client={client}>
      <ClusterPanel scenarioId="scenario-a" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Scenario A")).toBeTruthy();
  expect(screen.queryByText("Scenario B")).toBeNull();
  client.setQueryData(["cluster-jobs"], [
    { ...first, state: "RUNNING" },
    second,
  ]);
  await waitFor(() => expect(screen.getByText("RUNNING")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("表示するジョブ"), {
    target: { value: "all" },
  });
  expect(screen.getByText("Scenario B")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("表示するジョブ"), {
    target: { value: "scenario" },
  });
  expect(screen.queryByText("Scenario B")).toBeNull();
  client.clear();
});

it("switches to another local controller's queue without enabling remote actions", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const fetch = vi.fn((url: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          url.endsWith("/workers")
            ? { workers: [], global_gurobi_slots: 2 }
            : [
                {
                  id: url.startsWith("http") ? "remote-job" : "local-job",
                  state: "QUEUED",
                  worker_id: null,
                  created_at: "2026-09-24",
                  manifest: {
                    kind: "optimization",
                    summary: {
                      scenario_id: url.startsWith("http")
                        ? "scenario-b"
                        : "scenario-a",
                      scenario_name: url.startsWith("http")
                        ? "Remote Scenario"
                        : "Local Scenario",
                      planning_days: 1,
                      horizon_hours: 24,
                      service_dates: ["2026-09-24"],
                      expected_rolling_windows: 0,
                      research_status: "SEPARATE_ACCEPTANCE_REQUIRED",
                    },
                  },
                },
              ],
        ),
      ),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const { rerender } = render(
    <QueryClientProvider client={client}>
      <ClusterPanel scenarioId="scenario-a" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Local Scenario")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("監視先ポート（このPC）"), {
    target: { value: "8890" },
  });
  expect(await screen.findByText("Remote Scenario")).toBeTruthy();
  expect(screen.queryByText("Local Scenario")).toBeNull();
  expect(screen.getByRole("button", { name: "登録取消" }).hasAttribute("disabled")).toBe(true);
  expect(
    fetch.mock.calls.some(([url]) =>
      String(url).startsWith("http://localhost:8890/api/cluster/jobs"),
    ),
  ).toBe(true);
  expect(sessionStorage.getItem("ev-cluster-monitor-port")).toBe("8890");
  rerender(
    <QueryClientProvider client={client}>
      <ClusterPanel key="next-scenario" scenarioId="scenario-b" />
    </QueryClientProvider>,
  );
  expect(
    (screen.getByLabelText("監視先ポート（このPC）") as HTMLInputElement).value,
  ).toBe("8890");
  expect(screen.getByText("Remote Scenario")).toBeTruthy();
  client.clear();
});

it("shows the full batch denominator only in the all-scenarios view", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const job = (id: string, scenarioId: string, state: string) => ({
    id,
    state,
    worker_id: null,
    error: null,
    created_at: "2026-09-25",
    manifest: {
      kind: "optimization",
      batch_id: "shared-batch",
      task_id: id,
      batch_task_count: 2,
      summary: {
        scenario_id: scenarioId,
        scenario_name: scenarioId,
        planning_days: 1,
        horizon_hours: 24,
        service_dates: ["2026-09-25"],
        expected_rolling_windows: 24,
        research_status: "SEPARATE_ACCEPTANCE_REQUIRED",
      },
    },
  });
  const jobs = [job("task-a", "scenario-a", "COMPLETED"), job("task-b", "scenario-b", "QUEUED")];
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(
    url.endsWith("/workers") ? { workers: [], global_gurobi_slots: 2 } : jobs,
  )))));
  render(
    <QueryClientProvider client={client}>
      <ClusterPanel scenarioId="scenario-a" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("scenario-a")).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "分散バッチの進捗" })).toBeNull();
  fireEvent.change(screen.getByLabelText("表示するジョブ"), { target: { value: "all" } });
  expect(screen.getByRole("heading", { name: "分散バッチの進捗" })).toBeTruthy();
  expect(screen.getByText(/shared-batch · 50% · 回収確認 1\/2/)).toBeTruthy();
  client.clear();
});
