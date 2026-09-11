import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, post, put, type Job, type Json, type Row } from "../api";
import { ErrorBox } from "./common";
import { JsonField } from "./Fields";
import DataTable from "./DataTable";

const documents: Record<string, { label: string; key?: string }> = {
  calendar: { label: "運行カレンダー", key: "entries" },
  "calendar-dates": { label: "日付ごとの運行例外", key: "entries" },
  "depot-route-permissions": {
    label: "営業所と路線の対応",
    key: "permissions",
  },
  "depot-route-family-permissions": {
    label: "営業所と系統の対応",
    key: "permissions",
  },
  "vehicle-route-permissions": {
    label: "車両と路線の対応",
    key: "permissions",
  },
  "vehicle-route-family-permissions": {
    label: "車両と系統の対応",
    key: "permissions",
  },
  "deadhead-rules": { label: "回送ルール" },
  "turnaround-rules": { label: "折返しルール" },
  "duties/validate": { label: "仕業の検証" },
};
function ReferenceEditor({
  id,
  name,
  blocked,
  onSaved,
  onDirty,
}: {
  id: string;
  name: string;
  blocked: boolean;
  onSaved: () => void;
  onDirty: (value: boolean) => void;
}) {
  const [draft, setDraft] = useState<Json | undefined>();
  const [invalid, setInvalid] = useState(false);
  const [reset, setReset] = useState(0);
  useEffect(() => {
    onDirty(draft !== undefined || invalid);
  }, [draft, invalid, onDirty]);
  const definition = documents[name];
  const query = useQuery({
    queryKey: ["reference", id, name],
    queryFn: () => api<Row>(`/scenarios/${id}/${name}`),
  });
  const save = useMutation({
    mutationFn: () =>
      put(`/scenarios/${id}/${name}`, { [definition.key!]: draft }),
    onSuccess: () => {
      setDraft(undefined);
      void query.refetch();
      onSaved();
    },
  });
  return (
    <section className="panel">
      <h2>{definition.label}</h2>
      <ErrorBox error={query.error ?? save.error} />
      {query.data &&
        (definition.key ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <p className="subtle">
              この一覧全体を保存します。対象IDと運行日を確認してください。
            </p>
            <JsonField
              key={reset}
              value={draft ?? query.data.items}
              onChange={setDraft}
              onValidity={(valid) => setInvalid(!valid)}
              disabled={blocked || save.isPending}
            />
            <div className="actions">
              <button
                className="primary"
                disabled={
                  draft === undefined || invalid || blocked || save.isPending
                }
              >
                一覧を保存
              </button>
              <button
                type="button"
                onClick={() => {
                  setDraft(undefined);
                  setInvalid(false);
                  setReset((value) => value + 1);
                }}
              >
                元に戻す
              </button>
            </div>
          </form>
        ) : (
          <pre>{JSON.stringify(query.data, null, 2)}</pre>
        ))}
    </section>
  );
}
export default function DataWorkspace({
  id,
  blocked,
  onSaved,
  onDirty,
}: {
  id: string;
  blocked: boolean;
  onSaved: () => void;
  onDirty: (value: boolean) => void;
}) {
  const [referenceDirty, setReferenceDirty] = useState(false);
  useEffect(() => {
    onDirty(referenceDirty);
  }, [referenceDirty, onDirty]);
  const [section, setSection] = useState("table");
  const [jobId, setJobId] = useState("");
  const [csv, setCsv] = useState("");
  const [csvName, setCsvName] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const prepare = useMutation({
    mutationFn: (action: string) =>
      post<{ job_id: string }>(`/scenarios/${id}/${action}`, {}),
    onSuccess: (row) => {
      setJobId(row.job_id);
      onSaved();
    },
  });
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: !!jobId,
    queryFn: () => api<Job>(`/jobs/${jobId}`),
    refetchInterval: (q) =>
      q.state.data && ["completed", "failed"].includes(q.state.data.status)
        ? false
        : 2000,
  });
  const importData = useMutation({
    mutationFn: (apply: boolean): Promise<Row> =>
      post<Row>(`/desktop/scenarios/${id}/timetable-import`, {
        content: csv,
        apply,
        revision: apply ? importData.data?.revision : "",
      }),
    onSuccess: (_, apply) => {
      if (apply) {
        setCsv("");
        onSaved();
      }
    },
  });
  const exporting = useMutation({
    mutationFn: () =>
      post<Row>(`/desktop/scenarios/${id}/timetable-export`, {}),
  });
  const busy =
    blocked ||
    prepare.isPending ||
    ["pending", "running"].includes(job.data?.status ?? "");
  return (
    <>
      <div className="section-title">
        <h2>データを確認・整備する</h2>
        <select
          aria-label="データ編集メニュー"
          disabled={referenceDirty}
          value={section}
          onChange={(e) => setSection(e.target.value)}
        >
          <option value="table">入力・派生データ一覧</option>
          <option value="io">時刻表の取込み・書出し</option>
          <option value="build">派生データを作成</option>
          {Object.entries(documents).map(([key, value]) => (
            <option key={key} value={key}>
              {value.label}
            </option>
          ))}
        </select>
      </div>
      {section === "table" && <DataTable id={id} />}
      {documents[section] && (
        <ReferenceEditor
          key={section}
          id={id}
          name={section}
          blocked={blocked}
          onSaved={onSaved}
          onDirty={setReferenceDirty}
        />
      )}
      {section === "build" && (
        <section className="panel">
          <h2>時刻表から運行計画を組み立てる</h2>
          <p className="subtle">
            保存された対象範囲と接続条件を使い、派生データを更新します。
          </p>
          <div className="action-cards">
            {[
              ["build-trips", "1. トリップ"],
              ["build-graph", "2. 接続グラフ"],
              ["build-blocks", "3. ブロック"],
              ["generate-duties", "4. 仕業"],
              ["build-dispatch-plan", "5. 配車計画"],
            ].map(([action, label]) => (
              <button
                disabled={busy}
                key={action}
                onClick={() => prepare.mutate(action)}
              >
                {label}
              </button>
            ))}
          </div>
          <ErrorBox error={prepare.error ?? job.error} />
          {job.data && (
            <div className="job">
              <strong>{job.data.status}</strong>
              <progress max={100} value={job.data.progress} />
              <p>{job.data.message}</p>
              {job.data.error && <p className="error">{job.data.error}</p>}
            </div>
          )}
        </section>
      )}
      {section === "io" && (
        <section className="panel">
          <h2>時刻表をCSVから取り込む</h2>
          <p className="subtle">
            便ID・事業者ID・路線・運行日・時刻・正の距離が必要です。検査後に全時刻表を置き換えます。読み込んだ行を間引いたり補ったりしません。
          </p>
          <input
            aria-label="時刻表CSV"
            type="file"
            accept=".csv,text/csv"
            disabled={blocked || importData.isPending}
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              try {
                if (file.size > 20_000_000)
                  throw new Error("画面からの取込み上限は20 MBです。");
                const content = await file.text();
                setCsv(content);
                setCsvName(file.name);
                importData.reset();
                setError(null);
              } catch (reason) {
                setError(
                  reason instanceof Error ? reason : new Error(String(reason)),
                );
              }
            }}
          />
          <p>{csvName}</p>
          <div className="actions">
            <button
              disabled={!csv || blocked || importData.isPending}
              onClick={() => importData.mutate(false)}
            >
              内容を検査
            </button>
            {csv && importData.data?.valid === true && (
              <button
                className="primary"
                disabled={blocked || importData.isPending}
                onClick={() => importData.mutate(true)}
              >
                検査済みの時刻表に置き換える
              </button>
            )}
          </div>
          <ErrorBox error={error ?? importData.error} />
          {importData.data && (
            <pre>{JSON.stringify(importData.data, null, 2)}</pre>
          )}
          <h2>保存された時刻表を書き出す</h2>
          <p className="subtle">
            全列を保ったCSVをローカルの出力フォルダーに保存します。
          </p>
          <button
            disabled={exporting.isPending}
            onClick={() => exporting.mutate()}
          >
            {exporting.isPending ? "書出し中…" : "時刻表をCSVに書き出す"}
          </button>
          <ErrorBox error={exporting.error} />
          {exporting.data && (
            <pre>{JSON.stringify(exporting.data, null, 2)}</pre>
          )}
        </section>
      )}
    </>
  );
}
