// Consultation deck for Prof. Nishiyama, 2026-11 (latest pillar-A results, road map to 2028, candidates for pillar C).
// Built from ../2026-10-21_nishiyama_consult/build_consult_deck.js (same plain style and helpers). Data: the verified
// cases used by the midterm poster (DIAGNOSTIC, 30 JPY/kWh series); totals exclude the CO2 cost.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");


const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_LIGHT = "7AB8E8", BLUE_PALE = "EEF5FB", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2";
const THEME = { name: "TCU white", headFontFace: "Noto Sans JP", bodyFontFace: "Noto Sans JP",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "西山先生へのご相談 2026-11";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 25, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } },
            { line: { x: 0.6, y: 7.0, w: 12.1, h: 0, line: { color: GRID, width: 0.75 } } },
            { text: { text: "2026年11月　劉 承洋", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
  slideNumber: { x: 12.2, y: 7.05, w: 0.5, h: 0.3, fontSize: 10, color: SUB, align: "right" } });

const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 18, lineSpacingMultiple: 1.2, ...o });
const bullets = (s, items, o) => text(s, items.map((t, i) => ({ text: t, options: { bullet: { indent: 18 }, breakLine: i < items.length - 1 } })), { paraSpaceAfter: 8, ...o });
const chart = (o) => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 13, valAxisLabelFontSize: 12, valGridLine: { color: GRID, size: 0.75 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 13, legendColor: INK, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 12, dataLabelColor: INK,
  showLegend: true, legendPos: "t", valAxisTitleColor: SUB, catAxisTitleColor: SUB, valAxisTitleFontSize: 12, catAxisTitleFontSize: 12, ...o });
const caption = (s, t, x, y, w, h = 0.4) => text(s, t, { x, y, w, h, fontSize: 12, color: SUB });
const page = (title) => { const s = pres.addSlide({ masterName: "PLAIN" }); s.addText(title, { placeholder: "title" }); return s; };
const tableOpts = (o) => ({ fontSize: 14, color: INK, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID }, ...o });
const H = (t) => ({ text: t, options: { bold: true, fill: { color: HEAD }, align: "center" } });
const B = (t) => ({ text: t, options: { bold: true } });
const heading = (s, t, y, x = 0.6, w = 12.1) => text(s, t, { x, y, w, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });
const box = (s, x, y, w, h, fill = BLUE_PALE, line = GRID) => s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: line, width: 0.75 } });
const arrow = (s, x, y, w) => s.addShape(pres.shapes.LINE, { x, y, w, h: 0, line: { color: GREY, width: 2, endArrowType: "triangle" } });

// ---------------- data: the same verified cases as the midterm poster (DIAGNOSTIC, 30 JPY/kWh all-inclusive series)
const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "deck_data_latest.json"), "utf8"));
const CO2_YEN_PER_KG = 1; // in the objective only; never in a reported total (user decision 2026-11-16)
[...DATA.cases, ...DATA.pairs].forEach((r) => { if (r.total_cost_fuel_consumed != null) r.total_cost_reported = r.total_cost_fuel_consumed - r.total_co2_kg * CO2_YEN_PER_KG; });
const cases = DATA.cases.filter((r) => r.status === "VERIFIED");
const LIMITS = DATA.limits;
const SEASONS = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const SEASON_OF = Object.fromEntries(SEASONS);
const get = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const pairOf = (g, w, st) => DATA.pairs.find((x) => x.grid_limit_kw === g && x.week === w && x.start === st && x.status === "VERIFIED");
const man = (v) => (v / 1e4).toFixed(1);
const fmt = (v) => Math.round(v).toLocaleString("ja-JP");
const lab = (r) => `${r.grid_limit_kw} kW${SEASON_OF[r.week]}`;
const iceWins = cases.filter((r) => r.selected_start === "ice"), bevWins = cases.filter((r) => r.selected_start === "bev");
const rngTxt = (a, d = 0) => `${Math.min(...a).toFixed(d)}〜${Math.max(...a).toFixed(d)}`;
const maxTimeouts = Math.max(...DATA.pairs.filter((r) => r.status === "VERIFIED").map((r) => r.rolling_time_limit_steps));
const p9b = pairOf(900, "2025-01-06", "bev"), p9i = pairOf(900, "2025-01-06", "ice");
const p90b = pairOf(90, "2025-01-06", "bev"), p90i = pairOf(90, "2025-01-06", "ice");
const tc = (r) => r.total_cost_reported;

// ---- 1. Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 1.7, w: 11.5, h: 1.9, fontSize: 32, bold: true, valign: "bottom" });
text(s, "最新の結果と、3本目の柱についてのご相談", { x: 0.9, y: 3.7, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "2026年11月\n東京都市大学 大学院 修士1年　劉 承洋", { x: 0.9, y: 4.6, w: 11.5, h: 1.0, fontSize: 17, color: SUB });

// ---- 2. Background: from the 2050 declaration down to route buses
s = page("研究背景　2050年カーボンニュートラルから路線バスへ");
const STORY = [
  ["2050年カーボンニュートラル", "日本は2020年10月、2050年に温室効果ガスの排出を実質ゼロにすると宣言した"],
  ["交通分野", "運輸部門は日本のCO₂排出量の19.3%を占め、その約86%を自動車が出している（2024年度、国土交通省）"],
  ["路線バス", "電気バスの導入が進んでいるが、一度にすべては置き換えられず、当面は燃料（軽油）バスと併用する"],
  ["営業所の課題", "電気バスは夜、営業所でまとめて充電する。多くの車両を同時に充電すると受電電力が大きくなり、設備の増強や電気料金の上昇につながる"]];
STORY.forEach(([h, b], i) => {
  const y = 1.6 + i * 1.22;
  box(s, 0.6, y, 12.1, 1.0, i === 3 ? "DCEBF7" : BLUE_PALE);
  text(s, h, { x: 0.8, y: y + 0.1, w: 3.2, h: 0.8, fontSize: 17, bold: true, color: BLUE_DARK, valign: "middle" });
  text(s, b, { x: 4.1, y: y + 0.1, w: 8.4, h: 0.8, fontSize: 16, valign: "middle" });
  if (i < STORY.length - 1) text(s, "▼", { x: 6.4, y: y + 0.98, w: 0.5, h: 0.25, fontSize: 12, color: GREY, align: "center" });
});
caption(s, "受電設備や電気料金の負担を抑え、今の時刻表どおりの運行を保ったまま、電動化でCO₂を減らすことを目指す", 0.6, 6.5, 12.1);

// ---- 3. Objective
s = page("研究目的と最適化の中身");
text(s, "燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を数理最適化で決め、受電電力の上限が電気バスの担当便・費用・CO₂に与える影響を明らかにする。",
  { x: 0.6, y: 1.65, w: 12.1, h: 1.1, fontSize: 18 });
heading(s, "最適化で決めるもの", 2.95);
bullets(s, ["各便を担当する車両（電気バス・燃料バス）", "各電気バスの充電の時刻と量（15分刻み）"], { x: 0.6, y: 3.4, w: 12.1, h: 0.9, fontSize: 17, paraSpaceAfter: 4 });
heading(s, "条件と目的", 4.45);
text(s, "時刻表の全便を運行し、電池残量・充電器10基・受電上限の制約のもとで、1週間の費用（車両使用費・電気代・燃料代・受電上限の超過分の費用）とCO₂の費用の和を最小にする。CO₂の費用は計画を立てるときの重みとしてだけ使い、費用の集計には含めない。",
  { x: 0.6, y: 4.9, w: 12.1, h: 1.4, fontSize: 16 });

// ---- 4. Conditions
s = page("対象と計算条件");
s.addTable([
  [B("対象"), "東急バス 渋21〜23系統（弦巻営業所）、1週間 1,704便"],
  [B("車両・設備"), "電気バス35台・燃料バス25台、充電器 90 kW × 10基、太陽光 1,000 kW、蓄電池 6,000 kWh（設備は設置を仮定）"],
  [B("対象期間"), "2025年の冬（1/6〜）・春（4/7〜）・夏（7/7〜）の各1週間、実際の日射"],
  [B("受電上限"), "90／200／400／900 kWの4段階（× 3季節 ＝ 12ケース）。超過した電力量には500円/kWhの費用（仮）"],
  [B("単価"), "電気 17.43円/kWh＋基本料金（比較として30円/kWh込みでも計算）、軽油 150円/L、車両使用費 2万円/台・日"],
  [B("計算の打ち切り"), "最適性ギャップ5%（全ケース共通）、便割当3時間、毎時の立て直し300秒/回"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.2, 9.9], fontSize: 15, rowH: 0.7 }));
caption(s, "表1　計算条件。今回示す数値は旧版（30円/kWh込み）の結果で、この表の条件で全ケースを計算し直している", 0.6, 6.0, 12.1);

// ---- 5. Method
s = page("計算方法");
const FLOW = [["① 便割当", "1,704便を60台に割り当てる"], ["② 前日の計画", "割当を固定し、15分ごとの充電を決める"], ["③ 毎時の立て直し", "実際の日射で1時間ごとに計画し直す"], ["④ 集計", "実行した結果で費用・CO₂を数える"]];
FLOW.forEach(([h, b], i) => {
  const x = 0.6 + i * 3.1;
  box(s, x, 1.7, 2.75, 1.6);
  text(s, h, { x: x + 0.15, y: 1.8, w: 2.45, h: 0.45, fontSize: 16, bold: true, color: BLUE_DARK, align: "center" });
  text(s, b, { x: x + 0.15, y: 2.3, w: 2.45, h: 0.9, fontSize: 14, align: "center" });
  if (i < FLOW.length - 1) arrow(s, x + 2.78, 2.5, 0.28);
});
heading(s, "限られた計算時間で効率よく最適化する工夫", 3.65);
text(s, "便割当は問題が大きく、制限時間内に最適解かどうかを確かめられない。探索は最初の割当に近い解にとどまりやすいため、性質の異なる「電気バス優先」と「燃料バス優先」の2通りの割当から始め、総費用の安い方を採用する。",
  { x: 0.6, y: 4.1, w: 12.1, h: 1.4, fontSize: 16 });
caption(s, "求解にはGurobiを用いた。蓄電池は規則で充放電し、最適化していない", 0.6, 6.4, 12.1);

// ---- 6. Results: share and cost table
s = page("結果　受電上限が400 kW以上なら電気バスが9割超を担当");
s.addChart(pres.charts.BAR, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => (get(g, w) ? Math.round(get(g, w).bev_trip_share_pct * 10) / 10 : null)) })),
  chart({ x: 0.6, y: 1.45, w: 6.0, h: 3.9, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK, BLUE_LIGHT, GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスの担当便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
const cell = (g, w) => { const r = get(g, w); const ice = r && r.selected_start === "ice";
  return { text: r ? `${man(tc(r))}${ice ? "＊" : ""}` : "—", options: { align: "center", bold: ice, color: ice ? BLUE_DARK : INK } }; };
s.addTable([[H("受電上限"), ...SEASONS.map(([, n]) => H(n))], ...LIMITS.map((g) => [{ text: `${g} kW`, options: { bold: true, align: "center" } }, ...SEASONS.map(([w]) => cell(g, w))])],
  tableOpts({ x: 7.0, y: 1.7, w: 5.7, colW: [1.8, 1.3, 1.3, 1.3], fontSize: 16, rowH: 0.62 }));
caption(s, "図1　電気バスが担当した便の割合（全1,704便）", 0.6, 5.4, 6.0, 0.35);
caption(s, "表2　1週間の総費用［万円］（車両使用費・電気代・燃料代・超過費用。CO₂の費用は含めない）。＊は燃料バスを多く使う解", 7.0, 4.95, 5.7, 0.7);
bullets(s, [
  `受電上限が400 kW以上なら、電気バスが便の${rngTxt(bevWins.map((r) => r.bev_trip_share_pct), 1)}%を担当し、総費用も小さかった`,
  `上限の低い${iceWins.map(lab).join("・")}では燃料バスを多く使う解の方が安く、電気バスの担当便は${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}%にとどまった`],
  { x: 0.6, y: 5.85, w: 12.1, h: 0.9, fontSize: 15, paraSpaceAfter: 4 });

// ---- 7. Results: two solutions compared
s = page("結果　電気バスを多く使うとCO₂は半分以下に。費用は受電上限しだい");
const COLS = [["900 kW冬", p9b, "電気バス優先"], ["900 kW冬", p9i, "燃料バス優先"], ["90 kW冬", p90b, "電気バス優先"], ["90 kW冬", p90i, "燃料バス優先"]];
const adopted = [tc(p9b) <= tc(p9i), tc(p9i) < tc(p9b), tc(p90b) <= tc(p90i), tc(p90i) < tc(p90b)];
const c3 = (t, i) => ({ text: t, options: { align: "center", bold: adopted[i], color: adopted[i] ? BLUE_DARK : INK } });
const row3 = (label, f) => [B(label), ...COLS.map(([, r], i) => c3(f(r), i))];
s.addTable([[H("受電上限・季節"), ...COLS.map(([n]) => H(n))], [B("初期割当"), ...COLS.map(([, , n], i) => c3(n, i))],
  row3("総費用", (r) => `${man(tc(r))}万円`), row3("電気バス担当便", (r) => `${r.bev_trip_share_pct.toFixed(1)}%`),
  row3("CO₂", (r) => `${fmt(r.total_co2_kg)} kg`), row3("上限の超過", (r) => `${fmt(r.contract_over_limit_kwh)} kWh`)],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.5, 2.4, 2.4, 2.4, 2.4], fontSize: 15, rowH: 0.55 }));
caption(s, "表3　2通りの初期割当から最適化して得た解（1週間）。青字が採用した方", 0.6, 4.95, 12.1);
bullets(s, [
  `900 kW冬では、電気バスを多く使う解が${man(tc(p9i) - tc(p9b))}万円安く、CO₂は${Math.round((1 - p9b.total_co2_kg / p9i.total_co2_kg) * 100)}%少ない`,
  `90 kW冬では燃料バスを多く使う解が約${Math.round((tc(p90b) - tc(p90i)) / 1e4)}万円安いが、CO₂は約${(p90i.total_co2_kg / p90b.total_co2_kg).toFixed(1)}倍になる`],
  { x: 0.6, y: 5.4, w: 12.1, h: 1.0, fontSize: 15, paraSpaceAfter: 4 });

// ---- 8. Discussion and caveats
s = page("考察と、結果の扱い");
bullets(s, [
  "受電上限に余裕があれば、電動化は費用もCO₂も下げる。上限が低いと、費用とCO₂のどちらを重く見るかで望ましい運用が変わる",
  `上限の超過は、曇りの日の翌未明、蓄電池が空の時間に集中した（90 kW冬・電気バスを多く使う解で${fmt(p90b.contract_over_limit_kwh)} kWh/週）。前日の計画は太陽光を平年値で予測するため、曇りの日の不足を見込めない`,
  `数値はすべて診断用で、研究の結論にはまだ使わない。便割当は最適と確認できておらず、毎時の立て直しは最大${maxTimeouts}回（1週間174〜175回中）が時間切れ。表1の条件で全ケースを計算し直している`,
  "超過の費用（500円/kWh）と電力のCO₂排出係数（0.5 kg/kWh）は仮の値で、今後感度を調べる"],
  { x: 0.6, y: 1.65, w: 12.1, h: 5.2, fontSize: 16, paraSpaceAfter: 12 });

// ---- 9. Structure and road map
s = page("研究の構成と今後の予定");
s.addTable([
  [H("柱"), H("内容"), H("状況")],
  [B("A"), "受電上限と、電気バスが担当できる便・費用・CO₂の関係", "11/28の中間発表で報告。条件をそろえて再計算中"],
  [B("B"), "1日ごとに計画する場合と、日をまたいで計画する場合の比較（翌朝の電池不足、燃料バスへの振替、夜の買電）", "設計済み。中間発表後に計算"],
  [B("C"), "未定（本日ご相談したい点）", "―"]],
  tableOpts({ x: 0.6, y: 1.5, w: 12.1, colW: [0.8, 7.3, 4.0], fontSize: 14, rowH: 0.7 }));
const ROAD = [["2027年3月", "電気学会全国大会", "柱Aの内容"], ["2027年度", "学会発表（数回）", "柱B、蓄電池の最適化、単価の感度"],
  ["2027年11月", "中間発表", "日ごとの計画と比べた効果"], ["2028年2月", "修士最終発表", "受電上限・設備の決め方の指針、柱C"]];
ROAD.forEach(([when, where, what], i) => {
  const x = 0.6 + i * 3.1;
  box(s, x, 4.65, 2.8, 1.55, i === 3 ? "DCEBF7" : BLUE_PALE);
  text(s, [{ text: when, options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: where, options: { bold: true, breakLine: true } }, { text: what, options: { fontSize: 12, color: SUB } }],
    { x: x + 0.1, y: 4.72, w: 2.6, h: 1.4, fontSize: 14, align: "center" });
  if (i < ROAD.length - 1) arrow(s, x + 2.82, 5.42, 0.26);
});
caption(s, "図2　修士最終発表までの予定（予定する成果であり、まだ結果ではない）", 0.6, 6.3, 12.1);

// ---- 10. Candidates for pillar C
s = page("3本目の柱の候補　運行と利用者の視点を取り入れたい");
const CANDS = [
  ["運転士の勤務と充電", "充電の待機や車両の入れ替えが、運転士の拘束時間・休憩（2024年の労働時間規制の見直し）と両立するか。運転士不足の中で、電動化が勤務に与える負担"],
  ["利用者とユニバーサルデザイン", "混雑する便、高齢者・車いす利用の多い便に低床の電気バスを優先したときの、費用・充電への影響"],
  ["災害時の移動電源", "災害時に電気バスを避難所などへの給電に回したとき、翌日の運行と両立できる台数・電力量"],
  ["ダイヤ・路線の見直しと電動化", "減便や路線の再編をしたとき、電気バスで担える便・受電電力・費用・CO₂がどう変わるか"],
  ["事業者・利用者の受け止め", "最適化が示す運用（便ごとの車両の入れ替え、充電のための待機）を、事業者・利用者がどう評価するか（ヒアリング・アンケート）"],
  ["CO₂の見える化", "電気バスが担当する便を利用者に示すと、利用や評価が変わるか"]];
s.addTable([[H("候補"), H("問い")], ...CANDS.map(([t, d]) => [B(t), d])],
  tableOpts({ x: 0.6, y: 1.5, w: 12.1, colW: [3.2, 8.9], fontSize: 13, rowH: 0.64 }));
caption(s, "表4　3本目の柱の候補（10月の候補を見直し、運転士と利用者の視点を加えた）", 0.6, 6.55, 12.1);

// ---- 11. Questions
s = page("ご意見をいただきたい点");
text(s, [
  { text: "1. 公共交通・ユニバーサルデザインのご専門から見て、上の候補のうち意義がある、面白いと思われるものはどれか。ほかに入れるべき視点はあるか", options: { breakLine: true } },
  { text: "2. 利用者へのサービスの質や運転士の負担を、どのような指標・データで評価するのがよいか", options: { breakLine: true } },
  { text: "3. 事業者へのヒアリングや利用者調査で、計算結果を補う方法はあるか", options: { breakLine: true } },
  { text: "4. 2027年度の学会発表で、電気学会のほかに交通・都市計画の分野の学会にも出すべきか。出すならどこがよいか" }],
  { x: 0.6, y: 1.7, w: 12.1, h: 4.5, fontSize: 18, paraSpaceAfter: 16 });

// ---- 12. Glossary
s = page("補足　用語");
s.addTable([
  [B("便"), "バスが始発から終点まで1回運行すること"],
  [B("営業所"), "バスの車庫。電気バスはここで充電する"],
  [B("受電電力・受電上限"), "営業所が電力会社から受け取る電力（kW）と、その目安。超過した電力量には費用を課す"],
  [B("kW と kWh"), "kWはある時点の電力の大きさ、kWhは使用した電力量（kW × 時間）"],
  [B("基本料金"), "契約した電力の大きさに応じて毎月かかる電気料金。使った電力量に応じた料金とは別"],
  [B("数理最適化"), "制約と費用を数式で表し、費用が最小となる計画を計算機で求める方法"],
  [B("初期割当"), "最適化を始めるときに与える仮の便割当。ここから少しずつ良い割当を探す"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.6, 9.5], fontSize: 15, rowH: 0.62 }));

(async () => {
  const out = path.join(__dirname, process.env.DECK_OUT || "西山先生へのご相談_最新結果と3本目の柱.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  const JSZip = require(path.join(process.env.DECK_NODE_MODULES, "jszip"));
  const zip = await JSZip.loadAsync(fs.readFileSync(out));
  const themePath = Object.keys(zip.files).find((f) => /^ppt\/theme\/theme\d+\.xml$/.test(f));
  const xml = (await zip.file(themePath).async("string")).replace(/<a:ea typeface="[^"]*"\/>/g, `<a:ea typeface="${THEME.bodyFontFace}"/>`);
  zip.file(themePath, xml);
  fs.writeFileSync(out, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  console.log("wrote", out);
})();
