import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import CampaignProgress from "./CampaignProgress";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderProgress(payload: unknown) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(payload)))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><CampaignProgress /></QueryClientProvider>);
  return client;
}

it("shows completed-week percentages and an actionable failed-week detail", async () => {
  const client = renderProgress({
    schema_version: "monthly_campaign_progress_v1",
    campaign: "shibu24-monthly", generated_at_utc: new Date().toISOString(),
    git_sha: "fixed-source-sha", status: "ERROR", prepare_process: "STOPPED",
    stages: {
      overall: { completed: 3, total: 6, percent: 50 },
      prepare: { completed: 2, total: 2, percent: 100 },
      solve: { completed: 1, total: 2, percent: 50 },
      audit: { completed: 0, total: 2, percent: 0 },
    },
    campaign_stage: "FAILED", campaign_error: null, connection_status: null,
    failed_count: 1, recent_log: [], recent_errors: [],
    weeks: [
      { week: "2025-01-06", status: "AUDIT_FAILED", status_label: "成果物監査エラー",
        prepared: true, strict_scope_audit_passed: true, prepared_input_id: "prepared-first",
        prepared_input_sha256: "input-sha", scenario_id: "scenario-first", job_id: "job-first",
        worker_id: "worker-1", collected_sha256: "archive-sha", audit_verified: false,
        error_code: "SHA_MISMATCH", error: "Expected digest differs", warning_codes: [], overnight: null },
      { week: "2025-02-03", status: "PREPARED", status_label: "入力準備済み",
        prepared: true, strict_scope_audit_passed: true, prepared_input_id: "prepared-second",
        prepared_input_sha256: "input2", scenario_id: "scenario-second", job_id: null,
        worker_id: null, collected_sha256: null, audit_verified: false,
        error_code: null, error: null, warning_codes: [], overnight: null },
    ],
  });

  expect(await screen.findByText("要対応")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "月別キャンペーンの進捗" })).toBeTruthy();
  expect(screen.getByRole("progressbar", { name: "入力準備の進捗" }).getAttribute("value")).toBe("2");
  expect(screen.getByRole("progressbar", { name: "計算の進捗" }).getAttribute("value")).toBe("1");
  expect(screen.getByText("成果物監査エラー")).toBeTruthy();
  fireEvent.click(screen.getAllByText("詳細")[0]);
  expect(screen.getByText("Expected digest differs")).toBeTruthy();
  expect(screen.getByText("SHA_MISMATCH")).toBeTruthy();
  expect(screen.getByText(/研究採用・大域最適性の証明にはなりません/)).toBeTruthy();
  client.clear();
});

it("hides a campaign absent from the selected controller", async () => {
  const fetch = vi.fn(() => Promise.resolve(new Response(null, { status: 404 })));
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CampaignProgress origin="http://localhost:8890" />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "http://localhost:8890/campaign-progress.json",
    { cache: "no-store" },
  ));
  await waitFor(() =>
    expect(screen.queryByRole("heading", { name: "月別キャンペーンの進捗" })).toBeNull(),
  );
  client.clear();
});

it("hides progress from a different fixed source revision", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    schema_version: "monthly_campaign_progress_v1",
    campaign: "old-campaign",
    generated_at_utc: new Date().toISOString(),
    git_sha: "older-sha",
    status: "WAITING",
    prepare_process: "STOPPED",
    failed_count: 0,
    stages: {
      overall: { completed: 0, total: 3, percent: 0 },
      prepare: { completed: 0, total: 1, percent: 0 },
      solve: { completed: 0, total: 1, percent: 0 },
      audit: { completed: 0, total: 1, percent: 0 },
    },
    weeks: [{ week: "2025-01-06", status: "WAITING", status_label: "待機中", prepared: false, audit_verified: false }],
    recent_log: [],
    recent_errors: [],
  })))));
  render(
    <QueryClientProvider client={client}>
      <CampaignProgress controllerSha="current-sha" />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(client.getQueryData(["monthly-campaign-progress", ""])).toBeTruthy());
  expect(screen.queryByText("old-campaign")).toBeNull();
  client.clear();
});

it("rejects a response with the wrong schema instead of showing false progress", async () => {
  const client = renderProgress([]);
  expect(await screen.findByText(/進捗記録の形式が一致しません/)).toBeTruthy();
  expect(screen.queryByRole("progressbar")).toBeNull();
  client.clear();
});
