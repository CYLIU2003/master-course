import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BatteryCharging, Plus, Save } from "lucide-react";
import { api, put, rows, type Page, type Row } from "../api";
import { energyFields } from "../entityFields";
import { FieldGrid } from "./Fields";
import { ErrorBox } from "./common";
import type { Configuration, EditorProps } from "./SettingsPanel";

export function canonicalEnergyAsset(asset: Row): Row {
  const result = { ...asset };
  // Saved derived percentages must not override freshly edited kWh values.
  for (const key of Object.keys(result))
    if (
      /^bess_(initial_soc|soc_min|soc_max|terminal_soc_min|terminal_soc_target)_(percent|ratio)$/.test(
        key,
      ) ||
      /^bess.*Soc.*(Ratio|Percent)$/.test(key)
    )
      delete result[key];
  return result;
}
export function freeBessBand(asset: Row): Row {
  const capacity = Number(asset.bess_energy_kwh);
  return canonicalEnergyAsset({
    ...asset,
    bess_soc_min_kwh: capacity * 0.2,
    bess_soc_max_kwh: capacity * 0.8,
    bess_terminal_soc_min_kwh: capacity * 0.2,
    bess_terminal_soc_target_kwh: 0,
    bess_terminal_soc_policy: "minimum_only",
    bess_balance_period: "evaluation_period",
    bess_terminal_soc_deviation_penalty_yen_per_kwh: 0,
  });
}
export default function EnergyPanel({ id, onSaved, onDirty }: EditorProps) {
  const client = useQueryClient();
  const data = useQuery({
    queryKey: ["configuration", id],
    queryFn: () => api<Configuration>(`/desktop/scenarios/${id}/configuration`),
  });
  const depots = useQuery({
    queryKey: ["table", id, "depot-options"],
    queryFn: () =>
      api<Page<Row>>(`/desktop/scenarios/${id}/tables/depots?limit=250`),
  });
  const [base, setBase] = useState<Configuration | null>(null);
  const [assets, setAssets] = useState<Row[]>([]);
  const [index, setIndex] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [controls, setControls] = useState<Row>({});
  const [invalid, setInvalid] = useState(false);
  const [reset, setReset] = useState(0);
  useEffect(() => {
    if (!dirty && data.data) {
      setBase(data.data);
      setAssets(rows(data.data.values.depotEnergyAssets));
      setControls({
        bessBalancePeriod: data.data.values.bessBalancePeriod,
        rollingBessTerminalPolicy: data.data.values.rollingBessTerminalPolicy,
      });
    }
  }, [data.data, dirty]);
  useEffect(() => {
    onDirty(dirty || invalid);
  }, [dirty, invalid, onDirty]);
  const fields = energyFields.map((field) =>
    field.key === "depot_id"
      ? {
          ...field,
          options: (depots.data?.items ?? []).map(
            (row) => [String(row.id), String(row.name)] as const,
          ),
        }
      : field,
  );
  const save = useMutation({
    mutationFn: () =>
      put<Configuration>(`/desktop/scenarios/${id}/configuration`, {
        revision: base?.revision,
        changes: {
          depotEnergyAssets: assets.map(canonicalEnergyAsset),
          ...controls,
        },
      }),
    onSuccess: (result) => {
      client.setQueryData(["configuration", id], result);
      setBase(result);
      setAssets(rows(result.values.depotEnergyAssets));
      setDirty(false);
      setInvalid(false);
      onSaved();
    },
  });
  function edit(row: Row) {
    setAssets((previous) =>
      previous.map((value, i) => (i === index ? row : value)),
    );
    setDirty(true);
  }
  const asset = assets[index];
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="section-title">
        <div>
          <h2>PVと定置型蓄電池</h2>
          <p className="subtle">
            営業所ごとの容量・残量・電力の流れを設定します。
          </p>
        </div>
        <button
          type="button"
          disabled={!base}
          onClick={() => {
            setAssets([
              ...assets,
              {
                depot_id: "",
                bess_enabled: false,
                bess_terminal_soc_policy: "minimum_only",
                bess_balance_period: "evaluation_period",
                bess_charge_efficiency: 0.95,
                bess_discharge_efficiency: 0.95,
                allow_pv_to_bess: true,
                allow_bess_to_bus: true,
              },
            ]);
            setIndex(assets.length);
            setDirty(true);
          }}
        >
          <Plus size={16} />
          設備を追加
        </button>
      </div>
      <ErrorBox error={data.error ?? save.error} />
      <div className="asset-cards">
        {assets.map((row, i) => (
          <button
            type="button"
            key={i}
            disabled={invalid}
            className={index === i ? "active" : ""}
            onClick={() => setIndex(i)}
          >
            <BatteryCharging size={22} />
            <span>
              {String(
                depots.data?.items.find((depot) => depot.id === row.depot_id)
                  ?.name ??
                  row.depot_id ??
                  "営業所未選択",
              )}
              <small>
                {Number(row.bess_energy_kwh ?? 0).toLocaleString()} kWh ·{" "}
                {row.bess_enabled ? "使用する" : "使用しない"}
              </small>
            </span>
          </button>
        ))}
      </div>
      {asset ? (
        <section className="panel">
          <fieldset disabled={save.isPending}>
            <div className="energy-band">
              <div>
                <h3>BESSの残量を20〜80%にする</h3>
                <p>
                  日末・週末もこの範囲内で自由にします。初期残量へ戻す制約と目標逸脱費用は外します。ローリング時のBESS終端方針はシナリオ全体に適用します。
                </p>
              </div>
              <button
                type="button"
                disabled={!(Number(asset.bess_energy_kwh) > 0)}
                onClick={() => {
                  edit(freeBessBand(asset));
                  setControls({
                    bessBalancePeriod: "evaluation_period",
                    rollingBessTerminalPolicy: "minimum_only",
                  });
                }}
              >
                20〜80%を適用
              </button>
            </div>
            <FieldGrid
              key={`${index}-${reset}`}
              fields={fields}
              value={asset}
              onJsonValidity={(_key, valid) => setInvalid(!valid)}
              onChange={(key, value) => {
                edit(canonicalEnergyAsset({ ...asset, [key]: value }));
                if (key === "bess_terminal_soc_policy")
                  setControls({
                    ...controls,
                    rollingBessTerminalPolicy: "scenario",
                  });
                if (key === "bess_balance_period")
                  setControls({ ...controls, bessBalancePeriod: value });
              }}
            />
            <FieldGrid
              fields={[
                {
                  key: "rollingBessTerminalPolicy",
                  label: "ローリング時のBESS終端方針（全営業所）",
                  kind: "select",
                  options: [
                    ["scenario", "各設備の期間末設定に従う"],
                    ["minimum_only", "BESS下限以上なら自由"],
                  ],
                },
              ]}
              value={controls}
              onChange={(key, value) => {
                setControls({ ...controls, [key]: value });
                setDirty(true);
              }}
            />
            <p className="subtle">
              初期の蓄電量を使って期間を終えられます。結果では残量の増減と期間中の購入費を分けて確認してください。
            </p>
          </fieldset>
        </section>
      ) : (
        <section className="panel empty">
          設備はまだありません。「設備を追加」から営業所を選びます。
        </section>
      )}
      <div className="save-bar">
        <span>
          {dirty ? "設備の変更が未保存です" : "設備設定は保存されています"}
        </span>
        <button
          type="button"
          disabled={(!dirty && !invalid) || save.isPending}
          onClick={() => {
            setDirty(false);
            setInvalid(false);
            setAssets(rows(data.data?.values.depotEnergyAssets));
            setControls({
              bessBalancePeriod: data.data?.values.bessBalancePeriod,
              rollingBessTerminalPolicy:
                data.data?.values.rollingBessTerminalPolicy,
            });
            setIndex(0);
            setReset((value) => value + 1);
          }}
        >
          元に戻す
        </button>
        <button
          className="primary"
          disabled={
            !dirty ||
            invalid ||
            save.isPending ||
            assets.some((row) => !row.depot_id) ||
            new Set(assets.map((row) => row.depot_id)).size !== assets.length
          }
        >
          <Save size={16} />
          設備を保存
        </button>
      </div>
    </form>
  );
}
