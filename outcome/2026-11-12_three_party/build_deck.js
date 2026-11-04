// Three-party monthly meeting (2026-11-12): Prof. Urabe and Prof. Nakajima.
// Pillar A results on rc20 (DIAGNOSTIC): grid limits 90/200/400/600/900 kW x winter/spring/summer,
// the 10/22 lab questions, why the electric-bus share does not move, the simulation checks and the
// plan to the 11/28 midterm. Same visual style as the 10/22 lab deck. Every number is read from
// deck_data_rc20.json (prepare_deck_data.py, saved verified results only) unless marked as an input fact.
// The rc18 version of this deck is build_deck_rc18.js.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(path.join(process.env.PPTX_SKILL, "scripts", "apply_theme.js"));

const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "deck_data_rc20.json"), "utf8"));
const allCases = DATA.cases;
const cases = allCases.filter((r) => r.status === "VERIFIED");
const iceHour = DATA.ice_by_hour;
const eqSize = JSON.parse(fs.readFileSync(path.join(__dirname, "eq", "sizes.json"), "utf8"));
const diesel = DATA.diesel;
const LIMITS = [90, 200, 400, 600, 900];
const SEASONS = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const WIN = "2025-01-06";
const get = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const getAny = (g, w) => allCases.find((r) => r.grid_limit_kw === g && r.week === w);
const byLimit = (g) => cases.filter((r) => r.grid_limit_kw === g);
const avg = (g, k) => byLimit(g).reduce((a, r) => a + r[k], 0) / Math.max(byLimit(g).length, 1);
const val = (g, w, k, f = (v) => v) => (get(g, w) ? f(get(g, w)[k]) : null);
const fmt = (n) => Math.round(n).toLocaleString("ja-JP");
const man = (n) => (n / 1e4).toFixed(1);
const nVerified = cases.length, nAll = allCases.length;
const pending = allCases.filter((r) => r.status !== "VERIFIED").map((r) => `${r.grid_limit_kw} kW ${SEASONS.find((s) => s[0] === r.week)[1]}`);
// Unit economics from the model's own coefficients (input facts, not results).
const KWH_PER_KM = 1.316, KM_PER_L = 4.52, GRID_JPY = 30, DIESEL_JPY = 150, OVERAGE_JPY = 500, VDAY_JPY = 20000;
const bevGridPerKm = KWH_PER_KM * GRID_JPY, iceePerKm = DIESEL_JPY / KM_PER_L, bevOveragePerKm = KWH_PER_KM * (GRID_JPY + OVERAGE_JPY);

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
const co2Cut = SEASONS.filter(([w]) => get(900, w)).map(([w]) => 1 - get(900, w).total_co2_kg / Number(diesel.find((d) => d.week === w).co2_kg));
const pct = (v) => `${Math.round(v * 100)}%`;

// ---- Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 1.7, w: 11.5, h: 1.9, fontSize: 34, bold: true, valign: "bottom" });
text(s, "― 柱A 受電上限と電気バスの担当便：5段階 × 3季節の結果 ―", { x: 0.9, y: 3.7, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "三者ミーティング　2026年11月12日\n東京都市大学　劉 承洋", { x: 0.9, y: 4.6, w: 11.5, h: 1.0, fontSize: 18, color: SUB });
s.addNotes("それでは、11月の進捗をご報告します。修士1年の劉です。今日は、11月28日の中間発表の主軸である柱Aについて、計算の条件を見直し、受電上限を90から900 kWまでの5段階、3つの季節で計算し直した結果をご報告します。あわせて、10月22日の研究室で出た3つの質問への回答と、計算の中で見つかった課題、中間発表までの予定をお話しします。");

// ---- Contents with the three messages up front
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("本日の報告", { placeholder: "title" });
text(s, [S0, S1, S2, S3, S4, S5, S6].map((t, i) => ({ text: t, options: { breakLine: i < 6 } })), { x: 0.9, y: 1.6, w: 5.6, h: 4.6, fontSize: 19, paraSpaceAfter: 10 });
s.addShape(pres.shapes.RECTANGLE, { x: 6.9, y: 1.6, w: 5.8, h: 4.75, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
text(s, "本日お伝えしたいこと", { x: 7.15, y: 1.75, w: 5.3, h: 0.45, fontSize: 17, bold: true, color: BLUE_DARK });
bullets(s, [
  `受電上限を900 kWから90 kWまで下げても、電気バスの担当便は${shareMin}〜${shareMax}%でほぼ変わらない`,
  "400 kW以上では超過はほぼなし。400・600・900 kWの費用はほぼ同じ",
  "超過は前日の計画では見えず、実行中に現れる。そのため受電上限は便割当に効かず、超過費用として効く"],
  { x: 7.15, y: 2.3, w: 5.3, h: 3.9, fontSize: 16, paraSpaceAfter: 12 });
s.addNotes("本日の流れです。最初に、前回からの進捗と、計算の条件の変更点をご説明します。そのあと柱Aの結果、研究室で出た質問への回答、考察と課題、今後の予定の順にお話しします。右側に、今日お伝えしたいことを3つまとめました。1つ目は、受電上限を下げても電気バスの担当便はほとんど変わらないこと。2つ目は、400 kW以上では超過がなく、400、600、900 kWの費用はほぼ同じであること。3つ目は、超過は前日の計画では見えず実行中に現れるため、受電上限が便割当には効かず、超過費用として効いていることです。");

// ---- Progress since 10/8 and 10/22
s = page(S0, "前回の三者ミーティング（10月8日）からの進捗");
const ST = (t, done) => ({ text: t, options: { bold: true, align: "center", color: done ? BLUE_DARK : SUB, fill: { color: done ? "DCEBF7" : "F2F2F2" } } });
s.addTable([
  [H("項目"), H("内容"), H("状況"), H("補足")],
  [B("柱A の計算"), "冬・春・夏 × 受電上限 90/200/400/600/900 kW の15ケース", ST(nVerified === nAll ? "完了" : "ほぼ完了", nVerified === nAll), `${nVerified}件を検算済み。変更点は8ページ`],
  [B("便割当の見込みの修正"), "10/22 の考察「便割当の段階の見込みが楽観的」への対応", ST("完了", true), "10/25に修正。11/3の監査で見つかった2つ目のずれも修正（5章）"],
  [B("研究室の質問"), "特別な週、季節ごとの電力量、充電の分散", ST("回答", true), "4章"],
  [B("充電計画の改善"), "厳しい上限で充電計画の探索が不足する問題", ST("調査中", false), "初期解の試行は効果なし（原因は特定済み）。実行中の行き詰まりも課題"],
  [B("柱B"), "日ごとの計画と、日をまたいだ計画の比較", ST("実装中", false), "設計を決定（10/30）。日ごとの計画をつなぐ部分を実装中"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.6, 4.3, 1.2, 4.0], fontSize: 14, rowH: 0.78 }));
caption(s, "柱A：受電上限と電気バスの担当便（中間発表の主軸）、柱B：日をまたいだ計画の意味（年末まで）", 0.6, 6.45, 12.1);
s.addNotes("前回からの進捗です。柱Aは、受電上限を5段階、季節を3つにして計算し直し、検算の済んだケースから結果をお見せします。10月22日の研究室で、便を割り当てる段階の見込みが楽観的だという考察をお話ししましたが、走行中にも充電できるとみなしていた点を10月25日に修正しました。11月3日の監査で、毎朝の条件の差による2つ目のずれも見つかり、これも直しました。5章でご説明します。研究室で出た3つの質問には4章でお答えします。一方で、厳しい受電上限では充電計画の探索が足りないという問題が残っています。初期解を与える対策は効果がなく、その原因は特定しました。柱Bは10月30日に設計を決め、日ごとの計画をつなぐ部分を実装しています。");

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
  ["受電上限", "90 / 200 / 400 / 600 / 900 kW（900 kWは急速充電器10基×90 kWを同時に使える上限。超過分に500円/kWhの追加費用、仮の値）"],
  ["対象期間", "冬・春・夏の代表週（2025年1月6日・4月7日・7月7日から各1週間）"],
  ["毎朝の電池", "目標90%、下限80%（10月22日の結果では毎朝ほぼ満充電を必須にしていた）"],
  ["単価・係数", "電気 30円/kWh（基本料金を含む包括単価）、軽油 150円/L、車両使用費 2万円/台・日、CO₂ 軽油2.62 kg/L［1］・電力0.5 kg/kWh（仮の値）"],
  ["計画と実行", "前日に1週間分を計画（太陽光は過去の実績から作った平年値の予報）、実行は実際の天気で1時間ごとに充電を立て直す"]].map(([k, v]) => [B(k), v]),
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.0, 10.1], fontSize: 14, rowH: 0.6 }));
caption(s, "表1　計算条件（10月8日からの変更の経緯は次ページ）", 0.6, 6.45, 12.1);
s.addNotes("計算条件です。対象と車両、設備、代表週は10月22日と同じです。受電上限は、800 kWの代わりに、急速充電器10基をすべて同時に使える900 kWを入れ、600 kWも加えた5段階にしました。変わったのは毎朝の電池の条件で、以前は毎朝ほぼ満充電を必須にしていましたが、目標90%、下限80%としました。電気の単価30円は、基本料金を含めた包括的な単価として扱っています。また、前日の計画では太陽光を過去の実績から作った平年値で予報し、実行の段階では実際の天気に合わせて1時間ごとに充電を立て直しています。この予報の扱いが、後の考察で重要になります。");

// ---- What changed since the previous three-party meeting (10/8)
s = page(S2, "前回の三者ミーティング（10月8日）からの変更点（12点）");
s.addTable([
  [H("時期"), H("項目"), H("変更の内容"), H("理由・確認したこと")],
  ["10/9", B("CO₂係数"), "軽油を2.62 kg/Lに統一（以前は2.58〜2.67が混在）", "10/8の宿題（下準備1）"],
  ["10/9", B("太陽光"), "傾斜30°・真南の斜面日射（pvlib）", "10/8の宿題（下準備2）"],
  ["10/10", B("受電上限"), "上限を超えることを許し、超過分に500円/kWh（仮の値）", "受電上限を契約の目安として扱う（10/10に決定）"],
  ["10/10", B("燃料バス"), "初期の軽油残量を40〜90%でばらつかせる", "10/10に決定"],
  ["10/11", B("便割当の解き方"), "一部の便だけを解き直す大近傍探索（LNS）を追加", "汎用ソルバーだけでは初期解から改善しなかった"],
  ["10/27", B("電気料金"), "30円/kWhは基本料金込み。基本料金は足さず目安として示す", "基本料金を目的関数に入れる試行（10/14）は二重計上"],
  ["10/22〜25", B("便割当の見込み"), "走行中の充電と翌朝の期限の漏れを修正", "修正後（rc13）は見込みと実際の買電の差が2〜10%"],
  ["11/1", B("毎朝の電池"), "目標90%・下限80%、届かない分に50円/kWh（以前はほぼ満充電を必須）", "柱Bの日ごとの計画と条件をそろえるため"],
  ["10/31〜11/2", B("計算時間"), "便割当のLNSは90分。毎時の立て直しは1回120秒", "柱Bの計算量を減らすため（モデルの式は同じ）"],
  ["11/3", B("便割当の見込み（2）"), "便割当の段階にも毎朝90%に届かない分の50円/kWhを入れる", "監査で買電の見込みが約1/4と分かった"],
  ["11/3", B("便割当の出発点"), "各上限とも、同じ上限の前の版の割当から始める（600・900 kWは800 kWの割当）", "全上限が同じ出発点だと上限の差が出にくい"],
  ["11/3", B("受電上限・計算機"), "800 kW→600・900 kW。遅い計算機は制限時間を延ばす", "900 kWは充電器10基の上限。速さのムラを抑える"]],
  tableOpts({ x: 0.6, y: 1.42, w: 12.1, colW: [1.25, 1.95, 4.9, 4.0], fontSize: 10, rowH: 0.36 }));
caption(s, "表2　日付は変更を決めた日。全ケースを最新の版（rc20）で計算し直した。11/3に試した充電計画の初期解は効果がなく不採用", 0.6, 6.62, 12.1, 0.3);
s.addNotes("前回の三者ミーティング、10月8日からの変更点をまとめました。10月9日に、宿題だった燃料バスのCO₂係数と、太陽光パネルを30度傾けたときの日射を反映しました。10月10日には、受電上限を物理的な上限ではなく契約の目安として扱い、超えた分に費用をかける形にしました。また燃料バスの初期の軽油残量にばらつきを入れました。10月11日には、便の割当が初期解から改善しなかったので、一部の便だけを解き直す方法を加えました。電気料金は、30円が基本料金を含む単価なので、基本料金は足さずに目安として示すことにしました。10月22日から25日には、便割当の段階で走行中にも充電できるとみなしていた点と、翌朝の期限が抜けていた点を直しました。11月1日には、毎朝の電池を目標90%、下限80%にしました。また計算時間を減らすため、毎時の立て直しは1回120秒にしています。11月3日には監査の結果を受けて、便割当の段階にも毎朝の重みを入れ、出発点を上限ごとに分け、受電上限に600と900 kWを加えました。遅い計算機には制限時間を延ばして、速さの違いが結果に出にくいようにしています。どれも結果に影響するので、全ケースを最新の版で計算し直しました。");

// ---- A-1 BEV share
const CH = { x: 0.6, y: 2.25, w: 7.2, h: 4.1 }, RB = { x: 8.1, y: 2.4, w: 4.65, h: 3.9, fontSize: 16 };
s = page(S3, "結果(A-1)　受電上限と電気バスの担当便");
takeaway(s, `受電上限を900 kWから90 kWまで下げても、電気バスの担当便は${shareMin}〜${shareMax}%でほぼ変わらない`);
s.addChart(pres.charts.LINE, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => val(g, w, "bev_trip_share_pct", (v) => Math.round(v * 10) / 10)) })),
  chart({ ...CH, lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 7, chartColors: [BLUE_DARK, BLUE_LIGHT, GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスが担当した便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, `図1　受電上限と電気バスの担当便の割合（1,704便/週、${nVerified}/${nAll}ケース）`, 0.6, 6.45, 7.6);
bullets(s, [
  "上限90 kWでも、燃料バスへの振り替えは起きなかった",
  "上限による差より、季節による差（春がやや低い）の方が大きい",
  "各上限の便割当は、同じ上限の前の版（rc13）の割当から始めた（rc18の共通の出発点はやめた）",
  "理由は考察(2)：割当を決める前日の時点では超過が見えていない"], { ...RB, fontSize: 15 });
s.addNotes(`ここから柱Aの結果です。横軸が受電上限、縦軸が電気バスの担当した便の割合です。受電上限を900 kWから90 kWまで下げても、電気バスの担当便は${shareMin}から${shareMax}%で、ほとんど変わりませんでした。上限による差より季節による差の方が大きく、春がやや低くなっています。今回は、各上限の便割当を、同じ上限の前の版の割当から始めているので、前回のように全上限が同じ出発点を共有してはいません。なぜ担当便が変わらないのかは、考察の2つ目でご説明します。${pending.length ? `なお、${pending.join("と")}は計算し直し中で、図には入っていません。` : ""}`);

// ---- A-2 overage by limit and season
s = page(S3, "結果(A-2)　受電上限の超過量");
takeaway(s, "400 kW以上では超過はほぼなし（最大1 kWh）。超過が残るのは90 kWと200 kWの冬");
s.addChart(pres.charts.BAR, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => val(g, w, "contract_over_limit_kwh", (v) => Math.round(v))) })),
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK, BLUE_LIGHT, GREY], showValue: true, dataLabelPosition: "outEnd",
    dataLabelFormatCode: "#,##0", dataLabelFontSize: 11, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "上限を超えた電力量 [kWh/週]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図2　受電上限と季節ごとの超過電力量（1週間）。棒がないケースは計算し直し中", 0.6, 6.45, 7.6);
bullets(s, [
  w90 ? `冬・90 kW：${fmt(w90.contract_over_limit_kwh)} kWh、最大受電 ${fmt(w90.peak_grid_kw)} kW` : "冬・90 kW：計算中",
  w200 ? `冬・200 kW：${fmt(w200.contract_over_limit_kwh)} kWh、最大受電 ${fmt(w200.peak_grid_kw)} kW` : "冬・200 kW：計算中",
  "前日計画（予報）の段階では全ケースで超過0。超過は実行中に生じる",
  `900 kW（充電器10基を同時に使える上限）でも最大受電は${fmt(Math.min(...byLimit(900).map((r) => r.peak_grid_kw)))}〜${fmt(Math.max(...byLimit(900).map((r) => r.peak_grid_kw)))} kW`], RB);
s.addNotes(`受電上限を超えた電力量です。400 kW以上ではどの季節も超過はありません。200 kWでは春と夏はほぼ0で、超過が残るのは冬だけです。90 kWでは冬が最も多くなりました。前日に立てた計画の段階では、どのケースも超過は0で、超過は実際の天気で立て直しながら実行する中で生じています。また、充電器10基をすべて同時に使える900 kWの上限でも、実際の最大受電は700 kW前後で、上限まで使っていません。`);

// ---- A-3 operating cost
s = page(S3, "結果(A-3)　受電上限と運用費");
takeaway(s, "上限を下げて増える費用は、ほぼすべて超過分の追加費用。400 kW以上ではほぼ同じ");
s.addChart(pres.charts.BAR, [
  { name: "電気代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "electricity_cost") / 1e3) / 10) },
  { name: "燃料代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "fuel_cost") / 1e3) / 10) },
  { name: "超過分の追加費用", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "contract_overage_cost") / 1e3) / 10) }],
  chart({ ...CH, barDir: "col", barGrouping: "stacked", chartColors: [BLUE, GREY, "CFCFCF"], valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "運用費 [万円/週]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図3　受電上限と1週間の運用費の内訳（計算済みの季節の平均、車両使用費は除く）", 0.6, 6.45, 7.6);
bullets(s, [
  `運用費：約${Math.round(opex(900))}万円/週（900 kW）→ 約${Math.round(opex(90))}万円/週（90 kW）`,
  `400・600・900 kW の運用費はほぼ同じ（約${Math.round(Math.min(opex(400), opex(600), opex(900)))}〜${Math.round(Math.max(opex(400), opex(600), opex(900)))}万円/週）`,
  `燃料使用量：${Math.round(Math.min(...fuelL))}〜${Math.round(Math.max(...fuelL))} L/週（季節で決まり、上限ではほぼ変わらない）`,
  "超過分の500円/kWhは仮の値"], RB);
s.addNotes(`費用の内訳です。上限を900 kWから90 kWに下げると、運用費は約${Math.round(opex(900))}万円から約${Math.round(opex(90))}万円に増えますが、増えたのはほぼすべて超過分の追加費用です。400 kW、600 kW、900 kWの運用費はほぼ同じで、今回の設定では400 kWを超える上限はほとんど費用を下げません。超過分の500円は仮の値で、実際の料金ではない点にご注意ください。`);

// ---- A-4 diesel trips by departure band
s = page(S3, "結果(A-4)　燃料バスが担当した便の時間帯");
const BANDS = [["05-06", "早朝（5〜6時台）"], ["07-21", "日中（7〜21時台）"], ["22-", "深夜（22時以降）"]];
const iceShare = (g, b) => { const rs = iceHour.filter((r) => r.grid_limit_kw === g);
  return rs.length ? Math.round(rs.reduce((a, r) => a + r.bands[b].diesel / r.bands[b].total, 0) / rs.length * 1000) / 10 : null; };
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };
takeaway(s, "燃料バスが担当するのは主に早朝と深夜の便。受電上限を下げても増えない");
s.addChart(pres.charts.BAR, LIMITS.map((g) => ({ name: `${g} kW`, labels: BANDS.map((x) => x[1]), values: BANDS.map(([b]) => iceShare(g, b)) })),
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: ["DDDDDD", "BBBBBB", GREY, BLUE_LIGHT, BLUE_DARK], showValue: true,
    dataLabelPosition: "outEnd", dataLabelFormatCode: "0", dataLabelFontSize: 9, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "燃料バスが担当した便 [%]" }));
caption(s, "図4　出発時間帯別の燃料バス担当率（計算済みの季節の平均、凡例は受電上限）", 0.6, 6.45, 7.6);
bullets(s, [`早朝：${rng("05-06")}`, `深夜：${rng("22-")}`, `日中：${rng("07-21")}`,
  "時間帯は、時刻表の各便の出発時刻で分類した", "早朝・深夜に偏る理由は未確認"], RB);
s.addNotes("どの時間帯の便が燃料バスに回っているかを見ました。燃料バスが担当したのは主に早朝の5時から6時台と、夜22時以降の便で、日中はほとんど電気バスが担当していました。この傾向は受電上限を変えてもほとんど同じです。早朝・深夜に偏る理由は、まだ確かめていません。");

// ---- A-5 CO2
s = page(S3, "結果(A-5)　全車燃料バスとのCO₂比較");
takeaway(s, `電気バスと併用すると、CO₂は全車燃料バスより約${pct(Math.min(...co2Cut))}〜${pct(Math.max(...co2Cut))}少ない`);
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス（概算）", labels: SEASONS.map((x) => x[1]), values: SEASONS.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バスと併用（900 kW）", labels: SEASONS.map((x) => x[1]), values: SEASONS.map(([w]) => Math.round(get(900, w).total_co2_kg / 100) / 10) }],
  chart({ ...CH, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]" }));
caption(s, "図5　1週間のCO₂排出量（併用は受電上限900 kWの場合）", 0.6, 6.45, 7.6);
bullets(s, [
  "全車燃料バスは、900 kWの計画と同じ走行距離を軽油4.52 km/Lで換算した概算で、最適化の結果ではない",
  "電力の係数0.5 kg/kWhは仮の値",
  `受電上限による差は小さい（${nVerified}ケースで${(Math.min(...cases.map((r) => r.total_co2_kg)) / 1000).toFixed(1)}〜${(Math.max(...cases.map((r) => r.total_co2_kg)) / 1000).toFixed(1)} t/週）`], RB);
s.addNotes(`CO₂の比較です。灰色が全車燃料バスの場合、青が電気バスと併用した場合で、併用によりCO₂は約${pct(Math.min(...co2Cut))}から${pct(Math.max(...co2Cut))}少なくなりました。全車燃料バスの方は、同じ走行距離を燃費4.52 km/Lで軽油に換算した概算です。電力のCO₂係数0.5は仮の値です。`);

// ---- Results table (all cases)
s = page(S3, `柱Aの結果の一覧（${nAll}ケース、1週間の実行結果）`);
const S2label = (r) => r.stage2_solver_status === "optimal" ? "最適" : `時間切れ（${Math.round(r.stage2_mip_gap_ratio * 100)}%）`;
const failed1 = new Set((DATA.first_attempt_failures || []).map((c) => c.replace("wk", "").replace(/^0+/, "")));
const rows = [];
LIMITS.forEach((g) => SEASONS.forEach(([w, n]) => {
  const r = get(g, w), key = `${g}/${w}`, retried = failed1.has(key);
  if (!r) {
    rows.push([{ text: `${g} kW`, options: { align: "center" } }, { text: n, options: { align: "center" } },
      { text: retried ? "1回目は毎時の立て直しで停止。計算し直し中" : "計算中", options: { colspan: 8, color: SUB, align: "center" } }]);
    return;
  }
  const hot = r.contract_over_limit_kwh > 1;
  const c = (v) => ({ text: v, options: { align: "right", color: hot ? BLUE_DARK : INK, bold: hot } });
  rows.push([{ text: `${g} kW`, options: { align: "center" } }, { text: n + (retried ? "*" : ""), options: { align: "center" } },
    c(man(r.total_cost)), c(man(r.contract_overage_cost)), c(fmt(r.contract_over_limit_kwh)), c(fmt(r.peak_grid_kw)), c(fmt(r.grid_import_kwh)),
    c(r.bev_trip_share_pct.toFixed(1)), c(fmt(r.ice_fuel_consumed_l)), { text: S2label(r), options: { align: "center", color: r.stage2_solver_status === "optimal" ? INK : BLUE_DARK } }]);
}));
s.addTable([[H("上限"), H("季節"), H("総費用 [万円]"), H("うち超過 [万円]"), H("超過 [kWh]"), H("最大受電 [kW]"), H("買電 [kWh]"), H("電気バス担当 [%]"), H("軽油 [L]"), H("充電計画")], ...rows],
  tableOpts({ x: 0.6, y: 1.45, w: 12.1, colW: [0.9, 0.8, 1.35, 1.35, 1.1, 1.25, 1.15, 1.45, 1.0, 1.75], fontSize: 11, rowH: 0.3 }));
caption(s, "表3　青字は超過のあるケース。総費用は車両使用費（約402〜408万円）を含む。充電計画は前日計画のStage 2の求解状態。*は2回目の計算", 0.6, 6.45, 12.1, 0.5);
s.addNotes(`${nAll}ケースの一覧です。青字が上限を超過したケースです。総費用の大部分は車両の使用費です。右端は前日計画の充電計画を解いたときの状態で、冬の90 kWだけが制限時間で打ち切った解です。${(DATA.first_attempt_failures || []).length ? "90 kWの夏と400 kWの冬は、1回目の計算が毎時の立て直しの途中で止まったので、同じ条件で計算し直しました。これは考察で説明します。" : ""}`);

// ---- Lab questions
s = page(S4, "研究室の質問への回答（季節ごとの電力量・充電の分散・特別な週）");
const QF2 = DATA.qf2;
s.addChart(pres.charts.BAR, [
  { name: "太陽光で使えた量", labels: QF2.map((q) => q.season), values: QF2.map((q) => Math.round(q.pv_used)) },
  { name: "太陽光を捨てた量", labels: QF2.map((q) => q.season), values: QF2.map((q) => Math.round(q.pv_curtailed)) },
  { name: "買電", labels: QF2.map((q) => q.season), values: QF2.map((q) => Math.round(q.grid_import)) }],
  chart({ x: 0.6, y: 1.55, w: 6.4, h: 4.6, barDir: "col", barGrouping: "clustered", chartColors: [BLUE, "CFCFCF", GREY], showValue: true, dataLabelPosition: "outEnd",
    dataLabelFormatCode: "#,##0", dataLabelFontSize: 10, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "電力量 [kWh/週]" }));
caption(s, "図6　季節ごとの太陽光と買電（各季節の計算済みケースの平均）", 0.6, 6.25, 6.4);
const share = (n) => QF2.find((q) => q.season === n).grid_share_pct.toFixed(1);
s.addTable([
  [H("質問"), H("回答")],
  [B("季節ごとの電力量"), `バスの充電に占める買電の割合は冬${share("冬")}%、春${share("春")}%、夏${share("夏")}%`],
  [B("充電の分散"), "400・600 kWでは最大受電が上限ちょうどに収まり、分散できている。900 kWでは700 kW前後で上限まで使わない。モデルの中で分散して下がるのは超過分の費用だけ（30円/kWhは包括単価）"],
  [B("特別な週（GWなど）"), "時刻表は日付ごとのものを使うので、祝日ダイヤ（181便/日、平日264便）は入る。GWの週そのものはまだ計算していない"]],
  tableOpts({ x: 7.3, y: 1.55, w: 5.4, colW: [1.5, 3.9], fontSize: 12, rowH: [0.45, 1.0, 1.85, 1.3] }));
s.addNotes(`10月22日の研究室で出た3つの質問にお答えします。季節ごとの電力量は、左の図のとおりで、バスの充電に占める買電の割合は冬${share("冬")}%、春${share("春")}%、夏${share("夏")}%でした。充電の分散は、400 kWと600 kWでは最大受電が上限ちょうどに収まっており、分散できています。電気の単価は包括単価なので、モデルの中で分散して下がるのは超過分の費用だけです。特別な週は、祝日のダイヤは反映されますが、ゴールデンウィークの週そのものはまだ計算していません。`);

// ---- Discussion 1: forecast
s = page(S5, "考察(1)　超過の出どころ：前日計画の太陽光予報は平年値");
takeaway(s, "前日計画は毎日ほぼ同じ平年値で計画するため、曇りの日の不足を前もって見込めない");
const FC = [3391, 3401, 3412, 3423, 3436, 3448, 3462], AC = [1399, 2640, 3836, 4871, 5059, 5079, 1693];
const DAYS = ["1/6(月)", "1/7(火)", "1/8(水)", "1/9(木)", "1/10(金)", "1/11(土)", "1/12(日)"];
s.addChart(pres.charts.BAR, [{ name: "前日計画の予報（平年値）", labels: DAYS, values: FC }, { name: "実際の発電", labels: DAYS, values: AC }],
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: ["CFCFCF", BLUE], valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "太陽光の発電量 [kWh/日]" }));
caption(s, "図7　冬の代表週の日ごとの太陽光：予報と実際（入力データ。受電上限・版によらず同じ）", 0.6, 6.45, 7.6);
bullets(s, [
  "1週間の合計は予報と実際で1〜3%しか違わない",
  "晴れの日は蓄電池が満杯になって太陽光を捨て、曇りの日は蓄電池が空になって夜に買電する",
  "日をまたいで蓄電池の使い方を計画し直す方法を、柱Bで調べる"], RB);
s.addNotes("考察の1つ目です。前日の計画では、過去の実績から作った平年値で太陽光を予報しているので、毎日ほぼ同じ3,400 kWh程度を見込んでいます。一方、実際の発電は冬の週で1日1,400から5,100 kWhと大きく変わります。晴れの日は蓄電池が満杯になって太陽光を捨て、曇りの日は蓄電池が空になって夜に買電します。そのため、曇りの日の不足を前もって見込めず、厳しい上限では超過が起きます。");

// ---- Discussion 2: why the share does not move
s = page(S5, "考察(2)　電気バスの担当便が受電上限で変わらない理由");
takeaway(s, "便割当は前日に決まり、その時点では超過が見えない。見えなければ電気バスの方が得なまま");
s.addTable([
  [H("1 kmあたりの費用（モデルの係数から）"), H("円/km")],
  ["電気バス：買電で充電（1.316 kWh/km × 30円/kWh）", { text: bevGridPerKm.toFixed(1), options: { align: "right" } }],
  ["燃料バス：軽油（150円/L ÷ 4.52 km/L）", { text: iceePerKm.toFixed(1), options: { align: "right" } }],
  ["電気バス：上限を超えて買電（30＋500円/kWh）", { text: fmt(bevOveragePerKm), options: { align: "right", bold: true, color: BLUE_DARK } }],
  ["電気バス：太陽光・蓄電池で充電", { text: "購入費なし", options: { align: "right" } }],
  ["（参考）車両を1台・1日余分に使う費用", { text: "20,000円/日", options: { align: "right" } }]],
  tableOpts({ x: 0.6, y: 2.3, w: 6.6, colW: [5.1, 1.5], fontSize: 13, rowH: 0.48 }));
caption(s, "表4　入力の係数から計算した値（計算結果ではない）。CO₂費（1円/kg）は1 kmあたり1円未満。太陽光・蓄電池の設備費は未計上", 0.6, 5.25, 6.6, 0.5);
bullets(s, [
  "買電どうしなら燃料バスの方が約6円/km安いが、車両の追加（2万円/日）に比べて小さい",
  "超過する電気で走ると約700円/kmで、燃料バスに回す理由になる。ところが前日計画は全ケースで超過0と見込む",
  "割当は実行中に変えないので、実行中に現れる超過は割当に効かない",
  "確かめ方：実際の天気で前日計画を立てると割当が変わるか（結果は次のページ）"], { x: 7.5, y: 2.3, w: 5.2, h: 4.5, fontSize: 14 });
s.addNotes(`考察の2つ目、なぜ電気バスの担当便が受電上限で変わらないのかです。左の表は、モデルに入れた係数から計算した1 kmあたりの費用です。買電で充電した電気バスは約${bevGridPerKm.toFixed(0)}円/km、燃料バスは約${iceePerKm.toFixed(0)}円/kmで、買電どうしなら燃料バスの方が少し安いのですが、その差は約6円/kmで、車両を1台・1日余分に使う2万円に比べるとわずかです。一方、上限を超える電気で走ると約${fmt(bevOveragePerKm)}円/kmになり、燃料バスに回す理由になります。ところが、便の割当を決める前日の計画では、どのケースも超過を0と見込んでいて、超過は実行中にしか現れません。割当は実行中に変えないので、超過は割当に効かないというのが現時点の考えです。これを確かめるため、実際の天気で前日計画を立てた場合に割当が変わるかを計算しています。`);

// ---- Discussion 2 (cont.): day-ahead plan on actual PV (hindsight diagnostic)
const HS = (DATA.hindsight || []).filter((r) => r.status === "VERIFIED" && get(r.grid_limit_kw, r.week));
const hsPending = (DATA.hindsight || []).filter((r) => r.status !== "VERIFIED").map((r) => `${r.grid_limit_kw} kW ${SEASONS.find((x) => x[0] === r.week)[1]}`);
const S2state = (r) => r.stage2_solver_status === "optimal" ? "最適" : `${r.stage2_solver_status === "memory_limit" ? "メモリ上限" : "時間切れ"}（${Math.round(r.stage2_mip_gap_ratio * 100)}%）`;
const seasonOf = (w) => SEASONS.find((x) => x[0] === w)[1];
s = page(S5, "考察(2続き)　前日計画の太陽光を実際の値にした診断");
takeaway(s, "春の超過は予報の外れでほぼ消え、冬は残る。どちらでも電気バスの担当便は変わらない");
const hsTable = [[H("上限・季節"), H("前日計画の太陽光"), H("総費用 [万円]"), H("超過 [kWh]"), H("最大受電 [kW]"), H("電気バス担当 [%]"), H("前日の充電計画")]];
HS.forEach((h) => [[get(h.grid_limit_kw, h.week), "予報（平年値）"], [h, "実際の値"]].forEach(([r, lab], j) => {
  const c = (v) => ({ text: v, options: { align: "right", bold: j === 1, color: j === 1 ? BLUE_DARK : INK } });
  hsTable.push([{ text: `${h.grid_limit_kw} kW ${seasonOf(h.week)}`, options: { align: "center" } }, { text: lab, options: { align: "center", bold: j === 1 } },
    c(man(r.total_cost)), c(fmt(r.contract_over_limit_kwh)), c(fmt(r.peak_grid_kw)), c(r.bev_trip_share_pct.toFixed(1)), { text: S2state(r), options: { align: "center" } }]);
}));
s.addTable(hsTable, tableOpts({ x: 0.6, y: 2.25, w: 12.1, colW: [1.6, 1.9, 1.6, 1.4, 1.6, 1.8, 2.2], fontSize: 13, rowH: 0.42 }));
const hsLine = (h) => { const f = get(h.grid_limit_kw, h.week);
  return `${seasonOf(h.week)}：超過 ${fmt(f.contract_over_limit_kwh)}→${fmt(h.contract_over_limit_kwh)} kWh（${Math.round((1 - h.contract_over_limit_kwh / f.contract_over_limit_kwh) * 100)}%減）、総費用 ${man(h.total_cost - f.total_cost)}万円`; };
bullets(s, [
  ...HS.map(hsLine),
  "春の超過は予報の外れで説明できる。冬は予報が当たっても残り、太陽光の量そのものが足りないと見ている（推測）",
  "冬の実際の値の充電計画はメモリ上限で止まった解。残った超過の一部は探索不足の可能性がある",
  "予報の外れをなくしても担当便は変わらない。割当は車両の使用費（2万円/台・日）でほぼ決まると見ている"],
  { x: 0.6, y: 2.25 + 0.42 * (HS.length * 2 + 1) + 0.2, w: 12.1, h: 2.3, fontSize: 14, paraSpaceAfter: 4 });
caption(s, `表4b　前日計画の太陽光だけを実際の値に替え、ほかの条件は同じにした診断（DIAGNOSTIC）。${hsPending.length ? `${hsPending.join("・")}は計算中` : ""}`, 0.6, 6.45, 12.1);
s.addNotes(`考察の2つ目の確かめです。前日計画の太陽光だけを、予報ではなく実際の値に替えて計算しました。${HS.map((h) => hsLine(h)).join("。")}。春は超過がほとんど消えたので、春の超過は予報の外れから来ていると言えます。冬は予報が当たっても超過が残っていて、冬は太陽光の量そのものが足りないと見ています。ただし冬の実際の値の充電計画はメモリの上限で止まった解なので、残った超過の一部は探索不足の可能性もあります。また、どちらの季節でも電気バスの担当便は変わりませんでした。予報が外れて超過が見えないことだけでは、担当便が変わらない理由を説明しきれず、車両の使用費が割当をほぼ決めていると考えています。`);

// ---- Discussion 3: rolling
s = page(S5, "考察(3)　厳しい上限では、毎時の立て直しが時間切れ・失敗しやすい");
const RL = DATA.rolling, tl = (g, w) => { const r = RL.find((x) => x.grid_limit_kw === g && x.week === w); return r ? r.time_limit : null; };
takeaway(s, "90・200 kWでは毎時の立て直しの一部が時間切れ。1回目に2件が途中で止まった");
s.addChart(pres.charts.BAR, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => tl(g, w)) })),
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK, BLUE_LIGHT, GREY], showValue: true, dataLabelPosition: "outEnd",
    dataLabelFormatCode: "0", dataLabelFontSize: 11, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "時間切れの回数（1週間175回中）", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図8　毎時の立て直しで、制限時間内に最適と確認できなかった回数", 0.6, 6.45, 7.6);
bullets(s, [
  "時間切れの回は、その時点の最良の計画を実行する",
  "1回目の計算で90 kW夏（6日目21時）と400 kW冬（4日目0時）が停止：前者は解なしの時間切れ、後者は実行不可能",
  "後者は、夜のうちに全車を80%まで充電しきれない状態（充電器10基、翌朝の期限、前日計画の残量に合わせる条件）",
  "実行中は燃料バスへの振り替えができない作りなので、行き詰まると回復できない"], { ...RB, fontSize: 14 });
s.addNotes("考察の3つ目です。図は、1週間175回の毎時の立て直しのうち、制限時間内に最適と確認できなかった回数です。400 kW以上では0回ですが、90 kWと200 kWの冬では何十回もありました。さらに1回目の計算では、90 kWの夏と400 kWの冬が途中で止まりました。90 kWの夏は解が見つからないまま時間切れ、400 kWの冬は実行不可能で、夜のうちに全車を80%まで充電しきれない状態になったと見ています。今の作りでは実行中に燃料バスへ振り替えられないので、行き詰まると回復できません。これはシミュレーションの設計上の課題で、次のページで扱います。");

// ---- Simulation checks
s = page(S5, "シミュレーション自体の検討（11月3〜4日の監査）");
takeaway(s, "便割当の段階の見込みのずれは修正できた。残る課題は実行中の行き詰まりと探索時間");
const aud = (name, g, w) => (DATA.audit[name] || []).find((r) => r.grid_limit_kw === g && r.week === w);
const a18 = aud("rc18", 90, WIN), a20 = aud("rc20", 90, WIN);
s.addTable([
  [H("確認したこと"), H("rc18（11/3）"), H("rc20（今回）"), H("対応・残る課題")],
  [B("便割当の段階の買電の見込み（冬・90 kW）"), a18 ? `${fmt(a18.stage1_recourse_grid_import_kwh)} kWh（充電計画は${fmt(a18.stage2_day_ahead_grid_import_kwh)} kWh）` : "—",
    a20 ? `${fmt(a20.stage1_recourse_grid_import_kwh)} kWh（充電計画は${fmt(a20.stage2_day_ahead_grid_import_kwh)} kWh）` : "—", "便割当の段階にも毎朝の50円/kWhを入れて解消"],
  [B("便割当の出発点"), "4上限とも同じ割当", "上限ごとに前の版の割当", "出発点による偏りを除いた"],
  [B("充電の初期解（11/3の試行）"), "Gurobiが受け入れず", "使わない", "便割当の段階は充電電力の低下と最短の充電時間を省いている（IISで確定）"],
  [B("実行中の行き詰まり"), "—", "1回目に2件停止", "実行中の燃料バスへの振り替え、前日計画の残量に合わせる条件の緩和を検討"],
  [B("台による速さの違い"), "時間の制限が同じ", "遅い台は時間を延ばした", "本来は計算量（Gurobiの作業量）でそろえるのがよい"],
  [B("16 GBの台"), "使わず", "400 kW以上なら回る（試験）", "90 kWはメモリ不足。厳しいケースは32 GB以上で解く"]],
  tableOpts({ x: 0.6, y: 2.25, w: 12.1, colW: [2.9, 2.8, 2.8, 3.6], fontSize: 12, rowH: [0.42, 0.7, 0.5, 0.7, 0.7, 0.5, 0.6] }));
caption(s, "表5　保存済みの結果を読んで確認した（計算はしていない）。数値はaudit_stage1_recourse.pyで集計", 0.6, 6.45, 12.1);
s.addNotes(`ここで、シミュレーション自体の検討をまとめます。11月3日の監査で、便割当の段階が買電を大幅に少なく見込んでいることが分かりました。冬の90 kWでは、便割当の段階の見込みが${a18 ? fmt(a18.stage1_recourse_grid_import_kwh) : ""} kWh、充電計画が${a18 ? fmt(a18.stage2_day_ahead_grid_import_kwh) : ""} kWhでした。原因は、毎朝90%に届かない分の重みが充電計画にしかなかったことで、今回これを便割当の段階にも入れ、${a20 ? fmt(a20.stage1_recourse_grid_import_kwh) : ""} kWh対${a20 ? fmt(a20.stage2_day_ahead_grid_import_kwh) : ""} kWhとほぼ一致するようになりました。また、全上限が同じ出発点から始まっていた点もやめました。残る課題は、実行中の行き詰まりと探索時間です。実行中に燃料バスへ振り替えられない作りは、現実の運用とも違うので、検討すべき点だと考えています。`);

// ---- Limitations
s = page(S5, "課題と結果の扱い");
takeaway(s, "本日の結果は診断用（DIAGNOSTIC）。研究の結論とするには下の課題を明記するか解消する");
s.addTable([
  [H("課題"), H("内容"), H("対応")],
  [B("便割当の最適性"), "全ケースでメモリ上限に当たって停止。証明できるギャップは約45%", "限界として明記"],
  [B("2段階法"), "便割当 → 充電計画の順に解くので、全体の総費用の最適ではない", "限界として明記"],
  [B("充電計画"), "冬・90 kWの前日計画は打ち切った解。毎時の立て直しは厳しい上限で時間切れが多い", "考察(3)"],
  [B("実行中の行き詰まり"), "1回目の計算で2件が停止（計算し直し）", "振り替え・条件の緩和を検討"],
  [B("台ごとの時間の補正"), "遅い台は制限時間を延ばした（係数は実測の近似）", "作業量でそろえる方法を検討"],
  [B("仮の値"), "超過費用500円/kWh、電力のCO₂係数0.5 kg/kWh、CO₂単価1円/kg", "値を変えた感度の確認"],
  [B("全車燃料バス"), "走行距離からの概算で、最適化の結果ではない", "限界として明記"]],
  tableOpts({ x: 0.6, y: 2.3, w: 12.1, colW: [2.6, 5.6, 3.9], fontSize: 13, rowH: 0.56 }));
s.addNotes("結果の扱いについてです。本日の結果は、すべて診断用の結果として扱っています。便割当は全ケースでメモリの上限に当たって止まっており、最適性が確認できていません。2段階で解いているので、全体の総費用の最適でもありません。実行中の行き詰まりや、台ごとの時間の補正、仮の値も課題として残っています。中間発表では、これらを限界として明記したうえで結果を示す予定です。");

// ---- What the results support (research-level reading; facts from saved results, interpretations marked)
const rg = (a, d = 0) => `${Math.min(...a).toFixed(d)}〜${Math.max(...a).toFixed(d)}`;
const seasonShare = (w) => `${rg(cases.filter((r) => r.week === w).map((r) => r.bev_trip_share_pct), 1)}%`;
const exOv = cases.map((r) => (r.total_cost - r.contract_overage_cost) / 1e4);
const vehShare = cases.map((r) => r.vehicle_usage_cost / r.total_cost * 100), enShare = cases.map((r) => (r.electricity_cost + r.fuel_cost) / r.total_cost * 100);
const top3 = SEASONS.map(([w]) => [400, 600, 900].map((g) => get(g, w)).filter(Boolean).map((r) => r.total_cost));
const top3Spread = Math.max(...top3.filter((a) => a.length).map((a) => (Math.max(...a) - Math.min(...a)) / Math.min(...a) * 100));
const spr = SEASONS[1][0], sprCosts = LIMITS.filter((g) => g >= 200).map((g) => get(g, spr)).filter(Boolean).map((r) => man(r.total_cost));
const gridCo2 = cases.map((r) => r.grid_electricity_co2_kg / r.total_co2_kg * 100);
const co2CutAll = cases.map((r) => (1 - r.total_co2_kg / Number(diesel.find((d) => d.week === r.week).co2_kg)) * 100);
const qf = (n, k) => fmt(QF2.find((q) => q.season === n)[k]);
const tlOf = (g) => RL.filter((x) => x.grid_limit_kw === g).map((x) => x.time_limit);
const hsW = HS.find((h) => h.week === WIN), hsS = HS.find((h) => h.week === spr);
// Replicates (results_rc20 re-solves on other machines, collected 11/4) and rc18 -> rc20 differences (pillarA_table.md).
const REPL = "+0.04%（400 kW夏）・+0.4%（90 kW冬）", RC18 = { dMin: -6.1, dMax: 7.4, shareMin: 91.8, shareMax: 95.7 };
const FIND = (rows, y0, rowH) => tableOpts({ x: 0.6, y: y0, w: 12.1, colW: [0.45, 3.2, 4.65, 3.8], fontSize: 11, rowH, valign: "middle" });
const fRow = (n, claim, fact, note) => [{ text: String(n), options: { align: "center", bold: true, color: BLUE_DARK } }, B(claim), fact, { text: note, options: { color: SUB } }];
const FHEAD = [H("#"), H("言えること"), H("根拠（保存した結果から読んだ値）"), H("解釈・注意（推測を含む）")];

s = page(S5, "結果から言えること（1/2）：受電上限・費用・超過");
s.addTable([FHEAD,
  fRow(1, "受電上限は電気バスの担当便をほとんど動かさない",
    `15件で${shareMin}〜${shareMax}%。同じ季節の中の幅は冬${seasonShare(WIN)}、春${seasonShare(spr)}、夏${seasonShare(SEASONS[2][0])}で、季節の差の方が大きい`,
    `実際の太陽光で計画しても変わらない。総費用の${rg(vehShare)}%が車両の使用費、電気代と燃料代は${rg(enShare, 1)}%で、割当は車両の使用費でほぼ決まる`),
  fRow(2, "約700 kWから400 kWまでは、超過なしでピークを下げられる",
    `900 kWの最大受電は${rg(byLimit(900).map((r) => r.peak_grid_kw))} kWで制約が効かない。600 kWは上限まで使って超過0、400 kWの超過は最大${fmt(Math.max(...byLimit(400).map((r) => r.contract_over_limit_kwh)))} kWh`,
    "冬は200 kWと400 kWの間に、超過が出始める境目がある"),
  fRow(3, "上限を厳しくして増える費用は、ほぼすべて超過の追加費用",
    `超過の追加費用を除いた総費用は${rg(exOv, 1)}万円/週。超過の追加費用は90 kW冬で${man(w90.contract_overage_cost)}万円、200 kW冬で${man(w200.contract_overage_cost)}万円`,
    "大きさは仮の単価500円/kWhに比例する。結論の前に単価の感度の確認が要る"),
  fRow(4, "400・600・900 kWの費用の差は、計算のばらつきと区別できない",
    `同じ季節での差は最大${top3Spread.toFixed(1)}%。解き直しの差は${REPL}。上限を緩めると高くなるケースもある（春の200→900 kW：${sprCosts.join("→")}万円）`,
    "上限の順に費用が並ばないのは、便割当の探索の違いによる。1〜2台・日（2〜4万円）より小さい差は読めない"),
  fRow(5, "超過は実行中にだけ生じる。春は予報の外れ、冬は太陽光の不足で説明できる",
    `前日計画では全件で超過0。実際の太陽光で計画すると${hsS ? `春${fmt(get(90, spr).contract_over_limit_kwh)}→${fmt(hsS.contract_over_limit_kwh)} kWh` : "春は計算中"}、${hsW ? `冬${fmt(w90.contract_over_limit_kwh)}→${fmt(hsW.contract_over_limit_kwh)} kWh` : "冬は計算中"}（90 kW）`,
    "90 kWで予報が完全に当たる価値は約10〜13万円/週。冬の実際の値の充電計画は打ち切った解で、探索不足の可能性も残る")],
  FIND(null, 1.45, [0.42, 0.95, 0.8, 0.8, 0.95, 0.95]));
caption(s, "表6　すべてDIAGNOSTIC（研究の結論にはまだ使わない）。根拠は保存した結果、解釈は推測を含む", 0.6, 6.45, 12.1);
s.addNotes(`ここからは、結果から何が言えるかを、根拠と解釈を分けて整理します。1つ目に、受電上限は電気バスの担当便をほとんど動かしません。同じ季節の中では1ポイント程度しか動かず、季節の差の方が大きいです。総費用のほとんどが車両の使用費で、電気代と燃料代は数パーセントなので、割当は車両の使用費でほぼ決まると考えています。2つ目に、上限がないときのピークは約700 kWで、400 kWまでは超過なしに下げられます。3つ目に、上限を厳しくして増える費用は、ほぼすべて超過の追加費用で、これは仮の単価500円に比例するので、単価の感度を確かめる必要があります。4つ目に、400、600、900 kWの費用の差は、解き直したときのばらつきと同じ程度で、どれが安いかは言えません。上限を緩めた方が高くなるケースもあり、これは便割当の探索の違いによるものです。5つ目に、超過は実行中にだけ生じ、春は予報の外れ、冬は太陽光の不足で説明できます。`);

s = page(S5, "結果から言えること（2/2）：電力量・燃料バス・CO₂・計算");
s.addTable([FHEAD,
  fRow(6, "超過は電力量ではなく時間帯の問題。捨てた太陽光は買電より多い",
    `捨てた太陽光（冬・春・夏で${qf("冬", "pv_curtailed")}・${qf("春", "pv_curtailed")}・${qf("夏", "pv_curtailed")} kWh/週）が買電（${qf("冬", "grid_import")}・${qf("春", "grid_import")}・${qf("夏", "grid_import")} kWh）より多い。90 kW×168時間＝15,120 kWhも買電より大きい`,
    "蓄電池の使える範囲3,600 kWhは冬の充電の約1日分で、晴れの日の余りを曇りの日へ持ち越せない（柱Bで確かめる）"),
  fRow(7, "燃料バスは早朝と深夜の便に集中し、上限によらない",
    `燃料バスの担当率は早朝（5〜6時台）${rng("05-06")}、深夜（22時以降）${rng("22-")}、日中${rng("07-21")}`,
    "理由は未確認。仕業の端や夜の充電時間と重なる便と見ている"),
  fRow(8, "CO₂は全車燃料バスより約" + `${rg(co2CutAll)}%少なく、残りの大部分は買電から`,
    `併用は${rg(cases.map((r) => r.total_co2_kg / 1000), 2)} t/週、全車燃料バス（概算）は${rg(diesel.map((d) => Number(d.co2_kg) / 1000), 1)} t/週。併用のCO₂のうち買電が${rg(gridCo2)}%`,
    "さらに減らすには買電の量と電力の係数（仮の0.5 kg/kWh）が効く。全車燃料バスは概算で、最適化は計算中"),
  fRow(9, "買電で走る電気バスは、燃料バスより1 kmあたり少し高い",
    `買電の電気バス${bevGridPerKm.toFixed(1)}円/km、燃料バス${iceePerKm.toFixed(1)}円/km（入力の係数）。全車燃料バスの概算の総費用は${rg(diesel.map((d) => Number(d.total_cost) / 1e4), 0)}万円/週`,
    "電気バスが得なのは太陽光・蓄電池の電気で走る分。設備の規模が変われば結論も変わりうる"),
  fRow(10, "厳しい上限ほど解きにくく、完走も台と実行に左右される",
    `毎時の立て直し175回中の時間切れは90 kWで${rg(tlOf(90))}回、200 kW冬で${tl(200, WIN)}回、400 kW以上で0回。便割当のギャップは全件で約45%`,
    "本番の1回目に2件、解き直しは5件中3件が完走せず。完走したものどうしの差は0.4%以内"),
  fRow(11, "便割当の見込みの修正（rc18→rc20）でも、担当便の結論は変わらない",
    `費用の差は${RC18.dMin}〜+${RC18.dMax}万円（最大1.8%）。担当便はrc18で${RC18.shareMin}〜${RC18.shareMax}%、rc20で${shareMin}〜${shareMax}%`,
    "結論1は、便割当の段階の見込みの修正に対して頑健")],
  FIND(null, 1.4, [0.4, 0.82, 0.62, 0.78, 0.66, 0.8, 0.62]));
caption(s, "表7　すべてDIAGNOSTIC。CO₂の係数・超過の単価は仮の値", 0.6, 6.55, 12.1);
s.addNotes(`続きです。6つ目に、超過は電力量の不足ではなく時間帯の問題です。どの季節も、捨てた太陽光の方が買電より多く、蓄電池は冬の充電の約1日分しかないので、晴れの日の余りを曇りの日に持ち越せません。これが柱Bで日をまたいだ計画を調べる理由です。7つ目に、燃料バスは早朝と深夜の便に集中しています。理由はまだ確かめていません。8つ目に、CO₂は全車燃料バスより大きく減り、残りの大部分は買電から来ています。9つ目に、買電で走る電気バスは燃料バスより少し高く、電気バスが得なのは太陽光と蓄電池の電気で走る分です。10個目に、厳しい上限ほど計算が難しく、完走するかどうかも台や実行によって変わります。11個目に、便割当の見込みを直す前と後で、担当便の結論は変わりませんでした。`);

s = page(S5, "結果からまだ言えないこと・次に確かめること");
[["まだ言えないこと", [
  "最適であること（便割当のギャップ約45%、2段階法で全体の最適ではない）",
  "400・600・900 kWのどれが安いか（差がばらつきと同じ程度）",
  "超過の費用の大きさ（500円/kWhは仮の値）",
  "年間や特別な週（GWなど）への一般化（各季節1週間）",
  "全車燃料バスとの費用・CO₂の差（いまは概算）"], "F5F5F5", GRID],
 ["次に確かめること", [
  "超過の単価の感度（100〜1,000円/kWh）→ 3",
  `実際の太陽光での診断の残り（${hsPending.length ? hsPending.join("・") : "完了"}）→ 5`,
  "全車燃料バスの最適化（rc20、計算中）→ 8・9",
  "蓄電池の容量の感度と柱B（日をまたいだ計画）→ 6",
  "燃料バスの仕業から、早朝・深夜に偏る理由 → 7"], "EEF5FB", BLUE]].forEach(([h, items, fill, line], i) => {
  const x = 0.6 + i * 6.15;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: 5.95, h: 4.8, fill: { color: fill }, line: { color: line, width: 1 } });
  text(s, h, { x: x + 0.25, y: 1.65, w: 5.45, h: 0.45, fontSize: 18, bold: true, color: BLUE_DARK });
  bullets(s, items, { x: x + 0.25, y: 2.2, w: 5.45, h: 3.95, fontSize: 15, paraSpaceAfter: 8 });
});
caption(s, "右の矢印の数字は、前の2ページの「言えること」の番号", 0.6, 6.45, 12.1);
s.addNotes("最後に、今の結果ではまだ言えないことと、次に確かめることです。最適であること、400、600、900 kWのどれが安いか、超過の費用の大きさ、年間や特別な週への一般化、全車燃料バスとの差は、まだ言えません。次に、超過の単価の感度、実際の太陽光での診断の残り、全車燃料バスの最適化、蓄電池の容量の感度と柱B、燃料バスの便の仕業を確かめます。");

// ---- Summary
s = page(S6, "まとめ");
[[`${shareMin}〜${shareMax}%`, "電気バスの担当便", "受電上限を900 kWから90 kWまで下げても、ほぼ変わらない"],
 ["超過ほぼ0", "受電上限 400 kW以上", "超過が残るのは90 kWと200 kWの冬／400・600・900 kWの費用はほぼ同じ"],
 [`約${pct(Math.min(...co2Cut))}〜${pct(Math.max(...co2Cut))}減`, "CO₂（全車燃料バス比）", "電気バスとの併用による削減"]].forEach(([big, label, sub], i) => {
  const x = 0.6 + i * 4.1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.6, w: 3.9, h: 3.0, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  text(s, label, { x: x + 0.2, y: 1.75, w: 3.5, h: 0.45, fontSize: 15, color: SUB, align: "center" });
  text(s, big, { x: x + 0.1, y: 2.25, w: 3.7, h: 0.9, fontSize: 28, bold: true, color: BLUE_DARK, align: "center", valign: "middle" });
  text(s, sub.split("／").map((t, j, a) => ({ text: t, options: { breakLine: j < a.length - 1 } })), { x: x + 0.25, y: 3.25, w: 3.4, h: 1.2, fontSize: 14, align: "center" });
});
bullets(s, [
  "超過は前日の計画では見えず実行中に現れる。そのため受電上限は便割当に効かず、超過費用として効く",
  "現在の係数では、買電で走る電気バスは燃料バスより1 kmあたり少し高い。電気バスの利点は太陽光・蓄電池の電気で走る分"],
  { x: 0.6, y: 4.95, w: 12.1, h: 1.8, fontSize: 17, paraSpaceAfter: 8 });
s.addNotes("まとめです。受電上限を900 kWから90 kWまで下げても、電気バスの担当便はほとんど変わりませんでした。400 kW以上では超過がなく、400、600、900 kWの費用はほぼ同じです。電気バスとの併用で、CO₂は全車燃料バスより大きく減ります。超過は前日の計画では見えず実行中に現れるため、受電上限は便割当には効かず、超過費用として効いていると考えています。また、今の係数では、買電で走る電気バスは燃料バスより少し高く、電気バスの利点は太陽光と蓄電池の電気で走る分にあります。");


// ---- Plan
s = page(S6, "今後の予定");
const PERIODS = ["11月上旬", "11月中旬", "11月下旬", "12月前半", "12月後半", "1月〜"];
const GX = 5.0, GW = (12.7 - GX) / PERIODS.length, GY = 1.6, RH = 0.62;
PERIODS.forEach((p, i) => {
  s.addShape(pres.shapes.RECTANGLE, { x: GX + i * GW, y: GY, w: GW, h: 0.5, fill: { color: HEAD }, line: { color: GRID, width: 0.75 } });
  text(s, p, { x: GX + i * GW, y: GY, w: GW, h: 0.5, fontSize: 13, bold: true, align: "center", valign: "middle" });
});
const TASKS = [["柱A", "実行中の行き詰まり・探索時間の対策、感度の確認", 0, 2], ["柱A", "中間発表（11/28、A0ポスター）の準備", 1, 3],
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
s.addNotes("今後の予定です。11月中旬までは、実行中の行き詰まりと探索時間の対策、仮の値を変えた感度の確認を進め、並行して11月28日の中間発表のポスターを準備します。柱Bは11月中に日ごとの計画をつなぐ仕組みを仕上げ、12月前半に冬・春・夏の3季節で計算し、年内に結果をまとめます。1月以降は、運行や利用者の観点を取り入れた3本目の柱を検討しています。以上です。ご指導をお願いいたします。");

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
