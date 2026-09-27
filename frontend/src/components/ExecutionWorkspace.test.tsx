import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Overview } from "../api";
import ExecutionWorkspace from "./ExecutionWorkspace";

vi.mock("./RunPanel", () => ({ default: ({ id, blocked }: { id: string; blocked: boolean }) => <button disabled={blocked}>既存の開始 {id}</button> }));
vi.mock("./ExecutionProgress", () => ({ default: ({ scenarioId }: { scenarioId?: string }) => <p>進捗対象 {scenarioId ?? "全件"}</p> }));
vi.mock("./ClusterPanel", () => ({ default: () => <p>既存ジョブ一覧</p> }));
vi.mock("./LabConsole", () => ({ default: ({ onSelectScenario, readOnly, resultsOnly }: { onSelectScenario: (id: string) => void; readOnly: boolean; resultsOnly: boolean }) => resultsOnly ? <p>検算済み比較</p> :
  <button disabled={readOnly} onClick={() => onSelectScenario("requested")}>依頼の設定を確認</button> }));
afterEach(cleanup);

it("opens intake without a scenario, and only selects the requested scenario", () => {
  const choose = vi.fn(), select = vi.fn();
  render(<ExecutionWorkspace onChoose={choose} onNavigate={vi.fn()} onSelect={select} />);
  expect(screen.getByText("進捗対象 全件")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "実行対象のシナリオを選ぶ" }));
  expect(choose).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "研究室の依頼から選ぶ" }));
  fireEvent.click(screen.getByText("依頼の設定を確認"));
  expect(select).toHaveBeenCalledWith("requested");
  expect(screen.queryByText(/既存の開始/)).toBeNull();
});

it("keeps unsaved settings blocked and allows navigation back to save", () => {
  const navigate = vi.fn();
  render(<ExecutionWorkspace id="s1" data={{ meta: { name: "比較A" } } as Overview} blocked
    onChoose={vi.fn()} onNavigate={navigate} onSelect={vi.fn()} />);
  expect((screen.getByText("既存の開始 s1") as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByText("実行対象のシナリオを選ぶ") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByText("設定を確認・保存"));
  expect(navigate).toHaveBeenCalledWith("settings");
  expect(screen.getByText("進捗対象 s1")).toBeTruthy();
  expect(screen.getByText(/12代表週を一括開始するボタンではありません/)).toBeTruthy();
  fireEvent.click(screen.getByText("ジョブ一覧と機器・エラー詳細を開く"));
  expect(screen.getByText("既存ジョブ一覧")).toBeTruthy();
});
