// Lab progress report (2026-10-22): supervisor plus juniors from other topics.
// Research-presentation structure: contents, numbered sections, numbered figures/tables with sources,
// formulation, results table, discussion, references. White background, Tokyo City University blue
// (#0485D7) only for rules, headings and the proposed-case series; the comparison case is grey.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const rc8 = JSON.parse(fs.readFileSync(path.join(__dirname, "cases_rc8.json"), "utf8"));
const rc9 = JSON.parse(fs.readFileSync(path.join(__dirname, "cases_rc9.json"), "utf8")).filter((r) => r.status === "VERIFIED");
const night = JSON.parse(fs.readFileSync(path.join(__dirname, "night_profile_90kW_winter.json"), "utf8"));
const iceHour = JSON.parse(fs.readFileSync(path.join(__dirname, "ice_by_hour_rc8.json"), "utf8"));
const eqSize = JSON.parse(fs.readFileSync(path.join(__dirname, "eq", "sizes.json"), "utf8"));
const dl = fs.readFileSync(path.join(__dirname, "all_diesel_estimate.csv"), "utf8").replace(/^﻿/, "").trim().split(/\r?\n/);
const dk = dl[0].split(","), diesel = dl.slice(1).map((l) => Object.fromEntries(l.split(",").map((v, i) => [dk[i], v])));
const LIMITS = [90, 200, 400, 800];
const WIN = "2025-01-06";
const get = (rows, g, w) => rows.find((r) => r.grid_limit_kw === g && r.week === w);
const peakYear = (rows, g) => Math.max(...rows.filter((r) => r.grid_limit_kw === g && r.week !== "2025-10-06").map((r) => r.peak_grid_kw));
// Annual basic charge at the current TEPCO EP tariff (Kanto, high voltage, Basic plan, 2026-04-01, tax incl.).
const BASIC_YEN_PER_KW = 2530;
const basicYear = (kw) => kw * BASIC_YEN_PER_KW * 0.85 * 12;
const fmt = (n) => Math.round(n).toLocaleString("ja-JP");

const BLUE = "0485D7", BLUE_DARK = "0268B0", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2";
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

const S1 = "1. 研究背景と目的", S2 = "2. 問題設定と解法", S3 = "3. 結果：柱A 受電上限と電気バスの担当便",
  S4 = "4. 結果：柱C 基本料金の考慮", S5 = "5. 考察", S6 = "6. まとめと今後の予定", S0 = "前回からの進捗";

// ---- Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 1.7, w: 11.5, h: 1.9, fontSize: 34, bold: true, valign: "bottom" });
text(s, "― 受電上限・基本料金と電気バスの担当便・受電ピークの関係 ―", { x: 0.9, y: 3.7, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "研究室進捗報告　2026年10月22日\n東京都市大学　劉 承洋", { x: 0.9, y: 4.6, w: 11.5, h: 1.0, fontSize: 18, color: SUB });
s.addNotes("本日は、前回の三者ミーティングで決めた計画に沿って、柱Aの計算結果と、前倒しで着手した柱Cの結果を報告します。研究テーマの違う方にも分かるよう、用語の説明から入ります。");

// ---- Contents
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("目次", { placeholder: "title" });
text(s, [S1, S2, S3, S4, S5, S6].map((t, i) => ({ text: t, options: { breakLine: i < 5 } })), { x: 1.0, y: 1.7, w: 11, h: 3.8, fontSize: 21, paraSpaceAfter: 12 });
text(s, "今回の報告内容：前回の三者ミーティング（10月8日）で中間発表の主軸と決めた柱Aの計算が完了したため、その結果と、前倒しで着手した柱Cの結果を報告する。",
  { x: 1.0, y: 5.6, w: 11.3, h: 0.8, fontSize: 16, color: SUB });

// ---- Progress against the 2026-10-08 three-party meeting plan
s = page(S0, "前回の三者ミーティング（10月8日）で決めた計画と進捗");
s.addTable([
  [H("項目"), H("決めた内容"), H("現状")],
  [B("題目"), "GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化", "決定済み"],
  [B("下準備1"), "燃料バスのCO₂係数を根拠付きで算出する", "完了：軽油2.62 kg/L（環境省の算定制度）"],
  [B("下準備2"), "pvlibで傾斜30°の斜面日射を適用する", "完了：計画と実行の両方に適用"],
  [B("柱A（中間発表の主軸）"), "冬・春・夏 × 受電上限 90/200/400/800 kW、全車燃料バスとの比較", "計算完了（12ケース）。全車燃料バスは最適化で解が得られず、距離からの概算"],
  [B("柱C（日本の料金体系）"), "中間発表後に予定", "前倒しで着手：基本料金を考慮した16ケース。30分デマンドの扱いは未対応"],
  [B("柱B（日をまたぐ計画の価値）"), "中間発表後に予定", "未着手"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.9, 4.6, 4.6], fontSize: 14, rowH: 0.66 }));
caption(s, "柱A〜Cは研究方針（2026年10月8日）による。柱A：受電上限と電気バスの担当便、柱B：日をまたぐ計画、柱C：日本の電力契約に沿った費用評価", 0.6, 6.35, 12.1, 0.6);
s.addNotes("前回の三者ミーティングで決めた計画と、その進み具合です。題目と2つの下準備は済みました。中間発表の主軸の柱Aは、冬・春・夏の3週と受電上限4段階の計12ケースの計算が終わりました。全車燃料バスとの比較は、最適化では解が得られなかったため、走行距離からの概算です。中間発表後に予定していた柱Cは、基本料金を考慮した計算を前倒しで行いました。柱Bはまだ着手していません。");

// ---- 1. Background and objective
s = page(S1, "研究背景と目的");
text(s, "背景", { x: 0.6, y: 1.5, w: 12.1, h: 0.4, fontSize: 18, bold: true, color: BLUE_DARK });
bullets(s, [
  "脱炭素（GX）に向けて、路線バスへの電気バスの導入が進んでいる",
  "車両価格や充電時間の制約から、当面は燃料（軽油）バスとの併用が続くと考えられる",
  "電気バスは営業所で夜間にまとめて充電するため、受電電力のピークが大きくなりやすい。ピークは契約電力を通じて基本料金に直結する"],
  { x: 0.6, y: 1.95, w: 12.1, h: 2.3, fontSize: 17 });
text(s, "目的", { x: 0.6, y: 4.35, w: 12.1, h: 0.4, fontSize: 18, bold: true, color: BLUE_DARK });
bullets(s, [
  "燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を合わせて最適化し、次の3点を明らかにする",
  "柱A：受電上限を変えたとき、電気バスに任せられる便の割合・費用・CO₂がどう変わるか（中間発表の主軸）",
  "柱C：日本の高圧契約の基本料金を考慮すると、充電計画と費用がどう変わるか",
  "柱B：日をまたいで計画する価値を、日ごとの計画と比べて示す（中間発表後）"],
  { x: 0.6, y: 4.8, w: 12.1, h: 2.1, fontSize: 15, paraSpaceAfter: 4 });
s.addNotes("電気バスの導入は進んでいますが、当面は燃料バスとの併用が続きます。そのとき問題になるのが充電の電気で、夜にまとめて充電すると受電のピークが大きくなり、電気の基本料金が上がります。本研究では、便の割当と充電計画を合わせて最適化し、受電上限と基本料金の影響を調べています。");

// ---- 1. Terms (supplement)
s = page(S1, "（補足）本発表で用いる用語");
s.addTable([
  ["便", "バスが始発から終点まで1回運行すること。対象路線では1週間に1,704便"],
  ["燃料バス", "軽油で走行する従来のバス（ディーゼルバス）"],
  ["営業所", "バスの車庫。運行を終えたバスが戻り、電気バスはここで充電する"],
  ["受電（買電）", "営業所が電力会社から電気を購入すること"],
  ["kW（キロワット）", "ある時点で使用している電力の大きさ"],
  ["kWh（キロワット時）", "使用した電力量。kW × 時間"],
  ["太陽光・蓄電池", "営業所に設置した太陽光発電と大型の蓄電池（本研究では設置を仮定）"]].map(([k, v]) => [B(k), v]),
  tableOpts({ x: 0.6, y: 1.6, w: 12.1, colW: [2.9, 9.2], fontSize: 17, rowH: 0.64 }));
s.addNotes("研究テーマが違う方も多いので、先に用語をそろえておきます。特にkWとkWhの違いが今日の話の中心になるので、次のページで説明します。");

// ---- 1. kW vs kWh (supplement)
s = page(S1, "（補足）kWとkWhの違い：本研究で注目する「ピーク」");
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
  "高さ＝電力（kW）：そのピークが基本料金を決める　／　面積＝電力量（kWh）：電力量料金を決める",
  "同じ電力量でも、充電を時間的に分散させればピークを抑えられる"], { x: 0.6, y: 5.95, w: 12.1, h: 0.95, fontSize: 16, paraSpaceAfter: 4 });
s.addNotes("kWとkWhの違いです。水道に例えると、kWは蛇口から出る水の勢い、kWhはたまった水の量にあたります。左右の図は面積が同じなので、電力量料金は同じです。しかし左の方がピークが高いので、基本料金は左の方が高くなります。本研究では、このピークに注目しています。");

// ---- 1. Tariff
s = page(S1, "電気料金の構成と本研究での扱い");
s.addTable([
  [H(""), H("電力量料金"), H("基本料金")],
  [B("決まり方"), "使用した電力量（kWh）", "契約電力（kW）。500 kW未満は過去1年間の最大需要電力（30分平均）［1］"],
  [B("家庭での例え"), "毎月の使用量に応じた料金", "契約アンペア（ブレーカー）の大きさ"],
  [B("本研究での値"), "30円/kWh（設定値）", "2,530円/kW・月［3］× 0.85（力率100%）［2］"]],
  tableOpts({ x: 0.6, y: 1.6, w: 12.1, colW: [2.2, 3.9, 6.0], fontSize: 16, rowH: 0.7 }));
caption(s, "表1　事業者向け電気料金（高圧）の構成。出典［1］〜［3］", 0.6, 4.55, 12.1);
bullets(s, [
  "基本料金は過去1年間の最大値で決まるため、一度のピークがその後1年間の料金に影響する",
  "電気バスの充電が同じ時間帯に集中すると、このピークが大きくなる"], { x: 0.6, y: 5.1, w: 12.1, h: 1.4, fontSize: 17 });
s.addNotes("事業者向けの電気料金は、使った量に応じた電力量料金と、契約電力に応じた基本料金の2つからなります。500 kW未満の契約では、契約電力は過去1年間で最も大きかった30分平均の電力で決まります（実量制）。本研究の計算は15分ごとなので、15分間の最大で評価しており、やや厳しめの評価です。単価は東京電力EPの2026年4月からの料金表（関東・高圧・ベーシックプラン、税込）の値です。最適化の計算自体は旧単価1,890円で行っています。");

// ---- 2. Problem and solution approach
s = page(S2, "問題設定と解法");
const COLS = [
  ["決定変数（決めること）", ["各便の担当車両（電気・燃料）", "各車両の充電の時刻と量", "太陽光・蓄電池・買電の配分"]],
  ["制約条件（守るルール）", ["次の便の出発に間に合う", "電池残量が下限を下回らない", "充電器は同時に10基まで", "受電上限の超過分には追加費用"]],
  ["目的関数（最小化する費用）", ["1週間の総費用", "車両使用費・電気代・燃料代・超過分の費用", "基本料金を含む場合と含まない場合を比較"]]];
COLS.forEach(([head, items], i) => {
  const x = 0.6 + i * 4.1;
  text(s, head, { x, y: 1.55, w: 3.8, h: 0.45, fontSize: 17, bold: true, color: BLUE_DARK });
  s.addShape(pres.shapes.LINE, { x, y: 2.05, w: 3.8, h: 0, line: { color: GRID, width: 1 } });
  bullets(s, items, { x, y: 2.2, w: 3.8, h: 2.7, fontSize: 15 });
});
text(s, "解法", { x: 0.6, y: 4.45, w: 12.1, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });
bullets(s, [
  "便割当（Stage 1）と充電計画（Stage 2、15分刻み）の2段階に分け、混合整数計画問題として求解した［7］",
  "便割当は一括では解が改善しなかったため、一部の便のみを解き直す大近傍探索（LNS）［8］を併用した",
  "1時間ごとに計画を更新しながら1週間を運用し（ローリング）、その実行結果から費用を集計した"],
  { x: 0.6, y: 4.9, w: 12.1, h: 1.9, fontSize: 16, paraSpaceAfter: 6 });
s.addNotes("数理最適化は、決めること・守るルール・最小化したいものの3つを数式で書き、計算機で最もよい計画を探す方法です。時間割やシフト表を作るのに近いと考えてください。問題が大きいため、便割当と充電計画の2段階に分けて解いています。");

// ---- 2. Formulation
s = page(S2, "定式化（概略）");
const EQ_SCALE = 0.72;
const ROWS = [["目的関数", "objective"], ["便の被覆", "cover"], ["接続可能性", "connect"], ["電池残量", "soc"],
  ["充電器台数", "charger"], ["電力収支", "balance"], ["受電上限", "limit"], ["最大受電電力", "peak"]];
let ey = 1.55;
ROWS.forEach(([label, key]) => {
  const w = eqSize[key].w * EQ_SCALE, h = eqSize[key].h * EQ_SCALE, rowH = Math.max(h, 0.42) + 0.12;
  text(s, label, { x: 0.6, y: ey, w: 1.9, h: rowH - 0.12, fontSize: 15, bold: true, valign: "middle" });
  s.addImage({ path: path.join(__dirname, "eq", `${key}.png`), x: 2.55, y: ey + (rowH - 0.12 - h) / 2, w, h });
  ey += rowH;
});
text(s, [
  { text: "主な記号", options: { bold: true, breakLine: true } },
  { text: "u：車両の使用（車両・日）", options: { breakLine: true } },
  { text: "x：便 i の次に便 j を担当", options: { breakLine: true } },
  { text: "z, ξ：充電電力、充電中フラグ", options: { breakLine: true } },
  { text: "E：電池残量、e：走行消費", options: { breakLine: true } },
  { text: "g：買電量、s：上限超過量", options: { breakLine: true } },
  { text: "W：最大受電電力", options: { breakLine: true } },
  { text: "α：計画日数/30（月額の日割り）", options: { breakLine: true } },
  { text: "p", options: {} }, { text: "dem", options: { superscript: true } }, { text: "：基本料金単価（考慮しない場合は 0）", options: {} }],
  { x: 9.4, y: 1.6, w: 3.3, h: 4.0, fontSize: 13, color: SUB, lineSpacingMultiple: 1.25 });
text(s, [{ text: "記号は簡略化して示した。π＝500円/kWh（仮の値）、c" }, { text: "CO₂", options: { superscript: true } }, { text: "＝1円/kg、N" }, { text: "ch", options: { superscript: true } }, { text: "＝10。" }], { x: 0.6, y: 6.55, w: 12.1, h: 0.4, fontSize: 12, color: SUB });
s.addNotes("定式化の概略です。目的関数は、車両の使用費、電気代、上限を超えた分の追加費用、燃料代、CO₂費用、基本料金の合計です。基本料金を考慮しない場合は、最後の項を0にしています。受電上限は、超過量sを許したうえでsに費用をかける形にしています。最大受電電力Wは、各時刻の買電電力以上という制約で表しています。");

// ---- 2. Conditions
s = page(S2, "計算条件");
s.addTable([
  ["対象", "東急バス 渋21〜23系統（弦巻営業所）、時刻表は公共交通オープンデータ［6］"],
  ["運行", "1週間 1,704便"],
  ["車両", "電気バス35台・燃料バス25台（保有台数、固定）"],
  ["設備", "太陽光 1,000 kW（傾斜30°、pvlib［5］で斜面日射を算定）、蓄電池 6,000 kWh、充電器 90 kW × 10基"],
  ["受電上限", "90 / 200 / 400 / 800 kW（超過分に500円/kWhの追加費用、仮の値）"],
  ["対象期間", "冬・春・夏の代表週（基本料金を考慮する場合は秋も計算）"],
  ["単価・係数", "電力量 30円/kWh（設定値）、軽油 150円/L、CO₂ 軽油2.62 kg/L［4］・電力0.5 kg/kWh（仮の値）"],
  ["計算ケース", "基本料金を考慮しない 12ケース、考慮する 16ケース（計28ケース）"]].map(([k, v]) => [B(k), v]),
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.2, 9.9], fontSize: 15, rowH: 0.6 }));
caption(s, "表2　計算条件", 0.6, 6.45, 12.1);
s.addNotes("計算条件です。対象は東急バスの渋21から23系統で、弦巻営業所の1週間1,704便です。太陽光と蓄電池は、営業所に設置したと仮定した設定です。受電上限を4通り、季節を3〜4週、基本料金の有無の2通りで、計28ケースを計算しました。電力のCO₂係数0.5は仮の値で、東京電力EPの実値（令和6年度実績0.452）より大きめです。");

// ---- 3. Pillar A: grid limit vs BEV trip share
s = page(S3, "結果(A-1)　受電上限と電気バスの担当便");
const SEASONS = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
s.addChart(pres.charts.LINE, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc8, g, w).bev_trip_share_pct * 10) / 10) })),
  chart({ x: 0.6, y: 1.5, w: 7.6, h: 4.85, lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 7, chartColors: [BLUE_DARK, "7AB8E8", GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスが担当した便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図2　受電上限と電気バスの担当便の割合（基本料金を考慮しない場合、1,704便/週）", 0.6, 6.45, 7.6);
const shares = rc8.map((r) => r.bev_trip_share_pct), w90 = get(rc8, 90, WIN);
bullets(s, [
  `電気バスの担当便は${Math.min(...shares).toFixed(1)}〜${Math.max(...shares).toFixed(1)}%で、受電上限によらずほぼ一定だった`,
  `上限90 kWでも燃料バスへの振り替えは増えず、上限の超過分に追加費用を払う計画となった（冬：超過${fmt(w90.contract_over_limit_kwh)} kWh/週、約${Math.round(w90.contract_overage_cost / 1e4)}万円/週）`,
  "季節差（春がやや低い）は、受電上限による差より大きい"], { x: 8.6, y: 1.8, w: 4.2, h: 4.6, fontSize: 16 });
s.addNotes("柱Aの問いは、受電上限を下げると電気バスに任せられる便がどれだけ減るか、でした。結果は、上限を90 kWまで下げても、電気バスの担当便は92〜96%でほとんど変わりませんでした。燃料バスに振り替える代わりに、上限を超えた分の追加費用を払う計画になっています。なぜ振り替えが起きないかは、考察で述べます。");

// ---- 3. Pillar A: which trips go to diesel
s = page(S3, "結果(A-2)　燃料バスが担当した便の時間帯");
const BANDS = [["05-06", "早朝（5〜6時台）"], ["07-21", "日中（7〜21時台）"], ["22-", "深夜（22時以降）"]];
const iceShare = (g, b) => { const rs = iceHour.filter((r) => r.grid_limit_kw === g);
  return Math.round(rs.reduce((a, r) => a + r.bands[b].diesel / r.bands[b].total, 0) / rs.length * 1000) / 10; };
s.addChart(pres.charts.BAR, LIMITS.map((g) => ({ name: `${g} kW`, labels: BANDS.map((x) => x[1]), values: BANDS.map(([b]) => iceShare(g, b)) })),
  chart({ x: 0.6, y: 1.5, w: 7.6, h: 4.85, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", GREY, "7AB8E8", BLUE_DARK], showValue: true,
    dataLabelPosition: "outEnd", dataLabelFormatCode: "0", dataLabelFontSize: 10, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "燃料バスが担当した便 [%]" }));
caption(s, "図3　出発時間帯別の燃料バス担当率（冬・春・夏の平均、凡例は受電上限）", 0.6, 6.45, 7.6);
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };
bullets(s, [
  `燃料バスが担当したのは主に早朝（${rng("05-06")}）と深夜（${rng("22-")}）の便で、日中は${rng("07-21")}だった`,
  "この傾向は受電上限によらず同じで、上限を下げても燃料バスに戻る便は増えなかった",
  "時間帯は、時刻表の各便の出発時刻で分類した"], { x: 8.6, y: 1.8, w: 4.2, h: 4.6, fontSize: 16 });
s.addNotes("柱Aのもう一つの問いは、どの時間帯の便が先に燃料バスへ戻るか、でした。燃料バスが担当したのは主に早朝と深夜の便で、日中はほとんど電気バスでした。この傾向は受電上限を変えても同じでした。");

// ---- 3. Pillar A: CO2 against an all-diesel fleet
s = page(S3, "結果(A-3)　全車燃料バスとのCO₂比較");
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス（概算）", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バスと併用", labels: SE.map((x) => x[1]), values: SE.map(([w]) => Math.round(get(rc8, 800, w).total_co2_kg / 100) / 10) }],
  chart({ x: 0.6, y: 1.5, w: 7.6, h: 4.85, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]" }));
caption(s, "図4　1週間のCO₂排出量（併用は受電上限800 kW・基本料金を考慮しない場合）", 0.6, 6.45, 7.6);
bullets(s, ["電気バスとの併用により、CO₂は全車燃料バスと比べて約75〜85%少なかった",
  "全車燃料バスは走行距離から軽油量を求めた概算であり、最適化の結果ではない",
  "電力の係数0.5 kg/kWhは仮の値。実値0.452［4］で再計算しても削減率は約77〜86%"], { x: 8.6, y: 1.8, w: 4.2, h: 4.6, fontSize: 16 });
s.addNotes("CO₂の比較です。電気バスと併用すると、全部を燃料バスで走る場合より約8割少なくなります。電力の係数0.5は、東京電力EPの実値（令和6年度実績0.452）より大きめで、電気バスに不利な側の仮定です。");

// ---- 4. Pillar C: peak
s = page(S4, "結果(C-1)　基本料金の考慮による受電ピークの低減");
s.addChart(pres.charts.BAR, [
  { name: "基本料金を考慮しない", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc8, g, WIN).peak_grid_kw)) },
  { name: "基本料金を考慮する", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(rc9, g, WIN).peak_grid_kw)) }],
  chart({ x: 0.6, y: 1.5, w: 7.6, h: 4.85, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "最大受電電力 [kW]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図5　冬季代表週（2025年1月6日〜）の最大受電電力", 0.6, 6.45, 7.6);
bullets(s, [
  `考慮しない場合：${fmt(Math.min(...LIMITS.map((g) => get(rc8, g, WIN).peak_grid_kw)))}〜${fmt(Math.max(...LIMITS.map((g) => get(rc8, g, WIN).peak_grid_kw)))} kW`,
  `考慮する場合：${fmt(Math.min(...LIMITS.map((g) => get(rc9, g, WIN).peak_grid_kw)))}〜${fmt(Math.max(...LIMITS.map((g) => get(rc9, g, WIN).peak_grid_kw)))} kW（低減率25〜50%）`,
  "受電上限は超過分に追加費用を課す目安のため、ピークが上限を上回る場合がある",
  "電気バスが担当する便の割合は92〜96%で、ほぼ変化しなかった"], { x: 8.6, y: 1.8, w: 4.2, h: 4.6, fontSize: 16 });
s.addNotes("冬の1週間で最も大きかった15分間の買電電力を比べました。灰色が基本料金を考慮しない場合、青が考慮した場合です。考慮すると、受電上限によらず約370 kW前後に下がりました。90 kWや200 kWの上限では、ピークが上限を超えています。上限は超えた分に追加費用がかかる目安なので、計算上は超えることがあります。全便を運行し、実際に使ったのは電気バス26〜34台・燃料バス5〜7台です。");

// ---- 3. Result: night profile
s = page(S4, "結果(C-2)　ピーク低減の要因");
s.addChart(pres.charts.LINE, [
  { name: "基本料金を考慮しない", labels: night.labels, values: night.rc8_grid_kw },
  { name: "基本料金を考慮する", labels: night.labels, values: night.rc9_grid_kw }],
  chart({ x: 0.6, y: 1.5, w: 7.6, h: 4.85, lineSize: 2.5, lineDataSymbol: "none", valAxisMinVal: 0, catAxisLabelFrequency: 4, catAxisLabelFontSize: 12,
    showValAxisTitle: true, valAxisTitle: "買電電力 [kW]" }));
caption(s, "図6　受電上限90 kW・冬季の一晩（22時〜8時）における買電電力（15分値）", 0.6, 6.45, 7.6);
bullets(s, [
  `最大値：${fmt(Math.max(...night.rc8_grid_kw))} kW → ${fmt(Math.max(...night.rc9_grid_kw))} kW`,
  `1週間の買電量はほぼ同じ（${night.week_grid_kwh[0].toLocaleString()} → ${night.week_grid_kwh[1].toLocaleString()} kWh）`,
  "車庫に停車している夜間全体に充電を分散させ、ピークを抑えていた",
  "買電の96%は夜間（22〜6時）。日中の充電は主に太陽光と蓄電池でまかなわれていた"], { x: 8.6, y: 1.8, w: 4.2, h: 4.6, fontSize: 16 });
s.addNotes("なぜ下がったのかを一晩の買電の推移で見ます。灰色は短時間に多く買っていますが、青は同じくらいの量を夜の長い時間に分けて買っています。この例では買電量がほぼ同じなので、電力量料金はあまり変わらず、基本料金だけが下がります。");

// ---- 3. Result: annual basic charge
s = page(S4, "結果(C-3)　年間の基本料金");
s.addChart(pres.charts.BAR, [
  { name: "基本料金を考慮しない", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc8, g)) / 1e4)) },
  { name: "基本料金を考慮する", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(basicYear(peakYear(rc9, g)) / 1e4)) }],
  chart({ x: 0.6, y: 1.5, w: 7.6, h: 4.85, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "基本料金 [万円/年]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図7　年間の基本料金（契約電力＝代表週（冬・春・夏）の最大受電電力、単価［3］）", 0.6, 6.45, 7.6);
const b8 = Math.round(basicYear(peakYear(rc8, 90)) / 1e4), b9 = Math.round(basicYear(peakYear(rc9, 90)) / 1e4);
bullets(s, [`受電上限90 kW：年 ${b8.toLocaleString()}万円 → ${b9.toLocaleString()}万円`, "いずれの受電上限でも約2.5〜5割減少した",
  "電力量料金の増減は1週間で最大約2万円であり、基本料金の差と比べて小さい",
  "算定式：最大受電電力 × 2,530円/kW × 0.85 × 12か月"], { x: 8.6, y: 1.8, w: 4.2, h: 4.6, fontSize: 16 });
s.addNotes("ピークが下がると、年間の基本料金が下がります。90 kWの例では年に約645万円の差です。買電量は条件によって−11%〜+19%変わりましたが、電力量料金の差は1週間で最大約2万円です。単価が変わっても、削減の割合は変わりません。");

// ---- 3. Results table
s = page(S4, "結果(C)の一覧（冬季代表週）");
const row = (g) => {
  const a = get(rc8, g, WIN), b = get(rc9, g, WIN);
  return [`${g} kW`, fmt(a.peak_grid_kw), fmt(b.peak_grid_kw), fmt(a.grid_import_kwh), fmt(b.grid_import_kwh),
    a.bev_trip_share_pct.toFixed(1), b.bev_trip_share_pct.toFixed(1), fmt(basicYear(peakYear(rc8, g)) / 1e4), fmt(basicYear(peakYear(rc9, g)) / 1e4)];
};
s.addTable([
  [H("受電上限", { rowspan: 2 }), H("最大受電電力 [kW]", { colspan: 2 }), H("買電量 [kWh/週]", { colspan: 2 }), H("電気バス担当便 [%]", { colspan: 2 }), H("年間基本料金 [万円]", { colspan: 2 })],
  [H("考慮なし"), H("考慮あり"), H("考慮なし"), H("考慮あり"), H("考慮なし"), H("考慮あり"), H("考慮なし"), H("考慮あり")],
  ...LIMITS.map((g) => row(g).map((v, i) => ({ text: v, options: { align: i === 0 ? "center" : "right", bold: i === 0, color: i > 0 && i % 2 === 0 ? BLUE_DARK : INK } })))],
  tableOpts({ x: 0.6, y: 1.6, w: 12.1, colW: [1.5, 1.325, 1.325, 1.325, 1.325, 1.325, 1.325, 1.325, 1.325], fontSize: 15, rowH: 0.55 }));
caption(s, "表3　基本料金の考慮の有無による比較（年間基本料金は冬・春・夏の最大受電電力から算定）", 0.6, 5.0, 12.1);
bullets(s, [
  "基本料金を考慮すると、受電ピークはいずれの上限でも359〜380 kWとなった",
  "買電量と電気バスの担当便の割合の変化は、受電ピークの変化と比べて小さい"], { x: 0.6, y: 5.5, w: 12.1, h: 1.3, fontSize: 16 });
s.addNotes("冬の代表週の結果を一覧にしました。青い数字が基本料金を考慮した場合です。ピークは大きく下がる一方、買電量と電気バスの割合はあまり変わっていません。");

// ---- 4. Discussion
s = page(S5, "考察");
text(s, "得られた知見", { x: 0.6, y: 1.5, w: 12.1, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });
bullets(s, [
  "柱A：受電上限を下げても電気バスの担当便は減らず、燃料バスが担当するのは早朝・深夜の便に限られた。今回の条件では、上限は「担当便の配分」ではなく「超過費用」として効いている",
  "柱C：基本料金を考慮すると、受電上限の値によらずピークは359〜380 kWにそろった。ピークの水準は、上限よりも必要な充電量と夜間に充電できる時間の長さで決まっていると考えられる",
  "基本料金の差（年309〜976万円）は電力量料金の差（最大約2万円/週）より大きく、ピーク抑制の効果が費用面で支配的である"],
  { x: 0.6, y: 1.95, w: 12.1, h: 2.3, fontSize: 14 });
text(s, "課題と限界", { x: 0.6, y: 4.3, w: 12.1, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });
bullets(s, [
  "便割当の段階では28ケース中25ケースで買電量を0（残り3ケースも174〜692 kWh）と見込んでいたが、実際の充電計画では1週間に2,069〜6,303 kWhを買電した。2段階で解く際の見込みのずれが、燃料バスへの振り替えが起きない一因と考えられる",
  "結果はいずれも制限時間内に得られた計画であり（基本料金を考慮する充電計画のギャップ13〜67%）、最適性は確認できていない",
  "1週間で区切っているため、週の終わりに蓄電池を下限（20%）まで使う。超過費用500円/kWhと電力のCO₂係数は仮の値である"],
  { x: 0.6, y: 4.75, w: 12.1, h: 2.2, fontSize: 14 });
s.addNotes("考察です。柱Aでは、受電上限を下げても電気バスの担当便は減りませんでした。基本料金を考慮すると、受電上限によらずピークが同じくらいの水準にそろいました。必要な充電量と夜の長さで決まっていると考えています。一方で課題もあります。便割当の段階では、充電を太陽光と蓄電池でまかなえる見込みでしたが、実際には夜に電気を買っていました。2段階で解いていることによる見込みのずれで、燃料バスへの振り替えが起きない一因と考えています。これは推測で、今後確かめます。");

// ---- 5. Summary
s = page(S6, "まとめと今後の予定");
text(s, "まとめ", { x: 0.6, y: 1.5, w: 12.1, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });
bullets(s, [
  "柱A（12ケース）：受電上限を90〜800 kWで変えても、電気バスの担当便は92〜96%でほぼ一定。燃料バスは早朝・深夜の便を担当した。CO₂は全車燃料バスと比べて約75〜85%少なかった",
  "柱C（16ケース、前倒し）：基本料金を考慮すると、買電量を大きく変えずに受電ピークが25〜50%、年間の基本料金が約2.5〜5割減少した"],
  { x: 0.6, y: 1.95, w: 12.1, h: 2.2, fontSize: 16 });
text(s, "今後の予定（10月8日の研究方針に沿って）", { x: 0.6, y: 4.25, w: 12.1, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });
bullets(s, [
  "11月28日の中間発表まで：柱Aの深掘り（担当便が変わらない原因として、便割当段階の買電の見込みと実際の差を検証）、A0ポスターの作成",
  "中間発表後：柱C（30分デマンドの扱いと単価を確定して再計算）、柱B（日ごとの計画との比較、2〜3週）",
  "修士論文：柱A〜Cを合わせ、受電電力を抑えながら電気バスにどこまで便を任せられるかを結論とする"],
  { x: 0.6, y: 4.7, w: 12.1, h: 2.1, fontSize: 16 });
s.addNotes("まとめです。柱Aでは、受電上限を下げても電気バスの担当便はほぼ変わりませんでした。柱Cでは、基本料金を考慮して計画すると、買電量を大きく変えずに受電ピークと基本料金を下げられることを確認しました。今後は、便割当の段階の見込みと実際の差を確かめ、燃料バスに切り替えた方が有利になる条件を調べます。");

// ---- References
s = page("参考文献", "参考文献");
text(s, [
  "［1］東京電力エナジーパートナー：契約電力の決定方法（実量制），https://www.tepco.co.jp/ep/corporate/charge_c2/decision03.html（2026年10月19日閲覧）",
  "［2］東京電力エナジーパートナー：特別高圧・高圧のお客さま向けの電気料金プランについて（計算式），https://www.tepco.co.jp/ep/corporate/plan_h/minaoshi_2025plan.html（2026年10月20日閲覧）",
  "［3］東京電力エナジーパートナー：電気料金単価表（特別高圧・高圧），2026年4月1日実施，高圧・ベーシックプラン（関東）",
  "［4］環境省・経済産業省：算定方法・排出係数一覧（軽油）；電気事業者別排出係数（令和6年度実績），2026年1月公表・2月更新",
  "［5］W. F. Holmgren, C. W. Hansen, M. A. Mikofski: pvlib python: a python package for modeling solar energy systems, Journal of Open Source Software, 3(29), 884, 2018",
  "［6］公共交通オープンデータセンター：東急バス 時刻表データ（ODPT）",
  "［7］Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual",
  "［8］P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, Proc. CP-98, LNCS 1520, pp. 417–431, 1998"]
  .map((t, i, a) => ({ text: t, options: { breakLine: i < a.length - 1 } })),
  { x: 0.6, y: 1.55, w: 12.1, h: 5.35, fontSize: 13, paraSpaceAfter: 8, lineSpacingMultiple: 1.12 });

(async () => {
  const out = path.join(__dirname, "lab_progress_20261022.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
