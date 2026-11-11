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

// 11/9: main numbers from the latest version (rc33 7dc38d95 / rc35 9a0fe044), prepare_deck_data_latest.py.
// Each limit x season row is the cheaper of the two Stage 1 start points. Costs are shown with diesel
// valued by the litres burnt (post-hoc, same as the 11/8 tables); the accounting total stays in total_cost_accounting.
const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "deck_data_latest.json"), "utf8"));
DATA.cases.forEach((r) => { if (r.status === "VERIFIED") {
  r.total_cost_accounting = r.total_cost; r.fuel_cost_accounting = r.fuel_cost;
  r.total_cost = r.total_cost_fuel_consumed; r.fuel_cost = r.ice_fuel_consumed_l * 150; } });
const allCases = DATA.cases;
const cases = allCases.filter((r) => r.status === "VERIFIED");
const iceHour = DATA.ice_by_hour;
const eqSize = JSON.parse(fs.readFileSync(path.join(__dirname, "eq", "sizes.json"), "utf8"));
const diesel = DATA.diesel;
const LIMITS = DATA.limits;
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
// 2026-11-09: one start failed and nothing is running for these; they are "未完", not "計算中".
const STOPPED = new Map([["900/2025-07-07", "電気バス寄り。4回とも毎時の立て直しで停止"]]);
const caseLab = (r) => `${r.grid_limit_kw} kW ${SEASONS.find((s) => s[0] === r.week)[1]}`;
const notDone = allCases.filter((r) => r.status !== "VERIFIED");
const pending = notDone.filter((r) => !STOPPED.has(`${r.grid_limit_kw}/${r.week}`)).map(caseLab);
const stopped = notDone.filter((r) => STOPPED.has(`${r.grid_limit_kw}/${r.week}`)).map((r) => `${caseLab(r)}（${STOPPED.get(`${r.grid_limit_kw}/${r.week}`)}）`);
// Unit economics from the model's own coefficients (input facts, not results).
const KWH_PER_KM = 1.316, CHARGE_EFF = 0.95, KM_PER_L = 4.52, GRID_JPY = 30, DIESEL_JPY = 150, OVERAGE_JPY = 500, VDAY_JPY = 20000;
// Same formulas as the solver's powertrain_marginal_cost_audit.json (charging loss 0.95 included).
const bevGridPerKm = KWH_PER_KM / CHARGE_EFF * GRID_JPY, iceePerKm = DIESEL_JPY / KM_PER_L, bevOveragePerKm = KWH_PER_KM / CHARGE_EFF * (GRID_JPY + OVERAGE_JPY);

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

const S0 = "前回からの差分", S1 = "研究背景と目的", S2 = "問題設定と計算条件", S3 = "結果：柱A 費用とCO₂",
  S4 = "研究室の質問（10月22日）への回答", S5 = "超過の原因", S6 = "まとめと今後の予定", SA = "付録";

// Derived values used on several slides.
const shares = cases.map((r) => r.bev_trip_share_pct);
const shareMin = Math.min(...shares).toFixed(1), shareMax = Math.max(...shares).toFixed(1);
const opex = (g) => (avg(g, "electricity_cost") + avg(g, "fuel_cost") + avg(g, "contract_overage_cost")) / 1e4;
const fuelL = cases.map((r) => r.ice_fuel_consumed_l);
const w90 = get(90, WIN), w200 = get(200, WIN);
const co2Cut = SEASONS.filter(([w]) => get(900, w)).map(([w]) => 1 - get(900, w).total_co2_kg / Number(diesel.find((d) => d.week === w).co2_kg));
const pct = (v) => `${Math.round(v * 100)}%`;
// Latest-version helpers: both start points per case (DATA.pairs) and which one is cheaper.
const SEASON_OF = Object.fromEntries(SEASONS);
const lab = (r) => `${r.grid_limit_kw} kW${SEASON_OF[r.week]}`;
const iceWins = cases.filter((r) => r.selected_start === "ice"), bevWins = cases.filter((r) => r.selected_start === "bev");
const rngTxt = (a, d = 0) => !a.length ? "—" : Math.min(...a).toFixed(d) === Math.max(...a).toFixed(d) ? Math.min(...a).toFixed(d) : `${Math.min(...a).toFixed(d)}〜${Math.max(...a).toFixed(d)}`;
const startJa = (st) => (st === "ice" ? "燃料バス寄り" : "電気バス寄り");

// ---- Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 1.7, w: 11.5, h: 1.9, fontSize: 34, bold: true, valign: "bottom" });
text(s, "― 柱A 受電上限と電化：費用とCO₂のトレードオフと、超過の出方 ―", { x: 0.9, y: 3.7, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "三者ミーティング　2026年11月12日\n東京都市大学　劉 承洋", { x: 0.9, y: 4.6, w: 11.5, h: 1.0, fontSize: 18, color: SUB });
s.addNotes("それでは、11月の進捗をご報告します。修士1年の劉です。今日は、11月28日の中間発表の主軸である柱Aについて、計算の条件を見直し、受電上限を90から900 kWまでの5段階、3つの季節で計算し直した結果をご報告します。あわせて、10月22日の研究室で出た3つの質問への回答と、計算の中で見つかった課題、中間発表までの予定をお話しします。");

// ---- Contents with the three messages up front
s = pres.addSlide({ masterName: "PLAIN" });
s.addText("本日の報告", { placeholder: "title" });
const agPair = (g, st) => DATA.pairs.find((x) => x.grid_limit_kw === g && x.week === WIN && x.start === st && x.status === "VERIFIED");
const AG_B9 = agPair(900, "bev"), AG_I9 = agPair(900, "ice");
const AGENDA = ["1. 研究の目的と、前回（10/8）からの差分", "2. 結果：受電上限ごとの費用とCO₂", "3. 超過の原因", "4. 研究室の質問への回答", "5. まとめ・ご相談・今後の予定", "（条件・詳細は付録）"];
text(s, AGENDA.map((t, i) => ({ text: t, options: { breakLine: i < AGENDA.length - 1, color: i === AGENDA.length - 1 ? SUB : INK } })), { x: 0.9, y: 1.6, w: 5.6, h: 4.6, fontSize: 19, paraSpaceAfter: 12 });
s.addShape(pres.shapes.RECTANGLE, { x: 6.9, y: 1.6, w: 5.8, h: 4.75, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
text(s, "一言でいうと", { x: 7.15, y: 1.72, w: 5.3, h: 0.4, fontSize: 15, bold: true, color: BLUE_DARK });
text(s, "受電が十分なら電化は「安い＋CO₂が少ない」。受電が少ないと「安さかCO₂か」の選択になる", { x: 7.15, y: 2.1, w: 5.3, h: 0.95, fontSize: 16, bold: true });
bullets(s, [
  `受電に余裕があれば電気バス中心が安くCO₂も少ない（900 kW冬で${man(AG_I9.total_cost_fuel_consumed - AG_B9.total_cost_fuel_consumed)}万円安く、CO₂は${Math.round((1 - AG_B9.total_co2_kg / AG_I9.total_co2_kg) * 100)}%少ない）`,
  iceWins.length ? `受電が厳しいケース（${iceWins.map(lab).join("・")}）だけは燃料バス中心が安い。ただし90 kW冬でCO₂は約3倍` : "どの上限でも電気バス中心が安い",
  "CO₂は、両方そろったどのケースでも電気バス中心が少ない",
  "上限の超過は「曇りの日の翌未明」、蓄電池が空の時間に集中する"],
  { x: 7.15, y: 3.1, w: 5.3, h: 3.15, fontSize: 14, paraSpaceAfter: 6 });
s.addNotes("本日の流れです。時間が限られているので、前回10月8日からの差分を中心にお話しします。まず前回からの進捗と工夫した点、次に受電上限ごとの費用とCO₂、超過の原因、研究室の質問への回答、最後にまとめとご相談です。計算条件や細かい考察は付録に回しました。右側が一言でいうと、です。受電が十分なら電化は安くてCO₂も少ない。受電が少ない冬だけは、安さを取るかCO₂を取るかの選択になります。");

// ---- Progress since 10/8 and 10/22
s = page(S0, "前回の三者ミーティング（10月8日）からの進捗");
const ST = (t, done) => ({ text: t, options: { bold: true, align: "center", color: done ? BLUE_DARK : SUB, fill: { color: done ? "DCEBF7" : "F2F2F2" } } });
s.addTable([
  [H("項目"), H("内容"), H("状況"), H("補足")],
  [B("柱A の計算"), "冬・春・夏 × 受電上限 90/200/400/900 kW × 2つの出発点（最新版）", ST(nVerified === nAll ? "完了" : "計算中", nVerified === nAll), `${nVerified}／${nAll}件を検算済み。残る900 kW夏は未完。600 kWは最新版では計算しない`],
  [B("便割当の見込みの修正"), "10/22 の考察「便割当の段階の見込みが楽観的」への対応", ST("完了", true), "10/25に修正。11/3の監査で見つかった2つ目のずれも修正（付録）"],
  [B("研究室の質問"), "特別な週、季節ごとの電力量、充電の分散", ST("回答", true), "9ページ"],
  [B("計算の不具合"), "毎時の立て直しが途中で止まる問題", ST("一部修正", false), "3種類は原因を特定して修正。別に900 kW夏が4回とも途中で止まり、原因を調査中"],
  [B("超過の原因"), "90 kW冬で電気バス寄りが超過する理由", ST("特定", true), "蓄電池が空になる火曜未明に集中。予報を7割と見込むと超過は半分に減った"],
  [B("柱B"), "日ごとの計画と、日をまたいだ計画の比較", ST("実装中", false), "設計を決定（10/30）。日ごとの計画をつなぐ部分を実装中"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.6, 4.3, 1.2, 4.0], fontSize: 14, rowH: 0.68 }));
caption(s, "柱A：受電上限と電気バスの担当便（中間発表の主軸）、柱B：日をまたいだ計画の意味（年末まで）", 0.6, 6.45, 12.1);
s.addNotes("前回からの進捗です。柱Aは、最新の版で、受電上限4段階、季節3つ、便割当の出発点2つを計算し直しています。検算の済んだケースから結果をお見せします。計算が途中で止まる不具合が3種類見つかりましたが、原因を特定して直しました。ただ、900キロワットの夏の電気バス寄りだけは、同じ条件で4回計算して4回とも毎時の立て直しの途中で止まり、原因を調べているところです。この1件は未完として、そのまま表に出しています。90キロワットの冬で超過が出る理由も特定しました。10月22日の研究室で、便を割り当てる段階の見込みが楽観的だという考察をお話ししましたが、走行中にも充電できるとみなしていた点を10月25日に修正しました。11月3日の監査で、毎朝の条件の差による2つ目のずれも見つかり、これも直しました。5章でご説明します。研究室で出た3つの質問には4章でお答えします。一方で、厳しい受電上限では充電計画の探索が足りないという問題が残っています。初期解を与える対策は効果がなく、その原因は特定しました。柱Bは10月30日に設計を決め、日ごとの計画をつなぐ部分を実装しています。");

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
[["決めること", "各便の担当車両（電気・燃料）／各車両の充電の時刻と量／（蓄電池は決めない：余った太陽光を貯め、足りない分へ先に放電する規則で動く。系統からは貯めない）"],
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
s = page(SA, "定式化（概略）");
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
  ["受電上限", "90 / 200 / 400 / 900 kW（900 kWは急速充電器10基×90 kWを同時に使える上限。超過分に500円/kWhの追加費用、仮の値）"],
  ["対象期間", "冬・春・夏の代表週（2025年1月6日・4月7日・7月7日から各1週間）"],
  ["毎朝の電池", "目標90%、下限80%（10月22日の結果では毎朝ほぼ満充電を必須にしていた）"],
  ["単価・係数", "電気 30円/kWh（基本料金を含む包括単価）、軽油 150円/L、車両使用費 2万円/台・日、CO₂ 軽油2.62 kg/L［1］・電力0.5 kg/kWh（仮の値）"],
  ["計画と実行", "前日に1週間分を計画（太陽光は過去の実績から作った平年値の予報）、実行は実際の天気で1時間ごとに充電を立て直す"]].map(([k, v]) => [B(k), v]),
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.0, 10.1], fontSize: 14, rowH: 0.6 }));
caption(s, "表1　計算条件（10月8日からの変更の経緯は次ページ）", 0.6, 6.45, 12.1);
s.addNotes("計算条件です。対象と車両、設備、代表週は10月22日と同じです。受電上限は、急速充電器10基をすべて同時に使える900 kWを含む4段階です。変わったのは毎朝の電池の条件で、以前は毎朝ほぼ満充電を必須にしていましたが、目標90%、下限80%としました。電気の単価30円は、基本料金を含めた包括的な単価として扱っています。また、前日の計画では太陽光を過去の実績から作った平年値で予報し、実行の段階では実際の天気に合わせて1時間ごとに充電を立て直しています。この予報の扱いが、後の考察で重要になります。");

// ---- What changed since the previous three-party meeting (10/8)
s = page(SA, "前回の三者ミーティング（10月8日）からの変更点（12点）");
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
caption(s, "表2　日付は変更を決めた日。変更のたびに影響するケースを計算し直した（この資料の値は rc33・rc35・rc36）", 0.6, 6.62, 12.1, 0.3);
s.addNotes("前回の三者ミーティング、10月8日からの変更点をまとめました。10月9日に、宿題だった燃料バスのCO₂係数と、太陽光パネルを30度傾けたときの日射を反映しました。10月10日には、受電上限を物理的な上限ではなく契約の目安として扱い、超えた分に費用をかける形にしました。また燃料バスの初期の軽油残量にばらつきを入れました。10月11日には、便の割当が初期解から改善しなかったので、一部の便だけを解き直す方法を加えました。電気料金は、30円が基本料金を含む単価なので、基本料金は足さずに目安として示すことにしました。10月22日から25日には、便割当の段階で走行中にも充電できるとみなしていた点と、翌朝の期限が抜けていた点を直しました。11月1日には、毎朝の電池を目標90%、下限80%にしました。また計算時間を減らすため、毎時の立て直しは1回120秒にしています。11月3日には監査の結果を受けて、便割当の段階にも毎朝の重みを入れ、出発点を上限ごとに分け、受電上限に600と900 kWを加えました。遅い計算機には制限時間を延ばして、速さの違いが結果に出にくいようにしています。どれも結果に影響するので、全ケースを最新の版で計算し直しました。");

// ---- A-1 BEV share
const CH = { x: 0.6, y: 2.25, w: 7.2, h: 4.1 }, RB = { x: 8.1, y: 2.4, w: 4.65, h: 3.9, fontSize: 16 };
s = page(S3, "結果：受電上限と電気バスの担当便");
takeaway(s, iceWins.length ? `安い方は、${iceWins.map(lab).join("・")}が燃料バス寄り、ほかは電気バス寄り`
  : `どのケースも電気バス寄りの出発点が安く、電気バスの担当便は${shareMin}〜${shareMax}%`);
s.addChart(pres.charts.LINE, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => val(g, w, "bev_trip_share_pct", (v) => Math.round(v * 10) / 10)) })),
  chart({ ...CH, lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 7, chartColors: [BLUE_DARK, BLUE_LIGHT, GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスが担当した便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, `図1　受電上限と電気バスの担当便（1,704便/週、2つの出発点のうち総費用の安い方、${nVerified}/${nAll}ケース）。最新版rc33・rc35・rc36`, 0.6, 6.45, 7.6, 0.5);
const pairShares = cases.map((r) => [r.bev_trip_share_pct, r.other_start_bev_trip_share_pct]).flat();
bullets(s, [
  "各ケースを電気バス寄り・燃料バス寄りの2つの出発点で解き、総費用（燃料は使った分）の安い方を示す",
  iceWins.length ? `受電上限が低い冬（${iceWins.map(lab).join("・")}）では、燃料バス寄りの方が安い` : "燃料バス寄りの方が安いケースはまだない",
  `安い方の電気バスの担当便：燃料バス寄りのケースで${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}%、電気バス寄りのケースで${rngTxt(bevWins.map((r) => r.bev_trip_share_pct))}%`,
  `同じケースでも出発点で担当便が大きく変わる（${rngTxt(pairShares)}%）。便割当はまだ最適とは言えない`,
  ...(pending.length ? [`計算中：${pending.join("・")}`] : []),
  ...(stopped.length ? [`未完：${stopped.join("・")}`] : [])], { ...RB, fontSize: 15 });
s.addNotes(`ここから柱Aの結果です。最新の版で、すべてのケースを電気バス寄りと燃料バス寄りの2つの出発点から解き、総費用の安い方を示しています。横軸が受電上限、縦軸が電気バスの担当した便の割合です。${iceWins.length ? `${iceWins.map(lab).join("、")}では燃料バス寄りの方が安く、電気バスの担当便は${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}%に下がります。それ以外では電気バス寄りの方が安く、担当便は${rngTxt(bevWins.map((r) => r.bev_trip_share_pct))}%です。` : ""}同じケースでも出発点によって担当便が大きく変わるので、便割当はまだ最適とは言えません。${pending.length ? `なお、${pending.join("、")}は計算中で、図には入っていません。` : ""}${stopped.length ? `${stopped.map((x) => x.replace(/（.*/, "")).join("、")}は、出発点の一方の計算が失敗したため未完です。` : ""}`);

// ---- A-2 overage by limit and season
s = page(S3, "結果：受電上限の超過量");
const overCases = cases.filter((r) => r.contract_over_limit_kwh > 1);
takeaway(s, overCases.length ? `安い方の出発点で超過が残るのは${overCases.map(lab).join("・")}。それ以外は超過0` : "安い方の出発点では、どのケースも超過0");
s.addChart(pres.charts.BAR, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => val(g, w, "contract_over_limit_kwh", (v) => Math.round(v))) })),
  chart({ ...CH, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK, BLUE_LIGHT, GREY], showValue: true, dataLabelPosition: "outEnd",
    dataLabelFormatCode: "#,##0", dataLabelFontSize: 11, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "上限を超えた電力量 [kWh/週]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図2　受電上限と季節ごとの超過電力量（1週間、安い方の出発点）。棒がないケースは計算中または未完", 0.6, 6.45, 7.6);
const bevOver = (DATA.pairs || []).filter((r) => r.status === "VERIFIED" && r.start === "bev" && r.contract_over_limit_kwh > 1);
bullets(s, [
  ...overCases.map((r) => `${lab(r)}（${startJa(r.selected_start)}）：${fmt(r.contract_over_limit_kwh)} kWh、最大受電 ${fmt(r.peak_grid_kw)} kW`),
  `電気バス寄りの出発点では超過が出やすい：${bevOver.map((r) => `${lab(r)} ${fmt(r.contract_over_limit_kwh)} kWh`).join("、") || "なし"}`,
  "超過は実行中に生じる（90 kW冬・電気バス寄りの前日計画は超過0）",
  `900 kW（充電器10基を同時に使える上限）でも最大受電は${fmt(Math.min(...byLimit(900).map((r) => r.peak_grid_kw)))}〜${fmt(Math.max(...byLimit(900).map((r) => r.peak_grid_kw)))} kW`], { ...RB, fontSize: 13 });
s.addNotes(`受電上限を超えた電力量です。安い方の出発点で見ると、${overCases.length ? `超過が残るのは${overCases.map(lab).join("、")}です。` : "どのケースも超過はありません。"}電気バス寄りの出発点では、${bevOver.map((r) => `${lab(r)}で${fmt(r.contract_over_limit_kwh)}キロワット時`).join("、")}の超過が出ています。90キロワットの冬の電気バス寄りでは、前日に立てた計画の段階では超過は0で、超過は実際の天気で立て直しながら実行する中で生じています。また、充電器10基をすべて同時に使える900キロワットの上限でも、実際の最大受電は上限まで使っていません。`);

// ---- A-3 operating cost
s = page(S3, "結果：受電上限と運用費");
takeaway(s, `運用費は900 kWの約${Math.round(opex(900))}万円/週から90 kWの約${Math.round(opex(90))}万円/週へ。低い上限では超過費用か燃料代が増える`);
s.addChart(pres.charts.BAR, [
  { name: "電気代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "electricity_cost") / 1e3) / 10) },
  { name: "燃料代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "fuel_cost") / 1e3) / 10) },
  { name: "超過分の追加費用", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "contract_overage_cost") / 1e3) / 10) }],
  chart({ ...CH, barDir: "col", barGrouping: "stacked", chartColors: [BLUE, GREY, "CFCFCF"], valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "運用費 [万円/週]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図3　受電上限と1週間の運用費の内訳（安い方の出発点、計算済みの季節の平均、車両使用費は除く。燃料は使った分）", 0.6, 6.45, 7.6, 0.5);
bullets(s, [
  `運用費：約${Math.round(opex(900))}万円/週（900 kW）→ 約${Math.round(opex(90))}万円/週（90 kW）`,
  `400・900 kW の運用費：約${Math.round(opex(400))}・${Math.round(opex(900))}万円/週`,
  `燃料使用量：${Math.round(Math.min(...fuelL))}〜${Math.round(Math.max(...fuelL))} L/週（燃料バス寄りが安いケースで多い）`,
  "超過分の500円/kWhは仮の値",
  `超過で走る電気バスは約${fmt(bevOveragePerKm)}円/km、燃料バスは約${Math.round(iceePerKm + 2.62 / KM_PER_L)}円/km。燃料バス寄りの出発点では、この振り替えが起きて超過0`], { ...RB, fontSize: 14 });
s.addNotes(`費用の内訳です。安い方の出発点で見ると、上限を900 kWから90 kWに下げると、運用費は約${Math.round(opex(900))}万円から約${Math.round(opex(90))}万円に増えます。低い上限では、電気バス寄りなら超過費用、燃料バス寄りなら燃料代が増えます。超過分の500円は仮の値で、実際の料金ではない点にご注意ください。ただし、超過する電気で走る電気バスは1 kmあたり約730円で、燃料バスの約34円の20倍以上です。燃料バス寄りの出発点から解くと、この振り替えが起きて超過は0になりました。`);

// ---- A-3b cost and CO2 of both start points by grid limit (user request 11/9: show cheapness and CO2 side by side)
const PAIRS = [];
LIMITS.forEach((g) => SEASONS.forEach(([w]) => {
  const pick = (st) => (DATA.pairs || []).find((x) => x.grid_limit_kw === g && x.week === w && x.start === st && x.status === "VERIFIED");
  const b = pick("bev"), i = pick("ice");
  if (b && i) PAIRS.push({ label: lab(b), b, i });
}));
if (PAIRS.length) {
  s = page(S3, "2つの出発点の比較：費用の差とCO₂（受電上限・季節ごと）");
  const bevCheap = PAIRS.filter((p) => p.b.total_cost_fuel_consumed < p.i.total_cost_fuel_consumed);
  const iceCheap = PAIRS.filter((p) => p.b.total_cost_fuel_consumed >= p.i.total_cost_fuel_consumed);
  const co2Ratio = PAIRS.map((p) => p.i.total_co2_kg / p.b.total_co2_kg);
  takeaway(s, `CO₂は${PAIRS.length}ケースすべてで電気バス寄りが少なく、費用も${bevCheap.length}ケースで電気バス寄りが安い`);
  const cats = PAIRS.map((p) => p.label.replace(" kW", ""));
  s.addChart(pres.charts.BAR, [
    { name: "費用の差（電気バス寄り−燃料バス寄り）", labels: cats, values: PAIRS.map((p) => Math.round((p.b.total_cost_fuel_consumed - p.i.total_cost_fuel_consumed) / 1e3) / 10) }],
    chart({ x: 0.6, y: 2.2, w: 8.3, h: 2.25, barDir: "col", barGrouping: "clustered", chartColors: [BLUE_DARK], showValue: true, dataLabelPosition: "outEnd",
      dataLabelFormatCode: "+0.0;-0.0", dataLabelFontSize: 11, valAxisMinVal: -60, valAxisMaxVal: 60, valAxisMajorUnit: 30, catAxisLabelFontSize: 12, catAxisLabelPos: "low",
      showLegend: false, showValAxisTitle: true, valAxisTitle: "費用の差 [万円/週]" }));
  s.addChart(pres.charts.BAR, [
    { name: "電気バス寄り", labels: cats, values: PAIRS.map((p) => Math.round(p.b.total_co2_kg / 100) / 10) },
    { name: "燃料バス寄り", labels: cats, values: PAIRS.map((p) => Math.round(p.i.total_co2_kg / 100) / 10) }],
    chart({ x: 0.6, y: 4.45, w: 8.3, h: 2.05, barDir: "col", barGrouping: "clustered", chartColors: [BLUE, GREY], showValue: true, dataLabelPosition: "outEnd",
      dataLabelFormatCode: "0.0", dataLabelFontSize: 11, valAxisMinVal: 0, valAxisMaxVal: 10, valAxisMajorUnit: 5, catAxisLabelFontSize: 12, showLegend: false,
      showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]" }));
  caption(s, "図3b　横軸は受電上限［kW］と季節。上：総費用の差（電気バス寄り−燃料バス寄り）。下：CO₂（青が電気バス寄り、灰が燃料バス寄り）。rc33・rc35・rc36、DIAGNOSTIC", 0.6, 6.5, 8.3, 0.45);
  bullets(s, [
    `安さ：電気バス寄りが安いのは${bevCheap.map((p) => p.label).join("・") || "なし"}`,
    `燃料バス寄りが安いのは${iceCheap.map((p) => `${p.label}（${man(p.b.total_cost_fuel_consumed - p.i.total_cost_fuel_consumed)}万円安い）`).join("・") || "なし"}`,
    `環境：電気バス寄りのCO₂は${rngTxt(PAIRS.map((p) => p.b.total_co2_kg / 1000), 1)} t/週、燃料バス寄りは${rngTxt(PAIRS.map((p) => p.i.total_co2_kg / 1000), 1)} t/週（電気バス寄りは${Math.min(...co2Ratio).toFixed(1)}〜${Math.max(...co2Ratio).toFixed(1)}分の1）`,
    "低い上限の冬は、安さを取ると燃料バス寄り、CO₂を取ると電気バス寄りになる"], { x: 9.2, y: 2.35, w: 3.55, h: 4.3, fontSize: 14 });
  s.addNotes(`受電上限ごとに、電気バス寄りと燃料バス寄りの2つの出発点の費用とCO₂を並べました。上が1週間の総費用の差で、棒が下向きなら電気バス寄りが安いケースです。下がCO₂です。CO₂はどのケースでも電気バス寄りが少なく、燃料バス寄りの${Math.min(...co2Ratio).toFixed(1)}から${Math.max(...co2Ratio).toFixed(1)}分の1です。費用は、${bevCheap.map((p) => p.label).join("、")}で電気バス寄りが安く、${iceCheap.map((p) => p.label).join("、") || "なし"}では燃料バス寄りが安くなりました。受電上限が低い冬では、安さと環境へのやさしさが逆を向きます。`);
}

// ---- A-4 diesel trips by departure band
s = page(SA, "結果：燃料バスが担当した便の時間帯");
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
s = page(S3, "結果：全車燃料バスとのCO₂比較");
takeaway(s, `電気バスと併用すると、CO₂は全車燃料バスより約${pct(Math.min(...co2Cut)) === pct(Math.max(...co2Cut)) ? pct(Math.min(...co2Cut)) : `${pct(Math.min(...co2Cut))}〜${pct(Math.max(...co2Cut))}`}少ない`);
s.addChart(pres.charts.BAR, [
  { name: "全車燃料バス（概算）", labels: SEASONS.map((x) => x[1]), values: SEASONS.map(([w]) => Math.round(Number(diesel.find((d) => d.week === w).co2_kg) / 100) / 10) },
  { name: "電気バスと併用（900 kW）", labels: SEASONS.map((x) => x[1]), values: SEASONS.map(([w]) => (get(900, w) ? Math.round(get(900, w).total_co2_kg / 100) / 10 : null)) }],
  chart({ ...CH, barDir: "col", barGrouping: "clustered", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "CO₂ [t/週]" }));
caption(s, "図5　1週間のCO₂排出量（併用は受電上限900 kW・安い方の出発点。棒がない季節は未完）", 0.6, 6.45, 7.6);
bullets(s, [
  "全車燃料バスは、900 kWの計画と同じ走行距離を軽油4.52 km/Lで換算した概算で、最適化の結果ではない",
  "電力の係数0.5 kg/kWhは仮の値",
  `受電上限による差は小さい（${nVerified}ケースで${(Math.min(...cases.map((r) => r.total_co2_kg)) / 1000).toFixed(1)}〜${(Math.max(...cases.map((r) => r.total_co2_kg)) / 1000).toFixed(1)} t/週）`], RB);
s.addNotes(`CO₂の比較です。灰色が全車燃料バスの場合、青が電気バスと併用した場合で、併用によりCO₂は約${pct(Math.min(...co2Cut))}から${pct(Math.max(...co2Cut))}少なくなりました。全車燃料バスの方は、同じ走行距離を燃費4.52 km/Lで軽油に換算した概算です。電力のCO₂係数0.5は仮の値です。`);

// ---- Results table (all cases)
s = page(SA, `柱Aの結果の一覧（${nAll}ケース、1週間の実行結果、最新版）`);
const S2label = (r) => r.stage2_solver_status === "optimal" ? "最適" : `時間切れ（${Math.round(r.stage2_mip_gap_ratio * 100)}%）`;
const failed1 = new Set((DATA.first_attempt_failures || []).map((c) => c.replace("wk", "").replace(/^0+/, "")));
const rows = [];
LIMITS.forEach((g) => SEASONS.forEach(([w, n]) => {
  const r = get(g, w), key = `${g}/${w}`, retried = failed1.has(key);
  if (!r) {
    rows.push([{ text: `${g} kW`, options: { align: "center" } }, { text: n, options: { align: "center" } },
      { text: STOPPED.has(key) ? `未完：${STOPPED.get(key)}（76〜146回目、原因は調査中）` : retried ? "1回目は毎時の立て直しで停止。計算し直し中" : "計算中", options: { colspan: 8, color: SUB, align: "center" } }]);
    return;
  }
  const hot = r.contract_over_limit_kwh > 1;
  const c = (v) => ({ text: v, options: { align: "right", color: hot ? BLUE_DARK : INK, bold: hot } });
  rows.push([{ text: `${g} kW`, options: { align: "center" } }, { text: n + (retried ? "*" : ""), options: { align: "center" } },
    c(man(r.total_cost)), c(man(r.contract_overage_cost)), c(fmt(r.contract_over_limit_kwh)), c(fmt(r.peak_grid_kw)), c(fmt(r.grid_import_kwh)),
    c(r.bev_trip_share_pct.toFixed(1)), c(fmt(r.ice_fuel_consumed_l)), { text: `${startJa(r.selected_start)}（${({ "7dc38d95": "rc33", "9a0fe044": "rc35", "375dd6f2": "rc36" })[r.version] || r.version}）`, options: { align: "center" } }]);
}));
s.addTable([[H("上限"), H("季節"), H("総費用 [万円]"), H("うち超過 [万円]"), H("超過 [kWh]"), H("最大受電 [kW]"), H("買電 [kWh]"), H("電気バス担当 [%]"), H("軽油 [L]"), H("安い方（版）")], ...rows],
  tableOpts({ x: 0.6, y: 1.45, w: 12.1, colW: [0.9, 0.8, 1.35, 1.35, 1.1, 1.25, 1.15, 1.45, 1.0, 1.75], fontSize: 11, rowH: 0.3 }));
caption(s, "表3　2つの出発点のうち総費用（燃料は使った分）の安い方。青字は超過のあるケース。総費用は車両使用費を含む。rc35はrc33に充電計画の数値設定を1つ加えた版。rc36は充電電力の幅の隙間を閉じた版（400 kW夏の電気バス寄りはrc35では毎時の立て直しで停止）", 0.6, 6.45, 12.1, 0.5);
s.addNotes(`${nAll}ケースの一覧です。2つの出発点のうち、総費用の安い方を載せています。青字が上限を超過したケースです。総費用の大部分は車両の使用費です。右端は安かった出発点と、計算に使ったコードの版です。`);

// ---- Lab questions
s = page(S4, "研究室の質問への回答（季節ごとの電力量・充電の分散・特別な週）");
const QF2 = DATA.qf2;
s.addChart(pres.charts.BAR, [
  { name: "太陽光で使えた量", labels: QF2.map((q) => q.season), values: QF2.map((q) => Math.round(q.pv_used)) },
  { name: "太陽光を捨てた量", labels: QF2.map((q) => q.season), values: QF2.map((q) => Math.round(q.pv_curtailed)) },
  { name: "買電", labels: QF2.map((q) => q.season), values: QF2.map((q) => Math.round(q.grid_import)) }],
  chart({ x: 0.6, y: 1.55, w: 6.4, h: 4.6, barDir: "col", barGrouping: "clustered", chartColors: [BLUE, "CFCFCF", GREY], showValue: true, dataLabelPosition: "outEnd",
    dataLabelFormatCode: "#,##0", dataLabelFontSize: 10, valAxisMinVal: 0, showValAxisTitle: true, valAxisTitle: "電力量 [kWh/週]" }));
caption(s, "図6　季節ごとの太陽光と買電（各季節の計算済みケース・安い方の出発点の平均）", 0.6, 6.25, 6.4);
const share = (n) => { const q = QF2.find((x) => x.season === n); return q ? q.grid_share_pct.toFixed(1) : "（計算中）"; };
s.addTable([
  [H("質問"), H("回答")],
  [B("季節ごとの電力量"), `バスの充電に占める買電の割合は冬${share("冬")}%、春${share("春")}%、夏${share("夏")}%`],
  [B("充電の分散"), `超過のないケースでは最大受電が上限以内に収まり、分散できている（400 kW：${rngTxt(byLimit(400).map((r) => r.peak_grid_kw))} kW、900 kW：${rngTxt(byLimit(900).map((r) => r.peak_grid_kw))} kW）。モデルの中で分散して下がるのは超過分の費用だけ（30円/kWhは包括単価）`],
  [B("特別な週（GWなど）"), "時刻表は日付ごとのものを使うので、祝日ダイヤ（181便/日、平日264便）は入る。GWの週そのものはまだ計算していない"]],
  tableOpts({ x: 7.3, y: 1.55, w: 5.4, colW: [1.5, 3.9], fontSize: 12, rowH: [0.45, 1.0, 1.85, 1.3] }));
s.addNotes(`10月22日の研究室で出た3つの質問にお答えします。季節ごとの電力量は、左の図のとおりで、バスの充電に占める買電の割合は冬${share("冬")}%、春${share("春")}%、夏${share("夏")}%でした。充電の分散は、超過のないケースでは最大受電が上限以内に収まっており、分散できています。電気の単価は包括単価なので、モデルの中で分散して下がるのは超過分の費用だけです。特別な週は、祝日のダイヤは反映されますが、ゴールデンウィークの週そのものはまだ計算していません。`);

// ---- Discussion 1: forecast
s = page(SA, "考察(1)　超過の出どころ：前日計画の太陽光予報は平年値");
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

// ---- Discussion 2 (premise): per-km cost and CO2 depend on where the electricity comes from (input facts)
const GRID_CO2 = 0.5, ICE_CO2_L = 2.62, CO2_JPY = 1;
const bevGridCo2 = KWH_PER_KM / CHARGE_EFF * GRID_CO2, iceCo2 = ICE_CO2_L / KM_PER_L, iceTotal = iceePerKm + iceCo2 * CO2_JPY;
const breakEvenGrid = (iceTotal / (KWH_PER_KM / CHARGE_EFF)) - GRID_CO2 * CO2_JPY, breakEvenFactor = iceCo2 * CHARGE_EFF / KWH_PER_KM;
const KM_LABELS = ["電気バス（太陽光・蓄電池で充電）", "電気バス（買電で充電）", "燃料バス（軽油）"];
s = page(SA, "考察(2)の前提　1 kmあたりの費用とCO₂は、電気の出どころで逆転する");
takeaway(s, "買電で走るなら燃料バスの方が安くCO₂も少ない。電気バスが得なのは太陽光・蓄電池の電気のとき");
s.addChart(pres.charts.BAR, [{ name: "費用", labels: KM_LABELS, values: [0, Math.round((bevGridPerKm + bevGridCo2 * CO2_JPY) * 10) / 10, Math.round(iceTotal * 10) / 10] }],
  chart({ x: 0.6, y: 2.25, w: 6.0, h: 3.9, barDir: "bar", chartColors: [BLUE], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0",
    showLegend: false, valAxisMinVal: 0, showTitle: true, title: "1 kmあたりの費用 [円/km]（CO₂費1円/kgを含む）", titleFontSize: 13, catAxisLabelFontSize: 11 }));
s.addChart(pres.charts.BAR, [{ name: "CO₂", labels: KM_LABELS, values: [0, Math.round(bevGridCo2 * 100) / 100, Math.round(iceCo2 * 100) / 100] }],
  chart({ x: 6.75, y: 2.25, w: 6.0, h: 3.9, barDir: "bar", chartColors: [GREY], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00",
    showLegend: false, valAxisMinVal: 0, showTitle: true, title: "1 kmあたりのCO₂ [kg/km]", titleFontSize: 13, catAxisLabelFontSize: 11 }));
caption(s, `図7b　モデルに入れた係数から計算した値（計算結果ではない）。電費1.316 kWh/km、充電効率0.95、買電30円/kWh・${GRID_CO2} kg/kWh（仮）、軽油150円/L・4.52 km/L・${ICE_CO2_L} kg/L。損益分岐は買電${breakEvenGrid.toFixed(1)}円/kWh（CO₂費込み）、CO₂は電力の係数${breakEvenFactor.toFixed(2)} kg/kWh`, 0.6, 6.25, 12.1, 0.55);
s.addNotes(`考察の前に、費用の前提を確認します。左はバスが1 km走るのにかかる費用、右はCO₂です。電気バスは、太陽光や蓄電池の電気で走るときは燃料代がかからず、CO₂も出ません。ところが、電力会社から買った電気で走ると1 kmあたり約${Math.round(bevGridPerKm + bevGridCo2)}円で、燃料バスの約${Math.round(iceTotal)}円より高くなります。CO₂も、電力の係数を0.5とすると、買電で走る電気バスの方が多くなります。つまり、このモデルで電気バスが多く選ばれているのは、営業所の太陽光と蓄電池がバスの充電の8〜9割をまかなっているからだと考えています。これを確かめるため、太陽光と蓄電池を減らした計算を回しています。`);

// ---- Discussion 2: why the share does not move
s = page(SA, "（旧版rc20）考察(2)　電気バスの担当便が受電上限で変わらない理由");
takeaway(s, "当初の考え：前日には超過が見えない。検証の結果：主な理由は便割当が出発点から動かないこと");
s.addTable([
  [H("1 kmあたりの費用（モデルの係数から）"), H("円/km")],
  ["電気バス：買電で充電（1.316 kWh/km ÷ 充電効率0.95 × 30円/kWh）", { text: bevGridPerKm.toFixed(1), options: { align: "right" } }],
  ["燃料バス：軽油（150円/L ÷ 4.52 km/L）", { text: iceePerKm.toFixed(1), options: { align: "right" } }],
  ["電気バス：上限を超えて買電（30＋500円/kWh）", { text: fmt(bevOveragePerKm), options: { align: "right", bold: true, color: BLUE_DARK } }],
  ["電気バス：太陽光・蓄電池で充電", { text: "購入費なし", options: { align: "right" } }],
  ["（参考）車両を1台・1日余分に使う費用", { text: "20,000円/日", options: { align: "right" } }]],
  tableOpts({ x: 0.6, y: 2.3, w: 6.6, colW: [5.1, 1.5], fontSize: 13, rowH: 0.48 }));
caption(s, "表4　入力の係数から計算した値（計算結果ではない）。CO₂費（1円/kg）は1 kmあたり1円未満。太陽光・蓄電池の設備費は未計上", 0.6, 5.25, 6.6, 0.5);
bullets(s, [
  "買電どうしなら燃料バスの方が約8円/km安いが、車両の追加（2万円/日）に比べて小さい",
  "超過する電気で走ると約730円/kmで、燃料バスに回す理由になる。ところが前日計画は全ケースで超過0と見込む",
  "割当は実行中に変えないので、実行中に現れる超過は割当に効かない",
  "確かめ方：実際の天気で前日計画を立てても割当は変わらなかった（次のページ）",
  "さらに太陽光0 kW・蓄電池なしでも93.5%。費用の理屈では燃料バスが増えるはずで、探索の問題と判断"], { x: 7.5, y: 2.3, w: 5.2, h: 4.5, fontSize: 13 });
s.addNotes(`考察の2つ目、なぜ電気バスの担当便が受電上限で変わらないのかです。左の表は、モデルに入れた係数から計算した1 kmあたりの費用です。買電で充電した電気バスは約${bevGridPerKm.toFixed(0)}円/km、燃料バスは約${iceePerKm.toFixed(0)}円/kmで、買電どうしなら燃料バスの方が少し安いのですが、その差は約8円/kmで、車両を1台・1日余分に使う2万円に比べるとわずかです。一方、上限を超える電気で走ると約${fmt(bevOveragePerKm)}円/kmになり、燃料バスに回す理由になります。ところが、便の割当を決める前日の計画では、どのケースも超過を0と見込んでいて、超過は実行中にしか現れません。割当は実行中に変えないので、超過は割当に効かないというのが現時点の考えです。これを確かめるため、実際の天気で前日計画を立てた場合に割当が変わるかを計算しています。`);

// ---- 11/9: the slides below (hindsight, rolling, audit, "what the results support") are rc20 analyses kept
// in the appendix with an "旧版rc20" title. They read rc20 data, not the latest-version data used above.
{
const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "deck_data_rc20.json"), "utf8"));
const cases = DATA.cases.filter((r) => r.status === "VERIFIED");
const LIMITS = [90, 200, 400, 600, 900];
const iceHour = DATA.ice_by_hour, diesel = DATA.diesel, QF2 = DATA.qf2;
const get = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const getAny = (g, w) => DATA.cases.find((r) => r.grid_limit_kw === g && r.week === w);
const byLimit = (g) => cases.filter((r) => r.grid_limit_kw === g);
const shares = cases.map((r) => r.bev_trip_share_pct);
const shareMin = Math.min(...shares).toFixed(1), shareMax = Math.max(...shares).toFixed(1);
const w90 = get(90, WIN), w200 = get(200, WIN);
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };
// ---- Discussion 2 (cont.): day-ahead plan on actual PV (hindsight diagnostic)
const HS = (DATA.hindsight || []).filter((r) => r.status === "VERIFIED" && get(r.grid_limit_kw, r.week));
const hsPending = (DATA.hindsight || []).filter((r) => r.status !== "VERIFIED").map((r) => `${r.grid_limit_kw} kW ${SEASONS.find((x) => x[0] === r.week)[1]}`);
const S2state = (r) => r.stage2_solver_status === "optimal" ? "最適" : `${r.stage2_solver_status === "memory_limit" ? "メモリ上限" : "時間切れ"}（${Math.round(r.stage2_mip_gap_ratio * 100)}%）`;
const seasonOf = (w) => SEASONS.find((x) => x[0] === w)[1];
s = page(SA, "（旧版rc20）考察(2続き)　前日計画の太陽光を実際の値にした診断");
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
  "春の超過は予報の外れで説明できる。冬は予報が当たっても残る",
  "冬の実際の値の充電計画はメモリ上限で止まった解。残った超過の一部は探索不足の可能性がある",
  "予報の外れをなくしても担当便は変わらない。超過で走る電気バスは燃料バスの20倍以上高いので、本来は振り替わるはず＝探索の問題"],
  { x: 0.6, y: 2.25 + 0.42 * (HS.length * 2 + 1) + 0.2, w: 12.1, h: 2.3, fontSize: 14, paraSpaceAfter: 4 });
caption(s, `表4b　前日計画の太陽光だけを実際の値に替え、ほかの条件は同じにした診断（DIAGNOSTIC）。${hsPending.length ? `${hsPending.join("・")}は未実施` : ""}`, 0.6, 6.45, 12.1);
s.addNotes(`考察の2つ目の確かめです。前日計画の太陽光だけを、予報ではなく実際の値に替えて計算しました。${HS.map((h) => hsLine(h)).join("。")}。春は超過がほとんど消えたので、春の超過は予報の外れから来ていると言えます。冬は予報が当たっても超過が残りました。超過で走るより燃料バスで走る方がはるかに安いので、本来は燃料バスへの振り替えで避けられるはずの分です。また、どちらの季節でも電気バスの担当便は変わりませんでした。予報の外れをなくしても担当便が変わらないことから、便割当の探索が出発点から動けていないことが主な原因だと分かりました。`);

// ---- Discussion 3: rolling
s = page(SA, "（旧版rc20）考察(3)　厳しい上限では、毎時の立て直しが時間切れ・失敗しやすい");
const RL = DATA.rolling, tl = (g, w) => { const r = RL.find((x) => x.grid_limit_kw === g && x.week === w); return r ? r.time_limit : null; };
takeaway(s, "90・200 kWでは毎時の立て直しの一部が時間切れ。途中で止まった計算は結果の一覧に記載");
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
s = page(SA, "（旧版rc18・rc20）シミュレーション自体の検討（11月3〜4日の監査）");
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
  [B("充電計画"), "毎時の立て直しは厳しい上限で時間切れが多い（その時点の最良の計画を実行）", "時間切れの回数を明記"],
  [B("計算が途中で止まる問題"), "3種類の不具合を特定して修正し、直した版で計算し直した", "修正後に完了したケースは、毎時の立て直しをすべて受理。900 kW夏の電気バス寄りは別の原因で4回止まり、調査中"],
  [B("台ごとの時間の補正"), "遅い台は制限時間を延ばした（係数は実測の近似）", "作業量でそろえる方法を検討"],
  [B("仮の値・前提"), "超過費用500円/kWh、電力のCO₂係数0.5 kg/kWh、CO₂単価1円/kg。系統から蓄電池へは貯めない", "値を変えた感度の確認"],
  [B("全車燃料バス"), "走行距離からの概算で、最適化の結果ではない", "限界として明記"]],
  tableOpts({ x: 0.6, y: 2.3, w: 12.1, colW: [2.6, 5.6, 3.9], fontSize: 13, rowH: 0.56 }));
s.addNotes("結果の扱いについてです。本日の結果は、すべて診断用の結果として扱っています。便割当は全ケースでメモリの上限に当たって止まっており、最適性が確認できていません。2段階で解いているので、全体の総費用の最適でもありません。計算が途中で止まる不具合は3種類見つけて直し、直した版で計算し直しています。台ごとの時間の補正、仮の値、系統から蓄電池へ貯めないという前提も、結果を読むときの条件として残っています。中間発表では、これらを限界として明記したうえで結果を示す予定です。");

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

s = page(SA, "（旧版rc20）結果から言えること（1/2）：受電上限・費用・超過");
s.addTable([FHEAD,
  fRow(1, "電気バスの担当便は上限によらず一定（ただし出発点の影響）",
    `15件で${shareMin}〜${shareMax}%。同じ季節の中の幅は冬${seasonShare(WIN)}、春${seasonShare(spr)}、夏${seasonShare(SEASONS[2][0])}で、季節の差の方が大きい`,
    "実行した割当は出発点と98〜100%同じ。太陽光0 kW・蓄電池なしでも93.5%で、最適化の結果とは言えない（つまずき参照）"),
  fRow(2, "約700 kWから400 kWまでは、超過なしでピークを下げられる",
    `900 kWの最大受電は${rg(byLimit(900).map((r) => r.peak_grid_kw))} kWで制約が効かない。600 kWは上限まで使って超過0、400 kWの超過は最大${fmt(Math.max(...byLimit(400).map((r) => r.contract_over_limit_kwh)))} kWh`,
    "冬は200 kWと400 kWの間に、超過が出始める境目がある"),
  fRow(3, "上限を厳しくして増える費用は、ほぼすべて超過の追加費用",
    `超過の追加費用を除いた総費用は${rg(exOv, 1)}万円/週。超過の追加費用は90 kW冬で${man(w90.contract_overage_cost)}万円、200 kW冬で${man(w200.contract_overage_cost)}万円`,
    "超過で走る電気バスは燃料バスの20倍以上高く、超過費用の多くは振り替えで避けられるはず（90 kW冬で最大約66万円/週）。探索の問題で、上限の費用の大きさは言い過ぎ"),
  fRow(4, "400・600・900 kWの費用の差は、計算のばらつきと区別できない",
    `同じ季節での差は最大${top3Spread.toFixed(1)}%。解き直しの差は${REPL}。上限を緩めると高くなるケースもある（春の200→900 kW：${sprCosts.join("→")}万円）`,
    "上限の順に費用が並ばないのは、便割当の探索の違いによる。1〜2台・日（2〜4万円）より小さい差は読めない"),
  fRow(5, "超過は実行中にだけ生じる。春は予報の外れで大半が消える。冬は残る",
    `前日計画では全件で超過0。実際の太陽光で計画すると${hsS ? `春${fmt(get(90, spr).contract_over_limit_kwh)}→${fmt(hsS.contract_over_limit_kwh)} kWh` : "春は計算中"}、${hsW ? `冬${fmt(w90.contract_over_limit_kwh)}→${fmt(hsW.contract_over_limit_kwh)} kWh` : "冬は計算中"}（90 kW）`,
    "冬に残る超過も、燃料バスへの振り替えで避けられるはず。予報が当たっても担当便が動かないのは探索の問題（つまずき参照）")],
  FIND(null, 1.45, [0.42, 0.95, 0.8, 0.8, 0.95, 0.95]));
caption(s, "表6　すべてDIAGNOSTIC（研究の結論にはまだ使わない）。根拠は保存した結果、解釈は推測を含む", 0.6, 6.45, 12.1);
s.addNotes(`ここからは、結果から何が言えるかを、根拠と解釈を分けて整理します。1つ目に、受電上限は電気バスの担当便をほとんど動かしません。同じ季節の中では1ポイント程度しか動かず、季節の差の方が大きいです。総費用のほとんどが車両の使用費で、電気代と燃料代は数パーセントなので、割当は車両の使用費でほぼ決まると考えています。2つ目に、上限がないときのピークは約700 kWで、400 kWまでは超過なしに下げられます。3つ目に、上限を厳しくして増える費用は、ほぼすべて超過の追加費用で、これは仮の単価500円に比例するので、単価の感度を確かめる必要があります。4つ目に、400、600、900 kWの費用の差は、解き直したときのばらつきと同じ程度で、どれが安いかは言えません。上限を緩めた方が高くなるケースもあり、これは便割当の探索の違いによるものです。5つ目に、超過は実行中にだけ生じ、春は予報の外れ、冬は太陽光の不足で説明できます。`);

s = page(SA, "（旧版rc20）結果から言えること（2/2）：電力量・燃料バス・CO₂・計算");
s.addTable([FHEAD,
  fRow(6, "超過は電力量ではなく時間帯の問題。捨てた太陽光は買電より多い",
    `捨てた太陽光（冬・春・夏で${qf("冬", "pv_curtailed")}・${qf("春", "pv_curtailed")}・${qf("夏", "pv_curtailed")} kWh/週）が買電（${qf("冬", "grid_import")}・${qf("春", "grid_import")}・${qf("夏", "grid_import")} kWh）より多い。90 kW×168時間＝15,120 kWhも買電より大きい`,
    "蓄電池の使える範囲3,600 kWhは冬の充電の約1日分で、晴れの日の余りを曇りの日へ持ち越せない（柱Bで確かめる）"),
  fRow(7, "燃料バスは早朝と深夜の便に集中し、上限によらない",
    `燃料バスの担当率は早朝（5〜6時台）${rng("05-06")}、深夜（22時以降）${rng("22-")}、日中${rng("07-21")}`,
    "理由は未確認。仕業の端や夜の充電時間と重なる便と見ている"),
  fRow(8, "CO₂は全車燃料バスより約" + `${rg(co2CutAll)}%少なく、残りの大部分は買電から`,
    `併用は${rg(cases.map((r) => r.total_co2_kg / 1000), 2)} t/週、全車燃料バス（概算）は${rg(diesel.map((d) => Number(d.co2_kg) / 1000), 1)} t/週。併用のCO₂のうち買電が${rg(gridCo2)}%`,
    "さらに減らすには買電の量と電力の係数（仮の0.5 kg/kWh）が効く。全車燃料バスは概算で、最適化した値はまだない"),
  fRow(9, "買電で走る電気バスは、燃料バスより1 kmあたり少し高い",
    `買電の電気バス${bevGridPerKm.toFixed(1)}円/km、燃料バス${iceePerKm.toFixed(1)}円/km（入力の係数）。全車燃料バスの概算の総費用は${rg(diesel.map((d) => Number(d.total_cost) / 1e4), 0)}万円/週`,
    "電気バスが得なのは太陽光・蓄電池の電気で走る分。設備の規模が変われば結論も変わりうる"),
  fRow(10, "厳しい上限ほど解きにくく、完走も台と実行に左右される",
    `毎時の立て直し175回中の時間切れは90 kWで${rg(tlOf(90))}回、200 kW冬で${tl(200, WIN)}回、400 kW以上で0回。便割当のギャップは全件で約45%`,
    "本番の1回目に2件、解き直しは6件中4件が完走せず。完走したものどうしの差は0.4%以内"),
  fRow(11, "便割当の見込みの修正（rc18→rc20）でも、担当便の結論は変わらない",
    `費用の差は${RC18.dMin}〜+${RC18.dMax}万円（最大1.8%）。担当便はrc18で${RC18.shareMin}〜${RC18.shareMax}%、rc20で${shareMin}〜${shareMax}%`,
    "結論1は、便割当の段階の見込みの修正に対して頑健")],
  FIND(null, 1.4, [0.4, 0.82, 0.62, 0.78, 0.66, 0.8, 0.62]));
caption(s, "表7　すべてDIAGNOSTIC。CO₂の係数・超過の単価は仮の値", 0.6, 6.55, 12.1);
s.addNotes(`続きです。6つ目に、超過は電力量の不足ではなく時間帯の問題です。どの季節も、捨てた太陽光の方が買電より多く、蓄電池は冬の充電の約1日分しかないので、晴れの日の余りを曇りの日に持ち越せません。これが柱Bで日をまたいだ計画を調べる理由です。7つ目に、燃料バスは早朝と深夜の便に集中しています。理由はまだ確かめていません。8つ目に、CO₂は全車燃料バスより大きく減り、残りの大部分は買電から来ています。9つ目に、買電で走る電気バスは燃料バスより少し高く、電気バスが得なのは太陽光と蓄電池の電気で走る分です。10個目に、厳しい上限ほど計算が難しく、完走するかどうかも台や実行によって変わります。11個目に、便割当の見込みを直す前と後で、担当便の結論は変わりませんでした。`);

s = page(SA, "結果からまだ言えないこと・次に確かめること");
[["まだ言えないこと", [
  "電気バスと燃料バスの最適な分け方（便割当が出発点からほとんど動かない）",
  "最適であること（便割当のギャップ約45%、2段階法で全体の最適ではない）",
  "400・600・900 kWのどれが安いか（差がばらつきと同じ程度）",
  "超過の費用の大きさ（500円/kWhは仮の値）",
  "年間や特別な週（GWなど）への一般化（各季節1週間）",
  "全車燃料バスとの費用・CO₂の差（いまは概算）"], "F5F5F5", GRID],
 ["次に確かめること", [
  "超過の単価の感度（100〜1,000円/kWh）→ 3",
  `実際の太陽光での診断の残り（${hsPending.length ? hsPending.join("・") : "完了"}）→ 5`,
  "全車燃料バスの最適化（未実施）→ 8・9",
  "蓄電池の容量の感度と柱B（日をまたいだ計画）→ 6",
  "燃料バスの仕業から、早朝・深夜に偏る理由 → 7"], "EEF5FB", BLUE]].forEach(([h, items, fill, line], i) => {
  const x = 0.6 + i * 6.15;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: 5.95, h: 4.8, fill: { color: fill }, line: { color: line, width: 1 } });
  text(s, h, { x: x + 0.25, y: 1.65, w: 5.45, h: 0.45, fontSize: 18, bold: true, color: BLUE_DARK });
  bullets(s, items, { x: x + 0.25, y: 2.2, w: 5.45, h: 3.95, fontSize: 15, paraSpaceAfter: 8 });
});
caption(s, "右の矢印の数字は、前の2ページの「言えること」の番号", 0.6, 6.45, 12.1);
s.addNotes("最後に、今の結果ではまだ言えないことと、次に確かめることです。最適であること、400、600、900 kWのどれが安いか、超過の費用の大きさ、年間や特別な週への一般化、全車燃料バスとの差は、まだ言えません。次に、超過の単価の感度、実際の太陽光での診断の残り、全車燃料バスの最適化、蓄電池の容量の感度と柱B、燃料バスの便の仕業を確かめます。");

}

// ---- Stumbling points found by checking the results (11/4-11/5; numbers from the saved runs, DIAGNOSTIC)
s = page(S5, "今回のつまずきと対応（11月4〜5日の検証）");
takeaway(s, "結果の検証で、モデルの前提と探索に問題が見つかった。直して柱Aを計算し直している");
s.addTable([
  [H("つまずき"), H("見つけ方・事実"), H("影響"), H("対応")],
  [B("燃料バスが週の間に給油しない前提"), "便割当の燃料の制約が「初期の軽油−下限」の1週間分だけ（48〜127 L＝約220〜570 km/週）。電気バスは毎晩充電", "燃料バスが電気バスの仕業を引き受けられず、全車燃料バスは解なし", "車庫で給油する方式を実装（rc21）。初期20〜90%、運用20〜100%"],
  [B("便割当が出発点から動かない"), "実行した割当は出発点と98〜100%同じ。ALNSの改善は0〜2.3万円。太陽光0 kW・蓄電池なしでも電気バス93.5%", "電気バスの担当便は最適化の結果でない。上限による差が出なかった理由", "出発点2つ（電気バス寄り・燃料バス寄り）で解き安い方を採る。車両ごとの入れ替え操作を検討"],
  [B("ギャップ45%の中身"), "下界は車両の使用費だけ（約224万円）で弱い", "解の質を示せない", "小さい問題で厳密解と比べて質を示す（予定）"],
  [B("燃料代の数え方"), "満タンにすると週末にタンクに残る軽油も費用に入る（同じ配車で+4.4万円）", "全車燃料バスとの比較が不公平になる", "燃料は使った分で数えた総費用を主に、会計値も併記"],
  [B("計算の基盤"), "子機のディスク満杯で回収失敗、改行コード（CRLF）でPrepare停止、ssh の取り違え、メモリ不足の台", "診断1件が失敗、半日の遅れ", "古い生データをDへ退避（自動化）、手順を修正"]],
  tableOpts({ x: 0.6, y: 2.2, w: 12.1, colW: [2.3, 4.1, 2.8, 2.9], fontSize: 11, rowH: [0.38, 0.8, 0.85, 0.55, 0.62, 0.7] }));
caption(s, "表8　保存した計算結果とコードの確認による。数値はすべてDIAGNOSTIC", 0.6, 6.45, 12.1);
s.addNotes("今回の検証で見つかったつまずきをまとめます。1つ目に、燃料バスが1週間の間に一度も給油しない前提になっていました。電気バスは毎晩充電できるので、燃料バスにだけ不利な比べ方になっていて、燃料バスが電気バスの仕事を引き受けられませんでした。車庫で給油する方式を実装して直しました。2つ目に、便割当の計算が出発点の割当からほとんど動いていませんでした。実行した割当は出発点と98から100%同じで、太陽光も蓄電池もない場合でも電気バスが93.5%を担当していました。電気バスの担当便が上限によらず一定だったのは、最適化の結果ではなかったということです。出発点を2つにして、安い方を採る形で計算し直しています。3つ目に、ギャップ45%の下界は車両の使用費だけから作った弱いもので、解の質を示せていません。小さい問題で厳密解と比べる予定です。4つ目に、満タンに給油すると、週末に残る軽油も費用に入るので、燃料は使った分で数えた費用を主に示します。5つ目は計算の基盤の問題で、ディスクや改行コードなどで半日ほど遅れました。");

// ---- Where the overage comes from (rc20 90 kW winter; saved Stage 1 recourse, Stage 2 and executed plans)
s = page(SA, "（旧版rc20）超過はどこで生まれるか（90 kW冬の解剖）");
takeaway(s, "便割当の見積もりは超過0の充電方法を示すが、充電計画がそれを見つけられていない");
s.addTable([
  [H("90 kW・冬"), H("便割当の見積もり"), H("前日の充電計画"), H("実行（毎時の立て直し）")],
  [B("予報（平年値）で計画"), "買電 1,141 kWh・超過 0", "買電 1,172 kWh・超過 0", { text: "買電 3,481 kWh・超過 1,397 kWh", options: { bold: true, color: BLUE_DARK } }],
  [B("実際の太陽光で計画"), "買電 3,712 kWh・超過 0", { text: "買電 3,219 kWh・超過 1,209 kWh（ギャップ47%）", options: { bold: true, color: BLUE_DARK } }, "買電 3,265 kWh・超過 1,209 kWh"]],
  tableOpts({ x: 0.6, y: 2.2, w: 12.1, colW: [2.6, 3.0, 3.4, 3.1], fontSize: 13, rowH: [0.42, 0.55, 0.55] }));
bullets(s, [
  "予報で計画した場合：前日には曇りの日の不足が見えず、実行で買電が約3倍になる（柱Bの論点）",
  "実際の太陽光で計画した場合：便割当の見積もりは「昼に上限以内で買い、蓄電池を夜まで残す」方法で超過0。充電計画は昼に買わず、夕方に蓄電池が下限（1,200 kWh）に達し、夜に最大660 kWを買電",
  "1週間の蓄電池からバスへの量は同じ（18,422／18,829 kWh）。違いは時間の使い方＝充電計画（7日・約700区切り・38台の大きなMILP）の探索不足",
  "対策（rc22で試算）：(a) 便割当の見積もりを充電計画へヒントとして渡す（モデルは変えない）、(c) 毎時の立て直しを bound_first に。低い上限（90・200 kW）で効き目を確かめる"],
  { x: 0.6, y: 4.0, w: 12.1, h: 2.4, fontSize: 13, paraSpaceAfter: 4 });
caption(s, "表8b　rc20の保存した結果から。DIAGNOSTIC", 0.6, 6.45, 12.1);
s.addNotes("超過がどこで生まれているかを、90 kWの冬で解剖しました。予報で前日の計画を立てた場合は、便割当の見積もりも前日の充電計画も超過は0ですが、実行すると買電が約3倍になり、超過が出ます。前日には曇りの日の不足が見えないためで、これは柱Bの論点です。実際の太陽光で前日の計画を立てた場合でも、充電計画の段階で超過が出ています。便割当の見積もりは、昼のうちに上限以内で買って蓄電池を夜まで残すことで超過を0にしていますが、充電計画は昼に買わず、夕方に蓄電池が下限に達して、夜に大きく買電しています。1週間で蓄電池から送った量は同じなので、違いは時間の使い方で、充電計画の探索が足りないことが原因です。対策として、便割当の見積もりを充電計画にヒントとして渡す方法と、毎時の立て直しの探索の設定を変える方法を、低い上限で試しています。");

// ---- rc23 countermeasure trial (ff7bdaed, DIAGNOSTIC). Executed contract overage kWh / peak grid kW of the
// accepted 175-step chain, from evaluate_multiface.py (output/midterm_20261128/rc23_eval/rc23_eval3-12.md).
// null = still computing on 11/7: fill in when the case is collected.
const RC23 = {
  "90/2025-01-06": { base: [1452, 711], hint: [1395, 644], hintbf: [1442, 593] },
  "200/2025-01-06": { base: [532, 609], hint: [503, 578], hintbf: [542, 450] },
  "90/2025-04-07": { base: [260, 290], hint: [133, 198], hintbf: [308, 280] },
  "90/2025-07-07": { base: [311, 414], hint: [285, 267], hintbf: [258, 237] } };
const RC20_CASES = JSON.parse(fs.readFileSync(path.join(__dirname, "deck_data_rc20.json"), "utf8")).cases;
const ovCell = (v) => (v ? `${fmt(v[0])} kWh／${fmt(v[1])} kW` : { text: "計算中", options: { color: GREY } });
s = page(SA, "（旧版rc23）対策の試算：同じ条件での揺れのほうが大きい");
takeaway(s, "対策の違いによる差は、同じ設定の結果の揺れ（春 133〜308 kWh）に埋もれ、効いたとは言えない");
s.addTable([
  [H("ケース"), H("rc20（対策前）"), H("rc23 対策なし"), H("rc23 ヒント"), H("rc23 ヒント＋bound_first")],
  ...[[90, WIN, "90 kW・冬"], [200, WIN, "200 kW・冬"], [90, "2025-04-07", "90 kW・春"], [90, "2025-07-07", "90 kW・夏"]].map(([g, w, label]) => {
    const r = RC20_CASES.find((x) => x.grid_limit_kw === g && x.week === w), c = RC23[`${g}/${w}`];
    return [B(label), r ? `${fmt(r.contract_over_limit_kwh)} kWh／${fmt(r.peak_grid_kw)} kW` : "—", ovCell(c.base), ovCell(c.hint), ovCell(c.hintbf)];
  })],
  tableOpts({ x: 0.6, y: 2.2, w: 12.1, colW: [2.1, 2.5, 2.5, 2.5, 2.5], fontSize: 14, align: "center", rowH: [0.42, 0.48, 0.48, 0.48, 0.48] }));
bullets(s, [
  "春の「ヒント」と「ヒント＋bound_first」は、便割当・燃料代・車両費が1円まで同じ。違うのは毎時の充電計画の解き方だけなのに、超過が 133 と 308 kWh",
  "毎時の充電計画は1回120秒で打ち切り、その時点の最良案を使う（175回中27〜29回が時間切れ）。どこで打ち切られたかの差が1週間で積み重なる（推定）",
  "bound_first は200 kW冬で最大受電を下げた（578→450 kW）が、超過量は減らない",
  "rc22で見つかった不具合2つを直した：満充電のバスにも充電を強制（実行不能の原因）／超過量の報告のずれ（約0.01円）"],
  { x: 0.6, y: 4.7, w: 12.1, h: 1.7, fontSize: 13, paraSpaceAfter: 3 });
caption(s, "表8c　各セルは1週間の実行の超過量／最大受電。rc23（ff7bdaed）、各1回の計算。DIAGNOSTIC", 0.6, 6.45, 12.1);
s.addNotes("前回の解剖を受けて、対策を試算しました。便割当の見積もりを充電計画へヒントとして渡す方法と、毎時の立て直しを bound_first という探索の設定にする方法です。途中で、モデルの不具合を2つ見つけて直し、rc23として計算し直しました。結果は表のとおりで、春の90 kWでは、ヒントありが133 kWh、ヒントと bound_first の組み合わせが308 kWhでした。この2つは、便の割当も燃料代も1円まで同じで、違うのは毎時の充電計画の解き方だけです。毎時の計画は120秒で打ち切って、その時点の一番良い案を使っているので、どこで打ち切られたかの違いが1週間で積み重なったと考えています。したがって、1回ずつの計算では、対策が効いたとは言えません。bound_first は最大受電を下げる傾向はありますが、超過量は減っていません。");

// ---- Where in the executed week the overage falls, and whether it is a time-limit effect
// (rolling_overage_by_step.py on the rc23 archives; executed hour = first 60 min of each step)
s = page(SA, "（旧版rc23）超過は実行のどの時間に出るか：時間切れが原因ではない");
takeaway(s, "超過は特定の夜に集中し、多くは「最後まで解けた」時間に出る。制限時間を伸ばしても大部分は残る");
s.addTable([
  [H("ケース（rc23 ヒント）"), H("1週間の超過"), H("集中する時間"), H("そのうち時間切れの時間の分"), H("時間切れした回数")],
  [B("90 kW・冬"), "1,396 kWh", "1日目23時〜2日目6時に 1,301 kWh（93%）", "271 kWh（19%）", "35／175回"],
  [B("90 kW・春"), "133 kWh", "最終日23時〜週の終わりに 126 kWh（95%）", "0 kWh", "27／174回"],
  [B("90 kW・春（＋bound_first）"), "308 kWh", "同じ時間に 282 kWh（91%）", "6 kWh（2%）", "29／174回"],
  [B("90 kW・春（制限時間4倍）"), "203 kWh", "同じ時間に 186 kWh（91%）", "0 kWh", "24／174回"]],
  tableOpts({ x: 0.6, y: 2.2, w: 12.1, colW: [2.7, 1.5, 4.4, 2.1, 1.4], fontSize: 13, rowH: [0.42, 0.42, 0.42, 0.42, 0.42] }));
bullets(s, [
  "「最後まで解けた」時間の超過は、その時点の電池の残りからは避けられない（23〜6時に上限内で買えるのは 90 kW×7時間＝630 kWh まで）",
  "原因は、超過が出る夜より前の計画：その前に充電しておく（太陽光・蓄電池・昼の買電）か、足りない分を燃料バスに回す。後者は「超過費用は燃料バスの約20倍／km」という前回の指摘と同じ",
  "春の週末の集中は、週の終わりに電池を週の初めの量へ戻す決まり（期末条件）による可能性がある（推定・未確認）",
  "確認：春のヒントを毎時の制限時間4倍（480秒）にすると超過 203 kWh（120秒では 133 kWh）。時間切れは24回でその分の超過は0、最後の夜に 186 kWh（91%）。伸ばしても減らない（台が違い、便割当も少し違う）"],
  { x: 0.6, y: 4.55, w: 12.1, h: 1.85, fontSize: 13, paraSpaceAfter: 3 });
caption(s, "表8d　毎時の立て直しの各回で実行した1時間の超過を、その回の充電計画の状態（最適／時間切れ）で分けた。DIAGNOSTIC", 0.6, 6.45, 12.1);
s.addNotes("では、制限時間を伸ばせば超過は減るのかを確かめました。毎時の立て直しの各回で、実際に実行した1時間の超過を、その回の計算が最後まで解けたか、時間切れだったかで分けました。冬の90 kWでは、1週間の超過1,396 kWhのうち93%が、1日目の夜から2日目の朝の1晩に集中していて、時間切れの回の分は19%でした。春は、超過の9割以上が週の最後の夜に集中していて、時間切れの回の分はほぼ0でした。最後まで解けた回の超過は、その時点の電池の残りからは避けられないものです。90 kWでは、夜の23時から朝6時までに上限内で買えるのは630 kWhまでだからです。つまり、原因はその夜より前の計画にあり、前もって充電しておくか、足りない分を燃料バスに回す必要があります。後者は、超過費用が燃料バスの約20倍になるという前回の指摘と同じ方向です。念のため、制限時間を4倍にした計算もしました。結果は超過203 kWhで、120秒のときの133 kWhより減りませんでした。時間切れの回の超過は0で、9割が最後の夜に出ています。つまり制限時間を伸ばしても超過は減らず、原因は計画の構造にあると言えます。");

s = page(SA, "（11/5時点）柱Aの計算し直しの設計（rc21）");
takeaway(s, "基準＝全車燃料バスの従来運行。そこから電化したときの費用・CO₂・運行を、出発点に左右されない形で比べる");
s.addTable([
  [H("項目"), H("内容")],
  [B("基準"), "全車燃料バス60台の従来運行（車庫で給油、配車して運行させるだけの簡単な計算でよい）"],
  [B("柱Aの本体"), "受電上限 90・400・900 kW × 冬・春・夏、太陽光1,000 kW（今の設備）"],
  [B("柱Aの広げ（電化の構成）"), "太陽光 1,000・500・250・0 kW（0 kWは最後）"],
  [B("出発点"), "電気バス寄り（前の版の割当）と燃料バス寄り（燃料バス25台を全部使う）の2つで解き、総費用の安い方を採る。差を出発点への依存として示す"],
  [B("燃料バス"), "車庫で給油。初期の軽油は20〜90%の乱数を一度だけ振る。運用は20〜100%"],
  [B("評価"), "費用（燃料は使った分）・運行（全便・物理検査・毎時の立て直し）・CO₂（単価の感度つき）"],
  [B("台"), "7台・8枠を全部使う（1件2〜4時間、遅い台は時間を延ばす）"]],
  tableOpts({ x: 0.6, y: 2.2, w: 12.1, colW: [2.8, 9.3], fontSize: 13, rowH: 0.5 }));
caption(s, "表9　結果は11/12に間に合った分から示す。柱B（日をまたいだ計画）はこの後", 0.6, 6.45, 12.1);
s.addNotes("計算し直しの設計です。基準は、燃料バスだけの従来の運行です。そこから電気バスを入れたときに、費用、運行、CO₂がどう変わるかを比べます。柱Aの本体は受電上限の3段階と3季節で、太陽光は今の設備の1,000 kWです。電化の構成として、太陽光を500、250、0 kWに減らした場合も計算します。すべてのケースを電気バス寄りと燃料バス寄りの2つの出発点で解き、安い方を採ります。2つの差は、結果が出発点にどれだけ左右されるかを示す目安になります。柱Bの日をまたいだ計画は、この後に進めます。");

// ---- Summary
s = page(S6, "まとめ");
// Latest-version pairs (DATA.pairs, fuel valued by litres burnt as elsewhere in the deck).
const pairCost = (g, w, st) => { const r = (DATA.pairs || []).find((x) => x.grid_limit_kw === g && x.week === w && x.start === st && x.status === "VERIFIED"); return r; };
const pb9 = pairCost(900, WIN, "bev"), pi9 = pairCost(900, WIN, "ice"), pb90 = pairCost(90, WIN, "bev"), pi90 = pairCost(90, WIN, "ice");
const tc = (r) => r.total_cost_fuel_consumed;
const abate90 = (tc(pb90) - tc(pi90)) / (pi90.total_co2_kg - pb90.total_co2_kg);
[[`${man(tc(pi9) - tc(pb9))}万円安く`, "電化の効果（900 kW冬）", `電気バス中心は燃料バス中心より／CO₂は${Math.round((1 - pb9.total_co2_kg / pi9.total_co2_kg) * 100)}%少ない`],
 [`約${Math.round(abate90)}円／kg`, "CO₂を減らす費用（90 kW冬）", `燃料バス寄りが${man(tc(pb90) - tc(pi90))}万円安いが／CO₂は${(pi90.total_co2_kg / pb90.total_co2_kg).toFixed(1)}倍`],
 ["9割", "超過が火曜未明に集中", "蓄電池が空になる夜／予報を7割と見込むと半分に減る"]].forEach(([big, label, sub], i) => {
  const x = 0.6 + i * 4.1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 1.6, w: 3.9, h: 3.0, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  text(s, label, { x: x + 0.2, y: 1.75, w: 3.5, h: 0.45, fontSize: 15, color: SUB, align: "center" });
  text(s, big, { x: x + 0.1, y: 2.25, w: 3.7, h: 0.9, fontSize: 28, bold: true, color: BLUE_DARK, align: "center", valign: "middle" });
  text(s, sub.split("／").map((t, j, a) => ({ text: t, options: { breakLine: j < a.length - 1 } })), { x: x + 0.25, y: 3.25, w: 3.4, h: 1.2, fontSize: 14, align: "center" });
});
bullets(s, [
  "一言でいうと：受電が十分なら電化は「安い＋CO₂が少ない」。受電が少ないと「安さかCO₂か」の選択になる",
  iceWins.length ? `受電上限が下がると電気バス中心の優位は縮み、${iceWins.map(lab).join("・")}では燃料バス寄りが安い（最新版、安い方の出発点）` : "どの受電上限でも電気バス寄りが安い（最新版）",
  "次：系統から蓄電池へ貯めない前提のもとで、超過の夜だけ燃料バスに回す割当を探し、超過単価・CO₂単価の感度で結論の向きを確かめる"],
  { x: 0.6, y: 4.85, w: 12.1, h: 1.95, fontSize: 15, paraSpaceAfter: 6 });
s.addNotes(`まとめです。数値はすべて最新の版の結果です。受電上限900キロワットの冬では、電気バス中心の運用が燃料バス中心より約${man(tc(pi9) - tc(pb9))}万円安く、CO₂も約${Math.round((1 - pb9.total_co2_kg / pi9.total_co2_kg) * 100)}パーセント少なくなりました。一方、90キロワットの冬では燃料バス寄りが約${man(tc(pb90) - tc(pi90))}万円安く、CO₂は約${(pi90.total_co2_kg / pb90.total_co2_kg).toFixed(1)}倍で、電気バス寄りにしてCO₂を減らす費用は1キログラムあたり約${Math.round(abate90)}円です。超過の9割は、蓄電池が空になった火曜の未明に集中していて、予報を控えめに見る対策では直りませんでした。次は、系統から蓄電池へ貯めない今の前提のもとで、超過の夜だけ燃料バスに回す割当を探し、単価の感度で結論の向きを確かめます。`);


// ---- Plan
s = page(S6, "今後の予定");
const PERIODS = ["11月上旬", "11月中旬", "11月下旬", "12月前半", "12月後半", "1月〜"];
const GX = 5.0, GW = (12.7 - GX) / PERIODS.length, GY = 1.6, RH = 0.62;
PERIODS.forEach((p, i) => {
  s.addShape(pres.shapes.RECTANGLE, { x: GX + i * GW, y: GY, w: GW, h: 0.5, fill: { color: HEAD }, line: { color: GRID, width: 0.75 } });
  text(s, p, { x: GX + i * GW, y: GY, w: GW, h: 0.5, fontSize: 13, bold: true, align: "center", valign: "middle" });
});
const TASKS = [["柱A", "超過の夜だけ燃料バスに回す割当、同じ版での出発点比較、単価の感度", 0, 2], ["柱A", "中間発表（11/28、A0ポスター）の準備", 1, 3],
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
s.addNotes("今後の予定です。11月中旬までは、超過の夜だけ燃料バスに回す割当の探索、同じ版での出発点の比較、超過とCO₂の単価の感度を進め、並行して11月28日の中間発表のポスターを準備します。柱Bは11月中に日ごとの計画をつなぐ仕組みを仕上げ、12月前半に冬・春・夏の3季節で計算し、年内に結果をまとめます。1月以降は、運行や利用者の観点を取り入れた3本目の柱を検討しています。以上です。ご指導をお願いいたします。");

// ---- References
s = page("参考文献", "参考文献");
text(s, [
  "［1］環境省・経済産業省：温室効果ガス排出量算定・報告・公表制度 算定方法及び排出係数一覧（2025年版，軽油 2.62 tCO₂/kL，p.23）；電気事業者別排出係数一覧（令和8年提出用，2026年8月3日更新）",
  "［2］W. F. Holmgren, C. W. Hansen, M. A. Mikofski: pvlib python: a python package for modeling solar energy systems, Journal of Open Source Software, 3(29), 884, 2018",
  "［3］公共交通オープンデータセンター：東急バス 時刻表データ（ODPT）",
  "［4］Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0",
  "［5］P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, Proc. CP-98, LNCS 1520, pp. 417–431, 1998",
  "［6］S. S. G. Perumal, R. M. Lusby, J. Larsen: Electric bus planning & scheduling: A review of related problems and methodologies, European Journal of Operational Research, 301(2), pp. 395–413, 2022",
  "［7］M. Rinaldi, E. Picarelli, A. D'Ariano, F. Viti: Mixed-fleet single-terminal bus scheduling problem: Modelling, solution scheme and potential applications, Omega, 96, 102070, 2020"]
  .map((t, i, a) => ({ text: t, options: { breakLine: i < a.length - 1 } })),
  { x: 0.6, y: 1.5, w: 12.1, h: 4.9, fontSize: 13, paraSpaceAfter: 8, lineSpacingMultiple: 1.1 });
caption(s, "［5］〜［7］は原文を入手中（書誌情報のみ確認）。電力の係数は［1］の値ではなく仮の0.5 kg/kWh", 0.6, 6.45, 12.1, 0.45);
s.addNotes("参考文献です。原本は研究フォルダの先行文献フォルダにまとめて保存しています。軽油のCO₂係数2.62は［1］の一覧の値です。電力の係数は、今は仮の0.5を使っており、［1］の電気事業者別の値はまだ使っていません。ご質問の際に必要であればご覧ください。");

// ---- Positioning: novelty / usefulness / originality (claims checked against what the model and runs actually do)
s = page(S1, "本研究の位置づけ：新規性・有用性・独創性");
takeaway(s, "燃料バスとの混成で、便割当・充電・太陽光と蓄電池・受電上限を、1週間の実行まで通して評価");
[["新規性", "何が新しいか", [
   "電気バスの運用・充電計画の研究は多い［6］。燃料バスとの混成の便割当も研究がある［7］",
   "本研究はそこへ、営業所の太陽光・蓄電池と受電の契約上限を加え、1週間を通して扱う",
   "前日の計画だけでなく、実際の天気で毎時立て直した「実行」で費用・CO₂・超過を評価する"]],
 ["有用性", "誰の何に役立つか", [
   "事業者が決める受電契約・太陽光の規模・電化の度合いを、費用・CO₂・運行の3面で比べられる",
   `電化によるCO₂の削減を「1 kgあたり何円」で示せる（90 kW冬：約${Math.round(abate90)}円／kg）`,
   "実データ：東急バス渋21〜23の時刻表（ODPT）、実際の日射、60台・1,704便／週"]],
 ["独創性", "どこが独自か", [
   "超過が「いつ・なぜ」出るかを、毎時の実行から解剖する（特定の夜に集中、時間切れではない）",
   "出発点の違う2つの割当で解き、結論が出発点に左右されないかを確かめる検証の枠組み",
   "計画（前日）と実行（毎時）の差を分けて示し、柱B（日をまたいだ計画）の必要性につなげる"]]].forEach(([h, sub, items], i) => {
  const x = 0.6 + i * 4.1;
  s.addShape(pres.shapes.RECTANGLE, { x, y: 2.25, w: 3.9, h: 4.1, fill: { color: i === 2 ? "EEF5FB" : "F7F7F7" }, line: { color: i === 2 ? BLUE : GRID, width: 1 } });
  text(s, [{ text: h, options: { fontSize: 22, bold: true, color: BLUE_DARK, breakLine: true } }, { text: sub, options: { fontSize: 13, color: SUB } }], { x: x + 0.2, y: 2.35, w: 3.5, h: 0.8 });
  bullets(s, items, { x: x + 0.2, y: 3.2, w: 3.55, h: 3.1, fontSize: 13, paraSpaceAfter: 6 });
});
caption(s, "［6］［7］は参考文献。先行研究との比較は調査を続けている", 0.6, 6.45, 12.1);
s.addNotes("本研究の位置づけです。電気バスの車両運用と充電計画の研究は数多くあり、燃料バスとの混成で便を割り当てる研究もあります。本研究の新しい点は、そこに営業所の太陽光と蓄電池、受電の契約上限を加えて1週間を通して扱い、さらに前日の計画だけでなく、実際の天気で毎時立て直した実行の結果で費用、CO₂、超過を評価する点です。有用性としては、事業者が決める受電契約、太陽光の規模、電化の度合いを、費用、CO₂、運行の3つの面から比べられること、電化によるCO₂削減を1キログラムあたりの費用で示せることです。データは東急バスの実際の時刻表と実際の日射です。独創性としては、超過がいつ、なぜ出るのかを毎時の実行から解剖する点と、出発点の違う2つの割当で解いて、結論が出発点に左右されないかを確かめる枠組みです。先行研究との詳しい比較は、引き続き調査しています。");


// ---- Two start points at 90 kW winter (evaluate_multiface.py -> output/midterm_20261128/rc23_eval/ice90w.md).
// 11/8 pair on one version (rc23_eval/rc33_090w_pair.md): rc33 (7dc38d95) g090 BEV-heavy start, h090 ICE-heavy
// start. Same parent scenario, prepared settings and overrides; only the Stage 1 seed differs. DIAGNOSTIC.
const SP = { bev: { cost: 4794193, share: 93.1, bevN: 27, iceN: 11, over: 1291, overCost: 645317, grid: 3244, co2: 2136, diesel: 196 },
             ice: { cost: 4390136, share: 30.8, bevN: 24, iceN: 24, over: 0, overCost: 0, grid: 0, co2: 6354, diesel: 2425 } };
const spDiff = SP.bev.cost - SP.ice.cost, spAbate = spDiff / (SP.ice.co2 - SP.bev.co2);
s = page(S3, "出発点2つの比較（90 kW・冬）：費用とCO₂のトレードオフ");
takeaway(s, `燃料バス寄りは${man(spDiff)}万円安いが、CO₂は${(SP.ice.co2 / SP.bev.co2).toFixed(1)}倍。差のほぼ全部が超過費用`);
s.addTable([
  [H("90 kW・冬（1週間）"), H("電気バス寄りの出発点"), H("燃料バス寄りの出発点")],
  [B("電気バスの担当便"), `${SP.bev.share}%（電気${SP.bev.bevN}・燃料${SP.bev.iceN}台）`, `${SP.ice.share}%（電気${SP.ice.bevN}・燃料${SP.ice.iceN}台）`],
  [B("総費用（燃料は使った分）"), `${man(SP.bev.cost)}万円`, { text: `${man(SP.ice.cost)}万円（−${man(spDiff)}万円）`, options: { bold: true, color: BLUE_DARK } }],
  [B("うち超過費用"), `${man(SP.bev.overCost)}万円（${fmt(SP.bev.over)} kWh）`, "0"],
  [B("買電"), `${fmt(SP.bev.grid)} kWh`, "0 kWh（太陽光・蓄電池のみ）"],
  [B("CO₂"), `${fmt(SP.bev.co2)} kg`, { text: `${fmt(SP.ice.co2)} kg（軽油 ${fmt(SP.ice.diesel)} L）`, options: { bold: true, color: BLUE_DARK } }]],
  tableOpts({ x: 0.6, y: 2.2, w: 7.9, colW: [2.3, 2.8, 2.8], fontSize: 13, rowH: 0.46 }));
s.addShape(pres.shapes.RECTANGLE, { x: 8.7, y: 2.2, w: 4.0, h: 2.76, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
text(s, [{ text: "CO₂を減らす費用", options: { fontSize: 15, color: SUB, breakLine: true } },
  { text: `約${Math.round(spAbate)}円／kg`, options: { fontSize: 32, bold: true, color: BLUE_DARK, breakLine: true } },
  { text: "電気バス寄りにすると、CO₂ 1 kgを減らすのにかかる追加の費用（差額÷CO₂の差）", options: { fontSize: 12, color: SUB } }],
  { x: 8.85, y: 2.3, w: 3.7, h: 2.6, align: "center", valign: "middle" });
bullets(s, [
  `超過費用を除くと、電気バス寄りの方が${man(SP.ice.cost - (SP.bev.cost - SP.bev.overCost))}万円安い。最適な割当は2つの間にある：電気バス中心のまま、超過が出る夜の仕業だけ燃料バスに回す`,
  "探索を強めても、電気バス寄りの出発点からは燃料バスへ動かない（燃料バス寄りからは電気バスへ動き、7.6万円安くなった）",
  "超過の原因は前日計画の太陽光の見込み（表8i）。超過単価500円は仮の値で、結論はこれに左右される"],
  { x: 0.6, y: 5.15, w: 12.1, h: 1.3, fontSize: 13, paraSpaceAfter: 2 });
caption(s, "表8e　90 kW・冬の1週間の実行結果。rc33（7dc38d95）、違うのは出発点だけ。175回の毎時の立て直しをすべて受理、物理検査 VALID。DIAGNOSTIC", 0.6, 6.5, 12.1, 0.35);
s.addNotes(`ここが今日の中心です。90 kWの冬を、電気バス寄りと燃料バス寄りの2つの出発点で解きました。違うのは出発点だけで、設定は同じです。電気バス寄りでは電気バスが${SP.bev.share}%の便を担当し、燃料バス寄りでは${SP.ice.share}%でした。総費用は燃料バス寄りの方が約${man(spDiff)}万円安く、超過も買電も0でしたが、CO₂は約${(SP.ice.co2 / SP.bev.co2).toFixed(1)}倍になりました。費用の差のほぼ全部が超過費用で、超過費用を除くと、電気バス寄りの方が約${man(SP.ice.cost - (SP.bev.cost - SP.bev.overCost))}万円安くなります。つまり、最適な割当はこの2つの間にあり、電気バス中心のまま、超過が出る夜の仕業だけを燃料バスに回すのがよいと考えています。電気バス寄りにしたときのCO₂削減の費用は、1キログラムあたり約${Math.round(spAbate)}円です。便割当の探索を強めた今回の版では、燃料バス寄りから出発すると電気バスが増える方向に動き、費用も下がりましたが、電気バス寄りから出発すると燃料バスへは動きませんでした。前日計画では超過が見えていないためで、その原因は、先ほどの太陽光の見込みの頁でご説明したとおりです。超過の単価500円は仮の値で、結論の向きはこの値に左右されます。`);


// ---- Questions for the supervisors
s = page(S6, "ご相談したいこと");
takeaway(s, "結論の向きを左右する2つの値と、中間発表で主張する範囲についてご意見をいただきたい");
[["1", "超過の単価（今は仮に500円／kWh）", "実際の高圧契約では、上限を超えると以後の基本料金が上がるのが一般的。電気バス寄りと燃料バス寄りのどちらが安いかは、この値で逆転しうる。どの値・範囲で感度を取るべきか"],
 ["2", "CO₂の扱い", "費用にCO₂の単価を掛けて1つの目的にまとめるか、費用とCO₂の2つの目的として、両者の兼ね合い（パレート）で示すか。今の目安は約96円／kgで逆転"],
 ["3", "11/28 中間発表の主張の範囲", "「出発点で結果が大きく変わること」「費用とCO₂のトレードオフ」「超過の出方の解剖」を主にし、最適であることは主張しない形でよいか"]].forEach(([n, h, body], i) => {
  const y = 2.25 + i * 1.4;
  s.addShape(pres.shapes.OVAL, { x: 0.7, y: y + 0.15, w: 0.6, h: 0.6, fill: { color: BLUE }, line: { color: BLUE } });
  text(s, n, { x: 0.7, y: y + 0.15, w: 0.6, h: 0.6, fontSize: 20, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  text(s, [{ text: h, options: { bold: true, fontSize: 18, color: BLUE_DARK, breakLine: true } }, { text: body, options: { fontSize: 14 } }], { x: 1.55, y, w: 11.1, h: 1.3 });
});
s.addNotes("最後に、先生方にご相談したいことが3つあります。1つ目は超過の単価です。今は仮に500円としていますが、実際の高圧の契約では、上限を超えると以後の基本料金が上がるのが一般的です。電気バス寄りと燃料バス寄りのどちらが安いかは、この値で逆転しうるので、どの値や範囲で感度を取るべきかご意見をいただきたいです。2つ目はCO₂の扱いで、費用に単価を掛けて1つにまとめるか、費用とCO₂の2つの目的として兼ね合いを示すかです。3つ目は、11月28日の中間発表で、出発点で結果が大きく変わること、費用とCO₂のトレードオフ、超過の出方の解剖を主にして、最適であることは主張しない形でよいかです。");


// ---- Appendix divider
s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "付録", { x: 0.9, y: 2.6, w: 11.5, h: 1.0, fontSize: 40, bold: true, color: BLUE_DARK });
text(s, "定式化、変更点、結果の一覧、考察の詳細、計算し直しの設計など（ご質問の際に使います）", { x: 0.9, y: 3.7, w: 11.5, h: 0.6, fontSize: 18, color: SUB });
s.addNotes("ここから先は付録です。ご質問の際に使います。");

// ---- 11/7: the base case of pillar A, contract limit 900 kW and PV 1,000 kW (rc23_eval/k900pair.md, k900.md).
// Winter pair on one code version (11/8 rc33 7dc38d95: g900 BEV-heavy start, h900 ICE-heavy start, rc23_eval/rc33_all.md;
// rc29 gave 418.1 / 444.1); spring BEV-heavy from rc35 a900s10 (9a0fe044, rc23_eval/rc35_900s10.md), summer BEV-heavy
// from rc35 a900s10f (9a0fe044, pslab-mouse resubmission, rc23_eval/rc35_900s10f.md). DIAGNOSTIC.
const K9 = {
  wb: { cost: 4189120, share: 92.6, bev: 28, ice: 14, co2: 2470, grid: 3831, pvUse: 19867, pvCut: 4709, over: 0, peak: 780 },
  wi: { cost: 4387150, share: 37.6, bev: 28, ice: 24, co2: 5949, grid: 448, pvUse: 14258, pvCut: 10318, over: 0, peak: 416 },
  sb: { cost: 4157225, share: 93.5, bev: 30, ice: 13, co2: 1945, grid: 2860, pvUse: 22127, pvCut: 5692, over: 0, peak: 774 },
  // 2026-11-10: summer BEV-heavy is rerunning as rc36 a900u. The earlier rc35 a900s10f numbers were removed:
  // that launch carried no seed and default time limits, so it was not the same case as the other columns.
  ub: null };
const k9Save = K9.wi.cost - K9.wb.cost, k9Co2 = 1 - K9.wb.co2 / K9.wi.co2;
s = page(S3, "基準ケース（900 kW・太陽光1,000 kW）：電化で費用もCO₂も下がる");
takeaway(s, `冬の1週間：電気バス中心の運用は、燃料バス中心より${man(k9Save)}万円安く、CO₂は${Math.round(k9Co2 * 100)}%少ない`);
const k9Row = (label, f) => [B(label), ...["wb", "wi", "sb", "ub"].map((k) => (K9[k] ? f(K9[k]) : "未完"))];
s.addTable([
  [H("1週間の実行結果"), H("冬・電気バス中心"), H("冬・燃料バス中心"), H("春・電気バス中心"), H("夏・電気バス中心")],
  k9Row("総費用（燃料は使った分）", (r) => `${man(r.cost)}万円`),
  k9Row("電気バスの担当便（台数）", (r) => `${r.share.toFixed(1)}%（${r.bev}・${r.ice}台）`),
  k9Row("CO₂", (r) => `${fmt(r.co2)} kg`),
  k9Row("買電", (r) => `${fmt(r.grid)} kWh`),
  k9Row("太陽光：使えた／捨てた", (r) => `${fmt(r.pvUse)}／${fmt(r.pvCut)} kWh`),
  k9Row("契約超過／最大受電", (r) => `${fmt(r.over)} kWh／${fmt(r.peak)} kW`)],
  tableOpts({ x: 0.6, y: 2.2, w: 12.1, colW: [3.1, 2.25, 2.25, 2.25, 2.25], fontSize: 13, align: "center", rowH: 0.4 }));
bullets(s, [
  `冬の2つは同じ版・同じ条件で、違うのは便割当の出発点だけ。電気バス中心は燃料代が少なく（使った分 3.2万円 対 32.8万円）、太陽光を約1.4倍使う`,
  "燃料バス中心では太陽光の約4割（10,318 kWh）を捨てている。蓄電池が満杯になり、使い道がない。電気バス中心の値は前の版（rc29）と0.8万円差で再現",
  "受電上限に余裕がある900 kWでは、冬・春とも超過0（夏は電気バス中心の計算が4回とも途中で止まり未完）。電化の不利が出るのは上限が低い場合（90 kW・冬）だけ（次の頁）"],
  { x: 0.6, y: 5.3, w: 12.1, h: 1.15, fontSize: 12, paraSpaceAfter: 1 });
caption(s, "表8f　冬は rc33（7dc38d95）の2つの出発点、春は rc35（9a0fe044）の電気バス中心、夏は新しい版（rc36）で4回計算したが、毎時の立て直しの76〜146回目で止まり未完。冬・春は175／174回の毎時の立て直しをすべて受理、物理検査 VALID。DIAGNOSTIC", 0.6, 6.5, 12.1, 0.35);
s.addNotes(`柱Aの基準ケースとして、受電上限900キロワット、太陽光1,000キロワットの結果です。冬の2列は同じ版、同じ条件で、違うのは便割当の出発点だけです。電気バス中心の運用は、燃料バス中心に比べて1週間で約${man(k9Save)}万円安く、CO₂も約${Math.round(k9Co2 * 100)}パーセント少なくなりました。費用とCO₂の両方で電化が有利です。燃料バス中心では、太陽光の約4割を捨てていて、蓄電池が満杯になると使い道がないためです。電気バス中心の値は、前の版と0.8万円の差で再現しました。春の電気バス中心も、費用は約416万円、CO₂は1.9トンで、超過は0でした。夏は計算し直しています。電化の不利が出るのは、受電上限が低い90キロワットの冬だけで、それは次の頁でご説明します。`);

// ---- PV size at 900 kW winter (k900.md; mixed versions, marked)
const PVT = [
  ["1,000 kW", 4189120, 2470, 4387150, 5949, "rc33／rc33"],
  ["500 kW", 4365983, 5693, 4461176, 7230, "rc21／rc25"],
  ["250 kW", null, null, 4472827, 7423, "—／rc25"],
  ["0 kW", 4672507, 10823, 4552322, 9063, "rc33／rc25"]];
s = page(S3, "太陽光の量と電化の効果（受電上限900 kW・冬）");
takeaway(s, "太陽光があれば電化は費用もCO₂も得。太陽光0では逆に12万円高く、CO₂も多い");
s.addTable([
  [H("太陽光"), H("電気バス中心：費用"), H("電気バス中心：CO₂"), H("燃料バス中心：費用"), H("燃料バス中心：CO₂"), H("差（電気−燃料）"), H("版")],
  ...PVT.map(([pv, bc, bco, ic, ico, ver]) => [B(pv),
    bc ? `${man(bc)}万円` : { text: "未計算", options: { color: GREY } }, bco ? `${fmt(bco)} kg` : { text: "—", options: { color: GREY } },
    `${man(ic)}万円`, `${fmt(ico)} kg`,
    bc ? { text: `${bc < ic ? "−" : "＋"}${man(Math.abs(ic - bc))}万円／${bco < ico ? "−" : "＋"}${fmt(Math.abs(ico - bco))} kg`, options: { bold: true, color: bc < ic && bco < ico ? BLUE_DARK : INK } } : "—",
    { text: ver, options: { color: SUB } }])],
  tableOpts({ x: 0.6, y: 2.2, w: 12.1, colW: [1.2, 1.9, 1.8, 1.9, 1.8, 2.3, 1.2], fontSize: 13, align: "center", rowH: 0.45 }));
bullets(s, [
  "太陽光が多いほど電気バス中心が安く、CO₂も少ない。太陽光を減らすと、電気バス中心の費用とCO₂が増える（買電の係数は仮の0.5 kg/kWh）",
  "太陽光0では、買電のCO₂が軽油を上回り、電化はCO₂でも不利（10,823 kg 対 9,063 kg）。電化の効果は太陽光とセット",
  "注：「版」の列が違う行は版の違う結果の並置（rc21・rc25・rc33）。燃料バス中心の500 kW以下は同じ版での計算し直しが今後"],
  { x: 0.6, y: 4.65, w: 12.1, h: 1.7, fontSize: 13, paraSpaceAfter: 3 });
caption(s, "表8g　受電上限900 kW・冬の1週間の実行結果。電気バス中心＝電気バス寄りの出発点、燃料バス中心＝燃料バス寄りの出発点。DIAGNOSTIC", 0.6, 6.45, 12.1);
s.addNotes("同じ900キロワットの冬で、太陽光の量を変えた結果です。太陽光が1,000キロワットのときは、電気バス中心が約20万円安く、CO₂も少なくなりました。太陽光を減らすと、電気バス中心の費用とCO₂が増えていき、太陽光が0では、電気バス中心の方が約12万円高く、CO₂も多くなりました。これは、買電のCO₂の係数を仮に0.5としているためで、太陽光がないと、買った電気のCO₂が軽油を上回ります。つまり、電化の効果は太陽光とセットで考える必要があります。ただし、500キロワットより下は版の違う結果を並べているので、同じ版で計算し直す予定です。");

// ---- 11/8: contract limit x start point on one version (rc33 7dc38d95, rc23_eval/rc33_all.md, rc33_season.md). DIAGNOSTIC.
const LIM = [
  ["90 kW", { cost: 4794193, co2: 2136, over: 1291 }, { cost: 4390136, co2: 6354, over: 0 }],
  ["200 kW", { cost: 4379814, co2: 2266, over: 407 }, { cost: 4348630, co2: 5641, over: 0 }],
  ["400 kW", { cost: 4156611, co2: 2268, over: 0, mark: "＊" }, { cost: 4399369, co2: 6513, over: 0 }],
  ["900 kW", { cost: 4189120, co2: 2470, over: 0 }, { cost: 4387150, co2: 5949, over: 0 }]];
const cell = (r) => r ? `${man(r.cost)}万円／${fmt(r.co2)} kg${r.over ? `／超過 ${fmt(r.over)} kWh` : ""}${r.mark || ""}` : { text: "計算し直し中", options: { color: GREY } };
const diffCell = (b, i) => b && i ? { text: `${b.cost < i.cost ? "−" : "＋"}${man(Math.abs(b.cost - i.cost))}万円／−${fmt(i.co2 - b.co2)} kg`, options: { bold: true, color: b.cost < i.cost ? BLUE_DARK : INK } } : "—";
s = page(S3, "受電上限と2つの出発点（冬の4上限と、90 kWの3季節）");
takeaway(s, "電気バス寄りは400〜900 kWで20〜24万円安いが、200 kWでほぼ同額、90 kWで40万円高い");
s.addTable([
  [H("冬の1週間"), H("電気バス寄りの出発点：費用／CO₂"), H("燃料バス寄りの出発点：費用／CO₂"), H("差（電気−燃料）")],
  ...LIM.map(([lim, b, i]) => [B(lim), cell(b), cell(i), diffCell(b, i)])],
  tableOpts({ x: 0.6, y: 2.15, w: 12.1, colW: [1.4, 4.0, 3.4, 3.3], fontSize: 13, align: "center", rowH: 0.44 }));
s.addTable([
  [H("90 kW・季節"), H("電気バス寄り：費用／CO₂"), H("燃料バス寄り：費用／CO₂"), H("差（電気−燃料）")],
  [B("冬"), cell(LIM[0][1]), cell(LIM[0][2]), diffCell(LIM[0][1], LIM[0][2])],
  (() => { const q = (st) => { const p = DATA.pairs.find((x) => x.grid_limit_kw === 90 && x.week === "2025-04-07" && x.start === st && x.status === "VERIFIED"); return p && { cost: p.total_cost_fuel_consumed, co2: Math.round(p.total_co2_kg), over: Math.round(p.contract_over_limit_kwh), mark: "†" }; };
    return [B("春"), cell(q("bev")), cell(q("ice")), diffCell(q("bev"), q("ice"))]; })(),
  [B("夏"), cell({ cost: 4309168, co2: 1104, over: 405 }), cell({ cost: 4481917, co2: 7586, over: 0 }), diffCell({ cost: 4309168, co2: 1104 }, { cost: 4481917, co2: 7586 })]],
  tableOpts({ x: 0.6, y: 4.5, w: 12.1, colW: [1.4, 4.0, 3.4, 3.3], fontSize: 13, align: "center", rowH: 0.4 }));
caption(s, "表8h　印のない行はrc33（7dc38d95）で、違うのは便割当の出発点だけ。すべて175／174回の毎時の立て直しを受理、物理検査 VALID。＊400 kW電気バス寄りはrc35（9a0fe044、rc33との違いは充電計画の数値設定IntegralityFocusのみ、予報の割引なし）。†90 kW春は2つともrc36（375dd6f2）。DIAGNOSTIC", 0.6, 6.25, 12.1, 0.55);
s.addNotes("同じ版で、受電上限と便割当の出発点を組み合わせた結果です。違うのは出発点だけです。上限900キロワットでは電気バス寄りが約20万円安く、400キロワットでも約24万円安く、CO₂も少なくなりました。なお400キロワットの電気バス寄りは、数値の設定を1つだけ直した次の版で計算し直した結果です。上限を下げると、電気バス寄りの超過が増えて費用が上がり、200キロワットではほぼ同じ額、90キロワットでは燃料バス寄りの方が約40万円安くなりました。ただしCO₂は、どの上限でも電気バス寄りの方が3,000から4,000キログラム少ないです。季節で見ると、90キロワットでも夏は電気バス寄りの方が約17万円安くなりました。冬だけが逆転するのは、太陽光が少なく、予報の外れが大きいためで、次の頁でご説明します。");

// ---- 11/8: why the BEV-heavy plan overruns at 90 kW winter: the day-ahead PV forecast (rc33 g090 rolling pv_execution.json)
const FD = [["1日目（月）", 3391, 1399, 83], ["2日目", 3401, 2640, 1207], ["3〜6日目（平均）", 3430, 4711, 0], ["7日目", 3462, 1693, 0]];
s = page(S5, "超過の原因：前日計画の太陽光の見込み（90 kW・冬）");
takeaway(s, "予報は毎日ほぼ同じ量。実際は曇りの日に4割しか発電せず、蓄電池が足りなくなった翌夜に超過が出る");
s.addTable([
  [H("電気バス寄り（rc33）"), H("予報 kWh"), H("実際 kWh"), H("実際÷予報"), H("契約超過 kWh")],
  ...FD.map(([d, f, a, o]) => [B(d), fmt(f), fmt(a), { text: (a / f).toFixed(2), options: { bold: a / f < 0.6, color: a / f < 0.6 ? BLUE_DARK : INK } }, o ? { text: fmt(o), options: { bold: true } } : "0"])],
  tableOpts({ x: 0.6, y: 2.15, w: 7.2, colW: [2.2, 1.2, 1.2, 1.3, 1.3], fontSize: 13, align: "center", rowH: 0.44 }));
s.addShape(pres.shapes.RECTANGLE, { x: 8.1, y: 2.15, w: 4.6, h: 2.25, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
text(s, [{ text: "前日計画の見込み", options: { fontSize: 14, color: SUB, breakLine: true } },
  { text: "超過 0 kWh・405万円", options: { fontSize: 22, bold: true, color: BLUE_DARK, breakLine: true } },
  { text: "実行（実際の発電）", options: { fontSize: 14, color: SUB, breakLine: true } },
  { text: "超過 1,291 kWh・479万円", options: { fontSize: 22, bold: true, color: INK } }],
  { x: 8.25, y: 2.25, w: 4.3, h: 2.05, align: "center", valign: "middle" });
bullets(s, [
  "1週間の合計は予報と実際でほぼ同じ（23,974 対 24,577 kWh）。問題は日ごとの外れで、曇りの日の翌夜に超過の9割が出る",
  "前日計画は超過を見込まないので、便割当は電気バス中心を選ぶ。探索を強めても燃料バスへ動かない理由はこれ",
  "対策（案A）として計画のときだけ予報を控えめに見た。7割なら超過は半分に減ったが、半分にすると逆効果（次の頁）"],
  { x: 0.6, y: 4.6, w: 12.1, h: 1.75, fontSize: 13, paraSpaceAfter: 3 });
caption(s, "表8i　rc33 電気バス寄り（90 kW・冬）の毎時の実行記録から日ごとに集計。予報は前日計画が使う値。DIAGNOSTIC", 0.6, 6.45, 12.1);
s.addNotes("なぜ90キロワットの冬で電気バス寄りの超過が出るのかを調べました。前日計画が使う太陽光の予報は、毎日ほぼ同じ約3,400キロワット時です。1週間の合計は実際とほぼ同じですが、日ごとに見ると、1日目は予報の4割しか発電しませんでした。蓄電池にたまる電気が足りなくなり、2日目の夜に超過が1,207キロワット時出ています。前日計画では超過は0で405万円と見込んでいましたが、実際は1,291キロワット時の超過で479万円になりました。前日計画が超過を見込まないので、便割当は電気バス中心を選びます。探索を強めても燃料バスへ動かないのはこのためです。対策として、計画のときだけ太陽光の予報を控えめに見る方法を試しましたが、超過は1割ほどしか減らず、費用はかえって増えました。その理由を次の頁でご説明します。");

// ---- 11/8: what happens on the overage night, and why the forecast margin (plan A) does not remove it.
// rc33 g090 vs rc35 a090s50 hourly_energy_flow_chart.csv (scratchpad over_by_day.py), rc23_eval/rc35_a090s50_a400.md. DIAGNOSTIC.
const NIGHT = [["1日目（月）", 1399, 511, 83, 0], ["2日目（火）", 2640, 1853, 1207, 0], ["3〜5日目（計）", 13766, 691, 0, 2625], ["6〜7日目（計）", 6772, 189, 0, 1638]];
s = page(S5, "超過の夜の中身と、予報を控えめに見る対策（案A）の結果");
takeaway(s, "超過は火曜未明に集中。予報を7割と見込むと半分に減るが、燃料バス寄りよりまだ高い");
s.addTable([
  [H("電気バス寄り"), H("太陽光 kWh"), H("買電 kWh"), H("契約超過 kWh"), H("捨てた太陽光 kWh")],
  ...NIGHT.map(([d, pv, g, o, c]) => [B(d), fmt(pv), fmt(g), o ? { text: fmt(o), options: { bold: true } } : "0", c ? fmt(c) : "0"])],
  tableOpts({ x: 0.6, y: 2.15, w: 7.2, colW: [2.0, 1.25, 1.2, 1.35, 1.4], fontSize: 13, align: "center", rowH: 0.42 }));
s.addTable([
  [H("90 kW冬・電気寄り"), H("予報どおり"), H("予報×0.7"), H("予報×0.5")],
  [B("総費用"), "479.4万円", { text: "450.7万円", options: { bold: true } }, "491.5万円"],
  [B("契約超過"), "1,291 kWh", { text: "625 kWh", options: { bold: true } }, "1,134 kWh"],
  [B("電気バス担当便"), "93%", "78%", "78%"],
  [B("CO₂"), "2,136 kg", "2,955 kg", "3,504 kg"]],
  tableOpts({ x: 8.0, y: 2.15, w: 4.7, colW: [1.6, 1.05, 1.0, 1.05], fontSize: 12, align: "center", rowH: 0.42 }));
bullets(s, [
  "火曜0〜5時に27台が一斉に夜の充電をするとき、蓄電池は下限（1,200 kWh）まで空。月曜は曇りで、昼に貯められなかった",
  "月曜の買電は511 kWhで、超過なしで買える量（90 kW×24時間＝2,160 kWh）の約2割。ただし前提により系統から蓄電池へは貯められない",
  "予報を7割と見込むと、超過は約半分（1,291→625 kWh）、費用も約29万円下がった。それでも燃料バス寄り（439.0万円）より高く、CO₂は増えた",
  "半分と見込むと逆に費用が増え、超過は1割しか減らない。割り引くほど良くなるわけではない。どちらも電気バスの担当便が78%に下がっており、便割当の違いが効いているとみている（未確認）",
  "系統から蓄電池へ貯められない今の前提では、計画の工夫だけで超過を消すのは難しい。貯められる場合との比較は今後の課題"],
  { x: 0.6, y: 4.6, w: 12.1, h: 1.8, fontSize: 12, paraSpaceAfter: 2 });
caption(s, "表8j　rc33（7dc38d95）と rc35（9a0fe044、予報×0.7・×0.5は前日の計画だけ、実行は実測の発電）。毎時の実行記録から集計。どちらも175回の立て直しを受理、物理検査 VALID。DIAGNOSTIC", 0.6, 6.4, 12.1, 0.5);
s.addNotes("超過が出る夜の中身です。電気バス寄りの1週間を日ごとに見ると、超過のほとんどは2日目、火曜日の未明0時から5時に出ています。この時間は27台の電気バスが一斉に夜の充電をしますが、そのとき蓄電池はすでに下限まで空でした。月曜日が曇りで、昼のあいだに太陽光を十分に貯められなかったためです。一方、月曜日の買電は511キロワット時で、超過なしで買える量の約2割しか使っていません。ただ、今のシナリオの前提では系統から蓄電池へ充電できないため、この余った枠を夜に回すことができません。対策として、前日の計画のときだけ太陽光の予報を控えめに見込んで計算しました。7割と見込むと、超過はほぼ半分の625キロワット時になり、費用も約29万円下がりました。ただ、それでも燃料バス寄りより高く、CO₂は増えています。半分と見込んだ場合は、逆に費用が増えて、超過は1割ほどしか減りませんでした。割り引けば割り引くほど良くなるわけではなく、どちらも電気バスの担当便が78パーセントまで下がっているので、予報そのものより便割当の違いが効いているのではないかと見ていますが、まだ確かめていません。この前提のもとでは、90キロワットの冬の超過は計画の工夫では避けにくい構造だと考えています。系統から蓄電池へ貯められる場合の比較は、今後の課題とします。");

// ---- 11/9: what was devised (methods and research practice; each item is something the code or runs actually do)
s = page(S0, "工夫した点");
takeaway(s, "「たまたまそうなった」結果にしないために、やり方を変えたところ");
[["比べ方", "スタート地点を2つ用意した", "電気バスを多めに使う割当と、燃料バスを多めに使う割当の2通りから解き始めた。どちらから始めても同じ結論になるかを見たかったから"],
 ["運用の再現", "当日の天気で計画を組み直した", "前日に予報で計画を立て、当日は実際の天気を見ながら1時間ごとに組み直した。費用やCO₂は、この「実際に走らせた結果」で数えている"],
 ["解き方", "大きすぎる問題は2段に分けた", "1週間1,704便を60台に割り当てるのは一度には解けない。まず便の割当を決めてから充電を決める。割当は一部の車両・日だけを解き直して少しずつ良くした"],
 ["ごまかさない", "うまくいかない計算も隠さない", "止まった計算を、近い答えで埋めたり後から手で直したりはしていない。止まる原因を3つ見つけてプログラムを直した。まだ止まる1ケースは未完として出している"],
 ["計算機", "研究室のPC13台で同時に回した", "1ケース数時間かかるので、研究室のPCをつないで並行して計算した。PCごとの速さの違いは制限時間で調整し、止まった計算は自動で再開するようにした"],
 ["原因探し", "超過の出た時間を追いかけた", "記録を日・時間ごとにばらして、超過が曇りの月曜の翌未明、蓄電池が空の時間に集中していると突き止めた。思いついた対策も実際に計算して効き目を見た"]].forEach(([tag, h, body], i) => {
  const x = 0.6 + (i % 3) * 4.1, y = 2.2 + Math.floor(i / 3) * 2.2;
  s.addShape(pres.shapes.RECTANGLE, { x, y, w: 3.9, h: 2.05, fill: { color: i % 2 ? "F7F7F7" : "EEF5FB" }, line: { color: GRID, width: 0.75 } });
  text(s, [{ text: tag, options: { fontSize: 12, color: SUB, breakLine: true } }, { text: h, options: { fontSize: 15, bold: true, color: BLUE_DARK } }], { x: x + 0.15, y: y + 0.08, w: 3.6, h: 0.7 });
  text(s, body, { x: x + 0.15, y: y + 0.8, w: 3.6, h: 1.2, fontSize: 12, lineSpacingMultiple: 1.1 });
});
caption(s, "結果はすべて診断用（DIAGNOSTIC）", 0.6, 6.6, 12.1, 0.35);
s.addNotes("工夫したところを6つ挙げます。まず、スタート地点を2つ用意しました。電気バスを多めに使う割当と、燃料バスを多めに使う割当の両方から解き始めて、どちらからでも同じ結論になるかを見ています。次に、予報どおりにはいかない前提で動かしました。前日に予報で計画を立てて、当日は実際の天気で1時間ごとに組み直し、その結果で費用やCO₂を数えています。3つ目に、問題が大きすぎるので、便の割当と充電を2段に分けて解いています。4つ目に、うまくいかない計算もごまかしていません。止まった計算を近い答えで埋めたりせず、原因を3つ見つけて直しました。まだ止まる1ケースは、未完としてそのまま出しています。5つ目に、1ケース数時間かかるので、研究室のPC13台をつないで同時に回しました。最後に、超過がいつ出たかを1時間ずつ追って、曇りの月曜の翌未明に集中していることを突き止めました。");

// Slides are generated in code order (later slides reuse constants defined by earlier ones) and then
// reordered in the package: main talk first, details in the appendix. ORDER lists generated slide numbers.
const ORDER = [1, 2, 4, 3, 44, 39, 12, 42, 43, 16, 32, 37, 33, 34, 38, 35, 5, 7, 40, 41, 9, 10, 11, 14, 36, 27, 23, 6, 8, 13, 15, 17, 18, 19, 20, 21, 22, 24, 25, 26, 28, 30, 29, 31];
async function reorderSlides(file) {
  const JSZip = require(path.join(process.env.DECK_NODE_MODULES, "jszip"));
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const pres_xml = await zip.file("ppt/presentation.xml").async("string");
  const rels = await zip.file("ppt/_rels/presentation.xml.rels").async("string");
  const target = {};
  for (const m of rels.matchAll(/<Relationship [^>]*Id="([^"]+)"[^>]*Target="slides\/slide(\d+)\.xml"/g)) target[m[1]] = Number(m[2]);
  for (const m of rels.matchAll(/<Relationship [^>]*Target="slides\/slide(\d+)\.xml"[^>]*Id="([^"]+)"/g)) target[m[2]] = Number(m[1]);
  const lst = pres_xml.match(/<p:sldIdLst>([\s\S]*?)<\/p:sldIdLst>/)[1];
  const ids = [...lst.matchAll(/<p:sldId [^>]*\/>/g)].map((m) => m[0]);
  const byNum = {};
  ids.forEach((tag) => { byNum[target[tag.match(/r:id="([^"]+)"/)[1]]] = tag; });
  if (ORDER.length !== ids.length || ORDER.some((n) => !byNum[n])) throw new Error(`ORDER does not match the ${ids.length} generated slides`);
  zip.file("ppt/presentation.xml", pres_xml.replace(lst, ORDER.map((n) => byNum[n]).join("")));
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

(async () => {
  const out = path.join(__dirname, "three_party_20261112.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  await reorderSlides(out);
  console.log("wrote", out);
})();
