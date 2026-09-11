import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RotateCcw, Search } from "lucide-react";
import { api, put, strings, type Json, type Row } from "../api";
import { settingGroups } from "../settings";
import { FieldGrid } from "./Fields";
import { ErrorBox } from "./common";
import DataTable from "./DataTable";

export type Configuration = { values: Row; revision: string };
export type EditorProps = {
  id: string;
  onSaved: () => void;
  onDirty: (dirty: boolean) => void;
};
export default function SettingsPanel({ id, onSaved, onDirty }: EditorProps) {
  const client = useQueryClient();
  const data = useQuery({
    queryKey: ["configuration", id],
    queryFn: ({ signal }) =>
      api<Configuration>(`/desktop/scenarios/${id}/configuration`, { signal }),
  });
  const [base, setBase] = useState<Configuration | null>(null);
  const [changes, setChanges] = useState<Row>({});
  const [section, setSection] = useState("scope");
  const [search, setSearch] = useState("");
  const [invalid, setInvalid] = useState<Record<string, boolean>>({});
  const invalidJson = Object.values(invalid).some(Boolean);
  const dirty = Object.keys(changes).length > 0 || invalidJson;
  useEffect(() => {
    if (!dirty && data.data) setBase(data.data);
  }, [data.data, dirty]);
  useEffect(() => {
    onDirty(dirty);
  }, [dirty, onDirty]);
  const value = { ...base?.values, ...changes };
  function change(key: string, next: Json) {
    setChanges((previous) => {
      const result = { ...previous, [key]: next };
      if (JSON.stringify(base?.values[key]) === JSON.stringify(next))
        delete result[key];
      return result;
    });
  }
  const save = useMutation({
    mutationFn: () =>
      put<Configuration>(`/desktop/scenarios/${id}/configuration`, {
        changes,
        revision: base?.revision,
      }),
    onSuccess: (result) => {
      setBase(result);
      setChanges({});
      client.setQueryData(["configuration", id], result);
      onSaved();
    },
  });
  const groups = search.trim()
    ? settingGroups
        .map((group) => ({
          ...group,
          fields: group.fields.filter((field) =>
            (field.label + field.key)
              .toLowerCase()
              .includes(search.toLowerCase()),
          ),
        }))
        .filter((group) => group.fields.length)
    : settingGroups.filter((group) => group.id === section);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="section-title">
        <div>
          <h2>運行と計算の設定</h2>
          <p className="subtle">
            条件を整えて保存し、「実行」で入力を準備します。
          </p>
        </div>
        <label className="search">
          <Search size={16} />
          <input
            disabled={invalidJson}
            aria-label="設定を検索"
            placeholder="SOC、料金、PV…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>
      <div className="segmented">
        {[{ id: "scope", label: "対象範囲" }, ...settingGroups].map((group) => (
          <button
            disabled={invalidJson}
            type="button"
            key={group.id}
            className={section === group.id && !search ? "active" : ""}
            onClick={() => {
              setSection(group.id);
              setSearch("");
            }}
          >
            {group.label}
          </button>
        ))}
      </div>
      <ErrorBox error={data.error ?? save.error} />
      {base && (
        <fieldset disabled={save.isPending}>
          {section === "scope" && !search && (
            <section className="panel">
              <h2>対象の営業所と路線</h2>
              <p>
                {strings(value.selectedDepotIds).length} 営業所 /{" "}
                {strings(value.selectedRouteIds).length} 路線パターンを選択中
              </p>
              <DataTable
                id={id}
                fixed="depots"
                selected={strings(value.selectedDepotIds)}
                onSelection={(ids) => change("selectedDepotIds", ids)}
              />
              <DataTable
                id={id}
                fixed="routes"
                selected={strings(value.selectedRouteIds)}
                onSelection={(ids) => change("selectedRouteIds", ids)}
              />
            </section>
          )}
          {groups.map((group) => (
            <section className="panel" key={group.id}>
              <h2>{group.label}</h2>
              <p className="subtle">{group.description}</p>
              <FieldGrid
                fields={group.fields}
                value={value}
                onChange={change}
                onJsonValidity={(key, valid) =>
                  setInvalid((previous) => ({ ...previous, [key]: !valid }))
                }
              />
            </section>
          ))}
        </fieldset>
      )}
      <div className="save-bar" role="status">
        <span>
          {dirty
            ? `${Object.keys(changes).length} 項目の変更が未保存です`
            : save.isSuccess
              ? "保存しました。実行前に入力を再準備してください。"
              : "設定は保存されています"}
        </span>
        <button
          type="button"
          disabled={!dirty || save.isPending}
          onClick={() => {
            setChanges({});
            setInvalid({});
            setBase(data.data ?? null);
            setSection("scope");
            setSearch("");
          }}
        >
          <RotateCcw size={16} />
          元に戻す
        </button>
        <button
          className="primary"
          disabled={!dirty || invalidJson || save.isPending}
        >
          <Check size={16} />
          {save.isPending ? "保存中…" : "変更を保存"}
        </button>
      </div>
    </form>
  );
}
