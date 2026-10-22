// Lab progress report (2026-10-22): supervisor plus juniors from other topics.
// Scope agreed on 2026-10-21: pillar A (grid limit vs electric-bus trips) for the 11/28 midterm and
// pillar B (value of multi-day planning) by the end of 2026. Pillar C (basic charge) is not presented.
// Research-presentation structure: contents, numbered sections, numbered figures/tables with sources,
// formulation, results table, discussion, plan, references. White background, Tokyo City University
// blue (#0485D7) only for rules, headings and highlighted series.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const rc8 = JSON.parse(fs.readFileSync(path.join(__dirname, "cases_rc8.json"), "utf8"));
const iceHour = JSON.parse(fs.readFileSync(path.join(__dirname, "ice_by_hour_rc8.json"), "utf8"));
const eqSize = JSON.parse(fs.readFileSync(path.join(__dirname, "eq", "sizes.json"), "utf8"));
const dl = fs.readFileSync(path.join(__dirname, "all_diesel_estimate.csv"), "utf8").replace(/^﻿/, "").trim().split(/\r?\n/);
const dk = dl[0].split(","), diesel = dl.slice(1).map((l) => Object.fromEntries(l.split(",").map((v, i) => [dk[i], v])));
const LIMITS = [90, 200, 400, 800];
const SEASONS = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const WIN = "2025-01-06";
const get = (g, w) => rc8.find((r) => r.grid_limit_kw === g && r.week === w);
const byLimit = (g) => rc8.filter((r) => r.grid_limit_kw === g);
const avg = (g, k) => byLimit(g).reduce((a, r) => a + r[k], 0) / byLimit(g).length;
const fmt = (n) => Math.round(n).toLocaleString("ja-JP");

const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_LIGHT = "7AB8E8", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2";
const THEME = { name: "TCU white", headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "研究室進捗報告 2026-10-22";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 26, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } },
            { line: { x: 0.6, y: 7.0, w: 12.1, h: 0, line: { color: GRID, width: 0.75 } } },
            { text: { text: "研究室進捗報告　2026年10月22日　劉 承洋", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
  slideNumber: { x: 12.2, y: 7.05, w: 0.5, h: 0.3, fontSize: 10, color: SUB, align: "right" } });

const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 18, lineSpacingMultiple: 1.2, ...o });
const bullets = (s, items, o) => text(s, items.map((t, i) => ({ text: t, options: { bullet: { indent: 18 }, breakLine: i < items.length - 1 } })), { paraSpaceAfter: 8, ...o });
const chart = (o) => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 13, valAxisLabelFontSize: 12, valGridLine: { color: GRID, size: 0.75 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 13, legendColor: INK, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 12, dataLabelColor: INK,
  showLegend: true, legendPos: "t", chartColors: [GREY, BLUE], valAxisTitleColor: SUB, catAxisTitleColor: SUB, valAxisTitleFontSize: 12, catAxisTitleFontSize: 12, ...o });
const caption = (s, t, x, y, w, h = 0.4) => text(s, t, { x, y, w, h, fontSize: 12, color: SUB });
const page = (section, title) => {
  const s = pres.addSlide({ masterName: "PLAIN" });
  s.addText(title, { placeholder: "title" });
  text(s, section, { x: 8.7, y: 0.12, w: 4.0, h: 0.3, fontSize: 11, color: SUB, align: "right" });
  return s;
};
const tableOpts = (o) => ({ fontSize: 15, color: INK, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID }, ...o });
const H = (t, o = {}) => ({ text: t, options: { bold: true, fill: { color: HEAD }, align: "center", ...o } });
const B = (t) => ({ text: t, options: { bold: true } });
const heading = (s, t, y) => text(s, t, { x: 0.6, y, w: 12.1, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });
// One-line key message under the title rule (what the slide says).
const takeaway = (s, t) => {
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 1.45, w: 12.1, h: 0.62, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 1.45, w: 0.09, h: 0.62, fill: { color: BLUE }, line: { color: BLUE } });
  text(s, t, { x: 0.85, y: 1.45, w: 11.75, h: 0.62, fontSize: 18, bold: true, valign: "middle" });
};

const S0 = "前回からの進捗", S1 = "1. 研究背景と目的", S2 = "2. 研究の柱と進め方", S3 = "3. 問題設定と解法",
  S4 = "4. 結果：柱A 受電上限と電気バスの担当便", S5 = "5. 考察", S6 = "6. まとめと今後の予定";

// ---- Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 1.7, w: 11.5, h: 1.9, fontSize: 34, bold: true, valign: "bottom" });
text(s, "― 受電上限と電気バスに任せられる便の関係 ―", { x: 0.9, y: 3.7, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "研究室進捗報告　2026年10月22日\n東京都市大学　劉 承洋", { x: 0.9, y: 4.6, w: 11.5, h: 1.0, fontSize: 18, color: SUB });
s.addNotes("それでは、進捗報告を始めます。修士1年の劉です。題目は「GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化」です。今日は、前回の三者ミーティングで決めた計画に沿って、中間発表の主軸である柱Aの結果と、年末までに進める柱Bの計画をご報告します。研究テーマの違う方にも伝わるように、最初に用語の説明を入れています。");

// ---- Contents
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("目次", { placeholder: "title" });
text(s, [S1, S2, S3, S4, S5, S6].map((t, i) => ({ text: t, options: { breakLine: i < 5 } })), { x: 1.0, y: 1.7, w: 11, h: 3.8, fontSize: 21, paraSpaceAfter: 12 });
text(s, "今回の報告内容：中間発表（11月28日）の主軸とした柱Aの計算と集計が完了したため、その結果を報告する。あわせて、年末までに進める柱Bの計画を示す。",
  { x: 1.0, y: 5.6, w: 11.3, h: 0.8, fontSize: 16, color: SUB });
s.addNotes("本日の流れです。まず研究の背景と目的、それから研究を2つの柱に分けて進めていることをご説明します。次に計算の方法と条件を示し、柱Aの結果、考察、まとめと今後の予定の順にお話しします。");

// ---- Progress against the 2026-10-08 three-party meeting plan
s = page(S0, "前回の三者ミーティング（10月8日）で決めた計画と進捗");
const ST = (t, done) => ({ text: t, options: { bold: true, align: "center", color: done ? BLUE_DARK : SUB, fill: { color: done ? "DCEBF7" : "F2F2F2" } } });
s.addTable([
  [H("項目"), H("決めた内容"), H("状況"), H("補足")],
  [B("題目"), "GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化", ST("決定", true), "―"],
  [B("下準備1"), "燃料バスのCO₂係数を根拠付きで算出する", ST("完了", true), "軽油2.62 kg/L（環境省の算定制度）"],
  [B("下準備2"), "pvlibで傾斜30°の斜面日射を適用する", ST("完了", true), "計画と実行の両方に適用"],
  [B("柱A（中間発表の主軸）"), "冬・春・夏 × 受電上限 90/200/400/800 kW、全車燃料バスとの比較", ST("完了", true), "12ケースの計算と集計。全車燃料バスは距離からの概算。10月21日に試行計算（3ケース）"],
  [B("柱B（日をまたぐ意味）"), "中間発表後に予定", ST("準備中", false), "実験の設計を決定（10月21日）。実装は11月から"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.6, 3.9, 1.2, 4.4], fontSize: 14, rowH: 0.74 }));
caption(s, "研究方針（2026年10月8日）による。柱A：受電電力と担当便、柱B：日をまたぐ計画の意味", 0.6, 6.4, 12.1);
s.addNotes("はじめに、前回の三者ミーティングで決めた計画と、その進み具合です。題目は決定しました。下準備として決めた2点、燃料バスのCO₂係数と、太陽光パネルを30度傾けたときの日射の計算は、どちらも完了しています。中間発表の主軸とした柱Aは、冬・春・夏の3週と受電上限4段階、計12ケースの計算と集計が終わりました。全車燃料バスとの比較は、最適化で解が得られなかったため、走行距離からの概算としています。また、昨日10月21日に追加の試行計算を3ケース行いました。柱Bは実験の設計を決めた段階で、11月から実装に入ります。");

// ---- 1. Background and objective
s = page(S1, "研究背景と目的");
heading(s, "背景", 1.45);
const FLOW = [["電気バスの導入が進む", "脱炭素（GX）に向けて"], ["当面は燃料バスと併用", "車両価格・充電時間の制約"], ["夜にまとめて充電", "営業所で多くのバスが同時に"], ["受電電力が大きくなる", "受電設備・電気料金の負担"]];
FLOW.forEach(([t, sub], i) => {
  const x = 0.6 + i * 3.1, last = i === FLOW.length - 1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.95, w: 2.7, h: 1.25, fill: { color: last ? "DCEBF7" : "F5F5F5" }, line: { color: last ? BLUE : GRID, width: 1 } });
  text(s, [{ text: t, options: { breakLine: true, bold: true, color: last ? BLUE_DARK : INK } }, { text: sub, options: { fontSize: 12, color: SUB } }],
    { x: x + 0.1, y: 1.95, w: 2.5, h: 1.25, fontSize: 16, align: "center", valign: "middle" });
  if (!last) s.addShape(pres.shapes.LINE, { x: x + 2.72, y: 2.575, w: 0.36, h: 0, line: { color: SUB, width: 1.5, endArrowType: "triangle" } });
});
heading(s, "目的", 3.5);
text(s, "燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を合わせて最適化し、次の2点を明らかにする",
  { x: 0.6, y: 3.95, w: 12.1, h: 0.5, fontSize: 16 });
[["柱A　受電電力と担当便（中間発表）", "受電電力の上限を変えたとき、電気バスに任せられる便・費用・燃料・CO₂がどう変わるか", "EEF5FB", BLUE],
 ["柱B　日をまたぐ意味（年末まで）", "日ごとに計画した場合と比べて、日をまたいで計画すると何を防げるか", "F5F5F5", GREY]].forEach(([h, b, fill, line], i) => {
  const x = 0.6 + i * 6.15;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 4.6, w: 5.95, h: 2.1, fill: { color: fill }, line: { color: line, width: 1 } });
  text(s, h, { x: x + 0.25, y: 4.75, w: 5.45, h: 0.45, fontSize: 17, bold: true, color: BLUE_DARK });
  text(s, b, { x: x + 0.25, y: 5.3, w: 5.45, h: 1.25, fontSize: 16 });
});
s.addNotes("研究の背景です。脱炭素に向けて路線バスへの電気バスの導入が進んでいますが、車両価格や充電時間の制約から、当面は燃料バスとの併用が続くと考えられます。電気バスは夜に営業所でまとめて充電するため、営業所が電力会社から受け取る電力、つまり受電電力が大きくなり、受電設備や電気料金の負担になります。そこで本研究では、燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を合わせて最適化します。明らかにしたいことは2つで、受電電力の上限と電気バスの担当便の関係を調べる柱Aと、日をまたいで計画することの意味を調べる柱Bです。");

// ---- 1. Terms (supplement)
s = page(S1, "（補足）本発表で用いる用語");
s.addTable([
  ["便", "バスが始発から終点まで1回運行すること。対象路線では1週間に1,704便"],
  ["燃料バス", "軽油で走行する従来のバス（ディーゼルバス）"],
  ["営業所", "バスの車庫。運行を終えたバスが戻り、電気バスはここで充電する"],
  ["受電（買電）", "営業所が電力会社から電気を購入すること"],
  ["kW（キロワット）", "ある時点で使用している電力の大きさ"],
  ["kWh（キロワット時）", "使用した電力量。kW × 時間"],
  ["受電上限", "営業所が受け取る電力（kW）の目安。本研究では、超えた分に追加費用をかける"],
  ["便割当・充電計画", "どのバスがどの便を走るか、いつどれだけ充電するかを決めた計画"],
  ["代表週", "季節（冬・春・夏）を代表させるために選んだ1週間"],
  ["解なし", "すべての条件（時刻表・電池残量・受電上限など）を同時に満たす計画が見つからないこと"]].map(([k, v]) => [B(k), v]),
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.9, 9.2], fontSize: 15, rowH: 0.53 }));
s.addNotes("研究テーマの違う方も多いので、ここで用語をそろえておきます。便は、バスが始発から終点まで1回走ることで、対象の路線では1週間に1,704便あります。営業所はバスの車庫で、電気バスはここで充電します。受電上限は、営業所が受け取る電力の目安で、本研究では超えた分に追加の費用をかけています。最後の「解なし」は、条件をすべて満たす計画が見つからないことを指します。後半の結果で出てきますので、覚えておいてください。");

// ---- 1. kW vs kWh (supplement)
s = page(S1, "（補足）kWとkWhの違い：受電上限はkWの制約");
const AX = (x0, label) => {
  s.addShape(pres.shapes.LINE, { x: x0, y: 5.1, w: 4.6, h: 0, line: { color: SUB, width: 1.25 } });
  s.addShape(pres.shapes.LINE, { x: x0, y: 1.95, w: 0, h: 3.15, line: { color: SUB, width: 1.25 } });
  text(s, "時間 →", { x: x0 + 3.6, y: 5.15, w: 1.0, h: 0.3, fontSize: 12, color: SUB, align: "right" });
  text(s, "kW", { x: x0 - 0.55, y: 1.9, w: 0.5, h: 0.3, fontSize: 12, color: SUB, align: "right" });
  text(s, label, { x: x0, y: 1.5, w: 4.6, h: 0.4, fontSize: 17, bold: true });
};
AX(0.9, "(a) 短時間に集中して充電");
s.addShape(pres.shapes.RECTANGLE, { x: 2.0, y: 2.2, w: 1.2, h: 2.9, fill: { color: GREY }, line: { color: GREY } });
AX(6.3, "(b) 時間を分散して充電");
s.addShape(pres.shapes.RECTANGLE, { x: 7.4, y: 3.65, w: 2.4, h: 1.45, fill: { color: BLUE }, line: { color: BLUE } });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 2.2, w: 10.0, h: 0, line: { color: GREY, width: 1, dashType: "dash" } });
s.addShape(pres.shapes.LINE, { x: 6.3, y: 3.65, w: 4.6, h: 0, line: { color: BLUE, width: 1, dashType: "dash" } });
text(s, "ピーク大", { x: 3.3, y: 2.25, w: 1.4, h: 0.3, fontSize: 13, color: SUB });
text(s, "ピーク小", { x: 10.5, y: 3.3, w: 1.4, h: 0.3, fontSize: 13, color: BLUE_DARK });
caption(s, "図1　充電の集中と分散の模式図（(a)(b)の面積＝電力量は等しい）", 0.6, 5.5, 12.1);
bullets(s, [
  "高さ＝電力（kW）：受電上限と比べるのはこちら　／　面積＝電力量（kWh）：電気代を決める",
  "同じ電力量でも、充電を時間的に分散させればピークを抑えられる"], { x: 0.6, y: 5.95, w: 12.1, h: 0.95, fontSize: 16, paraSpaceAfter: 4 });
s.addNotes("もう一つ大事なのが、kWとkWhの違いです。水道に例えると、kWは蛇口から出る水の勢い、kWhはたまった水の量にあたります。左と右の図は面積、つまり使った電力量が同じなので、電気代は同じです。しかし左のように短い時間にまとめて充電すると、高さ、つまりkWのピークが大きくなります。受電上限は、このピークのkWに対する上限です。");

// ---- 2. Research pillars
s = page(S2, "研究の柱：柱A（中間発表の主軸）と柱B（年末まで）");
const PH = (t, fill, color) => ({ text: t, options: { bold: true, align: "center", color, fill: { color: fill } } });
s.addTable([
  [H(""), PH("柱A　受電電力と担当便（中間発表）", "DCEBF7", BLUE_DARK), PH("柱B　日をまたぐ意味（年末まで）", "EDEDED", INK)],
  [B("問い"), "受電上限を下げると、電気バスに任せられる便と費用はどう変わるか", "日ごとに計画した場合と比べ、日をまたいだ計画は何を防ぐか"],
  [B("実験"), "受電上限 90／200／400／800 kW × 冬・春・夏 ＝ 12ケース", "日ごとの計画を毎日つないで実行し、今の計画と比べる（冬・春・夏）"],
  [B("成果"), "受電上限と担当率・費用・燃料の曲線、燃料バスに戻る便の特徴", "翌朝の電池不足、燃料バスへの振替、夜の買電の差"],
  [B("状況"), { text: "計算・集計済み（本日報告）", options: { bold: true, color: BLUE_DARK } }, { text: "設計済み、11月から実装", options: { color: SUB } }]],
  tableOpts({ x: 0.6, y: 1.6, w: 12.1, colW: [1.5, 5.3, 5.3], fontSize: 16, rowH: 0.95 }));
caption(s, "表1　研究の2つの柱（研究方針 2026年10月8日）", 0.6, 6.45, 12.1);
s.addNotes("研究は2つの柱で進めています。柱Aは、受電上限を下げると、電気バスに任せられる便と費用がどう変わるかを調べるもので、中間発表の主軸です。受電上限4段階と3つの季節で12ケースを計算し、担当率・費用・燃料の曲線と、燃料バスに戻る便の特徴を出します。柱Bは、日ごとに計画した場合と比べて、日をまたいで計画すると何を防げるかを調べるもので、年末までに結果を出す予定です。柱Aは本日結果をご報告し、柱Bは計画をご説明します。");

// ---- 2. Pillar B: daily vs continuous planning (schematic)
s = page(S2, "柱Bの考え方：日ごとの計画と、日をまたいだ計画");
const DAYS = ["月", "火", "水", "木", "金", "土", "日"];
text(s, "(a) 日ごとの計画：その日の費用だけを最小にする（翌日は考えない）", { x: 0.6, y: 1.5, w: 12.1, h: 0.4, fontSize: 16, bold: true });
DAYS.forEach((d, i) => {
  const x = 0.6 + i * 1.72;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.95, w: 1.45, h: 0.7, fill: { color: "F2F2F2" }, line: { color: GREY, width: 1 } });
  text(s, d, { x, y: 1.95, w: 1.45, h: 0.7, fontSize: 16, align: "center", valign: "middle" });
  if (i < DAYS.length - 1) s.addShape(pres.shapes.LINE, { x: x + 1.47, y: 2.3, w: 0.23, h: 0, line: { color: SUB, width: 1.25, endArrowType: "triangle" } });
});
text(s, "→ は「前日の実行結果の電池残量を翌日に引き継ぐ」", { x: 0.6, y: 2.7, w: 12.1, h: 0.35, fontSize: 13, color: SUB });
text(s, "(b) 日をまたいだ計画（今の方法）：1週間の費用をまとめて最小にする", { x: 0.6, y: 3.2, w: 12.1, h: 0.4, fontSize: 16, bold: true, color: BLUE_DARK });
s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 3.65, w: 11.77, h: 0.7, fill: { color: "EEF5FB" }, line: { color: BLUE, width: 1 } });
text(s, "月 〜 日（翌日に必要な充電も、前の夜のうちに見込める）", { x: 0.6, y: 3.65, w: 11.77, h: 0.7, fontSize: 16, align: "center", valign: "middle", color: BLUE_DARK });
caption(s, "図2　柱Bで比べる2つの計画方法（模式図）", 0.6, 4.4, 12.1);
s.addTable([
  [H("比べるもの"), H("評価の仕方"), H("予想（仮説）")],
  ["翌朝の電池不足、燃料バスへの振替、夜の買電（量とピーク）", "2〜3週続けて回し、初期状態の影響が残る最初の週を除いて最後の1週を評価", "(a) では夜の充電を控えすぎ、翌朝の電池不足や燃料バスへの振替が増える"]],
  tableOpts({ x: 0.6, y: 4.95, w: 12.1, colW: [4.0, 4.0, 4.1], fontSize: 14, rowH: 0.5 }));
s.addNotes("柱Bの考え方を図で示します。上の(a)は日ごとの計画で、毎日その日の費用だけを最小にする計画を立て、前の日に実行した結果の電池残量を次の日に引き継ぎます。下の(b)が今の方法で、1週間をまとめて計画するので、翌日に必要な充電も前の夜のうちに見込めます。比べるのは、翌朝の電池不足、燃料バスへの振替、夜の買電です。最初の週は初期状態の影響を受けるので、2〜3週続けて回し、最後の1週だけを評価します。日ごとの計画では夜の充電を控えすぎて、翌朝の電池不足や燃料バスへの振替が増えるのではないかと予想しています。");

// ---- 3. Problem and solution approach
s = page(S3, "問題設定と解法");
const COLS = [
  ["決めること（決定変数）", "各便の担当車両（電気・燃料）／各車両の充電の時刻と量／太陽光・蓄電池・買電の配分"],
  ["守るルール（制約条件）", "次の便の出発に間に合う／電池残量が下限を下回らない／充電器は同時に10基まで／受電上限の超過分には追加費用"],
  ["最小化する費用（目的関数）", "1週間の総費用／内訳：車両使用費、電気代、燃料代、超過分の費用"]];
COLS.forEach(([head, body], i) => {
  const x = 0.6 + i * 4.1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.55, w: 3.9, h: 2.45, fill: { color: "F7F9FB" }, line: { color: GRID, width: 1 } });
  text(s, head, { x: x + 0.2, y: 1.65, w: 3.5, h: 0.45, fontSize: 16, bold: true, color: BLUE_DARK });
  text(s, body.split("／").map((t, j, a) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: j < a.length - 1 } })), { x: x + 0.2, y: 2.15, w: 3.5, h: 1.8, fontSize: 14, paraSpaceAfter: 4 });
});
heading(s, "解法の流れ", 4.2);
const STEPS = [["便割当（Stage 1）", "各便の担当車両を決める"], ["充電計画（Stage 2）", "15分ごとの充電を決める"], ["毎時の見直し", "1時間ごとに計画を更新"], ["費用・CO₂の集計", "実行した結果から求める"]];
STEPS.forEach(([t, sub], i) => {
  const x = 0.6 + i * 3.1, last = i === STEPS.length - 1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 4.7, w: 2.7, h: 1.2, fill: { color: last ? "DCEBF7" : "F5F5F5" }, line: { color: last ? BLUE : GRID, width: 1 } });
  text(s, [{ text: t, options: { bold: true, breakLine: true, color: last ? BLUE_DARK : INK } }, { text: sub, options: { fontSize: 13, color: SUB } }],
    { x: x + 0.1, y: 4.7, w: 2.5, h: 1.2, fontSize: 16, align: "center", valign: "middle" });
  if (!last) s.addShape(pres.shapes.LINE, { x: x + 2.72, y: 5.3, w: 0.36, h: 0, line: { color: SUB, width: 1.5, endArrowType: "triangle" } });
});
caption(s, "求解：Gurobi［4］。便割当は一括では改善しなかったため、一部の便のみを解き直す大近傍探索（LNS）［5］を併用", 0.6, 6.1, 12.1);
s.addNotes("次に計算の方法です。数理最適化では、決めること、守るルール、最小化する費用の3つを数式で表し、計算機で最もよい計画を探します。時間割やシフト表を作るのに近いと考えてください。決めるのは各便の担当車両と充電の時刻と量、守るルールは時刻表や電池残量、充電器の台数、受電上限です。最小化するのは1週間の総費用です。問題が大きいので、下の流れのとおり、まず便の割当を決め、次に充電計画を決め、さらに1時間ごとに計画を見直しながら1週間を運用して、その結果から費用とCO₂を集計しています。");

// ---- 3. Formulation
s = page(S3, "定式化（概略）");
const EQ_SCALE = 0.72;
const ROWS = [["目的関数", "objective"], ["便の被覆", "cover"], ["接続可能性", "connect"], ["電池残量", "soc"],
  ["充電器台数", "charger"], ["電力収支", "balance"], ["受電上限", "limit"]];
let ey = 1.6;
ROWS.forEach(([label, key]) => {
  const w = eqSize[key].w * EQ_SCALE, h = eqSize[key].h * EQ_SCALE, rowH = Math.max(h, 0.42) + 0.16;
  text(s, label, { x: 0.6, y: ey, w: 1.9, h: rowH - 0.16, fontSize: 15, bold: true, valign: "middle" });
  s.addImage({ path: path.join(__dirname, "eq", `${key}.png`), x: 2.55, y: ey + (rowH - 0.16 - h) / 2, w, h });
  ey += rowH;
});
text(s, [
  { text: "主な記号", options: { bold: true, breakLine: true } },
  { text: "u：車両の使用（車両・日）", options: { breakLine: true } },
  { text: "x：便 i の次に便 j を担当", options: { breakLine: true } },
  { text: "z, ξ：充電電力、充電中フラグ", options: { breakLine: true } },
  { text: "E：電池残量、e：走行消費", options: { breakLine: true } },
  { text: "g：買電量、s：上限超過量", options: { breakLine: true } },
  { text: "f：燃料使用量、Q：CO₂排出量", options: {} }],
  { x: 9.4, y: 1.6, w: 3.3, h: 3.4, fontSize: 13, color: SUB, lineSpacingMultiple: 1.25 });
text(s, [{ text: "前ページの3列（決めること・守るルール・最小化する費用）を式で表したもの。記号は簡略化した。π＝500円/kWh（仮の値）、c" }, { text: "CO₂", options: { superscript: true } }, { text: "＝1円/kg、N" }, { text: "ch", options: { superscript: true } }, { text: "＝10。" }],
  { x: 0.6, y: 6.55, w: 12.1, h: 0.4, fontSize: 12, color: SUB });
s.addNotes("こちらは、前のページの内容を式で表したものです。目的関数は、車両の使用費、電気代、上限を超えた分の追加費用、燃料代、CO₂の費用の合計です。受電上限は、超過量sを許したうえで、sに1 kWhあたり500円の費用をかける形にしています。時間の都合で、式の詳細は省略します。");

// ---- 3. Conditions
s = page(S3, "計算条件");
s.addTable([
  ["対象", "東急バス 渋21〜23系統（弦巻営業所）、時刻表は公共交通オープンデータ［3］"],
  ["運行", "1週間 1,704便"],
  ["車両", "電気バス35台・燃料バス25台（保有台数、固定）"],
  ["設備", "太陽光 1,000 kW（傾斜30°、pvlib［2］で斜面日射を算定）、蓄電池 6,000 kWh、充電器 90 kW×10基"],
  ["受電上限", "90 / 200 / 400 / 800 kW（超過分に500円/kWhの追加費用、仮の値）"],
  ["対象期間", "冬・春・夏の代表週（2025年1月6日・4月7日・7月7日から各1週間）"],
  ["単価・係数", "電力量 30円/kWh（設定値）、軽油 150円/L、車両使用費 2万円/台・日、CO₂ 軽油2.62 kg/L［1］・電力0.5 kg/kWh（仮の値）"],
  ["計算ケース", "受電上限4段階 × 3週 ＝ 12ケース"]].map(([k, v]) => [B(k), v]),
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.2, 9.9], fontSize: 15, rowH: 0.6 }));
caption(s, "表2　計算条件", 0.6, 6.45, 12.1);
s.addNotes("計算条件です。対象は東急バスの渋21から23系統、弦巻営業所の1週間1,704便です。車両は電気バス35台、燃料バス25台で固定しています。営業所には太陽光1,000 kW、蓄電池6,000 kWh、充電器10基を設置したと仮定しています。受電上限は90、200、400、800 kWの4段階で、冬・春・夏の代表週と組み合わせて12ケースを計算しました。電気の単価や超過分の費用など、一部は仮の値である点にご注意ください。");

// ---- 4. Pillar A: grid limit vs BEV trip share
const CH = { x: 0.6, y: 2.25, w: 7.2, h: 4.1 }, RB = { x: 8.1, y: 2.4, w: 4.65, h: 3.9, fontSize: 16 };
s = page(S4, "結果(A-1)　受電上限と電気バスの担当便");
const shares = rc8.map((r) => r.bev_trip_share_pct), w90 = get(90, WIN);
takeaway(s, `受電上限を800 kWから90 kWまで下げても、電気バスの担当便は${Math.min(...shares).toFixed(1)}〜${Math.max(...shares).toFixed(1)}%でほぼ変わらない`);
s.addChart(pres.charts.LINE, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(g, w).bev_trip_share_pct * 10) / 10) })),
  chart({ ...CH, lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 7, chartColors: [BLUE_DARK, BLUE_LIGHT, GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスが担当した便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図3　受電上限と電気バスの担当便の割合（1,704便/週）", 0.6, 6.45, 7.6);
bullets(s, [
  "上限90 kWでも燃料バスへの振り替えは起きなかった",
  `代わりに超過分の追加費用を払う計画になった（冬は約${Math.round(w90.contract_overage_cost / 1e4)}万円/週）`,
  "上限による差より、季節による差（春がやや低い）の方が大きい"], RB);
s.addNotes("ここから柱Aの結果です。横軸が受電上限、縦軸が電気バスの担当した便の割合です。上の帯に書いたとおり、受電上限を800 kWから90 kWまで下げても、電気バスの担当便は92.0〜96.5%で、ほとんど変わりませんでした。つまり、上限を下げても燃料バスへの振り替えは起きず、その代わりに上限を超えた分の追加費用を払う計画になっています。冬の90 kWでは、追加費用は1週間に約121万円でした。なぜこうなるかは、後ほど考察でご説明します。");

// ---- 4. Pillar A: weekly cost and fuel
s = page(S4, "結果(A-2)　受電上限と運用費・燃料使用量");
const opex = (g) => (avg(g, "electricity_cost") + avg(g, "fuel_cost") + avg(g, "contract_overage_cost")) / 1e4;
const fuelL = LIMITS.map((g) => avg(g, "ice_fuel_consumed_l"));
const veh = rc8.map((r) => r.vehicle_usage_cost / 1e4);
takeaway(s, "上限を下げると運用費は増えるが、増えた分はほぼすべて上限の超過費用。燃料使用量は変わらない");
s.addChart(pres.charts.BAR, [
  { name: "電気代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "electricity_cost") / 1e3) / 10) },
  { name: "燃料代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "fuel_cost") / 1e3) / 10) },
  { name: "上限の超過費用", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "contract_overage_cost") / 1e3) / 10) }],
  chart({ ...CH, barDir: "col", barGrouping: "stacked", chartColors: [BLUE, GREY, "CFCFCF"], valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "運用費 [万円/週]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図4　受電上限と1週間の運用費の内訳（冬・春・夏の平均、車両使用費は除く）", 0.6, 6.45, 7.6);
bullets(s, [
  `運用費：約${Math.round(opex(800))}万円/週（800 kW）→ 約${Math.round(opex(90))}万円/週（90 kW）`,
  `燃料使用量：約${Math.round(Math.min(...fuelL))}〜${Math.round(Math.max(...fuelL))} L/週で一定`,
  `車両使用費（約${Math.min(...veh)}〜${Math.max(...veh)}万円/週）は上限によらずほぼ同じため図から除いた`], RB);
s.addNotes("次に費用と燃料です。棒グラフは1週間の運用費の内訳で、3つの季節の平均です。上限を800 kWから90 kWに下げると、運用費は約11万円から約87万円に増えますが、増えた部分の灰色、つまりほぼすべてが上限の超過費用です。電気代と燃料代はほとんど変わらず、燃料の使用量も1週間に約155 Lで一定でした。なお、車両の使用費は上限によらずほぼ同じなので、図からは除いています。");

// ---- 4. Pillar A: which trips go to diesel
s = page(S4, "結果(A-3)　燃料バスが担当した便の時間帯");
const BANDS = [["05-06", "早朝（5〜6時台）"], ["07-21", "日中（7〜21時台）"], ["22-", "深夜（22時以降）"]];
const iceShare = (g, b) => { const rs = iceHour.filter((r) => r.grid_limit_kw === g);
  return Math.round(rs.reduce((a, r) => a + r.bands[b].diesel / r.bands[b].total, 0) / rs.length * 1000) / 10; };
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };
takeaway(s, "燃料バスが担当するのは早朝と深夜の便。受電上限を下げても増えない");
s.addChart(pres.charts.BAR, LIMITS.map((g) => ({ name: `${g} kW`, labels: BANDS.map((x) => x[1]), values: BANDS.map(([b]) => iceShare(g, b)) })),
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", GREY, BLUE_LIGHT, BLUE_DARK], showValue: true,
    dataLabelPosition: "outEnd", dataLabelFormatCode: "0", dataLabelFontSize: 10, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "燃料バスが担当した便 [%]" }));
caption(s, "図5　出発時間帯別の燃料バス担当率（冬・春・夏の平均、凡例は受電上限）", 0.6, 6.45, 7.6);
bullets(s, [
  `早朝：${rng("05-06")}`, `深夜：${rng("22-")}`, `日中：${rng("07-21")}`,
  "時間帯は、時刻表の各便の出発時刻で分類した"], RB);
s.addNotes("次に、どの時間帯の便が燃料バスに回っているかを見ました。燃料バスが担当したのは主に早朝の5時から6時台と、夜22時以降の便で、日中はほとんど電気バスが担当していました。この傾向は、受電上限を変えてもほとんど同じでした。早朝・深夜の便が燃料バスに回る理由は、まだ確かめていません。");

// ---- 4. Pillar A: CO2 against an all-diesel fleet
s = page(S4, "結果(A-4)　全車燃料バスとのCO₂比較");
takeaway(s, "電気バスと併用すると、CO₂は全車燃料バスより約75〜85%少ない");
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス（概算）", labels: SEASONS.map((x) => x[1]), values: SEASONS.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バスと併用", labels: SEASONS.map((x) => x[1]), values: SEASONS.map(([w]) => Math.round(get(800, w).total_co2_kg / 100) / 10) }],
  chart({ ...CH, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]" }));
caption(s, "図6　1週間のCO₂排出量（併用は受電上限800 kWの場合）", 0.6, 6.45, 7.6);
bullets(s, [
  "全車燃料バスは走行距離からの概算で、最適化の結果ではない",
  "電力の係数0.5 kg/kWhは仮の値。実値0.452［1］でも削減率は約77〜86%"], RB);
s.addNotes("CO₂の比較です。灰色が全車燃料バスの場合、青が電気バスと併用した場合です。電気バスと併用することで、CO₂は全車燃料バスより約75〜85%少なくなりました。ただし、全車燃料バスの方は走行距離から軽油の量を求めた概算です。また、電力のCO₂係数0.5は仮の値ですが、東京電力の実際の値0.452で計算し直しても、削減率は約77〜86%で、結論は変わりません。");

// ---- 4. Pillar A: hard-limit pilot (diagnostic)
s = page(S4, "結果(A-5)　試行：超過を許さない受電上限（速報）");
takeaway(s, "上限を超えられない条件にしても便割当は変わらず、実行中に計画が成り立たなくなった");
s.addTable([
  [H("受電上限"), H("便割当（電気バス／燃料バス）"), H("1週間の充電計画"), H("毎時の見直し（実行）")],
  [B("90 kW"), "―", "1時間内に見つからず", "実行できず"],
  [B("200 kW"), "1,620便／84便（超過可と同じ）", "最適（ピーク200 kW）", "初日10時に解なし"],
  [B("400 kW"), "1,626便／78便", "最適（ピーク400 kW）", "初日14時に解なし"]].map((r, i) => i === 0 ? r : r.map((v, j) => j === 0 ? v : { text: v, options: { align: "center" } })),
  tableOpts({ x: 0.6, y: 2.3, w: 12.1, colW: [1.7, 4.0, 3.2, 3.2], fontSize: 15, rowH: 0.58 }));
caption(s, "表3　冬の週で、受電上限を超過できない制約にした試行計算（診断。研究の結論には使わない）", 0.6, 4.7, 12.1);
bullets(s, ["200・400 kWは、計画上は上限ちょうどで間に合うが余裕がなく、実行中のずれで1台のバスが翌朝の電池残量を確保できなくなった"],
  { x: 0.6, y: 5.25, w: 12.1, h: 1.0, fontSize: 16 });
s.addNotes("最後に、昨日行った試行計算の速報です。受電上限を超えられない条件にして、冬の週で3ケースを計算しました。結果、便の割当は変わらず、電気バスが95%のままでした。200 kWと400 kWでは、1週間の計画の上では上限ちょうどで充電が間に合いますが、余裕がなく、実行中の小さなずれで1台のバスが翌朝に必要な電池残量を確保できなくなり、計画が成り立たなくなりました。90 kWでは、1時間以内に計画自体が見つかりませんでした。これは診断のための計算で、研究の結論には使いませんが、次の考察を裏付ける結果だと考えています。");

// ---- 4. Pillar A results table
s = page(S4, "柱Aの結果の一覧（冬・春・夏の平均）");
const maxPeak = (g) => Math.max(...byLimit(g).map((r) => r.peak_grid_kw));
takeaway(s, "上限を下げて増えるのは超過量と費用だけ。担当便・燃料・買電量はほぼ一定");
const HL = (v, on) => ({ text: v, options: { align: "right", bold: on, color: on ? BLUE_DARK : INK, fill: on ? { color: "EEF5FB" } : undefined } });
s.addTable([
  [H("受電上限"), H("電気バス担当便 [%]"), H("燃料使用量 [L/週]"), H("買電量 [kWh/週]"), H("最大受電電力 [kW]"), H("上限超過量 [kWh/週]"), H("運用費 [万円/週]"), H("CO₂ [t/週]")],
  ...LIMITS.map((g) => [{ text: `${g} kW`, options: { align: "center", bold: true } },
    HL(avg(g, "bev_trip_share_pct").toFixed(1), false), HL(fmt(avg(g, "ice_fuel_consumed_l")), false), HL(fmt(avg(g, "grid_import_kwh")), false), HL(fmt(maxPeak(g)), false),
    HL(fmt(avg(g, "contract_over_limit_kwh")), true), HL(opex(g).toFixed(1), true), HL((avg(g, "total_co2_kg") / 1000).toFixed(2), false)])],
  tableOpts({ x: 0.6, y: 2.3, w: 12.1, colW: [1.35, 1.6, 1.5, 1.5, 1.55, 1.6, 1.5, 1.5], fontSize: 14, rowH: 0.6 }));
caption(s, "表4　受電上限別の結果（最大受電電力は3週の最大値、運用費は車両使用費を除く）。青い列が上限によって大きく変わる項目", 0.6, 5.45, 12.1);
bullets(s, [
  `最大受電電力は、上限90〜400 kWでは上限を上回り（${fmt(maxPeak(400))}〜${fmt(maxPeak(90))} kW）、800 kWでは${fmt(maxPeak(800))} kWだった`], { x: 0.6, y: 5.95, w: 12.1, h: 0.9, fontSize: 16 });
s.addNotes("柱Aの結果を表にまとめました。青い列が、受電上限によって大きく変わった項目です。上限を下げると、上限を超えた量と運用費は大きく増えますが、電気バスの担当便、燃料の使用量、買電量はほとんど変わっていません。");

// ---- 5. Discussion
s = page(S5, "考察：担当便が変わらない理由（推測）");
takeaway(s, "便割当の段階の楽観的な見込みが、担当便が変わらない原因と考えられる");
const CHAIN = [["便割当の段階", "買電 0 kWh と見込む"], ["電気バスに約95%を割当", "受電上限によらない"],
  ["実際の充電計画", "夜に買電／2,137〜4,236 kWh/週"], ["上限を超過", "追加費用を払う／超過を許さないと解なし"]];
CHAIN.forEach(([t, sub], i) => {
  const x = 0.6 + i * 3.1, last = i === CHAIN.length - 1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 2.3, w: 2.7, h: 1.55, fill: { color: last ? "DCEBF7" : "F5F5F5" }, line: { color: last ? BLUE : GRID, width: 1 } });
  text(s, [{ text: t, options: { bold: true, breakLine: true, color: last ? BLUE_DARK : INK } },
    ...sub.split("／").map((u, j, arr) => ({ text: u, options: { fontSize: 13, color: SUB, breakLine: j < arr.length - 1 } }))],
    { x: x + 0.12, y: 2.3, w: 2.46, h: 1.55, fontSize: 16, align: "center", valign: "middle" });
  if (!last) s.addShape(pres.shapes.LINE, { x: x + 2.72, y: 3.075, w: 0.36, h: 0, line: { color: SUB, width: 1.5, endArrowType: "triangle" } });
});
caption(s, "図7　担当便が変わらない仕組み（推測。便割当段階の見込みは12ケースすべて買電0 kWh）", 0.6, 3.95, 12.1);
s.addTable([
  [H("課題と限界"), H("内容"), H("次の対応")],
  [B("便割当の見込み"), "上の仕組みは推測で、まだ確かめていない", "見込みと実際の買電を時間帯別に比較（10月末まで）"],
  [B("解の質"), "便割当は制限時間内の計画。最適性は未確認（充電計画は12ケース中11ケースで最適）", "解の質の確認"],
  [B("仮の値・期間"), "超過費用 500円/kWh、電力のCO₂係数 0.5 kg/kWh、1週間で区切っている", "値を変えた感度の確認"]],
  tableOpts({ x: 0.6, y: 4.45, w: 12.1, colW: [2.2, 5.6, 4.3], fontSize: 14, rowH: 0.55 }));
s.addNotes("では、なぜ担当便が変わらないのか、現時点の考えです。図のように、便を割り当てる段階では、充電は太陽光と蓄電池でまかなえると見込んでおり、12ケースすべてで買電を0 kWhと見積もっていました。そのため電気バスに約95%の便を割り当てますが、実際に充電計画を立てると、夜に1週間2,000〜4,000 kWh程度の電気を買う必要があり、上限を超えてしまいます。つまり、便割当の段階の見込みが楽観的なことが原因と考えています。ただしこれは推測で、下の表のとおり、10月末までに確かめる予定です。また、解の質や仮の値についても、今後確認が必要です。");

// ---- 6. Summary
s = page(S6, "まとめ");
const TILES = [["92.0〜96.5%", "電気バスの担当便", "受電上限を800 kWから90 kWまで下げても、ほぼ変わらない"],
  ["約11 → 87万円/週", "運用費（800 kW → 90 kW）", "増加分のほぼすべてが超過費用／燃料使用量は一定"],
  ["約75〜85%減", "CO₂（全車燃料バス比）", "電気バスとの併用による削減"]];
TILES.forEach(([big, label, sub], i) => {
  const x = 0.6 + i * 4.1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.6, w: 3.9, h: 3.0, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  text(s, label, { x: x + 0.2, y: 1.75, w: 3.5, h: 0.45, fontSize: 15, color: SUB, align: "center" });
  text(s, big, { x: x + 0.1, y: 2.25, w: 3.7, h: 0.9, fontSize: 30, bold: true, color: BLUE_DARK, align: "center", valign: "middle" });
  text(s, sub.split("／").map((t, j, a) => ({ text: t, options: { breakLine: j < a.length - 1 } })), { x: x + 0.25, y: 3.25, w: 3.4, h: 1.2, fontSize: 14, align: "center" });
});
bullets(s, [
  "燃料バスが担当したのは早朝・深夜の便に限られ、受電上限を下げても燃料バスに戻る便は増えなかった",
  "受電上限を超えられない条件の試行でも便割当は変わらず、便割当の段階の見込みの改善が次の課題である"],
  { x: 0.6, y: 4.95, w: 12.1, h: 1.8, fontSize: 17, paraSpaceAfter: 8 });
s.addNotes("まとめです。柱Aでは、受電上限を800 kWから90 kWまで下げても、電気バスの担当便は92.0〜96.5%でほとんど変わりませんでした。運用費は約11万円から87万円に増えましたが、増えたのはほぼ上限の超過費用です。また、電気バスとの併用でCO₂は全車燃料バスより約75〜85%少なくなりました。燃料バスが担当するのは早朝・深夜の便に限られ、上限を超えられない条件でも便割当は変わらなかったことから、便割当の段階の見込みを改善することが次の課題です。");

// ---- 6. Plan
s = page(S6, "今後の予定");
const PERIODS = ["10月下旬", "11月上旬", "11月中旬", "11月下旬", "12月前半", "12月後半", "1月〜"];
const GX = 5.0, GW = (12.7 - GX) / PERIODS.length, GY = 1.6, RH = 0.58;
PERIODS.forEach((p, i) => {
  s.addShape(pres.shapes.RECTANGLE, { x: GX + i * GW, y: GY, w: GW, h: 0.5, fill: { color: HEAD }, line: { color: GRID, width: 0.75 } });
  text(s, p, { x: GX + i * GW, y: GY, w: GW, h: 0.5, fontSize: 13, bold: true, align: "center", valign: "middle" });
});
const TASKS = [["柱A", "担当便が変わらない理由の分析", 0, 1], ["柱A", "試行で解なしとなった原因と改善の検討", 1, 2], ["柱A", "中間発表（11/28、A0ポスター）の準備", 2, 4],
  ["柱B", "日ごとの計画をつなぐ仕組みの実装", 1, 4], ["柱B", "冬・春・夏 × 2方式の計算", 4, 5], ["柱B", "集計と年内の報告", 5, 6], ["3本目", "運行・利用者の観点（内容は検討中）", 6, 7]];
TASKS.forEach(([p, label, a, b], i) => {
  const y = GY + 0.6 + i * RH, color = p === "柱A" ? BLUE : p === "柱B" ? GREY : "CFCFCF";
  text(s, [{ text: `${p}　`, options: { bold: true, color: p === "柱A" ? BLUE_DARK : SUB } }, { text: label }], { x: 0.6, y, w: 4.3, h: RH, fontSize: 14, valign: "middle" });
  s.addShape(pres.shapes.LINE, { x: GX, y: y + RH, w: 12.7 - GX, h: 0, line: { color: GRID, width: 0.5 } });
  s.addShape(pres.shapes.RECTANGLE, { x: GX + a * GW + 0.05, y: y + 0.14, w: (b - a) * GW - 0.1, h: RH - 0.28, fill: { color }, line: { color } });
});
const mx = GX + 3 * GW + GW * 0.85;
s.addShape(pres.shapes.LINE, { x: mx, y: GY + 0.55, w: 0, h: TASKS.length * RH + 0.1, line: { color: BLUE_DARK, width: 1.5, dashType: "dash" } });
text(s, "中間発表 11/28", { x: mx - 1.2, y: GY + 0.6 + TASKS.length * RH + 0.08, w: 2.4, h: 0.3, fontSize: 12, color: BLUE_DARK, align: "center", bold: true });
caption(s, "図8　今後の工程（柱Bの季節は柱Aと同じ冬・春・夏の代表週）", 0.6, 6.6, 7.0, 0.35);
s.addNotes("今後の予定です。中間発表までは柱Aに集中し、10月中に担当便が変わらない理由を分析し、11月上旬に試行計算で解なしになった原因と改善を検討します。その後、11月28日の中間発表に向けてポスターを準備します。柱Bは11月に仕組みを作り、12月前半に冬・春・夏の3季節で計算し、年内に結果をまとめます。1月以降は、運行や利用者の観点を取り入れた3本目の柱を検討しています。以上で発表を終わります。ご清聴ありがとうございました。");

// ---- References
s = page("参考文献", "参考文献");
text(s, [
  "［1］環境省・経済産業省：算定方法・排出係数一覧（軽油）；電気事業者別排出係数（令和6年度実績），2026年1月公表・2月更新",
  "［2］W. F. Holmgren, C. W. Hansen, M. A. Mikofski: pvlib python: a python package for modeling solar energy systems, Journal of Open Source Software, 3(29), 884, 2018",
  "［3］公共交通オープンデータセンター：東急バス 時刻表データ（ODPT）",
  "［4］Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual",
  "［5］P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, Proc. CP-98, LNCS 1520, pp. 417–431, 1998"]
  .map((t, i, a) => ({ text: t, options: { breakLine: i < a.length - 1 } })),
  { x: 0.6, y: 1.55, w: 12.1, h: 5.35, fontSize: 14, paraSpaceAfter: 10, lineSpacingMultiple: 1.15 });
s.addNotes("参考文献です。質問の際に必要であればご覧ください。");

(async () => {
  const out = path.join(__dirname, "lab_progress_20261022.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
