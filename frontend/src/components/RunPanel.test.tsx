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
  meta: { id: "s1", name: "Saved scenario" },
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
beforeEach(() => {
  const saved = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => saved.get(key) ?? null,
    setItem: (key: string, value: string) => saved.set(key, value),
  });
  requests.length = 0;
  revision = "original";
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, options: RequestInit = {}) => {
      const body = options.body
        ? (JSON.parse(String(options.body)) as Record<string, unknown>)
        : {};
      requests.push({ url, body });
      let payload: unknown = {};
      if (url.endsWith("/configuration"))
        payload = { ...configuration, revision };
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
