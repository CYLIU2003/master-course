import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, RefreshCw } from "lucide-react";
import { api, post, type Overview, type Scenario } from "../api";
import { ErrorBox } from "./common";
import Results from "./Results";
import RunPanel from "./RunPanel";
import DataTable from "./DataTable";
export default function Workspace({
  id,
  onSelect,
}: {
  id: string;
  onSelect: (id: string) => void;
}) {
  const [tab, setTab] = useState("overview");
  const client = useQueryClient();
  const overview = useQuery({
    queryKey: ["overview", id],
    queryFn: ({ signal }) =>
      api<Overview>(`/desktop/scenarios/${id}`, { signal }),
  });
  const duplicate = useMutation({
    mutationFn: () => post<Scenario>(`/scenarios/${id}/duplicate`, {}),
    onSuccess: (row) => {
      void client.invalidateQueries({ queryKey: ["scenarios"] });
      onSelect(row.id);
    },
  });
  return (
    <div className="workspace">
      <div className="page-title">
        <div>
          <span className="eyebrow">SCENARIO</span>
          <h1>{overview.data?.meta.name ?? "読み込み中…"}</h1>
          <p className="subtle">
            {overview.data?.meta.description ||
              "運行・充電・エネルギー計画の研究シナリオ"}
          </p>
        </div>
        <button
          disabled={duplicate.isPending}
          onClick={() => duplicate.mutate()}
        >
          <Copy size={16} /> 複製
        </button>
      </div>
      <ErrorBox error={overview.error ?? duplicate.error} />
      <nav className="tabs">
        {[
          ["overview", "概要と検証"],
          ["run", "入力と実行"],
          ["data", "データを確認"],
        ].map(([value, label]) => (
          <button
            key={value}
            className={tab === value ? "active" : ""}
            onClick={() => setTab(value)}
          >
            {label}
          </button>
        ))}
        <button
          aria-label="最新情報を取得"
          onClick={() =>
            void client.invalidateQueries({ queryKey: ["overview", id] })
          }
        >
          <RefreshCw size={15} />
        </button>
      </nav>
      {overview.data && (
        <>
          {tab === "overview" && <Results data={overview.data} />}
          <div hidden={tab !== "run"}>
            <RunPanel id={id} data={overview.data} />
          </div>
          {tab === "data" && <DataTable id={id} />}
        </>
      )}
    </div>
  );
}
