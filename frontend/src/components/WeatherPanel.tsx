import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, post, put, type Page, type Row } from "../api";
import { ErrorBox } from "./common";
import { FieldGrid } from "./Fields";
import type { Configuration } from "./SettingsPanel";

export default function WeatherPanel({
  id,
  onSaved,
  blocked,
}: {
  id: string;
  onSaved: () => void;
  blocked: boolean;
}) {
  const [value, setValue] = useState<Row>({
    action: "historical",
    service_date: "",
    issue_date: "",
    depot_id: "",
    station_id: "",
    station_name: "",
    source_path: "",
    weather_class: "auto",
    random_seed: 42,
  });
  const [pv, setPv] = useState<Row>({
    depot_id: "",
    target_date: "",
    slot_minutes: 15,
  });
  const depots = useQuery({
    queryKey: ["table", id, "depot-options"],
    queryFn: () =>
      api<Page<Row>>(`/desktop/scenarios/${id}/tables/depots?limit=250`),
  });
  const options = (depots.data?.items ?? []).map(
    (row) => [String(row.id), String(row.name)] as const,
  );
  const generation = useMutation({
    mutationFn: () => post<Row>("/desktop/weather/action", value),
  });
  const source = useMutation({
    mutationFn: async (file: File) => {
      if (file.size > 20_000_000)
        throw new Error(
          "入力上限は20 MBです。UTF-8の日別CSV/JSONを選択してください。",
        );
      return post<Row>("/desktop/weather/source", {
        filename: file.name,
        content: await file.text(),
      });
    },
    onSuccess: (result) => {
      setValue((previous) => ({ ...previous, source_path: result.path }));
      generation.reset();
    },
  });
  const save = useMutation({
    mutationFn: async () => {
      const config = await api<Configuration>(
        `/desktop/scenarios/${id}/configuration`,
      );
      const isCurve = generation.data?.kind === "representative_curve";
      return put(`/desktop/scenarios/${id}/configuration`, {
        revision: config.revision,
        changes: isCurve
          ? { solcastTypicalCurvePath: generation.data?.path }
          : {
              weatherProxyForecastPath: generation.data?.path,
              enableWeatherOperationPolicy: true,
            },
      });
    },
    onSuccess: onSaved,
  });
  const dates = useMutation({
    mutationFn: () =>
      api<Row>(
        `/pv/available-dates?depot_id=${encodeURIComponent(String(pv.depot_id))}`,
      ),
  });
  const profile = useMutation({
    mutationFn: () => post<Row>(`/scenarios/${id}/pv-profile/generate`, pv),
    onSuccess: onSaved,
  });
  return (
    <>
      <section className="panel">
        <h2>予報・代表PVカーブを作る</h2>
        <p className="subtle">
          取得済みのローカルデータを使います。実績から作る代理予報は、予報技能の検証とは区別してください。
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            generation.mutate();
          }}
        >
          <fieldset
            disabled={generation.isPending || source.isPending || blocked}
          >
            <label>
              CSV/JSONファイルを選択（UTF-8・20 MBまで）
              <input
                type="file"
                accept=".csv,.json"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) source.mutate(file);
                }}
              />
            </label>
            <FieldGrid
              fields={[
                {
                  key: "action",
                  label: "処理",
                  kind: "select",
                  required: true,
                  options: [
                    ["historical", "気象CSVから過去類似日予報"],
                    ["pv_proxy", "実測PVから代理予報"],
                    ["representative", "日別PVから代表カーブ"],
                    ["typical_proxy", "代表カーブから代理予報"],
                    ["inspect", "予報JSONを確認"],
                  ],
                },
                {
                  key: "source_path",
                  label: "入力ファイル（data または output 内のCSV/JSON）",
                },
                { key: "service_date", label: "対象日", kind: "date" },
                { key: "issue_date", label: "予報発行日", kind: "date" },
                { key: "depot_id", label: "営業所", kind: "select", options },
                { key: "station_id", label: "観測地点ID" },
                { key: "station_name", label: "観測地点名" },
                {
                  key: "weather_class",
                  label: "代表気象",
                  kind: "select",
                  options: ["auto", "sunny", "cloudy", "rainy"],
                },
                { key: "random_seed", label: "乱数seed", kind: "number" },
              ]}
              value={value}
              onChange={(key, next) => setValue({ ...value, [key]: next })}
            />
            <button className="primary">
              {generation.isPending ? "処理中…" : "生成・確認"}
            </button>
          </fieldset>
        </form>
        <ErrorBox error={source.error ?? generation.error ?? save.error} />
        {generation.data && (
          <div className="notice">
            <p>{String(generation.data.path)}</p>
            <details>
              <summary>内容と出典を確認</summary>
              <pre>{JSON.stringify(generation.data, null, 2)}</pre>
            </details>
            <button
              disabled={blocked || save.isPending}
              onClick={() => save.mutate()}
            >
              このシナリオで使用する
            </button>
            {save.isSuccess && <p>設定に保存しました。</p>}
          </div>
        )}
      </section>
      <section className="panel">
        <h2>日付別PVプロファイル</h2>
        <p className="subtle">
          対象日の実測データと設備容量からプロファイルを生成し、営業所設備へ反映します。
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            profile.mutate();
          }}
        >
          <fieldset disabled={profile.isPending || blocked}>
            <FieldGrid
              fields={[
                {
                  key: "depot_id",
                  label: "営業所",
                  kind: "select",
                  options,
                  required: true,
                },
                {
                  key: "target_date",
                  label: "対象日",
                  kind: "date",
                  required: true,
                },
                {
                  key: "pv_capacity_kw",
                  label: "PV容量（kW）",
                  kind: "number",
                  min: 0,
                },
                {
                  key: "depot_area_m2",
                  label: "営業所面積（m²）",
                  kind: "number",
                  min: 0,
                },
                {
                  key: "slot_minutes",
                  label: "時間刻み（分）",
                  kind: "select",
                  options: ["5", "15", "30", "60"],
                  numericOptions: true,
                },
              ]}
              value={pv}
              onChange={(key, next) => setPv({ ...pv, [key]: next })}
            />
            <div className="actions">
              <button
                type="button"
                disabled={!pv.depot_id || dates.isPending}
                onClick={() => dates.mutate()}
              >
                利用できる日付
              </button>
              <button className="primary">生成して設備に反映</button>
            </div>
          </fieldset>
        </form>
        <ErrorBox error={profile.error ?? dates.error} />
        {(profile.data || dates.data) && (
          <details open>
            <summary>処理結果</summary>
            <pre>{JSON.stringify(profile.data ?? dates.data, null, 2)}</pre>
          </details>
        )}
      </section>
    </>
  );
}
