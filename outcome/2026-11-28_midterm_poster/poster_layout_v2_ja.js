// Layout of the midterm poster after the advisor's comments of 2026-11-12 (included by build_poster_rc33.js).
// Order: 1 goal and my work, 2 method (what is optimized, objective, parameters), 3 case study,
// 4 results (bar charts of trip share and cost, the two initial assignments), 5 discussion, outlook, road to the final.
// "2つの出発点" is no longer used (it reads as a bus route's starting point): the two Stage 1 seeds are
// "電気バス優先の初期割当" and "燃料バス優先の初期割当".
module.exports = function layout(c) {
  const { s, pres, path, text, section, chart, caption, flowDiagram, M, W, COL, LX, RX, BLUE, BLUE_DARK, GREY, INK, SUB, GRID,
    cases, LIMITS, SE, SEASON_OF, lab, val, pairOf, iceWins, bevWins, rngTxt, man, fmt, pb90, pi90, eqSize, maxTimeouts, versions } = c;
  const NUM = 7.87;
  text("GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: M + NUM, y: M, w: W - NUM, h: 2.5, fontSize: 68, bold: true, valign: "middle" });
  text("東京都市大学　劉 承洋（研究室名・指導教員をここに記入）", { x: M + NUM, y: M + 2.55, w: W - NUM, h: 0.8, fontSize: 36, color: SUB });
  s.addShape(pres.shapes.LINE, { x: M, y: 8.8, w: W, h: 0, line: { color: BLUE, width: 8 } });
  const p9b = pairOf(900, "2025-01-06", "bev"), p9i = pairOf(900, "2025-01-06", "ice");
  const tc = (r) => r.total_cost_fuel_consumed;
  const wCut = Math.round((1 - p9b.total_co2_kg / p9i.total_co2_kg) * 100);
  text(`概要　路線バスの電動化では、営業所での充電が重なると受電電力が大きくなる。燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を最適化し、受電上限を変えたときの電気バスの担当便・費用・CO₂を冬・春・夏の代表週で評価した。受電上限900 kW・太陽光1,000 kWの冬では、電気バスを優先する運用は燃料バスを優先する運用より1週間で${man(tc(p9i) - tc(p9b))}万円安く、CO₂は${wCut}%少なかった。上限を下げるとこの差は縮み、${iceWins.map(lab).join("・")}では燃料バスを優先する方が安かった。`,
    { x: M + NUM, y: M + 3.45, w: W - NUM, h: 3.5, fontSize: 32 });

  // ---------------- left column
  let y = 9.2;
  y = section("1．背景と目的", LX, y, COL);
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y, w: COL, h: 2.35, fill: { color: "EEF5FB" }, line: { color: "EEF5FB" } });
  text([{ text: "目指すこと", options: { bold: true, color: BLUE_DARK, fontSize: 30, breakLine: true } },
    { text: "路線バスの電動化でCO₂を減らす（GX）。そのとき、受電設備と電気料金の負担を抑えながら、今の時刻表どおりに運行を続ける。", options: { bold: true } }],
    { x: LX + 0.35, y: y + 0.2, w: COL - 0.7, h: 2.0, fontSize: 31 });
  y += 2.6;
  text([{ text: "本研究の取り組み", options: { bold: true, color: BLUE_DARK, breakLine: true } },
    ...["燃料バスと併用する営業所で、便割当と充電計画を最適化する", "受電上限を変えて、電気バスに任せられる便・費用・CO₂を比べる", "受電上限の超過が、いつ・なぜ生じるかを調べる"]
      .map((t, i, a) => ({ text: t, options: { bullet: true, breakLine: i < a.length - 1 } }))],
    { x: LX, y, w: COL, h: 2.5, fontSize: 30, paraSpaceAfter: 4 });
  y += 2.65;

  y = section("2．手法", LX, y, COL);
  text([{ text: "最適化するもの　", options: { bold: true, color: BLUE_DARK } },
    { text: "(a) 各便をどの車両（電気バス・燃料バス）が担当するか、(b) 各電気バスをいつ・何kWで充電するか。時刻表の便はすべて運行する。" }],
    { x: LX, y, w: COL, h: 1.4, fontSize: 29 });
  y += 1.5;
  text([{ text: "目的関数　", options: { bold: true, color: BLUE_DARK } }, { text: "1週間の総費用を最小にする" }], { x: LX, y, w: COL, h: 0.6, fontSize: 29 });
  y += 0.7;
  const EQW = COL * 0.86, EQH = EQW * eqSize.objective.h / eqSize.objective.w;
  s.addImage({ path: path.join(__dirname, "..", "2026-11-12_three_party", "eq", "objective.png"), x: LX + 0.3, y, w: EQW, h: EQH,
    altText: "目的関数：車両使用費、電気代と上限超過の費用、燃料代、CO2の費用の和を最小化" });
  y += EQH + 0.15;
  caption("左から、車両使用費（使った台・日）、電気代と受電上限の超過費用、燃料代、CO₂の費用。主な制約：便の接続（到着＋折返し＋回送 ≦ 次の発車）、電池残量、充電器10基、受電上限", LX, y, COL, 1.1, 24);
  y += 1.2;
  flowDiagram(s, pres, LX, y, COL, [
    ["① 便割当", ["1,704便を60台に割当", "混合整数計画＋大近傍探索［5］"]],
    ["② 前日の計画", ["割当は固定、15分ごとに充電を計画", "太陽光は平年値の予報［2］"]],
    ["③ 毎時の立て直し", ["実際の天気で1時間ごとに再計画", "1週間に174〜175回"]],
    ["④ 集計", ["実行結果で費用・CO₂を集計", "2通りの初期割当の安い方を採用"]]], "Yu Gothic", 3.4, 22);
  caption("図1　計算の流れ（ソルバーはGurobi［4］）。蓄電池は規則で充放電する", LX, y + 3.45, COL, 0.6, 24);
  y += 4.15;
  const params = [["電気料金", "30円/kWh（基本料金を含む）"], ["軽油", "150円/L、CO₂ 2.62 kg/L［1］"], ["電力のCO₂", "0.5 kg/kWh（仮）、CO₂の費用 1円/kg"],
    ["車両使用費", "2万円/台・日"], ["受電上限の超過", "500円/kWh（仮）"], ["毎朝の電池残量", "目標90%・下限80%"],
    ["時間の刻み", "15分（立て直しは1時間ごと）"], ["計算の打ち切り", "最適性ギャップ1%、便割当3時間、立て直し120秒/回"]];
  const tbl = (rowsIn, x, yy, w, k = 3.9, fs = 27, rh = 0.56) => s.addTable(rowsIn.map(([a, b]) => [{ text: a, options: { bold: true, fill: { color: "F4F7FA" } } }, { text: b }]),
    { x, y: yy, w, colW: [k, w - k], fontSize: fs, fontFace: "Yu Gothic", color: INK, rowH: rh, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  tbl(params, LX, y, COL);
  y += params.length * 0.56 + 0.1;
  caption("表1　計算に用いた値（仮の値は今後、感度を調べる）", LX, y, COL, 0.6, 24);
  y += 0.85;

  y = section("3．ケーススタディ", LX, y, COL);
  const MAPW = COL * 0.70, MAPH = MAPW * 0.5221;
  s.addImage({ path: path.join(__dirname, "route_map_ja_poster.png"), x: LX + (COL - MAPW) / 2, y, w: MAPW, h: MAPH, altText: "渋21・渋22・渋23の路線図と弦巻営業所の位置" });
  y += MAPH + 0.08;
  caption("図2　対象路線と弦巻営業所（停留所の位置はODPT［3］、停留所の間は直線。背景は © OpenStreetMap contributors）", LX, y, COL, 1.1, 22);
  y += 1.15;
  const study = [["対象", "東急バス 渋21〜23系統（弦巻営業所）、1週間1,704便"], ["車両・設備", "電気バス35台・燃料バス25台、充電器90 kW×10、太陽光1,000 kW、蓄電池6,000 kWh"],
    ["比べるケース", "受電上限 90・200・400・900 kW × 冬・春・夏の代表週（2025年）＝12ケース"]];
  tbl(study, LX, y, COL, 3.3, 25, 0.8);
  y += study.length * 0.8 + 0.5;
  caption("表2　ケーススタディの条件", LX, y, COL, 0.5, 24);
  if (y + 0.5 > 45.5 - 1.6) throw new Error(`left column overflows: ${y}`);
  text([{ text: "参考文献　", options: { bold: true } },
    { text: "［1］環境省・経済産業省：算定方法及び排出係数一覧（2025年版）　［2］W. F. Holmgren et al.: pvlib python, JOSS 3(29), 884, 2018　［3］公共交通オープンデータセンター：東急バス 時刻表データ（ODPT）　［4］Gurobi Optimization, LLC: Gurobi Optimizer Reference Manual, Version 13.0　［5］P. Shaw: Using constraint programming and local search methods to solve vehicle routing problems, CP-98, LNCS 1520, 1998" }],
    { x: LX, y: 45.5 - 1.6, w: COL, h: 1.6, fontSize: 18, color: SUB });

  // ---------------- right column
  y = 9.2;
  y = section("4．結果", RX, y, COL);
  const halfR = (COL - 0.5) / 2, cats = LIMITS.map((g) => `${g}`);
  s.addChart(pres.charts.BAR, SE.map(([w, n]) => ({ name: n, labels: cats, values: LIMITS.map((g) => val(g, w, "bev_trip_share_pct", (v) => Math.round(v * 10) / 10)) })),
    { ...chart(), x: RX, y, w: halfR, h: 6.3, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60, chartColors: [BLUE_DARK, "7AB8E8", GREY],
      catAxisLabelFontSize: 26, valAxisLabelFontSize: 24, legendFontSize: 26, valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20,
      showCatAxisTitle: true, catAxisTitle: "受電上限 [kW]", catAxisTitleFontSize: 24, catAxisTitleColor: SUB,
      showValAxisTitle: true, valAxisTitle: "電気バス担当便 [%]", valAxisTitleFontSize: 24, valAxisTitleColor: SUB });
  const order = []; LIMITS.forEach((g) => SE.forEach(([w]) => { const r = cases.find((x) => x.grid_limit_kw === g && x.week === w); if (r) order.push(r); }));
  const ccats = order.map((r) => `${r.grid_limit_kw}${SEASON_OF[r.week]}`);
  const m1 = (v) => Math.round(v / 1e3) / 10;
  s.addChart(pres.charts.BAR, [
    { name: "電気代", labels: ccats, values: order.map((r) => m1(r.electricity_cost)) },
    { name: "燃料代", labels: ccats, values: order.map((r) => m1(r.fuel_cost)) },
    { name: "上限超過の費用", labels: ccats, values: order.map((r) => m1(r.contract_overage_cost)) }],
    { ...chart(), x: RX + halfR + 0.5, y, w: halfR, h: 6.3, barDir: "col", barGrouping: "stacked", barGapWidthPct: 40, chartColors: [BLUE, GREY, "E8A33D"],
      catAxisLabelFontSize: 17, valAxisLabelFontSize: 24, legendFontSize: 22, valAxisMinVal: 0,
      showValAxisTitle: true, valAxisTitle: "運用費 [万円/週]", valAxisTitleFontSize: 24, valAxisTitleColor: SUB });
  const totals = order.map((r) => r.total_cost / 1e4);
  caption("図3　受電上限と電気バスの担当便（1,704便/週）", RX, y + 6.35, halfR, 1.2, 24);
  caption(`図4　各ケースの最適化結果の費用（電気代＋燃料代＋超過費用）。総費用はこれに車両使用費を加えた${Math.min(...totals).toFixed(0)}〜${Math.max(...totals).toFixed(0)}万円/週`, RX + halfR + 0.5, y + 6.35, halfR, 1.6, 24);
  y += 8.0;
  text(`(1) 受電上限が400 kW以上なら、電気バスが便の${rngTxt(bevWins.map((r) => r.bev_trip_share_pct), 1)}%を担当し、運用費も小さい。上限の低い${iceWins.map(lab).join("・")}では燃料バスを多く使う方が安く、電気バスの担当便は${rngTxt(iceWins.map((r) => r.bev_trip_share_pct))}%に下がった。`,
    { x: RX, y, w: COL, h: 1.9, fontSize: 28 });
  y += 2.05;
  text([{ text: "限られた計算時間で良い解を得る工夫　", options: { bold: true, color: BLUE_DARK } },
    { text: "便割当は規模が大きく、制限時間内に最適とは確認できない。そこで「電気バスを優先して使う割当」と「燃料バスを優先して使う割当」の2通りを初期割当として最適化を始め、総費用の安い方を採用した（表3）。" }],
    { x: RX, y, w: COL, h: 2.4, fontSize: 28 });
  y += 2.55;
  const p90b = pb90, p90i = pi90;
  const cols = [["900 kW冬", p9b, "電気バス優先"], ["900 kW冬", p9i, "燃料バス優先"], ["90 kW冬", p90b, "電気バス優先"], ["90 kW冬", p90i, "燃料バス優先"]];
  const win = (a, b) => tc(a) <= tc(b);
  const adopted = [win(p9b, p9i), !win(p9b, p9i), win(p90b, p90i), !win(p90b, p90i)];
  const cell = (t, i, extra = {}) => ({ text: t, options: { align: "center", bold: adopted[i], color: adopted[i] ? BLUE_DARK : INK, ...extra } });
  const head = (t) => ({ text: t, options: { bold: true, fill: { color: "F2F2F2" }, align: "center" } });
  const row = (label, f) => [{ text: label, options: { bold: true } }, ...cols.map(([, r], i) => cell(f(r), i))];
  s.addTable([
    [head("受電上限・季節"), ...cols.map(([n]) => head(n))],
    [{ text: "初期割当", options: { bold: true } }, ...cols.map(([, , n], i) => cell(n, i))],
    row("総費用", (r) => `${man(tc(r))}万円`),
    row("電気バス担当便", (r) => `${r.bev_trip_share_pct.toFixed(1)}%`),
    row("CO₂", (r) => `${fmt(r.total_co2_kg)} kg`),
    row("上限の超過", (r) => `${fmt(r.contract_over_limit_kwh)} kWh`),
    [{ text: "採用", options: { bold: true } }, ...adopted.map((a, i) => cell(a ? "○" : "—", i))]],
    { x: RX, y, w: COL, colW: [3.7, (COL - 3.7) / 4, (COL - 3.7) / 4, (COL - 3.7) / 4, (COL - 3.7) / 4], fontSize: 25, fontFace: "Yu Gothic",
      color: INK, rowH: 0.62, valign: "middle", border: { type: "solid", pt: 1, color: GRID } });
  y += 7 * 0.62 + 0.1;
  caption("表3　2通りの初期割当から最適化した結果（1週間）。青字が採用した方", RX, y, COL, 0.6, 24);
  y += 0.8;
  const PAIRS = [];
  LIMITS.forEach((g) => SE.forEach(([w]) => { const b = pairOf(g, w, "bev"), i = pairOf(g, w, "ice"); if (b && i) PAIRS.push({ label: `${g}${SEASON_OF[w]}`, b, i }); }));
  const pcats = PAIRS.map((p) => p.label), half = (COL - 0.6) / 2;
  const pairChart = (o) => ({ ...chart(), y, w: half, h: 6.2, barDir: "bar", barGrouping: "clustered", chartColors: [BLUE, GREY], valAxisMinVal: 0, catAxisOrientation: "maxMin",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 13, legendFontSize: 22, catAxisLabelFontSize: 18, catAxisLabelFrequency: 1, barGapWidthPct: 15,
    valAxisLabelFontSize: 20, valAxisTitleFontSize: 22, valAxisTitleColor: SUB, showValAxisTitle: true, ...o });
  s.addChart(pres.charts.BAR, [{ name: "電気バス優先 − 燃料バス優先", labels: pcats, values: PAIRS.map((p) => Math.round((tc(p.b) - tc(p.i)) / 1e3) / 10) }],
    pairChart({ x: RX, chartColors: [BLUE_DARK], dataLabelFormatCode: "+0.0;-0.0", valAxisMinVal: -60, valAxisMaxVal: 60, valAxisMajorUnit: 30, catAxisLabelPos: "low", valAxisTitle: "費用の差 [万円/週]" }));
  s.addChart(pres.charts.BAR, [
    { name: "電気バス優先", labels: pcats, values: PAIRS.map((p) => Math.round(p.b.total_co2_kg / 100) / 10) },
    { name: "燃料バス優先", labels: pcats, values: PAIRS.map((p) => Math.round(p.i.total_co2_kg / 100) / 10) }],
    pairChart({ x: RX + half + 0.6, dataLabelFormatCode: "0.0", valAxisMaxVal: 10, valAxisMajorUnit: 2, valAxisTitle: "CO₂ [t/週]" }));
  y += 6.25;
  const bevCheap = PAIRS.filter((p) => tc(p.b) < tc(p.i)).length, co2Low = PAIRS.filter((p) => p.b.total_co2_kg < p.i.total_co2_kg).length;
  caption(`図5　2通りの初期割当の比較：費用の差（左。負は電気バス優先が安い）とCO₂（右）。CO₂は${PAIRS.length}ケース中${co2Low}ケースで電気バス優先が少なく、費用は${bevCheap}ケースで電気バス優先が安い`, RX, y, COL, 1.2, 24);
  y += 1.4;

  y = section("5．考察とまとめ", RX, y, COL);
  const perKg = Math.round((tc(p90b) - tc(p90i)) / (p90i.total_co2_kg - p90b.total_co2_kg));
  text([
    { text: `受電上限に余裕があれば、電化は費用もCO₂も下げる。上限が低い冬（90 kW）だけは燃料バス優先が約${Math.round((tc(p90b) - tc(p90i)) / 1e4)}万円安いが、CO₂は約${(p90i.total_co2_kg / p90b.total_co2_kg).toFixed(1)}倍になる（CO₂を1 kg減らす費用は約${perKg}円）。`, options: { bullet: true, breakLine: true } },
    { text: `上限の超過は、曇りの日の翌未明、蓄電池が空の時間に集中した（90 kW冬・電気バス優先で${fmt(p90b.contract_over_limit_kwh)} kWh/週の9割）。前日の計画は平年値の予報を使うため、曇りの不足を見込めない。`, options: { bullet: true } }],
    { x: RX, y, w: COL, h: 3.3, fontSize: 26, paraSpaceAfter: 4 });
  y += 3.4;
  text([{ text: "今後の展望　", options: { bold: true, color: BLUE_DARK } },
    { text: "日をまたいで計画する方式との比較、蓄電池の充放電も最適化に含めた場合の効果、超過単価・CO₂係数の感度を調べ、受電上限と設備の決め方の指針につなげる。" }],
    { x: RX, y, w: COL, h: 1.8, fontSize: 26 });
  y += 1.9;
  // road to the final presentation
  const steps = [["12月", "日をまたぐ計画の実装と計算"], ["1月", "蓄電池の最適化・単価の感度"], ["2月", "修士論文・学内最終発表"]];
  const sw = (COL - 0.6) / 3;
  steps.forEach(([when, what], i) => {
    const x = RX + i * (sw + 0.3);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: sw, h: 1.5, fill: { color: i === 2 ? "DCEBF7" : "F4F7FA" }, line: { color: BLUE, width: 1.5 } });
    text([{ text: when, options: { bold: true, color: BLUE_DARK, breakLine: true } }, { text: what }], { x: x + 0.15, y: y + 0.1, w: sw - 0.3, h: 1.3, fontSize: 22, align: "center" });
  });
  caption("図6　学内最終発表までの予定", RX, y + 1.55, COL, 0.5, 22);
  y += 2.15;
  caption(`注：結果はすべて診断用（DIAGNOSTIC）。便割当は制限内で最適と確認できておらず、2段階で解くため全体の最適でもない。毎時の立て直しは最大${maxTimeouts}回が時間切れ。計算プログラムの版が混ざっており（${versions}）、同じ設定（最適性ギャップ5%）で全ケースを計算し直している。基本料金は30円/kWhに含むため足さない。`,
    RX, y, COL, 45.5 - y, 20);
};
