import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import WorkerNodes, { type WorkerNode } from "./WorkerNodes";

afterEach(cleanup);
const node: WorkerNode = {
  id: "pc",
  name: "PSLAB",
  host: "100.64.1.2",
  ssh_user: "pslab",
  tailscale_ip: "100.64.1.2",
  transport: "ssh",
  enabled: true,
  mode: "active",
  status: "TAILSCALE_ONLINE",
  slots: 1,
  reserved: 0,
  gurobi: true,
  ram_gb: 0,
  tailscale_online: true,
  ssh_ready: false,
  environment_ready: false,
  can_run_optimization: false,
  can_run_diagnostic: false,
  readiness_reasons: ["SSH接続未確認"],
  network_checked_at: null,
  last_seen_at: null,
  last_probe_at: null,
  last_error: "Permission denied (publickey)",
  probing: false,
  metrics_stale: true,
  active_jobs: [],
  completed_jobs: 0,
  failed_jobs: 0,
  capability: {},
};
function mount(workers: WorkerNode[], action = vi.fn()) {
  render(
    <WorkerNodes
      data={{ workers, global_gurobi_slots: 2, reserved_gurobi_slots: 0 }}
      pending={false}
      onAction={action}
    />,
  );
  return action;
}
it("does not present Tailnet online as SSH or compute readiness", () => {
  mount([node]);
  const card = within(screen.getByRole("article", { name: "PSLAB" }));
  expect(card.getByText("Tailscale: オンライン")).toBeTruthy();
  expect(card.getByText("SSH: 未確認")).toBeTruthy();
  expect(
    card
      .getByRole("button", { name: "診断タスクを配布" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(card.getByText(/公開鍵とログインユーザー/)).toBeTruthy();
});
it("drains without a cancel request and offers enable for a drained node", () => {
  const action = mount([
    node,
    {
      ...node,
      id: "second",
      name: "SECOND",
      mode: "draining",
      status: "DRAINING",
    },
  ]);
  fireEvent.click(
    within(screen.getByRole("article", { name: "PSLAB" })).getByRole("button", {
      name: "新規割当停止",
    }),
  );
  expect(action).toHaveBeenCalledWith("/cluster/workers/pc/drain");
  fireEvent.click(
    within(screen.getByRole("article", { name: "SECOND" })).getByRole(
      "button",
      { name: "割当を有効化" },
    ),
  );
  expect(action).toHaveBeenCalledWith("/cluster/workers/second/enable");
});
it("filters a twelve-node pool without hiding an error behind online counts", () => {
  mount(
    Array.from({ length: 12 }, (_, i) => ({
      ...node,
      id: `pc-${i}`,
      name: `WORKER-${i}`,
    })),
  );
  expect(screen.getAllByRole("article")).toHaveLength(12);
  fireEvent.change(screen.getByPlaceholderText("PC名・Tailscale IP"), {
    target: { value: "WORKER-11" },
  });
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("article", { name: "WORKER-11" })).toBeTruthy();
});

it("shows a verified no-Gurobi worker as usable for its supported calculation", () => {
  mount([
    {
      ...node,
      id: "laptop-bolc6vit",
      name: "LAPTOP-BOLC6VIT",
      status: "SSH_READY",
      ssh_ready: true,
      environment_ready: true,
      can_run_no_gurobi: true,
      readiness_reasons: ["Gurobiのインストールと利用枠の設定が必要です"],
      last_error: null,
      metrics_stale: false,
    },
  ]);
  const card = within(screen.getByRole("article", { name: "LAPTOP-BOLC6VIT" }));
  expect(card.getByText("Gurobi不要の計算に対応")).toBeTruthy();
  expect(card.getByText(/Gurobi計算への確認事項/)).toBeTruthy();
  expect(
    screen
      .getAllByText("Gurobi不要の計算に対応")
      .find((element) => element.tagName === "SMALL")?.nextElementSibling
      ?.textContent,
  ).toBe("1 台");
  fireEvent.change(screen.getByLabelText("表示"), {
    target: { value: "ready" },
  });
  expect(screen.getByRole("article", { name: "LAPTOP-BOLC6VIT" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("表示"), {
    target: { value: "attention" },
  });
  expect(screen.queryByRole("article", { name: "LAPTOP-BOLC6VIT" })).toBeNull();
});
