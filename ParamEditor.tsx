/**
 * ParamEditor.tsx
 * バス運行パラメータ編集コンポーネント
 *
 * 設計方針:
 *   - プリセット選択で入力ゼロスタート
 *   - スライダー + 数値欄の双方向連動（useDeferredValue でスライダー高速化）
 *   - フリート構成ビジュアライザ（台数変更に即応、上限クランプあり）
 *   - 充電許可時間帯セレクタ（24コマ トグル）
 *   - サマリーバーで派生値をリアルタイム表示
 *   - onChange でフォームデータを親に渡すだけ（副作用なし）
 *
 * 実装時にエージェントが検討すべき点（コメント [AGENT] で記載）:
 *   - 既存の型定義 / API スキーマとの整合
 *   - CSS Modules / Tailwind への置き換え
 *   - i18n 対応（現在ハードコードの日本語ラベル）
 *   - バリデーション統合（react-hook-form / zod など）
 */

import React, {
  useCallback,
  useDeferredValue,
  useMemo,
  useState,
} from "react";

// ─── 型定義 ────────────────────────────────────────────────────────────────

export type TouPlan = "tou_std" | "tou_night" | "flat";

export interface BusParams {
  // 車両
  n_bev: number;          // BEV 台数
  n_ice: number;          // ICE 台数
  battery_kwh: number;    // BEV バッテリー容量 (kWh/台)
  soc_min_pct: number;    // 最低 SOC (%)

  // 充電設備
  n_chargers: number;     // 充電器台数
  charger_kw: number;     // 充電器出力 (kW/台)
  charge_hours: number[]; // 充電許可時間帯 (0-23)

  // エネルギー・料金
  tou_plan: TouPlan;
  pv_kw: number;          // PV 出力 (kW)
  demand_charge: number;  // デマンド料金 (円/kW)

  // ソルバー
  n_days: number;         // 計算対象日数
  time_limit_min: number; // 最大計算時間 (分)
}

// ─── プリセット定義 ────────────────────────────────────────────────────────

const DEFAULT_NIGHT_HOURS = [22, 23, 0, 1, 2, 3, 4, 5];

// [AGENT] 実際の路線・営業所データに合わせて値を調整すること
const PRESETS: Record<string, BusParams> = {
  meguro: {
    n_bev: 5, n_ice: 10, battery_kwh: 200, soc_min_pct: 20,
    n_chargers: 3, charger_kw: 150, charge_hours: DEFAULT_NIGHT_HOURS,
    tou_plan: "tou_std", pv_kw: 50, demand_charge: 1500,
    n_days: 7, time_limit_min: 10,
  },
  small: {
    n_bev: 2, n_ice: 8, battery_kwh: 150, soc_min_pct: 20,
    n_chargers: 2, charger_kw: 100, charge_hours: [22, 23, 0, 1, 2, 3],
    tou_plan: "tou_std", pv_kw: 0, demand_charge: 1200,
    n_days: 3, time_limit_min: 5,
  },
  full_bev: {
    n_bev: 15, n_ice: 0, battery_kwh: 300, soc_min_pct: 15,
    n_chargers: 6, charger_kw: 200, charge_hours: [22, 23, 0, 1, 2, 3, 4, 5, 6],
    tou_plan: "tou_night", pv_kw: 150, demand_charge: 1500,
    n_days: 14, time_limit_min: 30,
  },
};

const PRESET_LABELS: Record<string, string> = {
  meguro:   "目黒営業所モデル",
  small:    "小規模検証",
  full_bev: "フルBEV化",
};

const TOU_OPTIONS: { value: TouPlan; label: string; badge: string; desc: string }[] = [
  { value: "tou_std",   label: "TOU 標準",    badge: "昼高・夜安", desc: "夜間23〜7時が割安" },
  { value: "tou_night", label: "TOU 夜間割引", badge: "夜間最安",   desc: "22〜6時が特に安価" },
  { value: "flat",      label: "固定単価",     badge: "均一",       desc: "時間帯によらず一定" },
];

// ─── サブコンポーネント ────────────────────────────────────────────────────

/** スライダー + 数値入力の双方向連動フィールド */
interface SliderFieldProps {
  label: string;
  hint?: string;
  id: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  unit: string;
  onChange: (v: number) => void;
}

const SliderField: React.FC<SliderFieldProps> = ({
  label, hint, id, min, max, step = 1, value, unit, onChange,
}) => {
  // useDeferredValue: スライダー操作中は重い親再レンダーを後回しにする
  // [AGENT] 親側で重い計算がなければ不要。取り除いてシンプルにしてもよい。
  const deferred = useDeferredValue(value);

  const clamp = (v: number) => Math.max(min, Math.min(max, v));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label htmlFor={id} style={{ fontSize: 13 }}>{label}</label>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input
          type="range"
          id={id}
          min={min} max={max} step={step}
          value={deferred}
          style={{ flex: 1 }}
          onChange={(e) => onChange(clamp(Number(e.target.value)))}
        />
        <input
          type="number"
          min={min} max={max} step={step}
          value={value}
          style={{ width: 62, textAlign: "right" }}
          onChange={(e) => {
            const v = clamp(parseInt(e.target.value) || min);
            onChange(v);
          }}
        />
        <span style={{ fontSize: 11, color: "var(--color-text-secondary)", minWidth: 28 }}>
          {unit}
        </span>
      </div>
      {hint && (
        <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", lineHeight: 1.4 }}>
          {hint}
        </span>
      )}
    </div>
  );
};

/** フリート構成ビジュアライザ */
const FleetVisualizer: React.FC<{ n_bev: number; n_ice: number }> = ({ n_bev, n_ice }) => {
  // [AGENT] MAX_ICONS を超える台数は "+N台" に省略。大量台数時の DOM 肥大を防ぐ。
  const MAX_ICONS = 40;
  const total = n_bev + n_ice;
  const bevShow = Math.min(n_bev, MAX_ICONS);
  const iceShow = Math.min(n_ice, MAX_ICONS - bevShow);
  const overflow = total - MAX_ICONS;

  const busStyle = (type: "bev" | "ice"): React.CSSProperties => ({
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 28,
    height: 18,
    borderRadius: 3,
    fontSize: 9,
    fontWeight: 500,
    flexShrink: 0,
    background: type === "bev" ? "#9FE1CB" : "#FAC775",
    color: type === "bev" ? "#085041" : "#633806",
  });

  return (
    <div>
      <div
        style={{
          display: "flex",
          gap: 3,
          flexWrap: "wrap",
          minHeight: 32,
          alignItems: "center",
          padding: "8px 10px",
          background: "var(--color-background-secondary)",
          borderRadius: "var(--border-radius-md)",
          marginBottom: 8,
        }}
      >
        {total === 0 && (
          <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
            車両が 0 台です
          </span>
        )}
        {Array.from({ length: bevShow }, (_, i) => (
          <span key={`bev-${i}`} style={busStyle("bev")}>BEV</span>
        ))}
        {Array.from({ length: iceShow }, (_, i) => (
          <span key={`ice-${i}`} style={busStyle("ice")}>ICE</span>
        ))}
        {overflow > 0 && (
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginLeft: 4 }}>
            +{overflow}台
          </span>
        )}
      </div>
      <div style={{ display: "flex", gap: 16, fontSize: 11, color: "var(--color-text-secondary)" }}>
        <span>
          <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: "#9FE1CB", marginRight: 4, verticalAlign: "middle" }} />
          BEV（電気バス）
        </span>
        <span>
          <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: "#FAC775", marginRight: 4, verticalAlign: "middle" }} />
          ICE（ディーゼルバス）
        </span>
      </div>
    </div>
  );
};

/** 充電許可時間帯セレクタ（24コマ） */
const ChargeWindowSelector: React.FC<{
  value: number[];
  onChange: (hours: number[]) => void;
}> = ({ value, onChange }) => {
  const active = useMemo(() => new Set(value), [value]);

  const toggle = useCallback(
    (h: number) => {
      const next = new Set(active);
      next.has(h) ? next.delete(h) : next.add(h);
      onChange(Array.from(next).sort((a, b) => a - b));
    },
    [active, onChange]
  );

  return (
    <div>
      <div
        style={{
          display: "flex",
          height: 28,
          border: "0.5px solid var(--color-border-tertiary)",
          borderRadius: "var(--border-radius-md)",
          overflow: "hidden",
        }}
      >
        {Array.from({ length: 24 }, (_, h) => (
          <div
            key={h}
            onClick={() => toggle(h)}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 8,
              cursor: "pointer",
              userSelect: "none",
              background: active.has(h) ? "#9FE1CB" : undefined,
              color: active.has(h) ? "#085041" : "var(--color-text-tertiary)",
              fontWeight: active.has(h) ? 500 : 400,
              transition: "background 0.1s",
            }}
          >
            {h % 6 === 0 ? h : ""}
          </div>
        ))}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          color: "var(--color-text-tertiary)",
          marginTop: 3,
          padding: "0 2px",
        }}
      >
        {["0時", "6時", "12時", "18時", "24時"].map((l) => (
          <span key={l}>{l}</span>
        ))}
      </div>
    </div>
  );
};

/** サマリーバー（派生値を自動計算して表示） */
const SummaryBar: React.FC<{ params: BusParams }> = ({ params }) => {
  const total = params.n_bev + params.n_ice;
  const bevPct = total > 0 ? Math.round((params.n_bev / total) * 100) : 0;
  const chargeCap = params.n_chargers * params.charger_kw;

  const cards = [
    { label: "総車両台数",   value: total,    unit: "台" },
    { label: "BEV 比率",    value: bevPct,   unit: "%" },
    { label: "総充電容量",   value: chargeCap, unit: "kW" },
    { label: "PV 出力",     value: params.pv_kw, unit: "kW" },
  ];

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
        gap: 8,
        marginBottom: "1.5rem",
      }}
    >
      {cards.map(({ label, value, unit }) => (
        <div
          key={label}
          style={{
            background: "var(--color-background-secondary)",
            borderRadius: "var(--border-radius-md)",
            padding: "10px 12px",
          }}
        >
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 4 }}>
            {label}
          </div>
          <div style={{ fontSize: 18, fontWeight: 500 }}>
            {value}
            <span style={{ fontSize: 10, color: "var(--color-text-secondary)", marginLeft: 2 }}>
              {unit}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
};

// ─── メインコンポーネント ─────────────────────────────────────────────────

interface ParamEditorProps {
  initialParams?: Partial<BusParams>;
  onChange?: (params: BusParams) => void;
  onSubmit?: (params: BusParams) => void;
}

const ParamEditor: React.FC<ParamEditorProps> = ({
  initialParams,
  onChange,
  onSubmit,
}) => {
  const [params, setParams] = useState<BusParams>({
    ...PRESETS.meguro,
    ...initialParams,
  });
  const [activePreset, setActivePreset] = useState<string | null>("meguro");

  const update = useCallback(
    (patch: Partial<BusParams>) => {
      setParams((prev) => {
        const next = { ...prev, ...patch };
        onChange?.(next);
        return next;
      });
      setActivePreset(null); // カスタム状態に
    },
    [onChange]
  );

  const applyPreset = useCallback(
    (key: string) => {
      const p = PRESETS[key];
      if (!p) return;
      setParams(p);
      setActivePreset(key);
      onChange?.(p);
    },
    [onChange]
  );

  // ─── セクション共通スタイル ─────────────────────────────────────────────

  const sectionHd: React.CSSProperties = {
    fontSize: 12,
    fontWeight: 500,
    color: "var(--color-text-secondary)",
    letterSpacing: "0.05em",
    borderBottom: "0.5px solid var(--color-border-tertiary)",
    paddingBottom: 6,
    marginBottom: 14,
  };

  const paramGrid: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: "14px 24px",
  };

  const divider: React.CSSProperties = {
    height: "0.5px",
    background: "var(--color-border-tertiary)",
    margin: "1.5rem 0",
  };

  // ─── レンダー ────────────────────────────────────────────────────────────

  return (
    <div style={{ fontFamily: "var(--font-sans)", color: "var(--color-text-primary)" }}>

      {/* プリセット選択 */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: "1.5rem" }}>
        <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>プリセット:</span>
        {Object.entries(PRESET_LABELS).map(([key, label]) => (
          <button
            key={key}
            onClick={() => applyPreset(key)}
            style={{
              padding: "5px 14px",
              borderRadius: 20,
              border: "0.5px solid var(--color-border-secondary)",
              background: activePreset === key ? "#E1F5EE" : "var(--color-background-primary)",
              color: activePreset === key ? "#085041" : "var(--color-text-secondary)",
              fontSize: 12,
              cursor: "pointer",
              // [AGENT] アクティブ時は borderColor も変える
              ...(activePreset === key ? { borderColor: "#1D9E75" } : {}),
            }}
          >
            {label}
          </button>
        ))}
        {activePreset === null && (
          <span
            style={{
              padding: "5px 14px",
              borderRadius: 20,
              border: "0.5px solid var(--color-border-secondary)",
              fontSize: 12,
              color: "var(--color-text-tertiary)",
            }}
          >
            カスタム
          </span>
        )}
      </div>

      {/* サマリーバー */}
      <SummaryBar params={params} />

      {/* セクション: 車両構成 */}
      <section style={{ marginBottom: "1.5rem" }}>
        <div style={sectionHd}>車両構成</div>
        <FleetVisualizer n_bev={params.n_bev} n_ice={params.n_ice} />
        <div style={{ height: 14 }} />
        <div style={paramGrid}>
          <SliderField
            label="電気バス（BEV）台数" id="n_bev"
            min={0} max={30} value={params.n_bev} unit="台"
            onChange={(v) => update({ n_bev: v })}
          />
          <SliderField
            label="ディーゼルバス（ICE）台数" id="n_ice"
            min={0} max={30} value={params.n_ice} unit="台"
            onChange={(v) => update({ n_ice: v })}
          />
          <SliderField
            label="BEV バッテリー容量" id="battery_kwh"
            min={50} max={400} step={10} value={params.battery_kwh} unit="kWh"
            hint="1台あたり。大きいほど1充電で走れる距離が長い"
            onChange={(v) => update({ battery_kwh: v })}
          />
          <SliderField
            label="最低 SOC（充電切れ防止ライン）" id="soc_min_pct"
            min={5} max={40} value={params.soc_min_pct} unit="%"
            hint="バッテリー残量がこの値を下回らないよう計算する"
            onChange={(v) => update({ soc_min_pct: v })}
          />
        </div>
      </section>

      <div style={divider} />

      {/* セクション: 充電設備 */}
      <section style={{ marginBottom: "1.5rem" }}>
        <div style={sectionHd}>充電設備</div>
        <div style={{ ...paramGrid, marginBottom: 14 }}>
          <SliderField
            label="充電器台数" id="n_chargers"
            min={1} max={15} value={params.n_chargers} unit="台"
            hint="充電器が少ないと待ち行列が発生しやすい"
            onChange={(v) => update({ n_chargers: v })}
          />
          <SliderField
            label="充電器の出力（1台あたり）" id="charger_kw"
            min={30} max={300} step={10} value={params.charger_kw} unit="kW"
            hint="出力が大きいほど短時間で充電できる"
            onChange={(v) => update({ charger_kw: v })}
          />
        </div>
        <div style={{ marginBottom: 6, fontSize: 12, color: "var(--color-text-secondary)" }}>
          充電を許可する時間帯（クリックで切り替え）
        </div>
        <ChargeWindowSelector
          value={params.charge_hours}
          onChange={(v) => update({ charge_hours: v })}
        />
      </section>

      <div style={divider} />

      {/* セクション: 電気料金プラン */}
      <section style={{ marginBottom: "1.5rem" }}>
        <div style={sectionHd}>電気料金プラン</div>
        <div
          style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginBottom: 14 }}
        >
          {TOU_OPTIONS.map(({ value, label, badge, desc }) => (
            <div
              key={value}
              onClick={() => update({ tou_plan: value })}
              style={{
                border: params.tou_plan === value
                  ? "1.5px solid #1D9E75"
                  : "0.5px solid var(--color-border-tertiary)",
                borderRadius: "var(--border-radius-md)",
                padding: "10px",
                cursor: "pointer",
                background: params.tou_plan === value ? "#E1F5EE" : "var(--color-background-primary)",
              }}
            >
              <div
                style={{
                  fontSize: 9,
                  padding: "2px 6px",
                  borderRadius: 3,
                  display: "inline-block",
                  marginBottom: 5,
                  background: "#D3D1C7",
                  color: "#444441",
                  // [AGENT] badge の色は TOU_OPTIONS に colorKey を追加して動的に出し分ける
                }}
              >
                {badge}
              </div>
              <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 3 }}>{label}</div>
              <div style={{ fontSize: 10, color: "var(--color-text-secondary)", lineHeight: 1.4 }}>
                {desc}
              </div>
            </div>
          ))}
        </div>
        <div style={paramGrid}>
          <SliderField
            label="太陽光パネル出力" id="pv_kw"
            min={0} max={300} step={10} value={params.pv_kw} unit="kW"
            hint="0 にすると太陽光なしで計算"
            onChange={(v) => update({ pv_kw: v })}
          />
          <SliderField
            label="デマンド料金（最大需要電力）" id="demand_charge"
            min={0} max={3000} step={100} value={params.demand_charge} unit="円/kW"
            hint="月内の最大電力に課金される基本料金"
            onChange={(v) => update({ demand_charge: v })}
          />
        </div>
      </section>

      <div style={divider} />

      {/* セクション: 計算精度 */}
      <section style={{ marginBottom: "1.5rem" }}>
        <div style={sectionHd}>計算精度・時間</div>
        <div style={paramGrid}>
          <SliderField
            label="計算対象日数" id="n_days"
            min={1} max={30} value={params.n_days} unit="日"
            hint="多いほど精度↑・計算時間↑"
            onChange={(v) => update({ n_days: v })}
          />
          <SliderField
            label="最大計算時間" id="time_limit_min"
            min={1} max={60} value={params.time_limit_min} unit="分"
            onChange={(v) => update({ time_limit_min: v })}
          />
        </div>
      </section>

      {/* アクション */}
      <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
        {/* [AGENT] JSON確認ボタンは開発時のみ表示するか、削除してもよい */}
        <button
          onClick={() => console.log(JSON.stringify(params, null, 2))}
          style={{ padding: "8px 16px", borderRadius: "var(--border-radius-md)", fontSize: 13, cursor: "pointer" }}
        >
          JSON 確認
        </button>
        <button
          onClick={() => onSubmit?.(params)}
          style={{
            padding: "8px 18px",
            borderRadius: "var(--border-radius-md)",
            fontSize: 13,
            fontWeight: 500,
            cursor: "pointer",
            background: "#1D9E75",
            color: "#fff",
            border: "none",
          }}
        >
          最適化を開始する
        </button>
      </div>

    </div>
  );
};

export default ParamEditor;
