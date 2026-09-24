import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RouteScopeSelector from "./RouteScopeSelector";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("loads every route page and selects an entire family by exact pattern IDs", async () => {
  const first = Array.from({ length: 250 }, (_, index) => ({
    id: `r-${index}`, routeCode: index === 0 ? "渋２４" : "東98",
    name: `Pattern ${index}`, depotId: "d",
  }));
  const last = { id: "r-250", routeCode: "渋24", name: "成城学園前駅 → 渋谷駅", depotId: "d" };
  const fetcher = vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify({
    items: url.includes("offset=250") ? [last] : first,
    total: 251, offset: url.includes("offset=250") ? 250 : 0, limit: 250,
  }), { status: 200 })));
  vi.stubGlobal("fetch", fetcher);
  const selected = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <RouteScopeSelector id="scenario-a" selected={[]} onSelection={selected} />
  </QueryClientProvider>);

  expect(await screen.findByText("0 / 251 パターンを選択中")).toBeTruthy();
  expect(fetcher).toHaveBeenCalledTimes(2);
  fireEvent.change(screen.getByPlaceholderText("例：渋24、成城学園前"), { target: { value: "渋24" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "渋２４の全パターン" }));
  await waitFor(() => expect(selected).toHaveBeenCalledWith(["r-0", "r-250"]));
});

it("refuses to render an incomplete route catalog as a valid choice", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    items: [{ id: "r-1", routeCode: "渋24" }], total: 2, offset: 0, limit: 250,
  }), { status: 200 }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <RouteScopeSelector id="scenario-a" selected={[]} onSelection={vi.fn()} />
  </QueryClientProvider>);
  expect(await screen.findByText(/路線一覧が途中で欠けました/)).toBeTruthy();
});

it("can narrow an all-routes scenario to one exact family without losing unknown IDs silently", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    items: [
      { id: "shibu-out", routeCode: "渋24", name: "往路" },
      { id: "shibu-back", routeCode: "渋24", name: "復路" },
      { id: "other", routeCode: "東98", name: "他系統" },
    ], total: 3, offset: 0, limit: 250,
  }), { status: 200 }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const selected = vi.fn();
  const { rerender } = render(<QueryClientProvider client={client}>
    <RouteScopeSelector id="scenario-b" selected={["shibu-out", "shibu-back", "other"]} onSelection={selected} />
  </QueryClientProvider>);

  expect(await screen.findByText("3 / 3 パターンを選択中")).toBeTruthy();
  fireEvent.change(screen.getByPlaceholderText("例：渋24、成城学園前"), { target: { value: "渋24" } });
  fireEvent.click(screen.getByRole("button", { name: "この系統だけを対象にする" }));
  expect(selected).toHaveBeenCalledWith(["shibu-out", "shibu-back"]);

  rerender(<QueryClientProvider client={client}>
    <RouteScopeSelector id="scenario-b" selected={["shibu-out", "missing"]} onSelection={selected} />
  </QueryClientProvider>);
  expect(screen.getByRole("button", { name: "この系統だけを対象にする" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByText(/現行の路線一覧にない選択IDが1件/)).toBeTruthy();
});
