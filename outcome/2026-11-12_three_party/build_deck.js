// Three-party monthly meeting (2026-11-12): Prof. Urabe and Prof. Nakajima.
// Pillar A results on rc18 (12 verified cases, DIAGNOSTIC), the 10/22 lab questions, the Stage 2
// bottleneck found on 11/2-11/3 and the plan to the 11/28 midterm. Same visual style as the
// 10/22 lab deck (white, Tokyo City University blue #0485D7, Yu Gothic). Every number below is read
// from cases_rc18.json / ice_by_hour_rc18.json / all_diesel_estimate.csv unless marked as an input fact.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(path.join(process.env.PPTX_SKILL, "scripts", "apply_theme.js"));

const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "cases_rc18.json"), "utf8"));
if (cases.length !== 12 || cases.some((r) => r.status !== "VERIFIED")) throw new Error("expected 12 VERIFIED rc18 cases");
const iceHour = JSON.parse(fs.readFileSync(path.join(__dirname, "ice_by_hour_rc18.json"), "utf8"));
const eqSize = JSON.parse(fs.readFileSync(path.join(__dirname, "eq", "sizes.json"), "utf8"));
const dl = fs.readFileSync(path.join(__dirname, "all_diesel_estimate.csv"), "utf8").replace(/^﻿/, "").trim().split(/\r?\n/);
const dk = dl[0].split(","), diesel = dl.slice(1).map((l) => Object.fromEntries(l.split(",").map((v, i) => [dk[i], v])));
const LIMITS = [90, 200, 400, 800];
const SEASONS = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const WIN = "2025-01-06";
const get = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const byLimit = (g) => cases.filter((r) => r.grid_limit_kw === g);
const avg = (g, k) => byLimit(g).reduce((a, r) => a + r[k], 0) / byLimit(g).length;
const fmt = (n) => Math.round(n).toLocaleString("ja-JP");
const man = (n) => (n / 1e4).toFixed(1);

const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_LIGHT = "7AB8E8", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2";
const THEME = { name: "TCU white", headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "三者ミーティング 2026-11-12";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 26, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } },
            { line: { x: 0.6, y: 7.0, w: 12.1, h: 0, line: { color: GRID, width: 0.75 } } },
            { text: { text: "三者ミーティング　2026年11月12日　劉 承洋", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
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
const takeaway = (s, t) => {
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 1.45, w: 12.1, h: 0.62, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  text(s, t, { x: 0.85, y: 1.45, w: 11.75, h: 0.62, fontSize: 18, bold: true, valign: "middle" });
};
const flow = (s, items, y, h, lastHighlight = true) => items.forEach(([t, sub], i) => {
  const x = 0.6 + i * 3.1, last = lastHighlight && i === items.length - 1;
  s.addShape(pres.shapes.RECTANGLE, { x, y, w: 2.7, h, fill: { color: last ? "DCEBF7" : "F5F5F5" }, line: { color: last ? BLUE : GRID, width: 1 } });
  text(s, [{ text: t, options: { bold: true, breakLine: true, color: last ? BLUE_DARK : INK } },
    ...sub.split("／").map((u, j, arr) => ({ text: u, options: { fontSize: 13, color: SUB, breakLine: j < arr.length - 1 } }))],
    { x: x + 0.12, y, w: 2.46, h, fontSize: 16, align: "center", valign: "middle" });
  if (i < items.length - 1) s.addShape(pres.shapes.LINE, { x: x + 2.72, y: y + h / 2, w: 0.36, h: 0, line: { color: SUB, width: 1.5, endArrowType: "triangle" } });
});

const S0 = "前回からの進捗", S1 = "1. 研究背景と目的", S2 = "2. 問題設定と計算条件", S3 = "3. 結果：柱A 受電上限と電気バスの担当便",
  S4 = "4. 研究室の質問（10月22日）への回答", S5 = "5. 考察と課題", S6 = "6. まとめと今後の予定";

// Derived values used on several slides.
const shares = cases.map((r) => r.bev_trip_share_pct);
const shareMin = Math.min(...shares).toFixed(1), shareMax = Math.max(...shares).toFixed(1);
const opex = (g) => (avg(g, "electricity_cost") + avg(g, "fuel_cost") + avg(g, "contract_overage_cost")) / 1e4;
const fuelL = cases.map((r) => r.ice_fuel_consumed_l);
const w90 = get(90, WIN), w200 = get(200, WIN);
const co2Cut = SEASONS.map(([w]) => 1 - get(800, w).total_co2_kg / Number(diesel.find((d) => d.week === w).co2_kg));
const pct = (v) => `${Math.round(v * 100)}%`;

// ---- Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 1.7, w: 11.5, h: 1.9, fontSize: 34, bold: true, valign: "bottom" });
text(s, "― 柱A 受電上限と電気バスの担当便：12ケースの結果 ―", { x: 0.9, y: 3.7, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "三者ミーティング　2026年11月12日\n東京都市大学　劉 承洋", { x: 0.9, y: 4.6, w: 11.5, h: 1.0, fontSize: 18, color: SUB });
s.addNotes("それでは、11月の進捗をご報告します。修士1年の劉です。今日は、11月28日の中間発表の主軸である柱Aについて、計算の条件を見直したうえで12ケースをすべて計算し直した結果をご報告します。あわせて、10月22日の研究室で出た3つの質問への回答と、計算の中で見つかった課題、中間発表までの予定をお話しします。");

// ---- Contents with the three messages up front
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("本日の報告", { placeholder: "title" });
text(s, [S0, S1, S2, S3, S4, S5, S6].map((t, i) => ({ text: t, options: { breakLine: i < 6 } })), { x: 0.9, y: 1.6, w: 5.6, h: 4.6, fontSize: 19, paraSpaceAfter: 10 });
s.addShape(pres.shapes.RECTANGLE, { x: 6.9, y: 1.6, w: 5.8, h: 4.75, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
text(s, "本日お伝えしたいこと", { x: 7.15, y: 1.75, w: 5.3, h: 0.45, fontSize: 17, bold: true, color: BLUE_DARK });
bullets(s, [
  `受電上限を800 kWから90 kWまで下げても、電気バスの担当便は${shareMin}〜${shareMax}%でほぼ変わらない`,
  "400 kW以上では超過なし。超過が残るのは90 kW（3季節）と200 kWの冬",
  "超過は実行中に生じる。予報（平年値）の外れと、厳しい上限での充電計画の探索不足が関わる。対策を調査中"],
  { x: 7.15, y: 2.3, w: 5.3, h: 3.9, fontSize: 16, paraSpaceAfter: 12 });
s.addNotes("本日の流れです。最初に、前回からの進捗と、計算の条件の変更点をご説明します。そのあと柱Aの結果、研究室で出た質問への回答、考察と課題、今後の予定の順にお話しします。右側に、今日お伝えしたいことを3つまとめました。1つ目は、受電上限を下げても電気バスの担当便はほとんど変わらないこと。2つ目は、400 kW以上では超過がなく、超過が残るのは90 kWと200 kWの冬であること。3つ目は、超過は前日の計画ではなく実行中に生じ、太陽光予報の外れと、厳しい上限での充電計画の探索不足が関わっていることです。");

// ---- Progress since 10/8 and 10/22
s = page(S0, "前回の三者ミーティング（10月8日）からの進捗");
const ST = (t, done) => ({ text: t, options: { bold: true, align: "center", color: done ? BLUE_DARK : SUB, fill: { color: done ? "DCEBF7" : "F2F2F2" } } });
s.addTable([
  [H("項目"), H("内容"), H("状況"), H("補足")],
  [B("柱A の計算"), "冬・春・夏 × 受電上限 90/200/400/800 kW の12ケース", ST("完了", true), "条件を見直して計算し直した（変更点は8ページ）。12件とも結果の検算済み"],
  [B("便割当の見込みの修正"), "10/22 の考察「便割当の段階の見込みが楽観的」への対応", ST("要対応", false), "10/25に修正（rc13）。最新版では毎朝の条件の差で再びずれ（監査、5章）"],
  [B("研究室の質問"), "特別な週、季節ごとの電力量、充電の分散", ST("回答", true), "4章"],
  [B("充電計画の改善"), "厳しい上限で充電計画の探索が不足する問題", ST("調査中", false), "初期解を与える試行は効果なし（11/3）。原因を調査中"],
  [B("柱B"), "日ごとの計画と、日をまたいだ計画の比較", ST("実装中", false), "設計を決定（10/30）。日ごとの計画をつなぐ部分を実装中"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.6, 4.3, 1.2, 4.0], fontSize: 14, rowH: 0.78 }));
caption(s, "柱A：受電上限と電気バスの担当便（中間発表の主軸）、柱B：日をまたいだ計画の意味（年末まで）", 0.6, 6.45, 12.1);
s.addNotes("前回からの進捗です。柱Aの12ケースは、条件を見直したうえですべて計算し直し、12件とも結果の検算が済んでいます。10月22日の研究室で、便を割り当てる段階の見込みが楽観的だという考察をお話ししましたが、走行中にも充電できるとみなしていた点を10月25日に修正しました。ただし、11月3日の監査で、最新の版では毎朝の条件の差のために、また見込みがずれていることが分かりました。これは5章でご説明します。研究室で出た3つの質問には4章でお答えします。一方で、厳しい受電上限では充電計画の探索が足りないという問題が見つかり、11月3日に初期解を与える対策を試しましたが効果がなかったため、原因を調べています。柱Bは10月30日に設計を決め、日ごとの計画をつなぐ部分を実装しています。");

// ---- Background and objective
s = page(S1, "研究背景と目的");
heading(s, "背景", 1.45);
flow(s, [["電気バスの導入が進む", "脱炭素（GX）に向けて"], ["当面は燃料バスと併用", "車両価格・充電時間の制約"], ["夜にまとめて充電", "営業所で多くのバスが同時に"], ["受電電力が大きくなる", "受電設備・電気料金の負担"]], 1.95, 1.25);
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
s.addNotes("研究の背景と目的を簡単に振り返ります。電気バスの導入が進んでいますが、当面は燃料バスとの併用が続くと考えられます。電気バスは夜に営業所でまとめて充電するため、受電電力が大きくなります。本研究では、便の割当と充電計画を合わせて最適化し、受電上限と電気バスの担当便の関係を調べる柱Aと、日をまたいで計画することの意味を調べる柱Bの2つを明らかにします。今日は柱Aが中心です。");

// ---- Problem and approach
s = page(S2, "問題設定と解法");
[["決めること", "各便の担当車両（電気・燃料）／各車両の充電の時刻と量／太陽光・蓄電池・買電の配分"],
 ["守るルール", "次の便の出発に間に合う／電池残量が下限を下回らない／毎朝の電池残量（下限80%）／充電器は同時に10基まで／受電上限の超過分には追加費用"],
 ["最小化する費用", "1週間の総費用／内訳：車両使用費、電気代、燃料代、超過分の費用"]].forEach(([head, body], i) => {
  const x = 0.6 + i * 4.1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.55, w: 3.9, h: 2.5, fill: { color: "F7F9FB" }, line: { color: GRID, width: 1 } });
  text(s, head, { x: x + 0.2, y: 1.65, w: 3.5, h: 0.45, fontSize: 16, bold: true, color: BLUE_DARK });
  text(s, body.split("／").map((t, j, a) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: j < a.length - 1 } })), { x: x + 0.2, y: 2.15, w: 3.5, h: 1.85, fontSize: 14, paraSpaceAfter: 4 });
});
heading(s, "解法の流れ", 4.25);
flow(s, [["便割当（Stage 1）", "各便の担当車両を決める"], ["充電計画（Stage 2）", "15分ごとの充電を決める"], ["毎時の見直し", "1時間ごとに充電を立て直す"], ["費用・CO₂の集計", "実行した結果から求める"]], 4.75, 1.2);
caption(s, "求解：Gurobi［4］。便割当は一部の便だけを解き直す大近傍探索（LNS）［5］で90分改善。便割当は実行中に変えない", 0.6, 6.1, 12.1);
s.addNotes("計算の方法です。決めることは各便の担当車両と充電の時刻と量、守るルールは時刻表、電池残量、毎朝の電池残量、充電器の台数、受電上限です。最小化するのは1週間の総費用です。問題が大きいので、まず便の割当を決め、次に15分ごとの充電計画を決め、さらに1時間ごとに充電を立て直しながら1週間を運用し、実行した結果から費用とCO₂を集計しています。便の割当は、一部の便だけを解き直す方法で90分改善しています。");

// ---- Formulation
s = page(S2, "定式化（概略）");
const EQ_SCALE = 0.72;
let ey = 1.6;
[["目的関数", "objective"], ["便の被覆", "cover"], ["接続可能性", "connect"], ["電池残量", "soc"], ["充電器台数", "charger"], ["電力収支", "balance"], ["受電上限", "limit"]].forEach(([label, key]) => {
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
text(s, [{ text: "10月22日と同じ式。追加：毎朝の電池残量 ≥ 80%、90%に届かない分に50円/kWh（充電計画の中だけの重み。費用の集計には入れない）。π＝500円/kWh（仮の値）、c" },
  { text: "CO₂", options: { superscript: true } }, { text: "＝1円/kg、N" }, { text: "ch", options: { superscript: true } }, { text: "＝10。" }],
  { x: 0.6, y: 6.3, w: 12.1, h: 0.6, fontSize: 12, color: SUB });
s.addNotes("式は10月22日にお見せしたものと同じです。変わったのは毎朝の電池残量の扱いで、電気バスは毎朝80%以上で出発し、90%に届かない分には1 kWhあたり50円の重みをかけています。この50円は、なるべく満充電にするための計画上の重みで、費用の集計には入れていません。上限を超えた分の費用500円は、引き続き仮の値です。");

// ---- Conditions
s = page(S2, "計算条件");
s.addTable([
  ["対象", "東急バス 渋21〜23系統（弦巻営業所）、時刻表は公共交通オープンデータ［3］。1週間 1,704便"],
  ["車両", "電気バス35台・燃料バス25台（保有台数、固定）"],
  ["設備", "太陽光 1,000 kW（傾斜30°、pvlib［2］で斜面日射を算定）、蓄電池 6,000 kWh（使える範囲20〜80%）、充電器10基"],
  ["受電上限", "90 / 200 / 400 / 800 kW（超過分に500円/kWhの追加費用、仮の値）"],
  ["対象期間", "冬・春・夏の代表週（2025年1月6日・4月7日・7月7日から各1週間）"],
  ["毎朝の電池", "目標90%、下限80%（10月22日の結果では毎朝ほぼ満充電を必須にしていた）"],
  ["単価・係数", "電気 30円/kWh（基本料金を含む包括単価）、軽油 150円/L、車両使用費 2万円/台・日、CO₂ 軽油2.62 kg/L［1］・電力0.5 kg/kWh（仮の値）"],
  ["計画と実行", "前日に1週間分を計画（太陽光は過去の実績から作った平年値の予報）、実行は実際の天気で1時間ごとに充電を立て直す"]].map(([k, v]) => [B(k), v]),
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.0, 10.1], fontSize: 14, rowH: 0.6 }));
caption(s, "表1　計算条件（10月8日からの変更の経緯は次ページ）", 0.6, 6.45, 12.1);
s.addNotes("計算条件です。対象と車両、設備、受電上限、代表週は10月22日と同じです。変わったのは毎朝の電池の条件で、以前は毎朝ほぼ満充電を必須にしていましたが、目標90%、下限80%としました。電気の単価30円は、基本料金を含めた包括的な単価として扱っています。また、前日の計画では太陽光を過去の実績から作った平年値で予報し、実行の段階では実際の天気に合わせて1時間ごとに充電を立て直しています。この予報の扱いが、後の考察で重要になります。");

// ---- What changed since the previous three-party meeting (10/8)
s = page(S2, "前回の三者ミーティング（10月8日）からの変更点（9点）");
s.addTable([
  [H("時期"), H("項目"), H("変更の内容"), H("理由・確認したこと")],
  ["10/9", B("CO₂係数"), "軽油を2.62 kg/Lに統一（以前は2.58〜2.67が混在）", "10/8の宿題（下準備1）"],
  ["10/9", B("太陽光"), "傾斜30°・真南の斜面日射（pvlib）", "10/8の宿題（下準備2）"],
  ["10/10", B("受電上限"), "上限を超えることを許し、超過分に500円/kWh（仮の値）", "受電上限を物理的な上限ではなく契約の目安として扱う（10/10に決定）"],
  ["10/10", B("燃料バス"), "初期の軽油残量を40〜90%でばらつかせる", "10/10に決定"],
  ["10/11", B("便割当の解き方"), "一部の便だけを解き直す大近傍探索（LNS）を追加", "汎用ソルバーだけでは初期解から改善しなかった"],
  ["10/27", B("電気料金"), "30円/kWhは基本料金を含む包括単価。基本料金は足さず目安として示す", "基本料金を目的関数に入れた試行（10/14）は二重計上になる"],
  ["10/22〜25", B("便割当の見込み"), "走行中の充電と翌朝の期限の漏れを修正", "修正後（rc13）は見込みと実際の買電の差が2〜10%"],
  ["11/1", B("毎朝の電池"), "目標90%・下限80%、90%に届かない分に50円/kWh（以前はほぼ満充電を必須）", "柱Bの日ごとの計画と条件をそろえるため"],
  ["10/31〜11/2", B("計算時間"), "便割当はrc13の400 kWの割当から始めてLNS 90分。毎時の立て直しは1回120秒", "柱Bの計算量を減らすため（モデルの式は同じ）"]],
  tableOpts({ x: 0.6, y: 1.5, w: 12.1, colW: [1.25, 1.85, 4.9, 4.1], fontSize: 12, rowH: 0.47 }));
caption(s, "表2　日付は変更を決めた日。12ケースはすべて最新の版（rc18）で計算し直した。11/3に試した充電計画の初期解は効果がなく不採用", 0.6, 6.55, 12.1, 0.35);
s.addNotes("前回の三者ミーティング、10月8日からの変更点をまとめました。10月9日に、宿題だった燃料バスのCO₂係数と、太陽光パネルを30度傾けたときの日射を反映しました。10月10日には、受電上限を物理的な上限ではなく契約の目安として扱い、超えた分に費用をかける形にしました。また燃料バスの初期の軽油残量にばらつきを入れました。10月11日には、便の割当が初期解から改善しなかったので、一部の便だけを解き直す方法を加えました。電気料金は、30円が基本料金を含む単価なので、基本料金は足さずに目安として示すことにしました。10月22日から25日には、便割当の段階で走行中にも充電できるとみなしていた点と、翌朝の期限が抜けていた点を直しました。11月1日には、毎朝の電池を目標90%、下限80%にしました。また計算時間を減らすため、便割当は前の版の400 kWの割当から始め、毎時の立て直しは1回120秒にしています。どれも結果に影響するので、12ケースはすべて最新の版で計算し直しました。");

// ---- A-1 BEV share
const CH = { x: 0.6, y: 2.25, w: 7.2, h: 4.1 }, RB = { x: 8.1, y: 2.4, w: 4.65, h: 3.9, fontSize: 16 };
s = page(S3, "結果(A-1)　受電上限と電気バスの担当便");
takeaway(s, `受電上限を800 kWから90 kWまで下げても、電気バスの担当便は${shareMin}〜${shareMax}%でほぼ変わらない`);
s.addChart(pres.charts.LINE, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(g, w).bev_trip_share_pct * 10) / 10) })),
  chart({ ...CH, lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 7, chartColors: [BLUE_DARK, BLUE_LIGHT, GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスが担当した便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図1　受電上限と電気バスの担当便の割合（1,704便/週）", 0.6, 6.45, 7.6);
bullets(s, [
  "上限90 kWでも、燃料バスへの振り替えは起きなかった",
  "上限による差より、季節による差（春がやや低い）の方が大きい",
  "注意：4つの上限とも同じ割当（rc13の400 kW）から90分改善した。最終の割当の78〜98%の便が出発点と同じ車両",
  "出発点を共有しないrc13でも91.7〜95.7%で同じ傾向"], { ...RB, fontSize: 15 });
s.addNotes(`ここから柱Aの結果です。横軸が受電上限、縦軸が電気バスの担当した便の割合です。受電上限を800 kWから90 kWまで下げても、電気バスの担当便は${shareMin}から${shareMax}%で、ほとんど変わりませんでした。便割当の見込みを修正した後も、10月22日と同じ傾向です。上限による差より、季節による差の方が大きく、春がやや低くなっています。ただし注意点があります。今回は計算時間を減らすため、4つの上限とも同じ割当、前の版の400 kWの割当から始めて90分改善しており、最終の割当の78から98%の便は出発点と同じ車両のままです。そのため、この結果だけでは「上限によらない」とまでは言えません。ただ、出発点を共有していない前の版でも91.7から95.7%で同じ傾向でした。`);

// ---- A-2 overage by limit and season
s = page(S3, "結果(A-2)　受電上限の超過量");
takeaway(s, "400 kW以上では超過なし。超過が残るのは90 kW（3季節）と200 kWの冬");
s.addChart(pres.charts.BAR, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(g, w).contract_over_limit_kwh)) })),
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK, BLUE_LIGHT, GREY], showValue: true, dataLabelPosition: "outEnd",
    dataLabelFormatCode: "#,##0", dataLabelFontSize: 11, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "上限を超えた電力量 [kWh/週]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図2　受電上限と季節ごとの超過電力量（1週間）", 0.6, 6.45, 7.6);
bullets(s, [
  `冬・90 kW：${fmt(w90.contract_over_limit_kwh)} kWh、最大受電 ${fmt(w90.peak_grid_kw)} kW`,
  `冬・200 kW：${fmt(w200.contract_over_limit_kwh)} kWh、最大受電 ${fmt(w200.peak_grid_kw)} kW`,
  "200 kWの春・夏、400・800 kWはほぼ0",
  "前日計画（予報）の段階では12ケースとも超過0。超過は実行中に生じる（考察）"], RB);
s.addNotes(`次に、受電上限を超えた電力量です。400 kW以上では、どの季節も超過はありません。200 kWでは春と夏はほぼ0で、超過が残るのは冬だけです。90 kWでは3つの季節すべてで超過があり、冬が最も多く、1週間で${fmt(w90.contract_over_limit_kwh)} kWhでした。なお、前日に立てた計画の段階では、12ケースすべてで超過は0でした。超過は、実際の天気で1時間ごとに立て直しながら実行する中で生じています。その理由は考察でご説明します。`);

// ---- A-3 operating cost
s = page(S3, "結果(A-3)　受電上限と運用費");
takeaway(s, "上限を下げて増える費用は、ほぼすべて超過分の追加費用。電気代と燃料代はほぼ一定");
s.addChart(pres.charts.BAR, [
  { name: "電気代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "electricity_cost") / 1e3) / 10) },
  { name: "燃料代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "fuel_cost") / 1e3) / 10) },
  { name: "超過分の追加費用", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "contract_overage_cost") / 1e3) / 10) }],
  chart({ ...CH, barDir: "col", barGrouping: "stacked", chartColors: [BLUE, GREY, "CFCFCF"], valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "運用費 [万円/週]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図3　受電上限と1週間の運用費の内訳（冬・春・夏の平均、車両使用費は除く）", 0.6, 6.45, 7.6);
bullets(s, [
  `運用費：約${Math.round(opex(800))}万円/週（800 kW）→ 約${Math.round(opex(90))}万円/週（90 kW）`,
  `400 kW → 800 kW の差は、各季節で2.7万円/週以下`,
  `燃料使用量：${Math.round(Math.min(...fuelL))}〜${Math.round(Math.max(...fuelL))} L/週（季節で決まり、上限ではほぼ変わらない）`,
  `車両使用費（約${Math.round(Math.min(...cases.map((r) => r.vehicle_usage_cost)) / 1e4)}〜${Math.round(Math.max(...cases.map((r) => r.vehicle_usage_cost)) / 1e4)}万円/週）は図から除いた`], RB);
s.addNotes(`費用の内訳です。棒は1週間の運用費で、3つの季節の平均です。上限を800 kWから90 kWに下げると、運用費は約${Math.round(opex(800))}万円から約${Math.round(opex(90))}万円に増えますが、増えたのはほぼすべて超過分の追加費用です。電気代と燃料代はほとんど変わりません。また、400 kWから800 kWに上げても、費用は各季節で2.7万円以下しか下がらず、今回の設定では400 kWを超える上限はほとんど費用を下げません。なお、超過分の500円は仮の値で、実際の料金ではない点にご注意ください。`);

// ---- A-4 diesel trips by departure band
s = page(S3, "結果(A-4)　燃料バスが担当した便の時間帯");
const BANDS = [["05-06", "早朝（5〜6時台）"], ["07-21", "日中（7〜21時台）"], ["22-", "深夜（22時以降）"]];
const iceShare = (g, b) => { const rs = iceHour.filter((r) => r.grid_limit_kw === g);
  return Math.round(rs.reduce((a, r) => a + r.bands[b].diesel / r.bands[b].total, 0) / rs.length * 1000) / 10; };
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };
takeaway(s, "燃料バスが担当するのは主に早朝と深夜の便。受電上限を下げても増えない");
s.addChart(pres.charts.BAR, LIMITS.map((g) => ({ name: `${g} kW`, labels: BANDS.map((x) => x[1]), values: BANDS.map(([b]) => iceShare(g, b)) })),
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", GREY, BLUE_LIGHT, BLUE_DARK], showValue: true,
    dataLabelPosition: "outEnd", dataLabelFormatCode: "0", dataLabelFontSize: 10, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "燃料バスが担当した便 [%]" }));
caption(s, "図4　出発時間帯別の燃料バス担当率（冬・春・夏の平均、凡例は受電上限）", 0.6, 6.45, 7.6);
bullets(s, [`早朝：${rng("05-06")}`, `深夜：${rng("22-")}`, `日中：${rng("07-21")}`,
  "時間帯は、時刻表の各便の出発時刻で分類した", "早朝・深夜に偏る理由は未確認"], RB);
s.addNotes("どの時間帯の便が燃料バスに回っているかを見ました。燃料バスが担当したのは主に早朝の5時から6時台と、夜22時以降の便で、日中はほとんど電気バスが担当していました。この傾向は受電上限を変えてもほとんど同じで、10月22日と同じです。早朝・深夜に偏る理由は、まだ確かめていません。");

// ---- A-5 CO2
s = page(S3, "結果(A-5)　全車燃料バスとのCO₂比較");
takeaway(s, `電気バスと併用すると、CO₂は全車燃料バスより約${pct(Math.min(...co2Cut))}〜${pct(Math.max(...co2Cut))}少ない`);
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス（概算）", labels: SEASONS.map((x) => x[1]), values: SEASONS.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バスと併用（800 kW）", labels: SEASONS.map((x) => x[1]), values: SEASONS.map(([w]) => Math.round(get(800, w).total_co2_kg / 100) / 10) }],
  chart({ ...CH, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]" }));
caption(s, "図5　1週間のCO₂排出量（併用は受電上限800 kWの場合）", 0.6, 6.45, 7.6);
bullets(s, [
  "全車燃料バスは、同じ走行距離を軽油4.52 km/Lで換算した概算で、最適化の結果ではない",
  "電力の係数0.5 kg/kWhは仮の値",
  `受電上限による差は小さい（12ケースで${(Math.min(...SEASONS.map(([w]) => Math.min(...LIMITS.map((g) => get(g, w).total_co2_kg)))) / 1000).toFixed(1)}〜${(Math.max(...cases.map((r) => r.total_co2_kg)) / 1000).toFixed(1)} t/週）`], RB);
s.addNotes(`CO₂の比較です。灰色が全車燃料バスの場合、青が電気バスと併用した場合で、併用によりCO₂は約${pct(Math.min(...co2Cut))}から${pct(Math.max(...co2Cut))}少なくなりました。全車燃料バスの方は、同じ走行距離を燃費4.52 km/Lで軽油に換算した概算です。電力のCO₂係数0.5は仮の値です。受電上限による差は小さく、どのケースも1週間で1〜2トン台でした。`);

// ---- Results table (12 cases)
s = page(S3, "柱Aの結果の一覧（12ケース、1週間の実行結果）");
const S2label = (r) => r.stage2_solver_status === "optimal" ? "最適" : `時間切れ（${Math.round(r.stage2_mip_gap_ratio * 100)}%）`;
const rows = [];
LIMITS.forEach((g) => SEASONS.forEach(([w, n]) => { const r = get(g, w); const hot = r.contract_over_limit_kwh > 1;
  const c = (v) => ({ text: v, options: { align: "right", color: hot ? BLUE_DARK : INK, bold: hot } });
  rows.push([{ text: `${g} kW`, options: { align: "center" } }, { text: n, options: { align: "center" } },
    c(man(r.total_cost)), c(man(r.contract_overage_cost)), c(fmt(r.contract_over_limit_kwh)), c(fmt(r.peak_grid_kw)), c(fmt(r.grid_import_kwh)),
    c(r.bev_trip_share_pct.toFixed(1)), c(fmt(r.ice_fuel_consumed_l)), { text: S2label(r), options: { align: "center", color: r.stage2_solver_status === "optimal" ? INK : BLUE_DARK } }]); }));
s.addTable([[H("上限"), H("季節"), H("総費用 [万円]"), H("うち超過 [万円]"), H("超過 [kWh]"), H("最大受電 [kW]"), H("買電 [kWh]"), H("電気バス担当 [%]"), H("軽油 [L]"), H("充電計画")], ...rows],
  tableOpts({ x: 0.6, y: 1.5, w: 12.1, colW: [0.9, 0.8, 1.35, 1.35, 1.1, 1.25, 1.15, 1.45, 1.0, 1.75], fontSize: 12, rowH: 0.35 }));
caption(s, "表3　12ケースの結果。青字は超過のあるケース。総費用は車両使用費（約402〜408万円）を含む。充電計画は前日計画のStage 2の求解状態（括弧はギャップ）",
  0.6, 6.4, 12.1, 0.55);
s.addNotes("12ケースの結果を一覧にしました。青字が、上限を超過したケースです。総費用の大部分は車両の使用費で、1週間に約402万円から408万円です。右端は前日計画の充電計画を解いたときの状態で、冬の90 kWだけが1時間の制限時間で打ち切った解で、ギャップが26%残っています。他の11ケースは最適です。ただし、便割当の段階は全ケースで最適性が確認できていないので、週全体の最適ではありません。");

// ---- Lab questions
s = page(S4, "研究室の質問への回答（季節ごとの電力量・充電の分散・特別な週）");
const QF2 = [["冬", 24577, 4453, 3925, 16.4], ["春", 27819, 5590, 2431, 10.0], ["夏", 30189, 5805, 2388, 9.4]];
s.addChart(pres.charts.BAR, [
  { name: "太陽光で使えた量", labels: QF2.map((q) => q[0]), values: QF2.map((q) => q[1] - q[2]) },
  { name: "太陽光を捨てた量", labels: QF2.map((q) => q[0]), values: QF2.map((q) => q[2]) },
  { name: "買電", labels: QF2.map((q) => q[0]), values: QF2.map((q) => q[3]) }],
  chart({ x: 0.6, y: 1.55, w: 6.4, h: 4.6, barDir: "col", barGrouping: "clustered", chartColors: [BLUE, "CFCFCF", GREY], showValue: true, dataLabelPosition: "outEnd",
    dataLabelFormatCode: "#,##0", dataLabelFontSize: 10, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "電力量 [kWh/週]" }));
caption(s, "図6　季節ごとの太陽光と買電（各季節4ケースの平均）", 0.6, 6.25, 6.4);
s.addTable([
  [H("質問"), H("回答")],
  [B("季節ごとの電力量"), `バスの充電に占める買電の割合は冬16.4%、春10.0%、夏9.4%。春・夏は冬より買電が約1,500 kWh/週少ない`],
  [B("充電の分散"), "400 kWでは最大受電が上限ちょうどに収まり、分散できている。800 kWでは702〜792 kWで上限まで使わない。モデルの中で分散して下がるのは超過分の費用だけ（30円/kWhは包括単価）"],
  [B("特別な週（GWなど）"), "時刻表は日付ごとのものを使うので、祝日ダイヤ（181便/日、平日264便）は入る。GWの週そのものはまだ計算していない"]],
  tableOpts({ x: 7.3, y: 1.55, w: 5.4, colW: [1.5, 3.9], fontSize: 12, rowH: [0.45, 1.25, 1.6, 1.3] }));
s.addNotes("10月22日の研究室で出た3つの質問にお答えします。1つ目の季節ごとの電力量は、左の図のとおりで、バスの充電に占める買電の割合は冬16.4%、春10.0%、夏9.4%でした。太陽光の多い春・夏は、冬より買電が1週間で約1,500 kWh少なくなっています。2つ目の充電の分散は、400 kWでは最大受電が上限ちょうどに収まっており、充電を分散できています。ただし電気の単価は包括単価で扱っているので、モデルの中で分散して下がるのは超過分の費用だけです。3つ目の特別な週については、時刻表は日付ごとのものを使っているので祝日のダイヤは反映されますが、ゴールデンウィークの週そのものはまだ計算していません。");

// ---- Discussion 1: forecast
s = page(S5, "考察(1)　超過の出どころ：前日計画の太陽光予報は平年値");
takeaway(s, "前日計画は毎日ほぼ同じ平年値で計画するため、曇りの日の不足を前もって見込めない");
const FC = [3391, 3401, 3412, 3423, 3436, 3448, 3462], AC = [1399, 2640, 3836, 4871, 5059, 5079, 1693];
const DAYS = ["1/6(月)", "1/7(火)", "1/8(水)", "1/9(木)", "1/10(金)", "1/11(土)", "1/12(日)"];
s.addChart(pres.charts.BAR, [{ name: "前日計画の予報（平年値）", labels: DAYS, values: FC }, { name: "実際の発電", labels: DAYS, values: AC }],
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", BLUE], valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "太陽光の発電量 [kWh/日]" }));
caption(s, "図7　冬の代表週の日ごとの太陽光：予報と実際（入力データ。受電上限によらず同じ）", 0.6, 6.45, 7.6);
bullets(s, [
  "1週間の合計は予報と実際で1〜3%しか違わない",
  "晴れの日は蓄電池が満杯になって太陽光を捨て、曇りの日は蓄電池が空になって夜に買電する",
  "日をまたいで蓄電池の使い方を計画し直す方法を、柱Bで調べる"], RB);
s.addNotes("ここから考察です。超過の主な出どころの1つは、太陽光の予報です。前日の計画では、過去の実績から作った平年値で予報しているので、毎日ほぼ同じ3,400 kWh程度を見込んでいます。一方、実際の発電は冬の週で1日1,400から5,100 kWhと大きく変わります。1週間の合計はほぼ同じですが、晴れの日は蓄電池が満杯になって太陽光を捨て、曇りの日は蓄電池が空になって夜に買電することになります。そのため、曇りの日の不足を前もって見込めず、厳しい上限では超過が起きます。この点は柱Bで、日をまたいで蓄電池の使い方を計画し直す方法として調べます。");

// ---- Discussion 2: hourly re-planning under tight limits
s = page(S5, "考察(2)　厳しい上限では、毎時の立て直しが時間切れになりやすい");
takeaway(s, "超過は実行中に生じる。90・200 kWでは毎時の立て直し（1回120秒）の5〜23%が時間切れ");
const TL = { "90|2025-01-06": 34, "90|2025-04-07": 22, "90|2025-07-07": 41, "200|2025-01-06": 21, "200|2025-04-07": 9, "200|2025-07-07": 9 };
s.addChart(pres.charts.BAR, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => TL[`${g}|${w}`] || 0) })),
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK, BLUE_LIGHT, GREY], showValue: true, dataLabelPosition: "outEnd",
    dataLabelFormatCode: "0", dataLabelFontSize: 11, valAxisMinVal: 0, valAxisMaxVal: 50, showValAxisTitle: true, valAxisTitle: "時間切れの回数（1週間175回中）", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図8　毎時の立て直しで充電計画が制限時間（120秒）内に最適と確認できなかった回数", 0.6, 6.45, 7.6);
bullets(s, [
  "前日計画（予報）では12ケースとも超過0。予報より太陽光が少ない日に、立て直しで超過が出る",
  "時間切れの回は、その時点で見つかっている最良の計画を実行する",
  "実際の天気で前日計画を立てた診断（冬・90 kW）でも、充電計画は1時間で約77万円、下限は約31万円で差が大きい（DIAGNOSTIC）"], { ...RB, fontSize: 15 });
s.addNotes("考察の2つ目です。前日に立てた計画の段階では、12ケースすべてで超過は0でした。超過は、実際の天気で1時間ごとに充電を立て直しながら実行する中で出ています。図は、1週間175回の立て直しのうち、制限時間の120秒以内に最適と確認できなかった回数です。400 kW以上では0回ですが、90 kWでは22から41回、200 kWでは9から21回ありました。時間切れの回は、その時点で見つかっている最良の計画を実行しています。また、予報の影響を除くために実際の天気で前日計画を立てた診断でも、冬の90 kWでは充電計画が1時間で約77万円の解しか見つからず、理論上の下限約31万円との差が大きいままでした。厳しい上限では、充電計画を解く段階の探索が足りないと考えています。");

// ---- Model audit (11/3)
s = page(S5, "モデルの監査（11月3日）：便割当の段階の見込み");
takeaway(s, "今回の版では、便割当の段階が買電を少なく見込んでいる。原因は毎朝の条件の差と考えられる");
s.addTable([
  [H("確認したこと"), H("結果（12ケース）"), H("解釈と対応")],
  [B("便割当の段階の買電の見込み"), "冬 約260 kWh、春・夏 0 kWh。前日計画の充電計画は冬 約1,180 kWh、春・夏 190〜410 kWh（前の版rc13では差2〜10%）",
    "便割当の段階には「毎朝90%に届かない分の50円/kWh」が入っていない（下限80%だけ）。充電計画は30円/kWhで買って90%まで充電する（不足はほぼ0）。担当便の判断に影響しうる。対応を検討中"],
  [B("走行中の充電の見込み"), "見込みの1.2〜4.0%が、前日計画で走行中・回送中のコマにある（rc13も1.2〜3.9%）", "便割当の段階は充電計画より緩い問題として作ってあり、その範囲内"],
  [B("共通の出発点"), "最終の割当の78〜98%の便が出発点（rc13の400 kW）と同じ車両。担当便の割合は出発点との差が2ポイント以内", "上限による差が出にくい。出発点を共有しないrc13でも同じ傾向（結果A-1）"]],
  tableOpts({ x: 0.6, y: 2.3, w: 12.1, colW: [2.4, 4.6, 5.1], fontSize: 13, rowH: [0.45, 1.5, 0.95, 1.1] }));
caption(s, "表4　監査の結果（保存済みの12ケースの結果を読むだけで、計算はしていない。audit_stage1_recourse.py）", 0.6, 6.4, 12.1);
s.addNotes("11月3日に、モデルの監査として、便割当の段階の見込みを確かめました。1つ目は重要な点で、今回の版では、便割当の段階が見込む買電が、冬で約260 kWh、春と夏で0 kWhと、実際の充電計画の冬約1,180 kWh、春・夏190から410 kWhより大幅に少なくなっていました。前の版では差が2から10%でした。原因は毎朝の条件の差と考えています。充電計画には、毎朝90%に届かない分に1 kWhあたり50円の重みがあり、電気を30円で買って90%まで充電します。一方、便割当の段階には下限80%しか入っていません。そのため、便割当の段階は充電を少なく見込みます。担当便の判断に影響しうるので、対応を検討しています。2つ目に、走行中・回送中のコマへの充電の見込みは1から4%で、前の版と同程度、緩い問題として許される範囲でした。3つ目に、計算時間を減らすために4つの上限で同じ出発点を使ったため、割当の大部分が出発点と同じでした。");

// ---- Limitations
s = page(S5, "課題と結果の扱い");
takeaway(s, "本日の結果は診断用（DIAGNOSTIC）。研究の結論とするには下の課題を明記するか解消する");
s.addTable([
  [H("課題"), H("内容"), H("対応")],
  [B("便割当の最適性"), "全ケースでメモリ上限に当たって停止。証明できるギャップは約45%", "限界として明記。改善は柱Bと並行して検討"],
  [B("2段階法"), "便割当 → 充電計画の順に解くので、全体の総費用の最適ではない", "限界として明記"],
  [B("充電計画"), "冬・90 kWの前日計画は1時間で打ち切った解（ギャップ26%）。毎時の立て直しは90・200 kWで5〜23%が時間切れ", "原因の切り分け中（考察2）"],
  [B("便割当の見込み"), "毎朝の条件の差で、便割当の段階が買電を少なく見込む（監査）", "便割当の段階に同じ条件を入れるか検討"],
  [B("共通の出発点"), "4つの上限とも同じ割当から90分改善", "出発点を共有しないrc13と比べて明記"],
  [B("仮の値"), "超過費用500円/kWh、電力のCO₂係数0.5 kg/kWh、CO₂単価1円/kg", "値を変えた感度の確認"],
  [B("全車燃料バス"), "走行距離からの概算で、最適化の結果ではない", "限界として明記"]],
  tableOpts({ x: 0.6, y: 2.3, w: 12.1, colW: [2.6, 5.6, 3.9], fontSize: 13, rowH: 0.56 }));
s.addNotes("結果の扱いについてです。本日の結果は、すべて診断用の結果として扱っています。便割当は全ケースでメモリの上限に当たって止まっており、最適性が確認できていません。また2段階で解いているので、全体の総費用の最適ではありません。充電計画は、冬の90 kWの前日計画が制限時間で打ち切った解で、毎時の立て直しも厳しい上限では時間切れが多くあります。監査で分かった便割当の段階の見込みのずれと、共通の出発点の影響も課題です。超過費用やCO₂係数には仮の値が残っています。中間発表では、これらを限界として明記したうえで結果を示す予定です。");

// ---- Summary
s = page(S6, "まとめ");
[[`${shareMin}〜${shareMax}%`, "電気バスの担当便", "受電上限を800 kWから90 kWまで下げても、ほぼ変わらない"],
 ["超過 0 kWh", "受電上限 400 kW以上", "超過が残るのは90 kWと200 kWの冬／400 → 800 kWの費用差は2.7万円/週以下"],
 [`約${pct(Math.min(...co2Cut))}〜${pct(Math.max(...co2Cut))}減`, "CO₂（全車燃料バス比）", "電気バスとの併用による削減"]].forEach(([big, label, sub], i) => {
  const x = 0.6 + i * 4.1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.6, w: 3.9, h: 3.0, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  text(s, label, { x: x + 0.2, y: 1.75, w: 3.5, h: 0.45, fontSize: 15, color: SUB, align: "center" });
  text(s, big, { x: x + 0.1, y: 2.25, w: 3.7, h: 0.9, fontSize: 28, bold: true, color: BLUE_DARK, align: "center", valign: "middle" });
  text(s, sub.split("／").map((t, j, a) => ({ text: t, options: { breakLine: j < a.length - 1 } })), { x: x + 0.25, y: 3.25, w: 3.4, h: 1.2, fontSize: 14, align: "center" });
});
bullets(s, [
  "超過は前日計画ではなく実行中に生じる。予報（平年値）の外れと、毎時の立て直しの時間切れが関わる",
  "中間発表では本日の12ケースを、課題を明記したうえで示す。探索不足の対策は調査を続ける"],
  { x: 0.6, y: 4.95, w: 12.1, h: 1.8, fontSize: 17, paraSpaceAfter: 8 });
s.addNotes("まとめです。受電上限を800 kWから90 kWまで下げても、電気バスの担当便はほとんど変わりませんでした。400 kW以上では超過がなく、400 kWから800 kWに上げても費用はほとんど下がりません。電気バスとの併用で、CO₂は全車燃料バスより大きく減ります。超過は前日の計画ではなく実行中に生じ、太陽光予報の外れと、毎時の立て直しの時間切れが関わっています。また監査で、便割当の段階の見込みのずれと、共通の出発点の影響という課題が見つかりました。中間発表では本日の12ケースを、課題を明記したうえでお見せする予定です。");

// ---- Plan
s = page(S6, "今後の予定");
const PERIODS = ["11月上旬", "11月中旬", "11月下旬", "12月前半", "12月後半", "1月〜"];
const GX = 5.0, GW = (12.7 - GX) / PERIODS.length, GY = 1.6, RH = 0.62;
PERIODS.forEach((p, i) => {
  s.addShape(pres.shapes.RECTANGLE, { x: GX + i * GW, y: GY, w: GW, h: 0.5, fill: { color: HEAD }, line: { color: GRID, width: 0.75 } });
  text(s, p, { x: GX + i * GW, y: GY, w: GW, h: 0.5, fontSize: 13, bold: true, align: "center", valign: "middle" });
});
const TASKS = [["柱A", "充電計画の探索不足の原因と対策", 0, 2], ["柱A", "中間発表（11/28、A0ポスター）の準備", 1, 3],
  ["柱B", "日ごとの計画をつなぐ仕組みの実装", 0, 3], ["柱B", "冬・春・夏 × 2方式の計算", 3, 4], ["柱B", "集計と年内の報告", 4, 5], ["3本目", "運行・利用者の観点（内容は検討中）", 5, 6]];
TASKS.forEach(([p, label, a, b], i) => {
  const y = GY + 0.6 + i * RH, color = p === "柱A" ? BLUE : p === "柱B" ? GREY : "CFCFCF";
  text(s, [{ text: `${p}　`, options: { bold: true, color: p === "柱A" ? BLUE_DARK : SUB } }, { text: label }], { x: 0.6, y, w: 4.3, h: RH, fontSize: 14, valign: "middle" });
  s.addShape(pres.shapes.LINE, { x: GX, y: y + RH, w: 12.7 - GX, h: 0, line: { color: GRID, width: 0.5 } });
  s.addShape(pres.shapes.RECTANGLE, { x: GX + a * GW + 0.05, y: y + 0.15, w: (b - a) * GW - 0.1, h: RH - 0.3, fill: { color }, line: { color } });
});
const mx = GX + 2 * GW + GW * 0.85;
s.addShape(pres.shapes.LINE, { x: mx, y: GY + 0.55, w: 0, h: TASKS.length * RH + 0.1, line: { color: BLUE_DARK, width: 1.5, dashType: "dash" } });
text(s, "中間発表 11/28", { x: mx - 1.2, y: GY + 0.6 + TASKS.length * RH + 0.08, w: 2.4, h: 0.3, fontSize: 12, color: BLUE_DARK, align: "center", bold: true });
caption(s, "図9　今後の工程（柱Bの季節は柱Aと同じ冬・春・夏の代表週）", 0.6, 6.55, 7.0, 0.35);
s.addNotes("今後の予定です。11月中旬までは、充電計画の探索不足の原因を調べて対策を検討し、並行して11月28日の中間発表のポスターを準備します。柱Bは11月中に日ごとの計画をつなぐ仕組みを仕上げ、12月前半に冬・春・夏の3季節で計算し、年内に結果をまとめます。1月以降は、運行や利用者の観点を取り入れた3本目の柱を検討しています。以上です。ご指導をお願いいたします。");

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
s.addNotes("参考文献です。ご質問の際に必要であればご覧ください。");

(async () => {
  const out = path.join(__dirname, "three_party_20261112.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
