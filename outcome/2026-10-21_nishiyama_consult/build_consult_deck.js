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
            { text: { text: "西山先生へのご相談　2026年10月　劉 承洋", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
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
text(s, "研究の紹介と「3本目の柱」のご相談", { x: 0.9, y: 1.9, w: 11.5, h: 1.0, fontSize: 34, bold: true, valign: "bottom" });
text(s, "GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化", { x: 0.9, y: 3.0, w: 11.5, h: 0.6, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 3.8, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "西山先生へのご相談　2026年10月\n東京都市大学　修士1年　劉 承洋", { x: 0.9, y: 4.05, w: 11.5, h: 1.0, fontSize: 18, color: SUB });

// ---- 2. Purpose
s = page("本日ご相談したいこと");
bullets(s, [
  "電気バスの運行と充電の計画を、計算機で立てる研究をしている（次のページから説明します）",
  "修士研究は3本の柱で組み立てる予定で、2本（柱A・柱B）は内容と時期が決まっている",
  "3本目（軸C）は未定。これまでは電力や費用の側から考えてきたが、路線バスの現場や利用者から見て意味のある問いにしたい"],
  { x: 0.6, y: 1.7, w: 12.1, h: 2.6, fontSize: 18 });
heading(s, "ご助言いただきたいこと", 4.4);
bullets(s, [
  "バス事業者や利用者から見て、意味があり面白い問いはどれか",
  "利用者へのサービスの質を、どのような指標・データで評価すればよいか",
  "事業者へのヒアリングや利用者の調査などで、計算の結果を現場の視点から補う方法"],
  { x: 0.6, y: 4.85, w: 12.1, h: 2.0, fontSize: 17 });

// ---- 3. What the research is about (one picture)
s = page("どんな研究か：電気バスの充電が夜に集中する問題");
const STEPS = [["日中", "時刻表どおりに運行\n（電気バスと燃料バス）"], ["夕方〜夜", "運行を終えたバスが\n営業所（車庫）に戻る"], ["夜間", "電気バスを営業所で\nまとめて充電する"]];
STEPS.forEach(([t, d], i) => {
  const x = 0.6 + i * 4.2;
  box(s, x, 1.6, 3.6, 1.6);
  text(s, t, { x: x + 0.2, y: 1.7, w: 3.2, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });
  text(s, d, { x: x + 0.2, y: 2.15, w: 3.2, h: 0.95, fontSize: 15 });
  if (i < 2) arrow(s, x + 3.65, 2.4, 0.5);
});
heading(s, "何が問題か", 3.5);
bullets(s, [
  "多くの電気バスが同じ時間に充電すると、営業所が電力会社から一度に受け取る電力（受電電力）が大きくなる",
  "受電電力が大きいと、受電設備の増強や、電気料金（電力の大きさに応じてかかる料金）の増加が必要になる",
  "電気バスは高価で、充電にも時間がかかるため、当面は燃料（軽油）バスとの併用が続く。どの便を電気バスに任せ、いつ充電するかの工夫が要る"],
  { x: 0.6, y: 3.95, w: 12.1, h: 2.0, fontSize: 16 });
box(s, 0.6, 6.0, 12.1, 0.8, "EEF5FB", "EEF5FB");
text(s, "本研究：電気バスと燃料バスを併用する営業所で、どの便をどちらのバスが走り、いつ充電するかを、計算機で決める", { x: 0.8, y: 6.0, w: 11.8, h: 0.8, fontSize: 15, bold: true, valign: "middle", color: BLUE_DARK });

// ---- 4. What the computer decides
s = page("この研究で計算機に決めさせていること");
const COLS = [
  ["決めること", ["どの便を、どのバス（電気・燃料）が走るか", "どのバスを、いつ、どれだけ充電するか（15分ごと）", "営業所の太陽光・蓄電池・買う電気の使い分け"]],
  ["守るルール", ["時刻表どおり全便を運行する", "前の便を終えて、次の便の出発に間に合う", "電池の残りが足りなくならない", "充電器は同時に10基まで"]],
  ["小さくする費用（1週間）", ["車両の使用費", "電気代と燃料代", "受電電力の目安（受電上限）を超えた分の追加費用"]]];
COLS.forEach(([head, items], i) => {
  const x = 0.6 + i * 4.1;
  text(s, head, { x, y: 1.55, w: 3.8, h: 0.45, fontSize: 17, bold: true, color: BLUE_DARK });
  s.addShape(pres.shapes.LINE, { x, y: 2.05, w: 3.8, h: 0, line: { color: GRID, width: 1 } });
  bullets(s, items, { x, y: 2.2, w: 3.8, h: 3.0, fontSize: 15 });
});
box(s, 0.6, 5.35, 12.1, 1.25, "F7F7F7");
text(s, [
  { text: "計算のしかた（概要）：", options: { bold: true } },
  { text: "組み合わせが非常に多いため、「便の割当」と「充電の計画」の2段階に分けて、数理最適化（ルールを数式で書いて、計算機に最も費用の小さい計画を探させる方法）で解いている。さらに、1時間ごとに計画を立て直しながら1週間を実行したものとして、費用を集計している。" }],
  { x: 0.8, y: 5.45, w: 11.7, h: 1.1, fontSize: 14 });

// ---- 5. Case study
s = page("対象とした営業所と計算の条件");
s.addTable([
  [B("対象路線"), "東急バス 渋21〜23系統（弦巻営業所）。1週間で1,704便"],
  [B("車両"), "電気バス35台・燃料バス25台を保有している設定（台数は固定）"],
  [B("営業所の設備"), "太陽光発電 1,000 kW、蓄電池 6,000 kWh、充電器 10基（1基あたり90 kW）を置いた設定"],
  [B("計算した週"), "2025年の冬（1月6日〜）・春（4月7日〜）・夏（7月7日〜）の各1週間"],
  [B("受電上限"), "営業所が受け取る電力の目安。90／200／400／800 kWの4段階で比べた。超えた分には1 kWhあたり500円の追加費用をかける（仮の値）"],
  [B("単価"), "電気 30円/kWh、軽油 150円/L、車両の使用費 1台1日2万円"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.2, 9.9], fontSize: 15, rowH: 0.7 }));
caption(s, "kW（キロワット）は電力の大きさ、kWh（キロワット時）は使った電力の量（kW × 時間）。詳しくは最後の用語集", 0.6, 6.45, 12.1);

// ---- 6. Pillars
s = page("研究の3本の柱と進み具合");
s.addTable([
  [H("柱"), H("問い"), H("時期"), H("現状")],
  [B("A（主軸）"), "受電電力の上限を下げると、電気バスに任せられる便と費用はどう変わるか", "中間発表（11月28日）", "12ケースを計算済み。追加の計算を実行中"],
  [B("B"), "1日ごとに計画を立てる場合と比べて、何日か先まで続けて計画すると何が防げるか（翌朝の電池不足など）", "年末まで", "実験の進め方を決めた。11月に計算の仕組みを作る"],
  [{ text: "C", options: { bold: true, color: BLUE_DARK } }, { text: "未定（本日ご相談したい点）", options: { color: BLUE_DARK, bold: true } }, "年明け以降", "―"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [1.4, 4.7, 2.4, 3.6], fontSize: 15, rowH: 1.05 }));
caption(s, "柱A・Bは10月8日の三者ミーティング（占部先生・中島先生）で決定", 0.6, 6.35, 12.1);

// ---- 7. Pillar A result
s = page("柱Aの結果：受電上限を下げても、電気バスが担当する便は減らなかった");
s.addChart(pres.charts.LINE, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(g, w).bev_trip_share_pct * 10) / 10) })),
  chart({ x: 0.6, y: 1.4, w: 5.9, h: 3.3, lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 7, chartColors: [BLUE_DARK, BLUE_LIGHT, GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスが担当した便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限（営業所が受け取る電力の目安）" }));
s.addChart(pres.charts.BAR, [
  { name: "電気代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "electricity_cost") / 1e3) / 10) },
  { name: "燃料代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "fuel_cost") / 1e3) / 10) },
  { name: "上限を超えた分の追加費用", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "contract_overage_cost") / 1e3) / 10) }],
  chart({ x: 6.8, y: 1.4, w: 5.9, h: 3.3, barDir: "col", barGrouping: "stacked", chartColors: [BLUE, GREY, "CFCFCF"], valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "費用 [万円/週]", showCatAxisTitle: true, catAxisTitle: "受電上限（営業所が受け取る電力の目安）" }));
caption(s, "図1　電気バスが担当した便の割合（1週間・全1,704便）", 0.6, 4.72, 5.9, 0.35);
caption(s, "図2　1週間の運用費の内訳（3週の平均、車両の使用費を除く）", 6.8, 4.72, 5.9, 0.35);
const P = (k, v) => [{ text: k, options: { bold: true, fill: { color: HEAD } } }, v];
s.addTable([
  [...P("対象", "渋21〜23系統（弦巻営業所）、1週間 1,704便"), ...P("計算した週", "2025年の冬（1/6〜）・春（4/7〜）・夏（7/7〜）")],
  [...P("車両", "電気バス35台・燃料バス25台（台数は固定）"), ...P("受電上限", "90／200／400／800 kW（超過分は500円/kWh、仮）")],
  [...P("設備", "太陽光1,000 kW・蓄電池6,000 kWh・充電器90 kW×10基"), ...P("単価", "電気30円/kWh、軽油150円/L、車両1台1日2万円")],
  [...P("計算", "2段階の最適化、15分刻み、毎時見直しで1週間を実行"), ...P("ケース", "受電上限4段階 × 3週 ＝ 12ケース")]],
  tableOpts({ x: 0.6, y: 5.12, w: 12.1, colW: [1.0, 5.05, 1.1, 4.95], fontSize: 11, rowH: 0.43 }));
s.addNotes(`受電上限を800 kWから90 kWに下げても、電気バスの担当便は${Math.min(...shares).toFixed(1)}〜${Math.max(...shares).toFixed(1)}%でほぼ一定でした。運用費は1週間あたり約${Math.round(opex(800))}万円から約${Math.round(opex(90))}万円に増えましたが、増分はほぼすべて上限を超えた分の追加費用でした。`);

// ---- 8. How to read pillar A
s = page("柱Aの結果の読み方と、いま確かめていること");
heading(s, "分かったこと", 1.5);
bullets(s, [
  `受電上限を800 kWから90 kWに下げても、電気バスが担当する便は${Math.min(...shares).toFixed(1)}〜${Math.max(...shares).toFixed(1)}%でほぼ変わらなかった`,
  `費用は、1週間あたり約${Math.round(opex(800))}万円から約${Math.round(opex(90))}万円に増えた。増えた分はほぼすべて「上限を超えた分の追加費用」で、燃料の使用量（約155 L/週）は変わらない`,
  `燃料バスが担当したのは主に早朝（5〜6時台、${rng("05-06")}）と深夜（22時以降、${rng("22-")}）の便で、日中は${rng("07-21")}だった`],
  { x: 0.6, y: 1.95, w: 12.1, h: 2.4, fontSize: 15 });
heading(s, "なぜ燃料バスに切り替わらないのか（推測、検証中）", 4.4);
bullets(s, [
  "計算の第1段階（便の割当）では、充電はすべて太陽光と蓄電池でまかなえると見込んでいたが、実際の充電計画では1週間に2,137〜4,236 kWhの電気を買っていた",
  "この見込みのずれが、燃料バスへの切り替えが起きない原因の一つと考えている。受電上限を「絶対に超えられない上限」にした計算を実行中"],
  { x: 0.6, y: 4.85, w: 12.1, h: 2.0, fontSize: 15 });

// ---- 9. Link to Prof. Nishiyama's research
s = page("西山先生のご研究との接点");
heading(s, "先生のご研究（大学の教員紹介より）", 1.5);
bullets(s, [
  "路線バスの活性化方策、自治体の地域交通計画やバス会社のアドバイザー",
  "電池・モーター・インバータを床下に配置した電動低床バスの試作",
  "ユニバーサルデザインとエコデザイン（環境負荷の小さいデザイン）の融合、社会調査手法"],
  { x: 0.6, y: 1.95, w: 12.1, h: 1.7, fontSize: 16 });
heading(s, "本研究に足りない視点", 3.8);
bullets(s, [
  "これまでの評価は、受電電力・費用・CO₂といった事業者の電力側の数字が中心で、利用者へのサービスの質や、現場の運用の実情はほとんど扱っていない",
  "時刻表は変えずに計算しており、ダイヤの変更（減便・増便）や、車両の種類（低床・バリアフリー）による違いも扱っていない",
  "電気バスの導入を、利用者・事業者・地域にとっての価値として説明する視点をいただきたい"],
  { x: 0.6, y: 4.25, w: 12.1, h: 2.6, fontSize: 16 });

// ---- 10. Candidates: public transport and urban life
s = page("3本目の柱の候補（1）公共交通・都市生活の視点");
s.addTable([
  [H("候補"), H("問い"), H("今の計算の仕組みで"), H("必要になるもの")],
  [B("N1 ダイヤの変化と電動化"), "運転士不足による減便や、利用に合わせた増便をしたとき、電気バスに任せられる便・受電電力・費用・CO₂はどう変わるか", "できる。変更したダイヤを新しい入力として作る", "現実的なダイヤ変更の案（事業者の考え方）"],
  [B("N2 車両の使い分け（バリアフリー）"), "低床・フルフラットの電気バスを、高齢者や車いす利用の多い便に優先して割り当てると、費用や充電にどう影響するか", "便ごとに使える車両を指定するルールの追加が必要", "利用者の多い便・時間帯のデータ"],
  [B("N3 非常時の電気バス活用"), "災害時に電気バスを避難所などの電源として使った場合に、翌日の運行と両立できる台数・電力量はどれだけか", "バスから外へ電気を送る扱いの追加が必要", "給電先の必要な電力と、非常時の運行の想定"],
  [B("N4 利用者・事業者の受け止め"), "充電のための車両の入れ替えや待機など、計算が示す運用を、事業者や利用者はどう受け止めるか", "計算の結果をそのまま使える", "事業者へのヒアリング、利用者アンケート"]],
  tableOpts({ x: 0.6, y: 1.45, w: 12.1, colW: [2.6, 4.3, 2.7, 2.5], fontSize: 12, rowH: [0.45, 1.05, 1.05, 1.05, 1.05] }));
caption(s, "N1〜N4は先生のご専門に沿って考えた案で、まだ詳しく検討していない", 0.6, 6.25, 12.1);

// ---- 11. Candidates: power and cost
s = page("3本目の柱の候補（2）電力・費用の視点");
s.addTable([
  [H("候補"), H("問い"), H("今の計算の仕組みで"), H("近い先行研究")],
  [B("C1 日本の電気料金の仕組みでの評価"), "基本料金（電力の大きさで決まる料金）を含めると、充電の計画と費用はどう変わるか", "計算済み（受電のピークが25〜50%下がった）。30分平均での評価は未対応", "Hendriksら（豪）\nCausturら（ルクセンブルク）"],
  [B("C2 時間帯で変わるCO₂・電気料金"), "時間帯で変わるCO₂の排出量や電気料金に合わせて充電の時刻を変えると、CO₂と費用はどう変わるか", "仕組みはある。時間帯別のデータの準備が必要", "井原・紙屋（早稲田）"],
  [B("C3 導入台数・設備の段階的な計画"), "電気バスの台数や受電設備をどう段階的に増やすと、費用とCO₂のバランスがよいか", "台数を変えた計算はできる。計算の回数が多くなる", "Sistigら（独）、Bhidyaら（米）"],
  [B("C4 電力会社側への協力"), "営業所の蓄電池や充電の調整で、電力会社からの使用の抑制などの要請にどこまで応えられるか", "バスから電力網へ電気を送る扱いは未対応", "阿部・前・松橋（東大）"],
  [B("C5 天候と太陽光発電の予測の外れ"), "太陽光の予測が外れたとき、毎時の計画の立て直しでどこまで吸収できるか", "できる（過去に試算あり）", "研究例が多い分野"]],
  tableOpts({ x: 0.6, y: 1.45, w: 12.1, colW: [2.8, 3.8, 2.7, 2.8], fontSize: 12, rowH: [0.45, 0.95, 0.95, 0.95, 0.95, 0.95] }));

// ---- 12. Questions
s = page("ご助言いただきたいこと");
bullets(s, [
  "公共交通・バスの現場から見て、N1〜N4やC1〜C5のうち、意味があり面白い問いはどれか。ほかに見るべき点はあるか",
  "利用者へのサービスの質を、どのような指標・データで評価すればよいか",
  "バス事業者へのヒアリングや利用者の調査で、計算の結果を現場の視点から補う方法",
  "柱A・柱Bとのつながりとして、自然な組み立て方はあるか"],
  { x: 0.6, y: 1.7, w: 12.1, h: 3.4, fontSize: 18 });
heading(s, "補足：結果の数値について", 5.15);
bullets(s, [
  "計算は時間を区切って打ち切っており、最も良い計画であることまでは確かめられていない",
  "上限を超えた分の追加費用（500円/kWh）と、電気のCO₂排出係数（0.5 kg/kWh）は仮の値"],
  { x: 0.6, y: 5.6, w: 12.1, h: 1.3, fontSize: 15 });

// ---- 13. Glossary
s = page("（補足）用語の説明");
s.addTable([
  [B("便"), "バスが始発から終点まで1回運行すること"],
  [B("営業所"), "バスの車庫。運行を終えたバスが戻り、電気バスはここで充電する"],
  [B("受電電力"), "営業所が電力会社から受け取る電力。kW（キロワット）で表す"],
  [B("kW と kWh"), "kWはその時点の電力の大きさ（勢い）、kWhは使った電力の量（kW × 時間）"],
  [B("受電上限"), "受電電力の目安。本研究では、超えた電力量に追加費用をかけて、超えにくくしている"],
  [B("数理最適化"), "守るべきルールと費用を数式で表し、計算機に最も費用の小さい計画を探させる方法"],
  [B("2段階の計算"), "先に「どの便をどのバスが走るか」を決め、次にそれを固定して「いつ充電するか」を決める"],
  [B("毎時の見直し"), "1時間ごとに残りの計画を立て直しながら、1週間を実行したものとして計算する"]]
  .map(([k, v]) => [k, v]), tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.4, 9.7], fontSize: 15, rowH: 0.62 }));

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
