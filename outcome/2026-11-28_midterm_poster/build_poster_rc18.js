// Midterm (2026-11-28) A0 portrait poster (841 x 1189 mm), editable PowerPoint, rebuilt from rc18.
// Replaces the rc8/rc9 poster (build_poster.js is kept unchanged as the earlier version).
// Data: cases_rc18.json (12 VERIFIED cases, DIAGNOSTIC), ice_by_hour_rc18.json, all_diesel_estimate.csv.
// 30 JPY/kWh is an all-inclusive unit (basic + energy charge); the annual basic charge is shown only as a
// reference ("目安") and never added. Same plain layout as build_poster.js (white, TCU blue #0485D7).
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(path.join(process.env.PPTX_SKILL, "scripts", "apply_theme.js"));

const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "cases_rc18.json"), "utf8"));
if (cases.length !== 12 || cases.some((r) => r.status !== "VERIFIED")) throw new Error("expected 12 VERIFIED rc18 cases");
const iceHour = JSON.parse(fs.readFileSync(path.join(__dirname, "ice_by_hour_rc18.json"), "utf8"));
const dl = fs.readFileSync(path.join(__dirname, "all_diesel_estimate_rc18.csv"), "utf8").replace(/^﻿/, "").trim().split(/\r?\n/);
const dk = dl[0].split(","), diesel = dl.slice(1).map((l) => Object.fromEntries(l.split(",").map((v, i) => [dk[i], v])));
const LIMITS = [90, 200, 400, 800];
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const get = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const avg = (g, k) => { const rs = cases.filter((r) => r.grid_limit_kw === g); return rs.reduce((a, r) => a + r[k], 0) / rs.length; };
const opex = (g) => (avg(g, "electricity_cost") + avg(g, "fuel_cost") + avg(g, "contract_overage_cost")) / 1e4;
// Reference only: annual basic charge if the contract power were max(limit, annual peak) (TEPCO EP, 2026-04, high voltage).
const BASIC_YEN_PER_KW = 2530;
const peakYear = (g) => Math.max(...cases.filter((r) => r.grid_limit_kw === g).map((r) => r.peak_grid_kw));
const basicYear = (g) => Math.max(g, peakYear(g)) * BASIC_YEN_PER_KW * 0.85 * 12;

const BLUE = "0485D7", BLUE_DARK = "0268B0", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD";
const THEME = { name: "TCU white", headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.defineLayout({ name: "A0_PORTRAIT", width: 33.11, height: 46.81 });
pres.layout = "A0_PORTRAIT";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "中間発表ポスター 2026-11-28";
const M = 1.6, W = 33.11 - 2 * M, GAP = 0.9, COL = (W - GAP) / 2, LX = M, RX = M + COL + GAP;
const s = pres.addSlide();
s.background = { color: "FFFFFF" };
const text = (t, o) => { if (!(o.h > 0) || o.y + o.h > 46.81 - 1.2) throw new Error(`text box off the page: y=${o.y} h=${o.h}`); return s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 42, fontFace: "Yu Gothic", lineSpacingMultiple: 1.15, ...o }); };
const section = (label, x, y, w) => {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 1.25, fill: { color: BLUE }, line: { color: BLUE } });
  text(label, { x: x + 0.35, y, w: w - 0.5, h: 1.25, valign: "middle", fontSize: 50, bold: true, color: "FFFFFF" });
  return y + 1.6;
};
const chart = () => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 32, valAxisLabelFontSize: 28, valGridLine: { color: GRID, size: 1.5 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 32, legendColor: INK, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 30, dataLabelColor: INK,
  showLegend: true, legendPos: "t", valAxisTitleFontFace: "+mn-lt", catAxisTitleFontFace: "+mn-lt" });
const caption = (t, x, y, w, h = 0.9, fs = 30) => text(t, { x, y, w, h, fontSize: fs, color: SUB });

const shares = cases.map((r) => r.bev_trip_share_pct);
const shareRange = `${Math.min(...shares).toFixed(1)}〜${Math.max(...shares).toFixed(1)}%`;
const co2Cut = SE.map(([w]) => 1 - get(800, w).total_co2_kg / Number(diesel.find((d) => d.week === w).co2_kg));
const cutRange = `${Math.round(Math.min(...co2Cut) * 100)}〜${Math.round(Math.max(...co2Cut) * 100)}%`;
const w90 = get(90, "2025-01-06");

// ---- Title block: one blue rule under the title; the top-left 20 x 20 cm is kept free for the number.
const NUM = 7.87;
text("GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: M + NUM, y: M + 0.3, w: W - NUM, h: 3.4, fontSize: 80, bold: true, valign: "middle" });
text("東京都市大学　劉 承洋（研究室名・指導教員をここに記入）", { x: M + NUM, y: M + 3.9, w: W - NUM, h: 1.0, fontSize: 44, color: SUB });
s.addShape(pres.shapes.LINE, { x: M, y: M + 5.6, w: W, h: 0, line: { color: BLUE, width: 8 } });

// ---- Abstract (full width)
text(`概要　路線バスの電動化では、営業所での充電が重なると受電電力が大きくなる。本研究では、燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を最適化し、受電上限を変えたときの電気バスの担当便・費用・CO₂を冬・春・夏の代表週で評価した。受電上限を800 kWから90 kWまで下げても電気バスの担当便は${shareRange}でほぼ一定であり、400 kW以上では上限の超過がなかった。超過は前日の計画ではなく、実際の天気で計画を立て直す実行中に生じた。`,
  { x: M, y: 8.0, w: W, h: 3.9, fontSize: 42 });

// ---- Left column
let y = 12.5;
y = section("1．背景と目的", LX, y, COL);
text([
  { text: "路線バスで電気バスの導入が進んでいるが、車両価格や充電時間の制約から、当面は燃料（軽油）バスとの併用が続く。電気バスは夜に営業所でまとめて充電するため、受電電力が大きくなる。", options: { breakLine: true } },
  { text: "本研究の目的は、受電上限を変えたとき、(1) 電気バスに任せられる便の割合と、費用・燃料・CO₂がどう変わるか、(2) 上限の超過がどこで生じるかを明らかにすることである。" }],
  { x: LX, y, w: COL, h: 4.3, paraSpaceAfter: 10, fontSize: 36 });
y += 4.6;
y = section("2．対象と条件", LX, y, COL);
const rows = [["対象", "東急バス 渋21〜23系統（弦巻営業所）"], ["運行", "1週間 1,704便（平日264・土203・日祝181便/日）"], ["車両", "保有 電気バス35台・燃料バス25台（固定）"],
  ["設備", "太陽光1,000 kW（傾斜30°）・蓄電池6,000 kWh・充電器10基"], ["受電上限", "90/200/400/800 kW（超過分に500円/kWh・仮）"], ["期間", "冬・春・夏の代表週（2025年）"],
  ["毎朝の電池", "目標90%・下限80%"], ["単価", "電気30円/kWh（基本料金・従量料金を含む）・軽油150円/L"], ["CO₂", "軽油2.62 kg/L、電力0.5 kg/kWh（仮）"]];
s.addTable(rows.map(([k, v]) => [{ text: k, options: { bold: true } }, { text: v }]),
  { x: LX, y, w: COL, colW: [3.4, COL - 3.4], fontSize: 32, fontFace: "Yu Gothic", color: INK, rowH: 0.78, valign: "middle",
    border: { type: "solid", pt: 1, color: GRID } });
y += rows.length * 0.78 + 1.0;
y = section("3．手法", LX, y, COL);
text([
  { text: "便割当（Stage 1）：1,704便を60台に割り当てる混合整数計画問題。一部の便だけを解き直す大近傍探索（LNS）で改善した（各上限とも同じ割当から90分）。", options: { breakLine: true } },
  { text: "充電計画（Stage 2）：割当を固定し、15分ごとの充電・太陽光・蓄電池・買電を最適化する。前日の計画では、太陽光を過去の実績から作った平年値で予報する。", options: { breakLine: true } },
  { text: "実行：実際の天気で1時間ごとに充電を立て直しながら1週間を運用し（175回、1回120秒）、その結果で費用を集計した。" }],
  { x: LX, y, w: COL, h: 6.0, paraSpaceAfter: 14, fontSize: 34 });
y += 6.4;
const FC = [3391, 3401, 3412, 3423, 3436, 3448, 3462], AC = [1399, 2640, 3836, 4871, 5059, 5079, 1693];
const DAYS = ["月", "火", "水", "木", "金", "土", "日"];
s.addChart(pres.charts.BAR, [{ name: "前日の予報（平年値）", labels: DAYS, values: FC }, { name: "実際", labels: DAYS, values: AC }],
  { ...chart(), x: LX, y, w: COL, h: 5.2, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", BLUE], valAxisMinVal: 0,
    legendFontSize: 28, showValAxisTitle: true, valAxisTitle: "太陽光 [kWh/日]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
caption("図5　冬の代表週（2025年1月6日〜）の太陽光：前日の予報と実際（入力データ）", LX, y + 5.25, COL, 0.8, 28);
y += 6.3;
caption("注：結果はすべて診断用（DIAGNOSTIC）。便割当は全件メモリ上限で停止（証明できるギャップ約45%）、2段階法のため全体の最適ではない。冬・90 kWの前日の充電計画は時間切れ（ギャップ26%）、他の11件は最適。各上限とも同じ割当から改善したため、最終の割当の78〜98%の便が出発点と同じ車両。便割当の段階は毎朝90%の重みを見ないため、買電を少なく見込む。最大受電は15分平均。",
  LX, y, COL, 45.5 - y, 26);

// ---- Right column
y = 12.5;
y = section("4．結果", RX, y, COL);
s.addChart(pres.charts.LINE, SE.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(g, w).bev_trip_share_pct * 10) / 10) })),
  { ...chart(), x: RX, y, w: COL, h: 5.4, lineSize: 5, lineDataSymbol: "circle", lineDataSymbolSize: 14, chartColors: [BLUE_DARK, "7AB8E8", GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showCatAxisTitle: true, catAxisTitle: "受電上限", catAxisTitleFontSize: 30, catAxisTitleColor: SUB,
    showValAxisTitle: true, valAxisTitle: "電気バス担当便 [%]", valAxisTitleFontSize: 30, valAxisTitleColor: SUB });
caption("図1　受電上限と電気バスの担当便（1,704便/週）", RX, y + 5.45, COL);
y += 6.4;
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };
text(`(1) 受電上限を90〜800 kWで変えても、電気バスの担当便は${shareRange}でほぼ一定だった。燃料バスが担当したのは主に早朝（${rng("05-06")}）と深夜（${rng("22-")}）の便で（図2）、CO₂は全車燃料バスより約${cutRange}少なかった（図3）。`,
  { x: RX, y, w: COL, h: 3.0, fontSize: 33 });
y += 3.3;
const half = (COL - 0.6) / 2;
const BANDS = [["05-06", "早朝"], ["07-21", "日中"], ["22-", "深夜"]];
const iceShare = (g, b) => { const rs = iceHour.filter((r) => r.grid_limit_kw === g);
  return Math.round(rs.reduce((a, r) => a + r.bands[b].diesel / r.bands[b].total, 0) / rs.length * 1000) / 10; };
s.addChart(pres.charts.BAR, LIMITS.map((g) => ({ name: `${g}`, labels: BANDS.map((x) => x[1]), values: BANDS.map(([b]) => iceShare(g, b)) })),
  { ...chart(), x: RX, y, w: half, h: 5.0, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", GREY, "7AB8E8", BLUE_DARK], valAxisMinVal: 0,
    legendFontSize: 26, catAxisLabelFontSize: 28, showValAxisTitle: true, valAxisTitle: "燃料バス担当便 [%]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バス併用", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(get(800, w).total_co2_kg / 100) / 10) }],
  { ...chart(), x: RX + half + 0.6, y, w: half, h: 5.0, barDir: "col", barGrouping: "clustered", chartColors: [GREY, BLUE], valAxisMinVal: 0,
    legendFontSize: 26, catAxisLabelFontSize: 28, showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
caption("図2　時間帯別の燃料バス担当便（凡例：受電上限 kW）", RX, y + 5.05, half, 1.2, 28);
caption("図3　1週間のCO₂（併用は800 kW、全車燃料バスは走行距離からの概算）", RX + half + 0.6, y + 5.05, half, 1.2, 28);
y += 6.45;
s.addChart(pres.charts.BAR, SE.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(g, w).contract_over_limit_kwh)) })),
  { ...chart(), x: RX, y, w: half, h: 5.2, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK, "7AB8E8", GREY], valAxisMinVal: 0,
    legendFontSize: 26, catAxisLabelFontSize: 26, showValAxisTitle: true, valAxisTitle: "上限の超過 [kWh/週]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
s.addChart(pres.charts.BAR, [
  { name: "電気代", labels: LIMITS.map((g) => `${g}`), values: LIMITS.map((g) => Math.round(avg(g, "electricity_cost") / 1e3) / 10) },
  { name: "燃料代", labels: LIMITS.map((g) => `${g}`), values: LIMITS.map((g) => Math.round(avg(g, "fuel_cost") / 1e3) / 10) },
  { name: "超過費用", labels: LIMITS.map((g) => `${g}`), values: LIMITS.map((g) => Math.round(avg(g, "contract_overage_cost") / 1e3) / 10) }],
  { ...chart(), x: RX + half + 0.6, y, w: half, h: 5.2, barDir: "col", barGrouping: "stacked", chartColors: [BLUE, GREY, "CFCFCF"], valAxisMinVal: 0,
    legendFontSize: 26, catAxisLabelFontSize: 28, showValAxisTitle: true, valAxisTitle: "運用費 [万円/週]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
caption("図4　超過電力量（左）と運用費（右、3週平均・車両費を除く）", RX, y + 5.25, COL, 0.9, 28);
y += 6.2;
text(`(2) 400 kW以上では超過がなく、超過が残ったのは90 kW（3季節）と200 kWの冬だった（冬・90 kWで${Math.round(w90.contract_over_limit_kwh).toLocaleString("ja-JP")} kWh/週）。運用費は800 kWの約${Math.round(opex(800))}万円/週から90 kWの約${Math.round(opex(90))}万円/週に増えたが、増分はほぼ超過費用だった。（目安）年間最大の受電電力から見た基本料金は400 kWで最小（年約${Math.round(basicYear(400) / 1e4).toLocaleString("ja-JP")}万円、30円/kWhに含むため合計に足さない）。`,
  { x: RX, y, w: COL, h: 4.5, fontSize: 32 });
y += 4.7;

y = section("5．考察とまとめ", RX, y, COL);
text([
  { text: "前日の計画（予報）では12ケースとも超過0だった。超過は、実際の太陽光が予報（平年値）より少ない日に、計画を立て直す段階で生じた（図5）。90・200 kWでは立て直しの5〜23%が制限時間内に最適と確認できなかった。", options: { breakLine: true } },
  { text: "今後：充電計画の探索と便割当の段階の見込みの改善、日をまたいだ計画の評価（年内）。" }],
  { x: RX, y, w: COL, h: 45.5 - y, paraSpaceAfter: 8, fontSize: 30 });

(async () => {
  const out = path.join(__dirname, process.env.POSTER_OUT || "midterm_poster_A0_rc18.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
