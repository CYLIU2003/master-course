// Consultation deck for Prof. Nishiyama (Faculty of Urban Life Studies; public transport, buses,
// universal design). Written for a reader outside optimization and power systems: plain words first,
// a picture of the problem, action titles on result slides, and a glossary at the end.
// Same plain style as the 2026-10-22 lab deck. Data: verified rc8 cases (pillar A) from the lab folder.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const LAB = path.join(__dirname, "..", "2026-10-22_lab_progress");
const rc8 = JSON.parse(fs.readFileSync(path.join(LAB, "cases_rc8.json"), "utf8"));
const iceHour = JSON.parse(fs.readFileSync(path.join(LAB, "ice_by_hour_rc8.json"), "utf8"));
const LIMITS = [90, 200, 400, 800];
const SEASONS = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const get = (g, w) => rc8.find((r) => r.grid_limit_kw === g && r.week === w);
const byLimit = (g) => rc8.filter((r) => r.grid_limit_kw === g);
const avg = (g, k) => byLimit(g).reduce((a, r) => a + r[k], 0) / byLimit(g).length;
const opex = (g) => (avg(g, "electricity_cost") + avg(g, "fuel_cost") + avg(g, "contract_overage_cost")) / 1e4;
const shares = rc8.map((r) => r.bev_trip_share_pct);
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };

const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_LIGHT = "7AB8E8", BLUE_PALE = "EEF5FB", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2";
const THEME = { name: "TCU white", headFontFace: "Noto Sans JP", bodyFontFace: "Noto Sans JP",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "西山先生へのご相談 2026-10";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 25, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } },
            { line: { x: 0.6, y: 7.0, w: 12.1, h: 0, line: { color: GRID, width: 0.75 } } },
            { text: { text: "2026年10月　劉 承洋", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
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

// ---- 1. Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "GXに向けた燃料バスと併用する\n電気バスの便割当・充電計画の最適化", { x: 0.9, y: 1.7, w: 11.5, h: 1.9, fontSize: 32, bold: true, valign: "bottom" });
text(s, "研究の概要と今後の方向性について", { x: 0.9, y: 3.7, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "2026年10月\n東京都市大学 大学院 修士1年　劉 承洋", { x: 0.9, y: 4.6, w: 11.5, h: 1.0, fontSize: 17, color: SUB });

// ---- 2. Background
s = page("研究背景");
bullets(s, [
  "脱炭素化に向けて路線バスの電動化が進む一方、車両価格や充電時間の制約から、当面は燃料（軽油）バスとの併用が続く",
  "電気バスは運行終了後、営業所で夜間にまとめて充電される",
  "多数の車両が同時に充電すると、営業所が電力会社から受け取る電力（受電電力）が大きくなり、受電設備の増強や電気料金の増加につながる",
  "どの便を電気バスに任せ、いつ充電するかを工夫することで、この負担を抑えられる可能性がある"],
  { x: 0.6, y: 1.65, w: 12.1, h: 3.4, fontSize: 18, paraSpaceAfter: 12 });
// A plain one-day timeline: service by day, return in the evening, charging at night.
const TL_Y = 5.55, TL_X = 1.2, TL_W = 10.9;
const hourX = (h) => TL_X + (h - 4) / 24 * TL_W;
s.addShape(pres.shapes.RECTANGLE, { x: hourX(5), y: TL_Y, w: hourX(22) - hourX(5), h: 0.38, fill: { color: "D9D9D9" }, line: { color: "D9D9D9" } });
s.addShape(pres.shapes.RECTANGLE, { x: hourX(22), y: TL_Y, w: hourX(28) - hourX(22), h: 0.38, fill: { color: BLUE }, line: { color: BLUE } });
text(s, "運行（日中）", { x: hourX(5), y: TL_Y + 0.02, w: hourX(22) - hourX(5), h: 0.34, fontSize: 13, align: "center", valign: "middle" });
text(s, "営業所で充電（夜間）", { x: hourX(22), y: TL_Y + 0.02, w: hourX(28) - hourX(22), h: 0.34, fontSize: 13, align: "center", valign: "middle", color: "FFFFFF" });
[5, 10, 15, 20, 22, 28].forEach((h) => text(s, `${h % 24}時`, { x: hourX(h) - 0.4, y: TL_Y + 0.45, w: 0.8, h: 0.3, fontSize: 11, color: SUB, align: "center" }));
caption(s, "図1　電気バスの1日（模式図）", 0.6, 6.45, 12.1);

// ---- 3. Objective
s = page("研究目的");
text(s, "燃料バスと電気バスを併用する営業所を対象に、便の割当と充電計画を数理最適化によって決め、受電電力の上限が電気バスの運用と費用に与える影響を明らかにする。",
  { x: 0.6, y: 1.7, w: 12.1, h: 1.2, fontSize: 19 });
heading(s, "最適化で決めるもの", 3.2);
bullets(s, [
  "各便を担当する車両（電気バス・燃料バス）",
  "各電気バスの充電の時刻と量（15分刻み）",
  "営業所の太陽光発電・蓄電池・買電の使い分け"],
  { x: 0.6, y: 3.65, w: 12.1, h: 1.5, fontSize: 17, paraSpaceAfter: 4 });
heading(s, "条件と目的関数", 5.2);
text(s, "時刻表どおり全便を運行し、電池残量と充電器台数（10基）の制約を守ったうえで、1週間の費用（車両使用費・電気代・燃料代・受電上限の超過分の費用）を最小化する。",
  { x: 0.6, y: 5.65, w: 12.1, h: 1.1, fontSize: 17 });

// ---- 4. Case and conditions
s = page("対象と計算条件");
s.addTable([
  [B("対象"), "東急バス 渋21〜23系統（弦巻営業所）、1週間 1,704便"],
  [B("車両"), "電気バス35台・燃料バス25台（保有台数は固定）"],
  [B("営業所の設備"), "太陽光発電 1,000 kW、蓄電池 6,000 kWh、充電器 90 kW × 10基（いずれも設置を仮定）"],
  [B("対象期間"), "2025年の冬（1/6〜）・春（4/7〜）・夏（7/7〜）の各1週間"],
  [B("受電上限"), "90／200／400／800 kWの4段階。超過した電力量には500円/kWhの費用を課す（仮の値）"],
  [B("単価"), "電力量 30円/kWh、軽油 150円/L、車両使用費 2万円/台・日"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.2, 9.9], fontSize: 15, rowH: 0.66 }));
caption(s, "表1　計算条件（受電上限4段階 × 3週 ＝ 12ケース）", 0.6, 5.65, 12.1);

// ---- 5. Method
s = page("計算方法");
bullets(s, [
  "数理最適化（混合整数計画法）を用いる。問題の規模が大きいため、2段階に分けて解く",
  "第1段階：便の割当を決める（どの便をどの車両が担当するか）",
  "第2段階：割当を固定し、15分ごとの充電と電力の使い分けを決める",
  "1時間ごとに、その時点の状態から残りの計画を立て直しながら1週間を運用し、その結果から費用を集計する"],
  { x: 0.6, y: 1.65, w: 12.1, h: 3.8, fontSize: 18, paraSpaceAfter: 12 });
caption(s, "求解にはGurobiを用い、第1段階には一部の便だけを解き直す近傍探索を併用した", 0.6, 6.4, 12.1);

// ---- 6. Structure and progress
s = page("研究の構成と進捗");
s.addTable([
  [H("柱"), H("内容"), H("時期"), H("進捗")],
  [B("A"), "受電上限と、電気バスが担当できる便・費用の関係", "11月の中間発表", "12ケースの計算完了。追加の計算を実行中"],
  [B("B"), "1日ごとに計画する場合と、日をまたいで計画する場合の比較（翌朝の電池不足、燃料バスへの振替など）", "12月まで", "進め方を決定。11月に計算の準備"],
  [B("C"), "未定", "1月以降", "―"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [0.9, 5.6, 2.1, 3.5], fontSize: 15, rowH: 1.0 }));
caption(s, "柱A・Bは10月8日の打合せ（占部先生・中島先生）で決定した", 0.6, 5.7, 12.1);

// ---- 7. Result A
s = page("結果　受電上限と電気バスの担当便・費用");
s.addChart(pres.charts.LINE, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(g, w).bev_trip_share_pct * 10) / 10) })),
  chart({ x: 0.6, y: 1.45, w: 5.9, h: 3.5, lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 7, chartColors: [BLUE_DARK, BLUE_LIGHT, GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスの担当便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
s.addChart(pres.charts.BAR, [
  { name: "電気代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "electricity_cost") / 1e3) / 10) },
  { name: "燃料代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "fuel_cost") / 1e3) / 10) },
  { name: "上限超過分の費用", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "contract_overage_cost") / 1e3) / 10) }],
  chart({ x: 6.8, y: 1.45, w: 5.9, h: 3.5, barDir: "col", barGrouping: "stacked", chartColors: [BLUE, GREY, "CFCFCF"], valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "費用 [万円/週]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図2　電気バスが担当した便の割合（全1,704便）", 0.6, 4.98, 5.9, 0.35);
caption(s, "図3　1週間の運用費（3週の平均、車両使用費を除く）", 6.8, 4.98, 5.9, 0.35);
bullets(s, [
  `受電上限を800 kWから90 kWまで下げても、電気バスの担当便は${Math.min(...shares).toFixed(1)}〜${Math.max(...shares).toFixed(1)}%でほぼ一定であった`,
  `費用は約${Math.round(opex(800))}万円/週から約${Math.round(opex(90))}万円/週に増加し、その大部分は上限超過分の費用であった`],
  { x: 0.6, y: 5.45, w: 12.1, h: 1.0, fontSize: 15, paraSpaceAfter: 4 });
caption(s, "条件は表1のとおり（渋21〜23系統、1週間1,704便、電気バス35台・燃料バス25台、冬・春・夏の各1週間）", 0.6, 6.55, 12.1);

// ---- 8. Discussion
s = page("考察と課題");
bullets(s, [
  `燃料バスが担当したのは、主に早朝（5〜6時台、${rng("05-06")}）と深夜（22時以降、${rng("22-")}）の便であり、日中は${rng("07-21")}にとどまった。この傾向は受電上限によらなかった`,
  "受電上限を下げても燃料バスへの振替が増えなかったのは、第1段階（便の割当）で充電をすべて太陽光と蓄電池でまかなえると見込んでいたためと考えられる。実際の充電計画では、1週間に2,137〜4,236 kWhを買電していた",
  "現在、受電上限を超過できない条件での計算を行い、燃料バスへの振替が生じるかを確認している",
  "計算は時間で打ち切っており、最適性は確認できていない。また、超過分の費用（500円/kWh）と電力のCO₂排出係数（0.5 kg/kWh）は仮の値である"],
  { x: 0.6, y: 1.65, w: 12.1, h: 5.2, fontSize: 16, paraSpaceAfter: 12 });

// ---- 9. Direction for pillar C
s = page("3本目の柱について");
text(s, "これまでは電力・費用の観点から検討してきたが、3本目の柱では、路線バスの運行や利用者の観点を取り入れたいと考えている。現時点の候補は次のとおりである。",
  { x: 0.6, y: 1.65, w: 12.1, h: 1.0, fontSize: 17 });
const CANDS = [
  ["ダイヤ変更と電動化", "減便や増便をしたとき、電気バスで担当できる便・受電電力・費用・CO₂がどう変わるか"],
  ["車両の使い分け", "低床の電気バスを高齢者や車いす利用の多い便に優先して割り当てたときの、費用や充電への影響"],
  ["非常時の電源としての活用", "災害時に電気バスを避難所などの電源に回した場合に、翌日の運行と両立できる台数・電力量"],
  ["事業者・利用者の受け止め", "最適化が示す運用（車両の入れ替えや充電のための待機など）に対する、事業者・利用者の評価"],
  ["電気料金・CO₂の時間変化", "時間帯によって変わる電気料金やCO₂排出係数を考慮した充電計画"]];
text(s, CANDS.map(([t, d], i) => ({ text: `${i + 1}. ${t}：${d}`, options: { breakLine: i < CANDS.length - 1 } })),
  { x: 0.6, y: 2.75, w: 12.1, h: 4.1, fontSize: 16, paraSpaceAfter: 10 });

// ---- 10. Questions
s = page("ご意見をいただきたい点");
text(s, [
  { text: "1. 公共交通・バス事業の観点から、意義があると考えられるテーマはどれか。上記以外に検討すべき点はあるか", options: { breakLine: true } },
  { text: "2. 利用者へのサービスの質を、どのような指標やデータで評価するのがよいか", options: { breakLine: true } },
  { text: "3. 事業者へのヒアリングや利用者調査などにより、計算結果を補う方法はあるか" }],
  { x: 0.6, y: 1.7, w: 12.1, h: 3.0, fontSize: 18, paraSpaceAfter: 16 });

// ---- 11. Glossary
s = page("補足　用語");
s.addTable([
  [B("便"), "バスが始発から終点まで1回運行すること"],
  [B("営業所"), "バスの車庫。電気バスはここで充電する"],
  [B("受電電力"), "営業所が電力会社から受け取る電力。単位はkW"],
  [B("kW と kWh"), "kWはある時点の電力の大きさ、kWhは使用した電力量（kW × 時間）"],
  [B("受電上限"), "受電電力の目安。本研究では、超過した電力量に費用を課している"],
  [B("数理最適化"), "制約と費用を数式で表し、費用が最小となる計画を計算機で求める方法"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.4, 9.7], fontSize: 15, rowH: 0.62 }));

(async () => {

  const out = path.join(__dirname, process.env.DECK_OUT || "西山先生へのご相談_研究の現状と軸C.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  // The theme helper sets only the Latin typeface; set the East Asian one too so Japanese text uses Noto Sans JP.
  const JSZip = require(path.join(process.env.DECK_NODE_MODULES, "jszip"));
  const zip = await JSZip.loadAsync(fs.readFileSync(out));
  const themePath = Object.keys(zip.files).find((f) => /^ppt\/theme\/theme\d+\.xml$/.test(f));
  const xml = (await zip.file(themePath).async("string")).replace(/<a:ea typeface="[^"]*"\/>/g, `<a:ea typeface="${THEME.bodyFontFace}"/>`);
  zip.file(themePath, xml);
  fs.writeFileSync(out, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  console.log("wrote", out);
})();
