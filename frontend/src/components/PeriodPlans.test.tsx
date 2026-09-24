import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PeriodPlans from "./PeriodPlans";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function setup(periods: unknown[] = []) {
  const fetch = vi.fn((_url: string, init?: RequestInit) => Promise.resolve(new Response(JSON.stringify({
    revision: init?.method === "PUT" ? 2 : 1, periods: init?.body ? JSON.parse(String(init.body)).periods : periods,
    progress: { prepared: 0, verified: 0 } }))));
  vi.stubGlobal("fetch", fetch);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <PeriodPlans id="parent" onDirty={vi.fn()} /></QueryClientProvider>);
  return fetch;
}
it("adds several periods to one scenario without submitting compute jobs", async () => {
  const fetch = setup();
  await screen.findByText("まだ期間がありません。1つのシナリオに複数の週を追加できます。");
  for (const start of ["2025-01-06", "2025-02-03"]) {
    fireEvent.change(screen.getByLabelText("期間開始日"), { target: { value: start } });
    await waitFor(() => expect((screen.getByText("期間を追加") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("期間を追加"));
  }
  fireEvent.click(screen.getByText("計画を保存"));
  await waitFor(() => expect(fetch.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
  expect(fetch.mock.calls.every(([url]) => url.includes("/desktop/scenarios/parent/periods"))).toBe(true);
});
it("shows failed attempts and their evidence without calling them successful", async () => {
  setup([{ id: "jan", label: "1月", start: "2025-01-06", days: 7, attempts: [
    { id: "attempt", state: "FAILED", verified: false, error: "Stage2 infeasible", source_git_sha: "frozen" }] }]);
  await screen.findByText("エラー");
  expect(screen.getByText(/Stage2 infeasible/)).toBeTruthy();
});
