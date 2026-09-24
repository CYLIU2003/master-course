import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import BatchProgress from "./BatchProgress";

afterEach(cleanup);

it("uses declared tasks and the latest attempt without treating failure as completion", () => {
  render(
    <BatchProgress
      jobs={[
        {
          id: "old",
          state: "FAILED",
          worker_id: "pc-a",
          error: "old failure",
          created_at: "1",
          manifest: {
            batch_id: "may",
            task_id: "week-1",
            batch_task_count: 3,
            attempt_number: 1,
          },
        },
        {
          id: "new",
          state: "COMPLETED",
          worker_id: "pc-b",
          error: null,
          created_at: "2",
          manifest: {
            batch_id: "may",
            task_id: "week-1",
            batch_task_count: 3,
            attempt_number: 2,
          },
        },
        {
          id: "running",
          state: "RUNNING",
          worker_id: "pc-c",
          error: null,
          created_at: "3",
          manifest: {
            batch_id: "may",
            task_id: "week-2",
            batch_task_count: 3,
            attempt_number: 1,
          },
          execution_progress: {
            percent: 55,
            stage: "solve",
            message: "Running",
            observed_at: "now",
          },
        },
      ]}
    />,
  );
  const batch = screen.getByText(/may · 33% · 回収確認 1\/3 · 要確認 0/);
  expect(batch).toBeTruthy();
  const details = batch.closest("details")!;
  expect(within(details).getByText(/登録済み 2\/3/)).toBeTruthy();
  expect(within(details).getByText("55% · solve")).toBeTruthy();
  expect(within(details).queryByText("old failure")).toBeNull();
});
