import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";

beforeEach(() => {
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: vi.fn() });
  window.history.replaceState(null, "", "/");
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("creates a named scenario and sends its description through the existing API", async () => {
  const calls: Array<{ url: string; method: string; body: unknown }> = [];
  vi.stubGlobal("fetch", vi.fn((url: string, options: RequestInit = {}) => {
    const method = options.method ?? "GET";
    const body = options.body ? JSON.parse(String(options.body)) : null;
    calls.push({ url, method, body });
    const result = method === "POST"
      ? { id: "new-scenario", name: "新しい比較", description: "路線を選んで比較" }
      : url.includes("/desktop/scenarios/new-scenario")
        ? { meta: { id: "new-scenario", name: "新しい比較" }, stats: {}, scope: {}, settings: {}, result: { available: false, source: null, values: {} } }
        : { items: [], total: 0, offset: 0, limit: 50, warnings: [] };
    return Promise.resolve(new Response(JSON.stringify(result), { status: method === "POST" ? 201 : 200 }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><App /></QueryClientProvider>);

  fireEvent.click(await screen.findByRole("button", { name: "新しく作成" }));
  fireEvent.change(screen.getByLabelText("シナリオ名"), { target: { value: "新しい比較" } });
  fireEvent.change(screen.getByLabelText("説明"), { target: { value: "路線を選んで比較" } });
  fireEvent.click(screen.getByRole("button", { name: /^作成$/ }));

  await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/api/scenarios")
    && (call.body as { description: string }).description === "路線を選んで比較")).toBe(true));
});

it("edits a scenario name from the scenario list", async () => {
  const calls: Array<{ url: string; method: string; body: unknown }> = [];
  vi.stubGlobal("fetch", vi.fn((url: string, options: RequestInit = {}) => {
    const method = options.method ?? "GET";
    const body = options.body ? JSON.parse(String(options.body)) : null;
    calls.push({ url, method, body });
    const result = method === "PUT"
      ? { id: "s-1", name: "名称変更後", description: "説明" }
      : { items: [{ id: "s-1", name: "渋24 原案", description: "説明", routeGroup: "shibu24" }],
          total: 1, offset: 0, limit: 50, warnings: [] };
    return Promise.resolve(new Response(JSON.stringify(result), { status: 200 }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><App /></QueryClientProvider>);

  fireEvent.click(await screen.findByRole("button", { name: "名前・説明を編集" }));
  fireEvent.change(screen.getByLabelText("シナリオ名"), { target: { value: "名称変更後" } });
  fireEvent.click(screen.getByRole("button", { name: /^保存$/ }));

  await waitFor(() => expect(calls.some((call) => call.method === "PUT"
    && call.url.endsWith("/api/scenarios/s-1")
    && (call.body as { name: string }).name === "名称変更後")).toBe(true));
});

it("duplicates a scenario through the existing scenario API and opens the copy", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, options: RequestInit = {}) => {
    calls.push(`${options.method ?? "GET"} ${url}`);
    const result = options.method === "POST"
      ? { id: "s-copy", name: "渋24 原案 Copy" }
      : url.includes("/desktop/scenarios/s-copy")
        ? { meta: { id: "s-copy", name: "渋24 原案 Copy" }, stats: {}, scope: {}, settings: {}, result: { available: false, source: null, values: {} } }
        : { items: [{ id: "s-1", name: "渋24 原案", routeGroup: "shibu24" }],
            total: 1, offset: 0, limit: 50, warnings: [] };
    return Promise.resolve(new Response(JSON.stringify(result), { status: options.method === "POST" ? 201 : 200 }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><App /></QueryClientProvider>);

  fireEvent.click(await screen.findByRole("button", { name: "複製して新規作成" }));
  await waitFor(() => expect(calls).toContain("POST /api/scenarios/s-1/duplicate"));
  expect(await screen.findByText("渋24 原案 Copy")).toBeTruthy();
});
