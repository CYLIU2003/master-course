import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RunPanel, { executionControls } from "./RunPanel";
import type { Overview } from "../api";
const overview: Overview = {
  meta: { id: "s1", name: "Saved scenario", routeGroup: "other" },
  stats: {},
  scope: {},
  settings: {
    service_date: "2025-05-12",
    planning_days: 7,
    initial_soc: 0.8,
    diesel_price_per_l: 140,
    random_seed: 17,
    rolling_lookahead_hours: 24,
  },
  result: { available: false, source: null, values: {} },
};
const configuration = {
  values: {
    selectedDepotIds: ["tsurumaki"],
    selectedRouteIds: ["route-1"],
    serviceDate: "2025-05-12",
    serviceDates: ["2025-05-12"],
    planningDays: 7,
    solverMode: "phase3_two_stage",
    timeLimitSeconds: 465,
    randomSeed: 17,
    mipGap: 0.02,
  },
  revision: "original",
};
const requests: { url: string; body: Record<string, unknown> }[] = [];
let revision = "original";
let executionProfile = "existing_solver_v1";
let workerRows: Record<string, unknown>[] = [];
beforeEach(() => {
  const saved = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => saved.get(key) ?? null,
    setItem: (key: string, value: string) => saved.set(key, value),
  });
  requests.length = 0;
  revision = "original";
  executionProfile = "existing_solver_v1";
  workerRows = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, options: RequestInit = {}) => {
      const body = options.body
        ? (JSON.parse(String(options.body)) as Record<string, unknown>)
        : {};
      requests.push({ url, body });
      let payload: unknown = {};
      if (url.endsWith("/configuration"))
        payload = { ...configuration, values: { ...configuration.values, executionProfile }, revision };
      else if (url === "/api/cluster/workers")
        payload = {
          workers: workerRows,
          global_gurobi_slots: 1,
          reserved_gurobi_slots: 0,
        };
      else if (url === "/api/cluster/jobs")
        payload = { job_id: "distributed-job" };
      else if (url === "/api/desktop/scenarios/s1") payload = overview;
      else if (url.endsWith("/simulation/prepare"))
        payload = {
          ready: true,
          preparedInputId: "prepared-1",
          tripCount: 100,
          vehicleCount: 35,
          planningDays: 7,
          warnings: [],
        };
      else if (url.includes("/jobs/"))
        payload = {
          job_id: "known-job",
          status: "failed",
          progress: 20,
          message: "BFF restarted",
          error: "Worker orphaned after restart",
        };
      else if (
        url.endsWith("/run-optimization") ||
        url.endsWith("/simulation/run")
      )
        payload = { job_id: "new-job" };
      return Promise.resolve(
        new Response(JSON.stringify(payload), { status: 200 }),
      );
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(blocked = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RunPanel id="s1" data={overview} revision={0} blocked={blocked} />
    </QueryClientProvider>,
  );
}

it.each([
  ["existing_solver_v1", "solver", "alns"],
  ["alns_no_gurobi_v1", "alns", "solver"],
])("shows %s worker roles in the destination selector", async (profile, allowedId, blockedId) => {
  executionProfile = profile;
  workerRows = [
    { id: "solver", name: "Solver", enabled: true, job_role: "gurobi_only",
      can_run_no_gurobi: true, can_run_optimization: true },
    { id: "alns", name: "ALNS", enabled: true, job_role: "alns_only",
      can_run_no_gurobi: true, can_run_optimization: false },
  ];
  mount();
  const select = screen.getByLabelText("計算の配布先") as HTMLSelectElement;
  await waitFor(() => expect(select.querySelector(`option[value="${allowedId}"]`)).not.toBeNull());
  expect((select.querySelector(`option[value="${allowedId}"]`) as HTMLOptionElement).disabled).toBe(false);
  const blocked = select.querySelector(`option[value="${blockedId}"]`) as HTMLOptionElement;
  expect(blocked.disabled).toBe(true);
  expect(blocked.textContent).toContain("担当外");
});

async function prepare() {
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "1. 入力を準備" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "1. 入力を準備" }));
  await screen.findByText(/入力準備済み/);
}
it("shows 168 planned windows and blocks formal seven-day execution", async () => {
  mount();
  await prepare();
  expect(screen.getByText(/予定168回/)).toBeTruthy();
  fireEvent.click(screen.getByRole("checkbox", { name: /正式実行/ }));
  expect(
    screen
      .getByRole("button", { name: "2. 計算を開始" })
      .hasAttribute("disabled"),
  ).toBe(true);
});
it("sends the authoritative day-ahead profile when rolling is disabled", async () => {
  mount();
  await prepare();
  fireEvent.click(
    screen.getByRole("checkbox", { name: /時間ごとのローリング/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "2. 計算を開始" }));
  await waitFor(() =>
    expect(
      requests.find((row) => row.url.endsWith("/run-optimization"))?.body
        .run_profile,
    ).toBe("day_ahead_exploratory"),
  );
});
it("prepares fresh saved physical controls and sends the configured solver budget", async () => {
  mount();
  await prepare();
  expect(
    requests.find((row) => row.url.endsWith("/simulation/prepare"))?.body
      .simulation_settings,
  ).toEqual(overview.settings);
  fireEvent.click(screen.getByRole("button", { name: "2. 計算を開始" }));
  await waitFor(() =>
    expect(requests.some((row) => row.url.endsWith("/run-optimization"))).toBe(
      true,
    ),
  );
  expect(
    requests.find((row) => row.url.endsWith("/run-optimization"))?.body,
  ).toMatchObject({
    prepared_input_id: "prepared-1",
    time_limit_seconds: 465,
    mip_gap: 0.02,
    random_seed: 17,
    mode: "phase3_two_stage",
  });
});
it("rejects a prepared input when another writer changes saved settings", async () => {
  mount();
  await prepare();
  revision = "changed";
  fireEvent.click(screen.getByRole("button", { name: "2. 計算を開始" }));
  await screen.findByText(/入力条件が変更されています/);
  expect(requests.some((row) => row.url.endsWith("/run-optimization"))).toBe(
    false,
  );
});
it("sends frozen optimization to the distributed queue with the selected worker", async () => {
  mount();
  await prepare();
  fireEvent.change(screen.getByLabelText("計算の配布先"), {
    target: { value: "auto" },
  });
  fireEvent.click(screen.getByRole("button", { name: "2. 計算を開始" }));
  await waitFor(() =>
    expect(requests.some((row) => row.url === "/api/cluster/jobs")).toBe(true),
  );
  expect(
    requests.find((row) => row.url === "/api/cluster/jobs")?.body,
  ).toMatchObject({
    scenario_id: "s1",
    worker_id: null,
    minimum_ram_gb: 16,
    request: {
      prepared_input_id: "prepared-1",
      mode: "phase3_two_stage",
      time_limit_seconds: 465,
      rebuild_dispatch: false,
      use_existing_duties: false,
      random_seed: 17,
    },
  });
  expect(requests.some((row) => row.url.endsWith("/run-optimization"))).toBe(
    false,
  );
});
it("sends the chosen RAM floor with a distributed optimization", async () => {
  mount();
  await prepare();
  fireEvent.change(screen.getByLabelText("計算の配布先"), {
    target: { value: "auto" },
  });
  fireEvent.change(screen.getByLabelText("必要な空きRAM（GB）"), {
    target: { value: "24" },
  });
  fireEvent.click(screen.getByRole("button", { name: "2. 計算を開始" }));
  await waitFor(() =>
    expect(requests.some((row) => row.url === "/api/cluster/jobs")).toBe(true),
  );
  expect(
    requests.find((row) => row.url === "/api/cluster/jobs")?.body
      .minimum_ram_gb,
  ).toBe(24);
});
it("routes simulation through the prepared-simulation endpoint", async () => {
  mount();
  await prepare();
  fireEvent.change(screen.getByLabelText("実行する処理"), {
    target: { value: "simulate" },
  });
  fireEvent.click(screen.getByRole("button", { name: "2. 計算を開始" }));
  await waitFor(() =>
    expect(requests.some((row) => row.url.endsWith("/simulation/run"))).toBe(
      true,
    ),
  );
  expect(
    requests.find((row) => row.url.endsWith("/simulation/run"))?.body,
  ).toEqual({ prepared_input_id: "prepared-1", source: "duties" });
});
it("restores an existing job and exposes restart failure", async () => {
  localStorage.setItem("ev-job-s1", "known-job");
  mount();
  await screen.findByText("Worker orphaned after restart");
  expect(requests.some((row) => row.url === "/api/jobs/known-job")).toBe(true);
});
it("retains zero and false controls instead of silently applying defaults", () => {
  expect(
    executionControls({
      mipGap: 0,
      randomSeed: 0,
      stage1BevFrontierEnabled: false,
    }),
  ).toEqual({ mip_gap: 0, random_seed: 0, stage1_bev_frontier_enabled: false });
});

it("reuses a durable submission identity after a lost response and a remount", async () => {
  const originalFetch = globalThis.fetch;
  let dropReply = true;
  vi.stubGlobal("fetch", (url: string, options?: RequestInit) => {
    const response = originalFetch(url, options);
    if (url === "/api/cluster/jobs" && dropReply) {
      dropReply = false;
      return response.then(() => {
        throw new TypeError("accepted response lost");
      });
    }
    return response;
  });
  mount();
  await prepare();
  fireEvent.change(screen.getByLabelText("計算の配布先"), {
    target: { value: "auto" },
  });
  fireEvent.click(screen.getByRole("button", { name: "2. 計算を開始" }));
  await waitFor(() =>
    expect(requests.some((row) => row.url === "/api/cluster/jobs")).toBe(true),
  );
  const first = requests.find((row) => row.url === "/api/cluster/jobs")!.body
    .idempotency_key;
  expect(typeof first).toBe("string");
  await screen.findByText(/accepted response lost/);
  cleanup();
  mount();
  await prepare();
  fireEvent.change(screen.getByLabelText("計算の配布先"), {
    target: { value: "auto" },
  });
  fireEvent.click(screen.getByRole("button", { name: "2. 計算を開始" }));
  await waitFor(() =>
    expect(
      requests.filter((row) => row.url === "/api/cluster/jobs").length,
    ).toBe(2),
  );
  expect(
    requests.filter((row) => row.url === "/api/cluster/jobs")[1].body
      .idempotency_key,
  ).toBe(first);
});
