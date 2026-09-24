import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RotateCcw, Search } from "lucide-react";
import { api, put, strings, type Json, type Row } from "../api";
import { settingGroups } from "../settings";
import { FieldGrid } from "./Fields";
import { ErrorBox } from "./common";
import DataTable from "./DataTable";

const periodPresets = [
  { days: 1, label: "1日" },
  { days: 7, label: "1週" },
  { days: 14, label: "2週" },
  { days: 21, label: "3週" },
  { days: 28, label: "4週" },
] as const;

export function periodEnd(start: unknown, days: unknown): string | null {
  if (typeof start !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(start)) return null;
  const count = Number(days);
  if (!Number.isInteger(count) || count < 1 || count > 366) return null;
  const day = new Date(`${start}T00:00:00Z`);
  if (Number.isNaN(day.getTime()) || day.toISOString().slice(0, 10) !== start) return null;
  day.setUTCDate(day.getUTCDate() + count - 1);
  return day.toISOString().slice(0, 10);
}

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
              {group.id === "operation" && (
                <div className="period-editor">
                  <strong>一つのシナリオで計算期間を指定</strong>
                  <div className="segmented" role="group" aria-label="計算期間のプリセット">
                    {periodPresets.map(({ days, label }) => (
                      <button key={days} type="button"
                        className={Number(value.planningDays) === days ? "active" : ""}
                        onClick={() => change("planningDays", days)}>{label}</button>
                    ))}
                  </div>
                  <p className="subtle">
                    {periodEnd(value.serviceDate, value.planningDays)
                      ? `${String(value.serviceDate)} 〜 ${periodEnd(value.serviceDate, value.planningDays)}（${Number(value.planningDays)}日間）`
                      : "開始日と1〜366日の対象日数を指定してください。"}
                    保存後に入力準備すると、その期間のPrepared入力が別IDで記録されます。
                  </p>
                </div>
              )}
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
