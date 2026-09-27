import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LabConsole from "./LabConsole";
import type { ClusterWorkers, WorkerNode } from "./WorkerNodes";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const hash = "a".repeat(40);
const worker = (id: string, transport = "ssh") => ({ id, name: id, transport, tailscale_ip: transport === "local" ? null : `100.1.1.${id}`,
  capability: { ram_gb: 32, ram_free_gb: 20 }, readiness_reasons: ["コード不一致"], active_jobs: [], mode: "active", reserved: 0, status: "SSH_READY" } as unknown as WorkerNode);

function setup(readOnly = false) {
  const port = Number(new URL(window.location.origin).port || 80);
  const nodes = [worker('local', 'local'), ...Array.from({ length: 17 }, (_, i) => worker(String(i + 1)))];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('supervisor-control-')) return new Response(JSON.stringify({ schema_version: "supervisor_discovery_v1", controller_port: port,
      solver_git_sha: hash, control_origin: 'http://127.0.0.1:54321', token: 'x'.repeat(40) }));
    if (url.endsWith('/api/cluster/workers')) return new Response(JSON.stringify({ workers: nodes }));
    if (init?.method === 'POST') return new Response(JSON.stringify({ state: 'REVIEW_REQUIRED', solver_submitted: false }));
    return new Response(JSON.stringify({ schema_version: 'lab_console_v1', controller_port: port, solver_git_sha: hash, inventory_port: 8868, requests: [],
      report: { revision: 'b'.repeat(64), parent: 'scenario', included: 1, declared: 2, complete: false, observed_at_utc: '2026-09-27T10:00:00Z',
        cases: [{ week: '2025-01-06', state: 'REPORTING_RECOVERED', original_state: 'FAILED', included: true, total_cost_jpy: 123 },
          { week: '2025-02-03', state: 'RUNNING', included: false }] } }));
  });
  vi.stubGlobal('fetch', fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><LabConsole controllerSha={hash} readOnly={readOnly}
    workers={{ workers: nodes.slice(0, 5) } as ClusterWorkers} /></QueryClientProvider>);
  return { client, fetcher };
}

it('shows all 17 children separately from the five campaign workers', async () => {
  const { client } = setup();
  expect(await screen.findByText(/登録 18台（親機 1台・子機 17台）/)).toBeTruthy();
  expect(screen.getAllByText('今回の計算設定の対象外')).toHaveLength(13);
  expect(screen.getAllByText('割当候補・実投入時に判定')).toHaveLength(5);
  expect(screen.getByText('図表失敗を修復・再検算済み（元試行は失敗）')).toBeTruthy();
  expect(screen.getByText('未確定')).toBeTruthy();
  client.clear();
});

it('receives metadata without invoking job submission and labels it pending review', async () => {
  const { client, fetcher } = setup();
  await screen.findByText(/登録 18台/);
  fireEvent.change(screen.getByLabelText('依頼者'), { target: { value: '研究者A' } });
  fireEvent.change(screen.getByLabelText('研究テーマ'), { target: { value: '運用比較' } });
  fireEvent.change(screen.getByLabelText('タスク名'), { target: { value: '比較計算' } });
  fireEvent.change(screen.getByLabelText('入力・実行方法・期待する成果物'), { target: { value: '入力原本は別途共有' } });
  fireEvent.submit(screen.getByRole('button', { name: /依頼を受付簿へ保存/ }).closest('form')!);
  await screen.findByText(/受付簿へ保存しました/);
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST');
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe('http://127.0.0.1:54321/lab/requests');
  expect(JSON.parse(posts[0][1]!.body as string).requester).toBe('研究者A');
  expect(fetcher.mock.calls.some(([url]) => url.includes('/cluster/jobs'))).toBe(false);
  client.clear();
});

it('does not allow intake from another controller', async () => {
  const { client, fetcher } = setup(true);
  await screen.findByText(/登録 18台/);
  expect((screen.getByRole('button', { name: /依頼を受付簿へ保存/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  client.clear();
});

it('disables mutations when the service disconnects with cached data', async () => {
  const { client, fetcher } = setup();
  await screen.findByText(/登録 18台/);
  fetcher.mockRejectedValue(new Error('disconnected'));
  await client.invalidateQueries({ queryKey: ['lab-console'] });
  await waitFor(() => expect((screen.getByRole('button', { name: /依頼を受付簿へ保存/ }) as HTMLButtonElement).disabled).toBe(true));
  client.clear();
});
