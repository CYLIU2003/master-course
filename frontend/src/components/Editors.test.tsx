import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import EnergyPanel from "./EnergyPanel";
import SettingsPanel from "./SettingsPanel";
import DataWorkspace from "./DataWorkspace";
import EntityManager from "./EntityManager";
import { FieldGrid } from "./Fields";
import type { Row } from "../api";
const asset: Row = {
  depot_id: "d",
  bess_enabled: true,
  bess_energy_kwh: 6000,
  bess_power_kw: 900,
  bess_initial_soc_kwh: 3000,
  bess_soc_min_kwh: 1500,
  bess_soc_max_kwh: 5700,
  bess_soc_min_percent: 25,
  bess_soc_max_ratio: 0.95,
  bess_terminal_soc_target_percent: 50,
  bess_terminal_soc_target_kwh: 3000,
  bess_terminal_soc_policy: "return_to_initial",
  bess_balance_period: "daily",
};
const values: Row = {
  selectedDepotIds: ["d"],
  selectedRouteIds: ["r"],
  initialSoc: 0.8,
  socMin: 0.2,
  socMax: 0.9,
  objectiveWeights: { energy: 1 },
  depotEnergyAssets: [asset],
  bessBalancePeriod: "daily",
  rollingBessTerminalPolicy: "scenario",
};
let calls: { url: string; method: string; body: Row }[] = [];
beforeEach(() => {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, options: RequestInit = {}) => {
      const body: Row = options.body ? JSON.parse(String(options.body)) : {};
      calls.push({ url, method: options.method ?? "GET", body });
      let result: unknown = { items: [], total: 0, offset: 0, limit: 250 };
      if (url.endsWith("/configuration"))
        result = {
          values: { ...values, ...((body.changes as Row) ?? {}) },
          revision: "revision",
        };
      else if (url.includes("/tables/depots"))
        result = { items: [{ id: "d", name: "営業所D" }], total: 1 };
      else if (url.includes("/tables/vehicle_templates"))
        result = {
          items: [
            {
              id: "template",
              name: "電気バス標準",
              type: "BEV",
              batteryKwh: 300,
            },
          ],
          total: 1,
        };
      else if (url.endsWith("/calendar"))
        result = { items: [{ service_id: "WEEKDAY", monday: true }], total: 1 };
      return Promise.resolve(
        new Response(JSON.stringify(result), { status: 200 }),
      );
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(component: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>,
  );
}
it("applies the free BESS band through both asset and rolling configuration", async () => {
  mount(<EnergyPanel id="s" onSaved={vi.fn()} onDirty={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "20〜80%を適用" }));
  fireEvent.click(screen.getByRole("button", { name: "設備を保存" }));
  await waitFor(() =>
    expect(calls.some((call) => call.method === "PUT")).toBe(true),
  );
  const changes = calls.find((call) => call.method === "PUT")!.body
    .changes as Row;
  expect(changes).toMatchObject({
    bessBalancePeriod: "evaluation_period",
    rollingBessTerminalPolicy: "minimum_only",
  });
  const saved = (changes.depotEnergyAssets as Row[])[0];
  expect(saved).toMatchObject({
    bess_soc_min_kwh: 1200,
    bess_soc_max_kwh: 4800,
    bess_initial_soc_kwh: 3000,
    bess_terminal_soc_target_kwh: 0,
    bess_terminal_soc_policy: "minimum_only",
  });
  expect(saved).not.toHaveProperty("bess_soc_min_percent");
  expect(saved).not.toHaveProperty("bess_terminal_soc_target_percent");
});
it("saves only edited settings and keeps invalid JSON from being submitted", async () => {
  const dirty = vi.fn();
  mount(<SettingsPanel id="s" onSaved={vi.fn()} onDirty={dirty} />);
  fireEvent.click(await screen.findByRole("button", { name: "SOC・燃料" }));
  fireEvent.change(await screen.findByLabelText("車両の初期SOC（比率0〜1）"), {
    target: { value: "0.65" },
  });
  fireEvent.click(screen.getByRole("button", { name: "変更を保存" }));
  await waitFor(() =>
    expect(calls.some((call) => call.method === "PUT")).toBe(true),
  );
  expect(calls.find((call) => call.method === "PUT")!.body).toEqual({
    revision: "revision",
    changes: { initialSoc: 0.65 },
  });
  fireEvent.click(screen.getByRole("button", { name: "目的・実験" }));
  fireEvent.change(screen.getAllByLabelText("JSONデータ")[1], {
    target: { value: "{" },
  });
  expect(
    screen.getByRole("button", { name: "変更を保存" }).hasAttribute("disabled"),
  ).toBe(true);
  expect(
    screen.getByRole("button", { name: "SOC・燃料" }).hasAttribute("disabled"),
  ).toBe(true);
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
});
it("keeps a reference draft until explicit save or reset", async () => {
  const dirty = vi.fn();
  mount(
    <DataWorkspace id="s" blocked={false} onSaved={vi.fn()} onDirty={dirty} />,
  );
  fireEvent.change(screen.getByLabelText("データ編集メニュー"), {
    target: { value: "calendar" },
  });
  fireEvent.change(await screen.findByLabelText("JSONデータ"), {
    target: { value: "{" },
  });
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
  expect(
    screen.getByLabelText("データ編集メニュー").hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "元に戻す" }));
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
  expect(calls.some((call) => call.method === "PUT")).toBe(false);
});
it("creates a bounded vehicle batch using the chosen template values", async () => {
  mount(<EntityManager id="s" onSaved={vi.fn()} onDirty={vi.fn()} />);
  await screen.findByRole("button", { name: "追加" });
  await waitFor(() =>
    expect(
      calls.some((call) => call.url.includes("/tables/vehicle_templates")),
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "追加" }));
  fireEvent.change(await screen.findByLabelText("テンプレートから入力"), {
    target: { value: "template" },
  });
  fireEvent.change(screen.getByLabelText("作成する台数"), {
    target: { value: "3" },
  });
  fireEvent.click(screen.getByRole("button", { name: "作成" }));
  await waitFor(() =>
    expect(calls.some((call) => call.method === "POST")).toBe(true),
  );
  expect(calls.find((call) => call.method === "POST")!.body).toMatchObject({
    depotId: "d",
    quantity: 3,
    type: "BEV",
    batteryKwh: 300,
  });
});
it("shows saved enum values even when they are outside curated choices", () => {
  render(
    <FieldGrid
      fields={[
        { key: "mode", label: "Mode", kind: "select", options: ["known"] },
      ]}
      value={{ mode: "existing" }}
      onChange={vi.fn()}
    />,
  );
  expect((screen.getByLabelText("Mode") as HTMLSelectElement).value).toBe(
    "existing",
  );
  expect(
    screen.getByRole("option", { name: "existing（保存済み）" }),
  ).toBeTruthy();
});

it("resetting a BESS draft also discards its global terminal controls", async () => {
  mount(<EnergyPanel id="s" onSaved={vi.fn()} onDirty={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "20〜80%を適用" }));
  fireEvent.click(screen.getByRole("button", { name: "元に戻す" }));
  fireEvent.change(screen.getByLabelText("BESS充放電電力（kW）"), {
    target: { value: "800" },
  });
  fireEvent.click(screen.getByRole("button", { name: "設備を保存" }));
  await waitFor(() =>
    expect(calls.some((call) => call.method === "PUT")).toBe(true),
  );
  expect(
    calls.find((call) => call.method === "PUT")!.body.changes,
  ).toMatchObject({
    bessBalancePeriod: "daily",
    rollingBessTerminalPolicy: "scenario",
  });
});
