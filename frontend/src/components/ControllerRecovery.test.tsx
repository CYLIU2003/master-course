import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ControllerRecovery from "./ControllerRecovery";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const hash = "a".repeat(40);
function setup(origin = "", readOnly = false, badBinding = false) {
  const port = Number(new URL(origin || window.location.origin).port || 80);
  let enabled = true;
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes("supervisor-control-")) return new Response(JSON.stringify({ schema_version: "supervisor_discovery_v1",
      controller_port: badBinding ? 1 : port, solver_git_sha: hash, control_origin: "http://127.0.0.1:55432", token: "a".repeat(40) }));
    if (options?.method === "POST") enabled = url.endsWith("/enable");
    return new Response(JSON.stringify({ schema_version: "supervisor_ui_v1", controller_port: port, solver_git_sha: hash,
      enabled, status: enabled ? "PROCESS_PRESENT" : "DISABLED", binding_matches: true, starts: 0, max_starts: 3,
      service_observed_at_utc: "2026-09-27T10:00:00Z", last_tick_utc: "2026-09-27T10:00:00Z", process: { pid: 123 } }));
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ControllerRecovery origin={origin} readOnly={readOnly} controllerSha={hash} /></QueryClientProvider>);
  return { client, fetcher };
}

it("displays actual status and applies disable/enable to this controller", async () => {
  const { client, fetcher } = setup();
  expect(await screen.findByText(/管理プロセスの生存を確認/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "自動復旧を無効にする" }));
  await waitFor(() => expect((screen.getByRole("button", { name: "自動復旧を有効にする" }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "自動復旧を有効にする" }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST").map(([url]) => url))
    .toEqual(["http://127.0.0.1:55432/disable", "http://127.0.0.1:55432/enable"]));
  expect(screen.getByText(/新しい計算試行は作りません/)).toBeTruthy();
  client.clear();
});

it("keeps other controllers read-only", async () => {
  const { client, fetcher } = setup("http://127.0.0.1:8891", true);
  await screen.findByText(/管理プロセスの生存を確認/);
  expect((screen.getByRole("button", { name: "自動復旧を無効にする" }) as HTMLButtonElement).disabled).toBe(true);
  expect(fetcher.mock.calls[0][0]).toBe("http://127.0.0.1:8891/supervisor-control-8891.json");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  client.clear();
});

it("rejects discovery bound to a different controller before fetching it", async () => {
  const { client, fetcher } = setup("", false, true);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("対応が一致しません"));
  expect(fetcher.mock.calls).toHaveLength(1);
  client.clear();
});

it("marks cached status unknown and disables actions after a connection failure", async () => {
  const { client, fetcher } = setup();
  await screen.findByText(/管理プロセスの生存を確認/);
  fetcher.mockRejectedValue(new Error("disconnected"));
  fireEvent.click(screen.getByRole("button", { name: "復旧状態を更新" }));
  await screen.findByText(/現在状態は未確認/);
  expect((screen.getByRole("button", { name: "自動復旧を無効にする" }) as HTMLButtonElement).disabled).toBe(true);
  client.clear();
});
