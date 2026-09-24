import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, RefreshCw, Settings2, Trash2 } from "lucide-react";
import {
  api,
  post,
  put,
  remove,
  type Overview,
  type Row,
  type Scenario,
} from "../api";
import { ErrorBox } from "./common";
import Results from "./Results";
import RunPanel from "./RunPanel";
import SettingsPanel from "./SettingsPanel";
import EntityManager from "./EntityManager";
import EnergyPanel from "./EnergyPanel";
import WeatherPanel from "./WeatherPanel";
import DataWorkspace from "./DataWorkspace";
import ResultDetails from "./ResultDetails";
import ComparePanel from "./ComparePanel";
import ClusterPanel from "./ClusterPanel";

export default function Workspace({
  id,
  page,
  onSelect,
  onDirty,
}: {
  id: string;
  page: string;
  onSelect: (id: string) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const client = useQueryClient();
  const [visited, setVisited] = useState(new Set([page]));
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState<Row | null>(null);
  const [deleting, setDeleting] = useState(false);
  const overview = useQuery({
    queryKey: ["overview", id],
    queryFn: ({ signal }) =>
      api<Overview>(`/desktop/scenarios/${id}`, { signal }),
  });
  const locked = Object.values(dirty).some(Boolean) || editing !== null;
  useEffect(() => {
    setVisited((previous) => new Set([...previous, page]));
  }, [page]);
  useEffect(() => {
    onDirty(locked);
  }, [locked, onDirty]);
  const settingsDirty = useCallback(
    (value: boolean) =>
      setDirty((previous) => ({ ...previous, settings: value })),
    [],
  );
  const fleetDirty = useCallback(
    (value: boolean) => setDirty((previous) => ({ ...previous, fleet: value })),
    [],
  );
  const depotsDirty = useCallback(
    (value: boolean) =>
      setDirty((previous) => ({ ...previous, depots: value })),
    [],
  );
  const routesDirty = useCallback(
    (value: boolean) =>
      setDirty((previous) => ({ ...previous, routes: value })),
    [],
  );
  const dataDirty = useCallback(
    (value: boolean) => setDirty((previous) => ({ ...previous, data: value })),
    [],
  );
  const energyDirty = useCallback(
    (value: boolean) =>
      setDirty((previous) => ({ ...previous, energy: value })),
    [],
  );
  const saved = useCallback(() => {
    setRevision((value) => value + 1);
    void client.invalidateQueries({
      predicate: (query) => query.queryKey[1] === id,
    });
    void client.invalidateQueries({ queryKey: ["scenarios"] });
  }, [client, id]);
  const duplicate = useMutation({
    mutationFn: () => post<Scenario>(`/scenarios/${id}/duplicate`, {}),
    onSuccess: (row) => {
      saved();
      onSelect(row.id);
    },
  });
  const meta = useMutation({
    mutationFn: (action: string) =>
      action === "delete"
        ? remove(`/scenarios/${id}`)
        : action === "activate"
          ? post(`/scenarios/${id}/activate`, {})
          : put(`/scenarios/${id}`, editing),
    onSuccess: (_, action) => {
      setEditing(null);
      setDeleting(false);
      saved();
      if (action === "delete") onSelect("");
    },
  });
  const data = overview.data;
  return (
    <div className="workspace">
      <div className="page-title">
        <div>
          <span className="eyebrow">SCENARIO WORKSPACE</span>
          <h1>{data?.meta.name ?? "読み込み中…"}</h1>
          <p className="subtle">
            {data?.meta.description ||
              "運行計画からエネルギー運用、結果の確認まで。"}
          </p>
        </div>
        <div className="actions">
          <button
            disabled={duplicate.isPending || locked}
            onClick={() => duplicate.mutate()}
          >
            <Copy size={16} />
            複製
          </button>
          <button
            aria-label="シナリオの設定"
            disabled={locked}
            onClick={() =>
              setEditing({
                name: data?.meta.name ?? "",
                description: data?.meta.description ?? "",
              })
            }
          >
            <Settings2 size={16} />
          </button>
          <button aria-label="最新情報を取得" disabled={locked} onClick={saved}>
            <RefreshCw size={16} />
          </button>
        </div>
      </div>
      <ErrorBox error={overview.error ?? duplicate.error ?? meta.error} />
      {locked && (
        <div className="draft-notice">
          未保存の変更があります。編集した画面で保存または「元に戻す」を選んでください。
        </div>
      )}
      {editing && (
        <form
          className="panel"
          onSubmit={(e) => {
            e.preventDefault();
            meta.mutate("save");
          }}
        >
          <h2>シナリオの設定</h2>
          <div className="form-grid">
            <label>
              名前
              <input
                required
                value={String(editing.name)}
                onChange={(e) =>
                  setEditing({ ...editing, name: e.target.value })
                }
              />
            </label>
            <label>
              説明
              <input
                value={String(editing.description)}
                onChange={(e) =>
                  setEditing({ ...editing, description: e.target.value })
                }
              />
            </label>
          </div>
          <div className="actions">
            <button className="primary" disabled={meta.isPending}>
              保存
            </button>
            <button type="button" onClick={() => meta.mutate("activate")}>
              起動時のシナリオにする
            </button>
            <button type="button" onClick={() => setEditing(null)}>
              閉じる
            </button>
            <button
              type="button"
              className="danger"
              onClick={() => setDeleting(true)}
            >
              <Trash2 size={16} />
              削除
            </button>
          </div>
          {deleting && (
            <div className="warning">
              このシナリオを削除します。
              <button
                type="button"
                className="danger"
                disabled={meta.isPending}
                onClick={() => meta.mutate("delete")}
              >
                削除を確定
              </button>
            </div>
          )}
        </form>
      )}
      {data && (
        <>
          {page === "overview" && <Results data={data} />}
          {visited.has("settings") && (
            <div hidden={page !== "settings"}>
              <SettingsPanel id={id} onSaved={saved} onDirty={settingsDirty} />
            </div>
          )}
          {visited.has("fleet") && (
            <div hidden={page !== "fleet"}>
              <EntityManager id={id} onSaved={saved} onDirty={fleetDirty} />
            </div>
          )}
          {visited.has("depots") && (
            <div hidden={page !== "depots"}>
              <EntityManager
                kind="depots"
                id={id}
                onSaved={saved}
                onDirty={depotsDirty}
              />
            </div>
          )}
          {visited.has("routes") && (
            <div hidden={page !== "routes"}>
              <EntityManager
                kind="routes"
                id={id}
                onSaved={saved}
                onDirty={routesDirty}
              />
            </div>
          )}
          {visited.has("energy") && (
            <div hidden={page !== "energy"}>
              <EnergyPanel id={id} onSaved={saved} onDirty={energyDirty} />
            </div>
          )}
          {visited.has("weather") && (
            <div hidden={page !== "weather"}>
              <WeatherPanel id={id} onSaved={saved} blocked={locked} />
            </div>
          )}
          {visited.has("data") && (
            <div hidden={page !== "data"}>
              <DataWorkspace
                id={id}
                onSaved={saved}
                onDirty={dataDirty}
                blocked={
                  Object.entries(dirty).some(
                    ([key, value]) => key !== "data" && value,
                  ) || editing !== null
                }
              />
            </div>
          )}
          {visited.has("run") && (
            <div hidden={page !== "run"}>
              <RunPanel
                id={id}
                data={data}
                revision={revision}
                blocked={locked}
              />
            </div>
          )}
          {page === "results" && <ResultDetails id={id} data={data} />}
          {page === "compare" && <ComparePanel data={data} />}
          {page === "cluster" && <ClusterPanel scenarioId={id} />}
        </>
      )}
    </div>
  );
}
