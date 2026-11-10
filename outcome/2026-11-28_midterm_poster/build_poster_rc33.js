// Midterm (2026-11-28) A0 portrait poster (841 x 1189 mm), editable PowerPoint, rebuilt from rc20,
// 2026-11-07: the base case (900 kW, PV 1,000 kW) BEV-heavy vs ICE-heavy table replaces figs 2-3
// (rc29 d25cc724 winter pair, rc35 spring/summer; ../../output/midterm_20261128/rc23_eval/k900pair.md).
// 2026-11-08: winter pair replaced by rc33 7dc38d95 (g900/h900, rc23_eval/rc33_all.md); 90 kW winter pair and PV 0 from rc33.
// Data: ../2026-11-12_three_party/deck_data_rc20.json (prepare_deck_data.py, verified cases only, DIAGNOSTIC).
// Grid limits 90/200/400/600/900 kW (900 = all ten 90 kW chargers at once). 30 JPY/kWh is all-inclusive;
// the annual basic charge is a reference ("目安") only and is never added. Earlier versions:
// build_poster.js (rc8/rc9) and build_poster_rc18.js.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(path.join(process.env.PPTX_SKILL, "scripts", "apply_theme.js"));

// 11/9: latest version (rc33/rc35) via ../2026-11-12_three_party/prepare_deck_data_latest.py; cheaper of the two
// start points per limit x season; diesel valued by the litres burnt (post-hoc, as in the deck).
const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "deck_data_latest.json"), "utf8"));
DATA.cases.forEach((r) => { if (r.status === "VERIFIED") {
  r.total_cost_accounting = r.total_cost; r.total_cost = r.total_cost_fuel_consumed; r.fuel_cost = r.ice_fuel_consumed_l * 150; } });
const cases = DATA.cases.filter((r) => r.status === "VERIFIED");
const iceHour = DATA.ice_by_hour;
const diesel = DATA.diesel;
const LIMITS = DATA.limits;
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const get = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const avg = (g, k) => { const rs = cases.filter((r) => r.grid_limit_kw === g); return rs.reduce((a, r) => a + r[k], 0) / Math.max(rs.length, 1); };
const val = (g, w, k, f = (v) => v) => (get(g, w) ? f(get(g, w)[k]) : null);
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

// Latest-version helpers (cheaper of the two start points per limit x season).
const SEASON_OF = Object.fromEntries(SE);
const lab = (r) => `${r.grid_limit_kw} kW${SEASON_OF[r.week]}`;
const iceWins = cases.filter((r) => r.selected_start === "ice"), bevWins = cases.filter((r) => r.selected_start === "bev");
const rngTxt = (a, d = 0) => !a.length ? "—" : Math.min(...a).toFixed(d) === Math.max(...a).toFixed(d) ? Math.min(...a).toFixed(d) : `${Math.min(...a).toFixed(d)}〜${Math.max(...a).toFixed(d)}`;
// 2026-11-09: 90 kW spring has no running job; its ICE-heavy run (rc35 a090s10) FAILED, so it is not "計算中".
// 400 kW summer: the BEV-heavy run (rc35 a400s10) FAILED; only the ICE-heavy start finished.
const STOPPED = new Map([]);
const notDone = DATA.cases.filter((r) => r.status !== "VERIFIED");
const pend = notDone.filter((r) => !STOPPED.has(`${r.grid_limit_kw}/${r.week}`)).map((r) => `${r.grid_limit_kw} kW${SEASON_OF[r.week]}`);
const stopped = notDone.filter((r) => STOPPED.has(`${r.grid_limit_kw}/${r.week}`)).map((r) => `${r.grid_limit_kw} kW${SEASON_OF[r.week]}は${STOPPED.get(`${r.grid_limit_kw}/${r.week}`)}`);
const pairOf = (g, w, st) => DATA.pairs.find((x) => x.grid_limit_kw === g && x.week === w && x.start === st && x.status === "VERIFIED");
const pb90 = pairOf(90, "2025-01-06", "bev"), pi90 = pairOf(90, "2025-01-06", "ice");
const tcc = (r) => r.total_cost_fuel_consumed;
const shares = cases.map((r) => r.bev_trip_share_pct);
const shareRange = `${Math.min(...shares).toFixed(1)}〜${Math.max(...shares).toFixed(1)}%`;
const co2Cut = SE.filter(([w]) => get(900, w)).map(([w]) => 1 - get(900, w).total_co2_kg / Number(diesel.find((d) => d.week === w).co2_kg));
const maxTimeouts = Math.max(...DATA.rolling.map((r) => r.time_limit));
const bevGridPerKm = 1.316 * 30, icePerKm = 150 / 4.52, bevOverPerKm = 1.316 * 530;
const cutRange = `${Math.round(Math.min(...co2Cut) * 100)}〜${Math.round(Math.max(...co2Cut) * 100)}%`;
const w90 = get(90, "2025-01-06");
const man = (v) => (v / 1e4).toFixed(1);
const fmt = (v) => Math.round(v).toLocaleString("ja-JP");
const K9 = {
  wb: { cost: 4189120, share: 92.6, co2: 2470, pvUse: 19867, pvCut: 4709, over: 0 },
  wi: { cost: 4387150, share: 37.6, co2: 5949, pvUse: 14258, pvCut: 10318, over: 0 },
  sb: { cost: 4157225, share: 93.5, co2: 1945, pvUse: 22127, pvCut: 5692, over: 0 },
  // 2026-11-10: summer BEV-heavy is rerunning as rc36 a900u. The earlier rc35 a900s10f numbers were removed:
  // that launch carried no seed and default time limits, so it was not the same case as the other columns.
  ub: null };

// ---- Title block: one blue rule under the title; the top-left 20 x 20 cm is kept free for the number.
const NUM = 7.87;
text("GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: M + NUM, y: M + 0.3, w: W - NUM, h: 3.4, fontSize: 80, bold: true, valign: "middle" });
text("東京都市大学　劉 承洋（研究室名・指導教員をここに記入）", { x: M + NUM, y: M + 3.9, w: W - NUM, h: 1.0, fontSize: 44, color: SUB });
s.addShape(pres.shapes.LINE, { x: M, y: M + 5.6, w: W, h: 0, line: { color: BLUE, width: 8 } });

// ---- Abstract (full width)
text(`概要　路線バスの電動化では、営業所での充電が重なると受電電力が大きくなる。燃料バスと電気バスを併用する営業所で便の割当と充電計画を最適化し、受電上限を変えたときの担当便・費用・CO₂を冬・春・夏の代表週で評価した。受電上限900 kW・太陽光1,000 kWの冬では、電気バス中心の運用は燃料バス中心より1週間で${man(K9.wi.cost - K9.wb.cost)}万円安く、CO₂は${Math.round((1 - K9.wb.co2 / K9.wi.co2) * 100)}%少なかった。上限を下げると電気バス中心の優位は縮み、${iceWins.length ? `${iceWins.map(lab).join("・")}では燃料バス中心の方が安かった（90 kW冬でCO₂は約${(pi90.total_co2_kg / pb90.total_co2_kg).toFixed(1)}倍）。` : "どの上限でも電気バス中心が安かった。"}`,
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
const rows = [["対象", "東急バス 渋21〜23系統（弦巻営業所）、時刻表はODPT［3］"], ["運行", "1週間 1,704便（平日264・土203・日祝181便/日）"], ["車両", "保有 電気バス35台・燃料バス25台（固定）"],
  ["設備", "太陽光1,000 kW・蓄電池6,000 kWh・充電器90 kW×10"], ["受電上限", "90・200・400・900 kW（超過は500円/kWh・仮）"], ["期間", "冬・春・夏の代表週（2025年）"],
  ["毎朝の電池", "目標90%・下限80%"], ["単価", "電気30円/kWh（基本料金込み）・軽油150円/L"], ["CO₂", "軽油2.62 kg/L［1］、電力0.5 kg/kWh（仮）"]];
s.addTable(rows.map(([k, v]) => [{ text: k, options: { bold: true } }, { text: v }]),
  { x: LX, y, w: COL, colW: [3.4, COL - 3.4], fontSize: 32, fontFace: "Yu Gothic", color: INK, rowH: 0.70, valign: "middle",
    border: { type: "solid", pt: 1, color: GRID } });
y += rows.length * 0.70 + 1.0;
y = section("3．手法", LX, y, COL);
text([
  { text: "便割当（Stage 1）：1,704便を60台に割り当てる混合整数計画問題。一部の便だけを解き直す大近傍探索（LNS）［5］で90分改善した（Gurobi［4］）。毎朝の電池の不足分の重みを充電計画と共通にした。", options: { breakLine: true } },
  { text: "充電計画（Stage 2）：割当を固定し、15分ごとの充電・太陽光・蓄電池・買電を最適化する。前日の計画では、太陽光を過去の実績から作った平年値で予報する（斜面日射はpvlib［2］）。", options: { breakLine: true } },
  { text: "実行：実際の天気で1時間ごとに充電を立て直しながら1週間を運用し（175回、1回120秒）、その結果で費用を集計した。" }],
  { x: LX, y, w: COL, h: 6.0, paraSpaceAfter: 14, fontSize: 34 });
y += 6.4;
const FC = [3391, 3401, 3412, 3423, 3436, 3448, 3462], AC = [1399, 2640, 3836, 4871, 5059, 5079, 1693];
const DAYS = ["月", "火", "水", "木", "金", "土", "日"];
s.addChart(pres.charts.BAR, [{ name: "前日の予報（平年値）", labels: DAYS, values: FC }, { name: "実際", labels: DAYS, values: AC }],
  { ...chart(), x: LX, y, w: COL, h: 3.8, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", BLUE], valAxisMinVal: 0,
    legendFontSize: 28, showValAxisTitle: true, valAxisTitle: "太陽光 [kWh/日]", valAxisTitleFontSize: 26, valAxisTitleColor: SUB });
caption("図5　冬の代表週（2025年1月6日〜）の太陽光：前日の予報と実際（入力データ）", LX, y + 3.85, COL, 0.8, 28);
y += 4.9;
caption(`注：結果はすべて診断用（DIAGNOSTIC）。最新版（rc33・rc35）。各ケースを電気バス寄り・燃料バス寄りの2つの出発点から解き、総費用（燃料は使った分）の安い方を示す。便割当はメモリ上限で停止し、2段階法のため全体の最適ではない。毎時の立て直しは最大${maxTimeouts}/175回が時間切れ。遅い計算機は制限時間を延ばした。${pend.length ? `${pend.join("・")}は計算中。` : ""}${stopped.length ? `${stopped.join("、")}の計算が失敗し未完。` : ""}最大受電は15分平均。`,
  LX, y, COL, 45.5 - y - 2.5, 24);
text([{ text: "参考文献（原本は 先行文献／2026-11-08_中間発表の参考文献）", options: { bold: true, breakLine: true } },
  ...["［1］環境省・経済産業省：算定方法及び排出係数一覧（2025年版）", "［2］W. F. Holmgren et al.: pvlib python, JOSS 3(29), 884, 2018",
    "［3］公共交通オープンデータセンター：東急バス 時刻表データ（ODPT）", "［4］Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0",
    "［5］P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, CP-98, LNCS 1520, 1998"]
    .map((t, i, a) => ({ text: t, options: { breakLine: i < a.length - 1 } }))],
  { x: LX, y: 45.5 - 2.4, w: COL, h: 2.4, fontSize: 20, color: SUB });

// ---- Right column
y = 12.5;
y = section("4．結果", RX, y, COL);
s.addChart(pres.charts.LINE, SE.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => val(g, w, "bev_trip_share_pct", (v) => Math.round(v * 10) / 10)) })),
  { ...chart(), x: RX, y, w: COL, h: 5.4, lineSize: 5, lineDataSymbol: "circle", lineDataSymbolSize: 14, chartColors: [BLUE_DARK, "7AB8E8", GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showCatAxisTitle: true, catAxisTitle: "受電上限", catAxisTitleFontSize: 30, catAxisTitleColor: SUB,
    showValAxisTitle: true, valAxisTitle: "電気バス担当便 [%]", valAxisTitleFontSize: 30, valAxisTitleColor: SUB });
caption("図1　受電上限と電気バスの担当便（1,704便/週、安い方の出発点）", RX, y + 5.45, COL);
y += 6.4;
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };
text(`(1) 2つの出発点のうち安い方で見ると、${iceWins.length ? `受電上限の低い${iceWins.map(lab).join("・")}では燃料バス寄りが安く、電気バスの担当便は${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}%だった。` : ""}それ以外は電気バス寄りが安く、担当便は${rngTxt(bevWins.map((r) => r.bev_trip_share_pct), 1)}%だった。同じケースでも出発点で担当便は大きく変わった。`,
  { x: RX, y, w: COL, h: 3.0, fontSize: 33 });
y += 3.3;
const half = (COL - 0.6) / 2;
const K9COLS = [["wb", "冬・電気中心"], ["wi", "冬・燃料中心"], ["sb", "春・電気中心"], ["ub", "夏・電気中心"]];
const k9Row = (label, f) => [{ text: label, options: { bold: true } }, ...K9COLS.map(([k]) => ({ text: (K9[k] ? f(K9[k]) : "計算中"), options: { align: "center" } }))];
s.addTable([
  [{ text: "基準ケース", options: { bold: true, fill: { color: "F2F2F2" } } },
   ...K9COLS.map(([, n]) => ({ text: n, options: { bold: true, fill: { color: "F2F2F2" }, align: "center" } }))],
  k9Row("総費用", (r) => `${man(r.cost)}万円`),
  k9Row("電気バス担当便", (r) => `${r.share.toFixed(1)}%`),
  k9Row("CO₂", (r) => `${fmt(r.co2)} kg`),
  k9Row("太陽光 使用／廃棄 [MWh]", (r) => `${(r.pvUse / 1e3).toFixed(1)}／${(r.pvCut / 1e3).toFixed(1)}`),
  k9Row("上限の超過", (r) => `${fmt(r.over)} kWh`)],
  { x: RX, y, w: COL, colW: [4.0, (COL - 4.0) / 4, (COL - 4.0) / 4, (COL - 4.0) / 4, (COL - 4.0) / 4], fontSize: 27, fontFace: "Yu Gothic",
    color: INK, rowH: 0.74, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
caption(`表1　受電上限900 kW・太陽光1,000 kWの1週間。冬の2列は同じ版で出発点だけが違う（rc33）、春は電気中心（rc35）、夏は新しい版（rc36）で計算中。冬は電気中心が${man(K9.wi.cost - K9.wb.cost)}万円安くCO₂は${Math.round((1 - K9.wb.co2 / K9.wi.co2) * 100)}%少ない。燃料中心は太陽光の約4割を捨てる。DIAGNOSTIC`, RX, y + 4.75, COL, 1.6, 26);
y += 6.5;
// 11/9 (user request): cost and CO2 of both start points by grid limit, cases where both are verified.
const PAIRS = [];
LIMITS.forEach((g) => SE.forEach(([w]) => { const b = pairOf(g, w, "bev"), i = pairOf(g, w, "ice"); if (b && i) PAIRS.push({ label: `${g}${SEASON_OF[w]}`, b, i }); }));
const pcats = PAIRS.map((p) => p.label);
const pairChart = (o) => ({ ...chart(), y, w: half, h: 5.7, barDir: "bar", barGrouping: "clustered", chartColors: [BLUE, GREY], valAxisMinVal: 0, catAxisOrientation: "maxMin", barGapWidthPct: 60,
  showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 18, legendFontSize: 26, catAxisLabelFontSize: 20, catAxisLabelFrequency: 1, barGapWidthPct: 40, valAxisLabelFontSize: 22, valAxisTitleFontSize: 26, valAxisTitleColor: SUB, showValAxisTitle: true, ...o });
s.addChart(pres.charts.BAR, [
  { name: "電気バス寄り", labels: pcats, values: PAIRS.map((p) => Math.round(p.b.total_cost_fuel_consumed / 1e4)) },
  { name: "燃料バス寄り", labels: pcats, values: PAIRS.map((p) => Math.round(p.i.total_cost_fuel_consumed / 1e4)) }],
  pairChart({ x: RX, dataLabelFormatCode: "0", valAxisMaxVal: 600, valAxisMajorUnit: 200, showValAxisTitle: true, valAxisTitle: "総費用 [万円/週]" }));
s.addChart(pres.charts.BAR, [
  { name: "電気バス寄り", labels: pcats, values: PAIRS.map((p) => Math.round(p.b.total_co2_kg / 100) / 10) },
  { name: "燃料バス寄り", labels: pcats, values: PAIRS.map((p) => Math.round(p.i.total_co2_kg / 100) / 10) }],
  pairChart({ x: RX + half + 0.6, dataLabelFormatCode: "0.0", valAxisMaxVal: 10, valAxisMajorUnit: 2, valAxisTitle: "CO₂ [t/週]" }));
caption("図4　総費用（左、燃料は使った分）とCO₂（右）。2つの出発点がそろったケース", RX, y + 5.75, COL, 0.9, 28);
y += 6.7;
const overCases = cases.filter((r) => r.contract_over_limit_kwh > 1);
text(`(2) 安い方の出発点で超過が残ったのは${overCases.length ? overCases.map((r) => `${lab(r)}（${Math.round(r.contract_over_limit_kwh).toLocaleString("ja-JP")} kWh/週）`).join("・") : "なし"}。電気バス寄りの出発点では90 kW冬で${Math.round(pb90.contract_over_limit_kwh).toLocaleString("ja-JP")} kWh/週の超過が出た。図4のとおり、CO₂は${PAIRS.length}ケースすべてで電気バス寄りが少なく（燃料バス寄りの${(Math.min(...PAIRS.map((p) => p.i.total_co2_kg / p.b.total_co2_kg))).toFixed(1)}〜${(Math.max(...PAIRS.map((p) => p.i.total_co2_kg / p.b.total_co2_kg))).toFixed(1)}分の1）、費用も${PAIRS.filter((p) => p.b.total_cost_fuel_consumed < p.i.total_cost_fuel_consumed).length}ケースで電気バス寄りが安い。（目安）年間最大の受電電力から見た基本料金は30円/kWhに含むため合計に足さない。`,
  { x: RX, y, w: COL, h: 4.0, fontSize: 32 });
y += 4.2;

y = section("5．考察とまとめ", RX, y, COL);
text([
  { text: "90 kW冬・電気バス寄りでは、前日の計画の超過は0。実行の超過の9割は、曇りの月曜（発電は予報の41%、図5）の翌未明、蓄電池が空の時間に出た。系統から蓄電池へ貯めない前提のため、月曜に余った受電枠を夜に回せない。計画だけ予報を半分と見込んでも、超過は1割しか減らなかった。", options: { breakLine: true } },
  { text: "上限に余裕があれば電化は費用もCO₂も下げる（表1）。不利なのは上限が低い冬（90 kWで燃料バス寄りが約40万円安く、CO₂は約3倍）と太陽光がない場合。今後：系統から蓄電池へ貯める場合との比較、日をまたぐ計画。" }],
  { x: RX, y, w: COL, h: 45.5 - y, paraSpaceAfter: 6, fontSize: 26 });

(async () => {
  const out = path.join(__dirname, process.env.POSTER_OUT || "midterm_poster_A0_rc33.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
