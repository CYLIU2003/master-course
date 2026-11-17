// Consultation deck for Prof. Nishiyama, 2026-11 (purpose first, latest pillar-A results, link to his research,
// pillar-C directions, questions, thanks; technical details in the appendix).
// Revised 2026-11-16 after a Gemini review: polite wording, consultation purpose up front, pillar-C candidates
// re-ordered by their link to his published work (mobility, universal design, electric full-flat bus, co-creation).
// Data: the verified cases used by the midterm poster (DIAGNOSTIC, earlier versions, 30 JPY/kWh series); totals exclude the CO2 cost.
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
const co2Ratio = (p90i.total_co2_kg / p90b.total_co2_kg).toFixed(1);
const PROVISIONAL = "数値は条件をそろえる前の暫定値で、研究の結論には使っていません（現在、全ケースを同じ条件で計算し直しています）";

// ---- 1. Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "西山 敏樹 先生　ご相談資料", { x: 0.9, y: 1.2, w: 11.5, h: 0.5, fontSize: 18, color: SUB });
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 1.8, w: 11.5, h: 1.8, fontSize: 32, bold: true, valign: "bottom" });
text(s, "研究の進捗のご報告と、3本目の柱についてのご相談", { x: 0.9, y: 3.7, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "2026年11月\n東京都市大学 大学院 修士1年　劉 承洋", { x: 0.9, y: 4.6, w: 11.5, h: 1.0, fontSize: 17, color: SUB });

// ---- 2. Purpose of today's consultation
s = page("本日のご相談の内容");
box(s, 0.6, 1.6, 12.1, 1.5, "DCEBF7");
text(s, [{ text: "本日お伺いしたいこと", options: { bold: true, color: BLUE_DARK, breakLine: true } },
  { text: "これまで電力と費用の面から研究を進めてまいりました。3本目の柱（柱C）では、利用者や地域にとっての価値という視点を取り入れたいと考えております。その方向性について、ご助言を賜れますと幸いです。", options: { fontSize: 16 } }],
  { x: 0.85, y: 1.72, w: 11.6, h: 1.3, fontSize: 17 });
heading(s, "本日の流れ", 3.45);
const AGENDA = [["1", "研究の概要と最新の結果", "約5分（スライド3〜6）"], ["2", "先生のご研究から学ばせていただきたいこと", "スライド7"], ["3", "3本目の柱の方向性（案）", "スライド8"], ["4", "ご助言を賜りたい点", "スライド9"]];
AGENDA.forEach(([n, t, d], i) => {
  const y = 3.95 + i * 0.68;
  s.addShape(pres.shapes.OVAL, { x: 0.7, y: y + 0.04, w: 0.42, h: 0.42, fill: { color: BLUE }, line: { color: BLUE } });
  text(s, n, { x: 0.7, y: y + 0.04, w: 0.42, h: 0.42, fontSize: 15, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  text(s, t, { x: 1.35, y, w: 7.4, h: 0.5, fontSize: 17, valign: "middle" });
  text(s, d, { x: 8.9, y, w: 3.8, h: 0.5, fontSize: 14, color: SUB, valign: "middle", align: "right" });
});
caption(s, "計算条件などの詳しい内容は、末尾の補足スライドにまとめております", 0.6, 6.6, 12.1);

// ---- 3. Background: from the 2050 declaration down to route buses
s = page("研究背景　2050年カーボンニュートラルから路線バスへ");
const STORY = [
  ["2050年カーボンニュートラル", "日本は2020年10月、2050年に温室効果ガスの排出を実質ゼロにすると宣言した"],
  ["交通分野", "運輸部門は日本のCO₂排出量の19.3%を占め、その約86%を自動車が出している（2024年度、国土交通省）"],
  ["路線バス", "電気バスの導入が進んでいるが、一度にすべては置き換えられず、当面は燃料（軽油）バスと併用する"],
  ["営業所の課題", "電気バスは夜、営業所でまとめて充電する。多くの車両を同時に充電すると、営業所が受け取る電力（受電電力）が大きくなり、設備の増強や電気料金の上昇につながる"]];
STORY.forEach(([h, b], i) => {
  const y = 1.6 + i * 1.22;
  box(s, 0.6, y, 12.1, 1.0, i === 3 ? "DCEBF7" : BLUE_PALE);
  text(s, h, { x: 0.8, y: y + 0.1, w: 3.2, h: 0.8, fontSize: 17, bold: true, color: BLUE_DARK, valign: "middle" });
  text(s, b, { x: 4.1, y: y + 0.1, w: 8.4, h: 0.8, fontSize: 16, valign: "middle" });
  if (i < STORY.length - 1) text(s, "▼", { x: 6.4, y: y + 0.98, w: 0.5, h: 0.25, fontSize: 12, color: GREY, align: "center" });
});
caption(s, "受電設備や電気料金の負担を抑え、今の時刻表どおりの運行を保ったまま、電動化でCO₂を減らすことを目指す", 0.6, 6.5, 12.1);

// ---- 4. Objective and target (route map = poster Fig. 2, added 2026-11-17 at the user's request)
s = page("研究目的と対象");
text(s, "燃料バスと電気バスを併用する営業所を対象に、どの便をどのバスが担当するか（便割当）と、電気バスをいつ充電するか（充電計画）を数理最適化で決め、営業所の受電電力の上限によって、電気バスが担当できる便・費用・CO₂がどう変わるかを調べる。",
  { x: 0.6, y: 1.55, w: 12.1, h: 1.1, fontSize: 16 });
s.addTable([
  [B("対象"), "東急バス 渋21〜23系統（弦巻営業所）、1週間 1,704便。時刻表の便はすべて運行する"],
  [B("車両・設備"), "電気バス35台・燃料バス25台、充電器10基、太陽光発電・蓄電池（設備は設置を仮定）"],
  [B("比べる条件"), "受電上限 90／200／400／900 kW（契約で受け取れる電力の目安）× 冬・春・夏の各1週間 ＝ 12ケース"],
  [B("見るもの"), "電気バスが担当した便の割合、1週間の総費用、CO₂排出量"]],
  tableOpts({ x: 0.6, y: 2.8, w: 6.9, colW: [1.5, 5.4], fontSize: 13, rowH: 0.78 }));
const MAPW = 5.0, MAPH = MAPW * 1409 / 2700;
s.addImage({ path: path.join(__dirname, "..", "2026-11-28_midterm_poster", "route_map_ja_poster.png"), x: 7.7, y: 2.8, w: MAPW, h: MAPH,
  altText: "渋21・渋22・渋23の路線図と弦巻営業所の位置" });
caption(s, "対象路線と弦巻営業所（停留所の位置は公共交通オープンデータ（ODPT）、停留所の間は直線。背景は © OpenStreetMap contributors）", 7.7, 2.8 + MAPH + 0.08, MAPW, 0.6);
caption(s, "受電上限を超えた電力量には費用（仮の値）を課しています。詳しい条件は補足スライドA1をご覧ください", 0.6, 6.45, 12.1);

// ---- 4b. Method (poster Fig. 1 and the objective, added 2026-11-17 at the user's request)
s = page("手法　便割当と充電計画を、1週間の総費用が最小になるよう決める");
text(s, [{ text: "最適化するもの　", options: { bold: true, color: BLUE_DARK } },
  { text: "(a) 各便を電気バス・燃料バスのどの車両が担当するか、(b) 各電気バスをいつ・何kWで充電するか。時刻表の便はすべて運行する。" }],
  { x: 0.6, y: 1.5, w: 12.1, h: 0.65, fontSize: 15 });
text(s, [{ text: "目的関数　", options: { bold: true, color: BLUE_DARK } }, { text: "1週間の総費用を最小にする" }], { x: 0.6, y: 2.15, w: 12.1, h: 0.4, fontSize: 15 });
const EQW = 7.6, EQH = EQW * 0.763 / 7.273;
s.addImage({ path: path.join(__dirname, "..", "2026-11-12_three_party", "eq", "objective.png"), x: 0.9, y: 2.55, w: EQW, h: EQH,
  altText: "目的関数：車両使用費、電気代と上限超過の費用、燃料代、CO2の費用の和を最小化" });
caption(s, "左から車両使用費（u：車両kを日dに使うか）、電気代と超過費用（g：時刻tの買電量、s：超過量）、燃料代（f：便jの軽油）、CO₂の費用（Q：排出量）。c・p・πは単価。CO₂の費用は計算の中だけで用い、示す総費用には含めない。主な制約：便の接続（到着＋折返し＋回送 ≦ 次の発車）、電池残量、充電器10基、受電上限（超過分は費用）",
  0.6, 2.55 + EQH + 0.05, 12.1, 0.7);
const STEPS = [
  ["① 便割当", ["1,704便を60台に割り当てる", "整数計画と、割当を部分的に組み直す探索"]],
  ["② 前日の計画", ["割当を固定し、15分ごとの充電を決める", "太陽光は平年値で予測"]],
  ["③ 毎時の立て直し", ["実際の日射で1時間ごとに計画し直す", "最終日の翌朝まで174〜175回"]],
  ["④ 集計", ["実行した結果で費用とCO₂を数える", "2通りの初期割当の安い方を採用"]]];
const FY = 4.3, FH = 1.95, FGAP = 0.3, FBW = (12.1 - FGAP * 3) / 4;
STEPS.forEach(([hd, body], i) => {
  const bx = 0.6 + i * (FBW + FGAP);
  s.addShape(pres.shapes.RECTANGLE, { x: bx, y: FY, w: FBW, h: FH, fill: { color: "F4F7FA" }, line: { color: BLUE, width: 1.25 } });
  s.addShape(pres.shapes.RECTANGLE, { x: bx, y: FY, w: FBW, h: 0.5, fill: { color: i === 3 ? BLUE_DARK : BLUE }, line: { color: BLUE, width: 1.25 } });
  text(s, hd, { x: bx + 0.05, y: FY, w: FBW - 0.1, h: 0.5, fontSize: 15, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  bullets(s, body, { x: bx + 0.12, y: FY + 0.6, w: FBW - 0.22, h: FH - 0.7, fontSize: 13, paraSpaceAfter: 4, lineSpacingMultiple: 1.1 });
  if (i < 3) s.addShape(pres.shapes.ISOSCELES_TRIANGLE, { x: bx + FBW + 0.06, y: FY + FH / 2 - 0.12, w: 0.18, h: 0.24, rotate: 90, fill: { color: BLUE }, line: { color: BLUE } });
});
caption(s, "計算の流れ（ソルバーはGurobi）。蓄電池は決めた規則で充放電し、最適化していない。2通りの初期割当の理由と比較は補足A2", 0.6, FY + FH + 0.1, 12.1);

// ---- 5. Results: share and cost table
s = page("結果　受電上限が400 kW以上なら電気バスが9割超を担当");
s.addChart(pres.charts.BAR, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => (get(g, w) ? Math.round(get(g, w).bev_trip_share_pct * 10) / 10 : null)) })),
  chart({ x: 0.6, y: 1.45, w: 6.0, h: 3.9, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK, BLUE_LIGHT, GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスの担当便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
const cell = (g, w) => { const r = get(g, w); const ice = r && r.selected_start === "ice";
  return { text: r ? `${man(tc(r))}${ice ? "＊" : ""}` : "—", options: { align: "center", bold: ice, color: ice ? BLUE_DARK : INK } }; };
s.addTable([[H("受電上限"), ...SEASONS.map(([, n]) => H(n))], ...LIMITS.map((g) => [{ text: `${g} kW`, options: { bold: true, align: "center" } }, ...SEASONS.map(([w]) => cell(g, w))])],
  tableOpts({ x: 7.0, y: 1.7, w: 5.7, colW: [1.8, 1.3, 1.3, 1.3], fontSize: 16, rowH: 0.62 }));
caption(s, "図1　電気バスが担当した便の割合（全1,704便）", 0.6, 5.3, 6.0, 0.35);
caption(s, "表1　1週間の総費用［万円］（車両・電気・燃料・上限超過の費用）。＊は燃料バスを多く使う解", 7.0, 4.95, 5.7, 0.7);
bullets(s, [
  `受電上限が400 kW以上なら、電気バスが便の${rngTxt(bevWins.map((r) => r.bev_trip_share_pct), 1)}%を担当し、総費用も小さかった`,
  `上限の低い${iceWins.map(lab).join("・")}（＊）では燃料バスを多く使う解が安く、電気バスの担当便は${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}%。90 kW冬では、電気バスを多く使う解に比べCO₂が約${co2Ratio}倍（補足A2）`],
  { x: 0.6, y: 5.65, w: 12.1, h: 0.95, fontSize: 14, paraSpaceAfter: 2 });
caption(s, PROVISIONAL, 0.6, 6.68, 12.1, 0.3);

// ---- 6. Bridge to pillar C, and the road map
s = page("結果から見えてきたことと、今後の予定");
box(s, 0.6, 1.55, 12.1, 1.75, BLUE_PALE);
text(s, [
  { text: "受電上限が低い営業所では、電気バスに任せられる便が限られ、費用とCO₂のどちらを重く見るかで望ましい運用が変わります。", options: { breakLine: true } },
  { text: "そのとき「限られた電気バスを、どの便に、どのように使うのが、利用者や地域にとって望ましいか」は、電力と費用の計算だけでは決められないと考えるようになりました。", options: { bold: true, color: BLUE_DARK } }],
  { x: 0.85, y: 1.7, w: 11.6, h: 1.5, fontSize: 16, paraSpaceAfter: 6 });
s.addTable([
  [H("柱"), H("内容"), H("状況")],
  [B("A"), "受電上限と、電気バスが担当できる便・費用・CO₂の関係", "11/28の修士1年中間発表で報告。再計算中"],
  [B("B"), "1日ずつ計画する場合と、数日まとめて計画する場合の比較", "中間発表後に計算"],
  [B("C"), "利用者・地域の視点（本日ご相談したい点）", "検討中"]],
  tableOpts({ x: 0.6, y: 3.5, w: 12.1, colW: [0.8, 7.6, 3.7], fontSize: 14, rowH: 0.45 }));
const ROAD = [["2027年3月", "電気学会全国大会", "柱A"], ["2027年度", "学会発表（数回）", "柱B・蓄電池の最適化"], ["2027年11月", "修士2年中間発表", "柱Bの成果"], ["2028年2月", "修士最終発表", "設備の決め方の指針・柱C"]];
ROAD.forEach(([when, where, what], i) => {
  const x = 0.6 + i * 3.1;
  box(s, x, 5.55, 2.8, 1.05, i === 3 ? "DCEBF7" : BLUE_PALE);
  text(s, [{ text: `${when}　${where}`, options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: what, options: { fontSize: 12, color: SUB } }],
    { x: x + 0.1, y: 5.62, w: 2.6, h: 0.9, fontSize: 13, align: "center", valign: "middle" });
  if (i < ROAD.length - 1) arrow(s, x + 2.82, 6.07, 0.26);
});

// ---- 7. What I hope to learn from Prof. Nishiyama's work
s = page("先生のご研究から学ばせていただきたいこと");
text(s, "先生のご研究について、公開されている論文・講義紹介を拝見した範囲で整理いたしました。誤りがございましたら、ご指摘いただけますと幸いです。",
  { x: 0.6, y: 1.5, w: 12.1, h: 0.6, fontSize: 14, color: SUB });
const WORKS = [
  ["乗り物の開発と普及", "ユニバーサルデザインと環境に配慮した段差のない電動フルフラットバスの試作と、その普及の研究。バス事業者への実態調査と利用者へのアンケートから、普及の形を整理 [1]"],
  ["地域との共創", "地域の方々と対話しながら、新しい移動のサービスを一緒につくる取り組み [2]"],
  ["乗り物・営業所を地域に活かす", "使われなくなった乗り物や営業所の空きスペースを、地域の居場所や移動販売に活かし、住民の困りごとと事業者の経営を一緒に考える取り組み [2]"]];
WORKS.forEach(([h, b], i) => {
  const x = 0.6 + i * 4.1;
  box(s, x, 2.25, 3.9, 2.35);
  text(s, h, { x: x + 0.2, y: 2.35, w: 3.5, h: 0.45, fontSize: 16, bold: true, color: BLUE_DARK });
  text(s, b, { x: x + 0.2, y: 2.85, w: 3.5, h: 1.7, fontSize: 14 });
});
box(s, 0.6, 4.8, 12.1, 1.35, "DCEBF7");
text(s, [{ text: "本研究との接点", options: { bold: true, color: BLUE_DARK, breakLine: true } },
  { text: "本研究は電気バスの使い方を電力と費用の面から計算してまいりましたが、利用者や地域にとっての価値を評価する視点がまだ十分ではありません。この点について、ご指導を賜りたく存じます。", options: { fontSize: 15 } }],
  { x: 0.85, y: 4.9, w: 11.6, h: 1.2, fontSize: 16 });
caption(s, "[1] T. Nishiyama, Int. J. Critical Infrastructures, Vol. 11, No. 2, pp. 136–147, 2015（電動フルフラットバスの試作と普及戦略）\n[2] 夢ナビ講義「走るスーパー・動く居場所　乗り物が変える地域の未来」（東京都市大学 都市生活学部）",
  0.6, 6.3, 12.1, 0.6);

// ---- 8. Directions for pillar C
s = page("3本目の柱の方向性（案）");
const DIRS = [
  ["① 運行していない電気バスと営業所を地域に活かす",
    "日中など運行していない時間の電気バスや、営業所の空きスペース・太陽光の電気を、地域の居場所や移動販売に使うとき、運行と両立できる台数・時間帯・電力量はどれくらいか（災害時の電源としての活用は、その応用として検討）",
    "運行しない時間に「地域で使う」状態と電力を加え、次の運行に必要な電池の残量を守る条件を入れる"],
  ["② ユニバーサルデザインの視点で車両を割り当てる",
    `受電上限が低いと、電気バスが担当できる便は${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}%に限られる。乗り降りしやすい電気バス（例：フルフラット車）を一部に導入すると仮定し、限られた電気バスを高齢の方や車いす利用の多い便などに優先すると、費用・CO₂はどう変わるか`,
    "便ごとに「優先したい度合い」を与え、その便を電気バスが担当する割合を条件や評価に加える"],
  ["③ 現場や利用者の声から計画の条件を決める",
    "事業者へのヒアリングや利用者調査で、受け入れられる運用（車両の入れ替えの回数、運転士の休憩と充電の両立など）を先に調べ、それを計画の条件にする",
    "調べた条件を入れた計画と入れない計画を比べ、費用や電気バスの担当便の差を示す"]];
DIRS.forEach(([h, q, m], i) => {
  const y = 1.5 + i * 1.62;
  box(s, 0.6, y, 12.1, 1.5);
  text(s, h, { x: 0.8, y: y + 0.1, w: 11.7, h: 0.4, fontSize: 16, bold: true, color: BLUE_DARK });
  text(s, [{ text: "問い：", options: { bold: true } }, { text: q, options: { breakLine: true } }, { text: "計算への入れ方：", options: { bold: true, color: SUB } }, { text: m, options: { color: SUB } }],
    { x: 0.8, y: y + 0.52, w: 11.7, h: 0.95, fontSize: 13, paraSpaceAfter: 2 });
});
caption(s, "参考：ダイヤや車両の大きさの見直しは、時刻表を固定するという今の前提を外すため、将来の課題と考えております。②では、燃料バスとの違い（段差・静かさ・揺れなど）をどう定めるかもご相談したい点です",
  0.6, 6.4, 12.1, 0.55);

// ---- 9. Questions
s = page("ご助言を賜りたい点");
box(s, 0.6, 1.55, 3.6, 3.3, BLUE_PALE);
text(s, [{ text: "柱Cの方向性（案）", options: { bold: true, color: BLUE_DARK, breakLine: true } },
  { text: "① 運行していない電気バスと営業所を地域に活かす", options: { breakLine: true } },
  { text: "② ユニバーサルデザインの視点で車両を割り当てる", options: { breakLine: true } },
  { text: "③ 現場や利用者の声から計画の条件を決める" }],
  { x: 0.8, y: 1.7, w: 3.25, h: 3.0, fontSize: 14, paraSpaceAfter: 12 });
text(s, [
  { text: "1. 左の3つの方向性のうち、利用者や地域にとって取り組む意義が大きいと思われるものはどれでしょうか。また、私が見落としている視点がございましたら、ご教示いただけますと幸いです。", options: { breakLine: true } },
  { text: "2. 利用者の移動のしやすさや、事業者・地域の受け止めを研究に取り入れる際、数値の指標と、アンケートや対話などの調査を、どのように組み合わせるのがよいでしょうか。", options: { breakLine: true } },
  { text: "3. 修士の残りの期間で取り組める調査として、どの程度の範囲が現実的でしょうか。先生のこれまでの調査のご知見から、活かせる点がございましたらご教示いただけますと幸いです。" }],
  { x: 4.5, y: 1.6, w: 8.2, h: 4.3, fontSize: 16, paraSpaceAfter: 14 });
caption(s, "お時間が許せば：交通やまちづくりの分野の方々にも意義を認めていただける研究にするには、どのような点が求められるでしょうか", 4.5, 6.2, 8.2, 0.6);

// ---- 10. Thanks
s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "本日はお時間をいただき、ありがとうございました", { x: 0.9, y: 2.3, w: 11.5, h: 0.9, fontSize: 30, bold: true, align: "center" });
s.addShape(pres.shapes.LINE, { x: 3.4, y: 3.4, w: 6.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "いただいたご助言は、柱Cの計画にまとめ、改めてご報告いたします。\n今後ともご指導のほど、よろしくお願い申し上げます。", { x: 0.9, y: 3.7, w: 11.5, h: 1.2, fontSize: 18, color: SUB, align: "center" });

// ---- A1. Conditions (appendix)
s = page("補足A1　計算条件");
s.addTable([
  [B("対象"), "東急バス 渋21〜23系統（弦巻営業所）、1週間 1,704便"],
  [B("車両・設備"), "電気バス35台・燃料バス25台、充電器 90 kW × 10基、太陽光 1,000 kW、蓄電池 6,000 kWh（設備は設置を仮定）"],
  [B("対象期間"), "2025年の冬（1/6〜）・春（4/7〜）・夏（7/7〜）の各1週間、実際の日射"],
  [B("受電上限"), "90／200／400／900 kWの4段階（× 3季節 ＝ 12ケース）。超過した電力量には500円/kWhの費用（仮の値）"],
  [B("単価"), "電気 17.43円/kWh＋基本料金（比較として30円/kWh込みでも計算）、軽油 150円/L、車両使用費 2万円/台・日"],
  [B("CO₂"), "計画を立てるときにはCO₂の排出も抑えるよう考慮しているが、総費用（実際にかかるお金）には含めず、CO₂は kg で別に示す"],
  [B("計算の打ち切り"), "最適性ギャップ5%（全ケース共通）、便割当3時間、毎時の立て直し300秒/回"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.2, 9.9], fontSize: 14, rowH: 0.65 }));
caption(s, "今回お示しした数値は旧版の計算（30円/kWh込み）の結果で、この表の条件で全ケースを計算し直しています", 0.6, 6.3, 12.1);

// ---- A2. Why two initial assignments, the two solutions compared, and caveats (appendix)
s = page("補足A2　2通りの初期割当と、結果の扱い");
text(s, "便割当は問題が大きく、制限時間内に最適と確かめられない。探索は最初の割当に近い解にとどまりやすいため、性質の異なる「電気バス優先」と「燃料バス優先」の2通りの初期割当から始め、総費用の安い方を採用した。", { x: 0.6, y: 1.5, w: 12.1, h: 0.65, fontSize: 13 });
const COLS = [["900 kW冬", p9b, "電気バス優先"], ["900 kW冬", p9i, "燃料バス優先"], ["90 kW冬", p90b, "電気バス優先"], ["90 kW冬", p90i, "燃料バス優先"]];
const adopted = [tc(p9b) <= tc(p9i), tc(p9i) < tc(p9b), tc(p90b) <= tc(p90i), tc(p90i) < tc(p90b)];
const c3 = (t, i) => ({ text: t, options: { align: "center", bold: adopted[i], color: adopted[i] ? BLUE_DARK : INK } });
const row3 = (label, f) => [B(label), ...COLS.map(([, r], i) => c3(f(r), i))];
s.addTable([[H("受電上限・季節"), ...COLS.map(([n]) => H(n))], [B("初期割当"), ...COLS.map(([, , n], i) => c3(n, i))],
  row3("総費用", (r) => `${man(tc(r))}万円`), row3("電気バス担当便", (r) => `${r.bev_trip_share_pct.toFixed(1)}%`),
  row3("CO₂", (r) => `${fmt(r.total_co2_kg)} kg`), row3("上限の超過", (r) => `${fmt(r.contract_over_limit_kwh)} kWh`)],
  tableOpts({ x: 0.6, y: 2.2, w: 12.1, colW: [2.5, 2.4, 2.4, 2.4, 2.4], fontSize: 13, rowH: 0.4 }));
caption(s, "表A2　2通りの初期割当から得た解（1週間）。青字が採用した方", 0.6, 4.65, 12.1, 0.35);
bullets(s, [
  `900 kW冬では、電気バスを多く使う解が${man(tc(p9i) - tc(p9b))}万円安く、CO₂は${Math.round((1 - p9b.total_co2_kg / p9i.total_co2_kg) * 100)}%少ない。90 kW冬では燃料バスを多く使う解が約${Math.round((tc(p90b) - tc(p90i)) / 1e4)}万円安いが、CO₂は約${co2Ratio}倍`,
  `上限の超過は、曇りの日の翌未明、蓄電池が空の時間に集中した（90 kW冬・電気バスを多く使う解で${fmt(p90b.contract_over_limit_kwh)} kWh/週）`,
  `数値は暫定値（診断用）で、研究の結論には使っていない。便割当は最適と確認できておらず、2段階で解くため全体の最適でもない。毎時の立て直しは最大${maxTimeouts}回（1週間174〜175回中）が時間切れ`,
  "超過の費用（500円/kWh）と電力のCO₂排出係数（0.5 kg/kWh）は仮の値で、今後感度を調べる"],
  { x: 0.6, y: 5.0, w: 12.1, h: 1.95, fontSize: 12, paraSpaceAfter: 3 });

// ---- A3. Glossary (appendix): power and optimization terms only
s = page("補足A3　用語（電力・最適化）");
s.addTable([
  [B("受電電力・受電上限"), "営業所が電力会社から受け取る電力（kW）と、その目安。本研究では、上限を超えた電力量に費用を課している"],
  [B("kW と kWh"), "kWはある時点の電力の大きさ、kWhは使用した電力量（kW × 時間）"],
  [B("基本料金"), "契約した電力の大きさに応じて毎月かかる電気料金。使った電力量に応じた料金とは別"],
  [B("数理最適化"), "条件と費用を数式で表し、費用が最小となる計画を計算機で求める方法"],
  [B("初期割当"), "最適化を始めるときに与える仮の便割当。ここから少しずつ良い割当を探す"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.8, 9.3], fontSize: 15, rowH: 0.75 }));

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
