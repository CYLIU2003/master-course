import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RunPanel from "./RunPanel";
import type { Overview } from "../api";

// Selection paging is tested by the real Electron smoke. Keep this test focused
// on request semantics, stale Prepare state, and background job transitions.
vi.mock("./DataTable", () => ({ default: () => <div>scope table</div> }));
const data: Overview = {
  meta: { id: "s1", name: "Existing scenario" },
  stats: {},
  scope: {
    depotSelection: { depotIds: ["tsurumaki"] },
    routeSelection: { includeRouteIds: ["route-1"] },
  },
  settings: {
    service_date: "2025-05-12",
    planning_days: 7,
    initial_soc: 80,
    diesel_price_per_l: 140,
    random_seed: 42,
    rolling_lookahead_hours: 24,
  },
  result: { available: false, source: null, values: {} },
};
const requests: { url: string; body: Record<string, unknown> }[] = [];
beforeEach(() => {
  const saved = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => saved.get(key) ?? null,
    setItem: (key: string, value: string) => saved.set(key, value),
    clear: () => saved.clear(),
  });
  localStorage.clear();
  requests.length = 0;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <RunPanel id="s1" data={data} />
    </QueryClientProvider>,
  );
}
function respond(payload: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status }));
}
it("retains saved physical controls and invalidates Prepare after editing", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, options: RequestInit) => {
      requests.push({ url, body: JSON.parse(String(options.body)) });
      return respond({
        ready: true,
        preparedInputId: "prepared-1",
        tripCount: 100,
        vehicleCount: 35,
        planningDays: 7,
        warnings: [],
      });
    }),
  );
  mount();
  expect(
    screen
      .getByRole("button", { name: "最適化を実行" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "入力を準備" }));
  await screen.findByText(/入力準備済み/);
  expect(requests).toHaveLength(1);
  expect(requests[0].body.service_dates).toEqual([
    "2025-05-12",
    "2025-05-13",
    "2025-05-14",
    "2025-05-15",
    "2025-05-16",
    "2025-05-17",
    "2025-05-18",
  ]);
  expect(requests[0].body.simulation_settings).toMatchObject({
    initial_soc: 80,
    diesel_price_per_l: 140,
    random_seed: 42,
    rolling_lookahead_hours: 24,
  });
  expect(
    screen
      .getByRole("button", { name: "最適化を実行" })
      .hasAttribute("disabled"),
  ).toBe(false);
  fireEvent.change(screen.getByLabelText("開始日"), {
    target: { value: "2025-05-19" },
  });
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "最適化を実行" })
        .hasAttribute("disabled"),
    ).toBe(true),
  );
});
it("restores polling for an existing job and exposes restart-orphan failure", async () => {
  localStorage.setItem("ev-job-s1", "known-job");
  const fetch = vi.fn(() =>
    respond({
      job_id: "known-job",
      status: "failed",
      progress: 20,
      message: "BFF restarted",
      error: "Worker orphaned after restart",
    }),
  );
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByText("Worker orphaned after restart");
  expect(fetch.mock.calls.length).toBe(1);
  expect(
    screen.getByRole("button", { name: "入力を準備" }).hasAttribute("disabled"),
  ).toBe(false);
});
