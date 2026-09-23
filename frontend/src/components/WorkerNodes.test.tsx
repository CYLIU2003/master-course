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
  job_role: "both",
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
it("explains SSH timeouts without exposing a raw subprocess command", () => {
  mount([{ ...node, probe_error_code: "SSH_TIMEOUT", last_error: "Command '['ssh', '100.72.59.121']' timed out after 10 seconds" }]);
  expect(screen.getByText(/SSHの応答がありません。自動で再確認します/)).toBeTruthy();
  expect(screen.queryByText(/Command \[/)).toBeNull();
});
it("sets each worker's job role and does not offer Gurobi on an unconfigured worker", () => {
  const action = mount([{ ...node, gurobi: false, job_role: "alns_only" }]);
  const select = screen.getByRole("combobox", { name: "PSLABの計算担当" });
  const options = within(select).getAllByRole("option") as HTMLOptionElement[];
  expect(options.find((option) => option.value === "gurobi_only")?.disabled).toBe(true);
  fireEvent.change(select, { target: { value: "diagnostic_only" } });
  expect(action).toHaveBeenCalledWith("/cluster/workers/pc/role/diagnostic_only");
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

it("sorts each requested hardware metric and keeps unknown values last", () => {
  mount([
    {
      ...node,
      id: "a",
      name: "A",
      capability: {
        cpu_model: "Intel(R) Core(TM) i7-6700 CPU @ 3.40GHz",
        cpu_physical_cores: 4,
        cpu_count: 20,
        ram_gb: 16,
        ram_free_gb: 2,
        disk_free_gb: 50,
      },
    },
    {
      ...node,
      id: "b",
      name: "B",
      capability: {
        cpu_model: "Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz",
        cpu_physical_cores: 8,
        cpu_count: 8,
        ram_gb: 8,
        ram_free_gb: 6,
        disk_free_gb: 100,
      },
    },
    { ...node, id: "c", name: "C", capability: { cpu_model: "unmapped CPU" } },
  ]);
  const order = () =>
    screen
      .getAllByRole("article")
      .map((card) => card.getAttribute("aria-label"));
  const sort = (field: string) =>
    fireEvent.change(screen.getByLabelText("並べ替え"), {
      target: { value: field },
    });
  expect(order()).toEqual(["B", "A", "C"]);
  sort("logical_threads");
  expect(order()).toEqual(["A", "B", "C"]);
  sort("ram_total");
  expect(order()).toEqual(["A", "B", "C"]);
  sort("ram_available");
  expect(order()).toEqual(["B", "A", "C"]);
  sort("disk_available");
  expect(order()).toEqual(["B", "A", "C"]);
  sort("passmark_cpu_mark");
  expect(order()).toEqual(["A", "B", "C"]);
  expect(
    within(screen.getByRole("article", { name: "A" }))
      .getByRole("link", { name: "8,032" })
      .getAttribute("href"),
  ).toContain("id=2598");
  fireEvent.change(screen.getByLabelText("順序"), { target: { value: "asc" } });
  expect(order()).toEqual(["B", "A", "C"]);
});
