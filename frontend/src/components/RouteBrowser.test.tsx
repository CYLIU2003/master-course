import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RouteBrowser from "./RouteBrowser";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows patterns only after a depot is checked and keeps other depots hidden", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    depots: [{ id: "d1", name: "営業所A" }, { id: "d2", name: "営業所B" }],
    routes: [
      { id: "r1", routeCode: "渋21", name: "渋21 A→B", depotIds: ["d1"], startStop: "A", endStop: "B", routeVariantType: "main", direction: "outbound", distanceKm: 1.5, stopCount: 2, stops: [{ id: "a", name: "A", lat: 35, lon: 139 }, { id: "b", name: "B", lat: 35.01, lon: 139 }], tripCount: 4 },
      { id: "r2", routeCode: "黒01", name: "黒01 C→D", depotIds: ["d2"], startStop: "C", endStop: "D", routeVariantType: "branch", direction: "inbound", distanceKm: 2, stopCount: 2, stops: [], tripCount: 2 },
    ],
  }), { status: 200 }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><RouteBrowser id="s" /></QueryClientProvider>);
  await screen.findByText("営業所A");
  expect(screen.queryByText(/渋21 · 1パターン/)).toBeNull();
  fireEvent.click(screen.getByLabelText(/営業所A/));
  expect(screen.getByText(/渋21 · 1パターン/)).toBeTruthy();
  expect(screen.queryByText(/黒01 · 1パターン/)).toBeNull();
  fireEvent.click(screen.getByText(/営業所A · 1系統/));
  fireEvent.click(screen.getByText(/渋21 · 1パターン/));
  expect(screen.getByText(/A → B/)).toBeTruthy();
  await waitFor(() => expect(screen.getByText(/1.50 km/)).toBeTruthy());
});

it("selects a depot's patterns and removes them when the depot is unchecked", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    depots: [{ id: "d", name: "営業所D" }],
    routes: [{ id: "r", routeCode: "R", name: "R", depotIds: ["d"], startStop: "A", endStop: "B", routeVariantType: "main", direction: "outbound", distanceKm: 1, stopCount: 2, stops: [], tripCount: 1 }],
  }), { status: 200 }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onScopeChange = vi.fn();
  const view = render(<QueryClientProvider client={client}><RouteBrowser id="s" selectedDepots={[]} selectedRoutes={[]} onScopeChange={onScopeChange} /></QueryClientProvider>);
  await screen.findByText("営業所D");
  fireEvent.click(screen.getAllByRole("checkbox")[0]);
  expect(onScopeChange).toHaveBeenLastCalledWith(["d"], ["r"]);
  view.rerender(<QueryClientProvider client={client}><RouteBrowser id="s" selectedDepots={["d"]} selectedRoutes={["r"]} onScopeChange={onScopeChange} /></QueryClientProvider>);
  fireEvent.click(screen.getAllByRole("checkbox")[0]);
  expect(onScopeChange).toHaveBeenLastCalledWith([], []);
});

it("loads ODPT and exposes unconfirmed patterns only after that group is checked", async () => {
  const fetchMock = vi.fn((_url: unknown) => Promise.resolve(new Response(JSON.stringify({
    depots: [{ id: "d", name: "営業所D" }],
    routes: [{ id: "r", routeCode: "森02", name: "森02", depotIds: [], startStop: "A", endStop: "B", routeVariantType: "main", direction: "outbound", distanceKm: 1, storedDistanceKm: 0, stopCount: 2, stops: [], tripCount: 0 }],
  }), { status: 200 })));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><RouteBrowser id="s" source="odpt" /></QueryClientProvider>);
  await screen.findByText("所管未確認");
  expect(String(fetchMock.mock.calls[0][0])).toContain("/desktop/route-catalog/odpt");
  expect(screen.queryByText(/森02 · 1パターン/)).toBeNull();
  fireEvent.click(screen.getByLabelText(/所管未確認/));
  expect(screen.getByText(/森02 · 1パターン/)).toBeTruthy();
  expect(screen.getByText(/距離0のパターンが 1 件/)).toBeTruthy();
});

it("shows a sourced depot reference only after that depot is checked", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    depots: [{ id: "nippa", name: "新羽営業所" }],
    officialReferenceCapturedAt: "2026-09-25",
    routes: [{
      id: "r", routeCode: "日51", name: "日51", depotIds: [],
      officialDepotReference: { depotId: "nippa", sourceUrl: "https://www.tokyubus.co.jp/route/routemap/pdf/09_nippa.pdf", sourceDate: "2026-04-01" },
      startStop: "A", endStop: "B", routeVariantType: "main", direction: "unknown",
      distanceKm: 1, stopCount: 2, stops: [], tripCount: 1,
    }],
  }), { status: 200 }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><RouteBrowser id="s" source="odpt" /></QueryClientProvider>);
  await screen.findByText("新羽営業所");
  expect(screen.queryByText(/日51 · 1パターン/)).toBeNull();
  expect(screen.queryByText("所管未確認")).toBeNull();
  fireEvent.click(screen.getByLabelText(/新羽営業所/));
  fireEvent.click(screen.getByText(/新羽営業所 · 1系統/));
  fireEvent.click(screen.getByText(/日51 · 1パターン/));
  fireEvent.click(screen.getByText(/A → B/));
  expect(screen.getByRole("link", { name: "東急バス公式資料" }).getAttribute("href")).toContain("09_nippa.pdf");
  expect(screen.getByText(/ODPT保存所管: 未割当/)).toBeTruthy();
});


it("preserves earlier exclusions and unknown route IDs when another depot changes", async () => {
  const routes = [
    { id: "a1", depotIds: ["a"] }, { id: "a2", depotIds: ["a"] },
    { id: "b1", depotIds: ["b"] },
  ].map((r) => ({ ...r, name: r.id, routeCode: r.id, routeVariantType: "main", direction: "unknown", distanceKm: null, stops: [], stopCount: 0 }));
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    depots: [{ id: "a", name: "Depot A" }, { id: "b", name: "Depot B" }], routes,
  })))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const change = vi.fn();
  const renderBrowser = (depots: string[], selected: string[]) =>
    <QueryClientProvider client={client}><RouteBrowser id="s" selectedDepots={depots} selectedRoutes={selected} onScopeChange={change} /></QueryClientProvider>;
  const view = render(renderBrowser(["a"], ["a1", "unknown-id"]));
  await screen.findByText("Depot B");
  fireEvent.click(screen.getByLabelText(/Depot B\s*1パターン/));
  expect(change).toHaveBeenLastCalledWith(["a", "b"], ["a1", "unknown-id", "b1"]);
  view.rerender(renderBrowser(["a", "b"], ["a1", "unknown-id", "b1"]));
  fireEvent.click(screen.getByLabelText(/Depot B\s*1パターン/));
  expect(change).toHaveBeenLastCalledWith(["a"], ["a1", "unknown-id"]);
  client.clear();
});
