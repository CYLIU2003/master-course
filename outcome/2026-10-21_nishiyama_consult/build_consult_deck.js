// Consultation deck for Prof. Nishiyama: current research and candidates for pillar C.
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

const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_LIGHT = "7AB8E8", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2";
const THEME = { name: "TCU white", headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "西山先生へのご相談 2026-10";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 26, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
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
const heading = (s, t, y) => text(s, t, { x: 0.6, y, w: 12.1, h: 0.4, fontSize: 17, bold: true, color: BLUE_DARK });

// ---- Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "研究の現状と「軸C」のご相談", { x: 0.9, y: 2.0, w: 11.5, h: 1.0, fontSize: 34, bold: true, valign: "bottom" });
text(s, "GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化", { x: 0.9, y: 3.1, w: 11.5, h: 0.6, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 3.9, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "西山先生へのご相談　2026年10月\n東京都市大学　修士1年　劉 承洋", { x: 0.9, y: 4.15, w: 11.5, h: 1.0, fontSize: 18, color: SUB });

// ---- Purpose
s = page("本日ご相談したいこと");
bullets(s, [
  "修士研究は3本の柱（A・B・C）で進めている。柱Aと柱Bは内容と時期が決まっている",
  "3本目の柱（軸C）を何にするかを決めたい",
  "これまでは電力・費用の側から考えてきたが、路線バスの現場や利用者の側から見て意味のある問いにしたい。公共交通・バスの視点からご助言をいただきたい"],
  { x: 0.6, y: 1.7, w: 12.1, h: 2.4, fontSize: 19 });
heading(s, "ご助言いただきたい3点", 4.3);
bullets(s, [
  "バス事業者や利用者から見て、意味があり面白い問いはどれか。ほかに見るべき点はあるか",
  "サービスの質（利用者への影響）をどのような指標・データで評価すればよいか",
  "事業者へのヒアリングや利用者の調査など、最適化の結果を現場の視点で補う方法"],
  { x: 0.6, y: 4.75, w: 12.1, h: 2.0, fontSize: 17 });

// ---- Overview
s = page("研究の概要");
s.addTable([
  [B("題目"), "GXに向けた燃料バスと併用する電気バスの便割当・充電計画の最適化"],
  [B("背景"), "電気バスは営業所で夜間にまとめて充電するため、営業所の受電電力が大きくなりやすい。当面は燃料（軽油）バスとの併用が続く"],
  [B("対象"), "東急バス 渋21〜23系統（弦巻営業所）、1週間1,704便。保有は電気バス35台・燃料バス25台"],
  [B("設備（設定）"), "太陽光 1,000 kW（傾斜30°）、蓄電池 6,000 kWh、充電器 90 kW × 10基"],
  [B("決めること"), "各便の担当車両（電気・燃料）と、15分ごとの充電・太陽光・蓄電池・買電の配分"],
  [B("手法"), "便割当（Stage 1）と充電計画（Stage 2）の2段階の混合整数計画（Gurobi）。便割当には大近傍探索（LNS）を併用。1時間ごとに計画を更新しながら1週間を実行し、実行結果から費用を集計"]]
  .map(([k, v]) => [k, v]), tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [2.2, 9.9], fontSize: 15, rowH: 0.8 }));

// ---- Pillars and status
s = page("研究の柱と進み具合");
s.addTable([
  [H("柱"), H("問い"), H("時期"), H("現状")],
  [B("A（主軸）"), "受電電力の上限を下げると、電気バスに任せられる便と費用はどう変わるか", "中間発表（11/28）", "計算済み（冬・春・夏 × 上限90／200／400／800 kWの12ケース）。追加の試行計算を実行中"],
  [B("B"), "日ごとに計画した場合と比べて、日をまたいで連続して計画すると何を防げるか", "年末まで", "実験の設計を決定済み（日ごとの計画を2〜3週つなぎ、最後の1週を評価）。11月に実装"],
  [{ text: "C", options: { bold: true, color: BLUE_DARK } }, { text: "未定（本日ご相談したい点）", options: { color: BLUE_DARK, bold: true } }, "年明け以降", "―"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [1.4, 4.3, 2.2, 4.2], fontSize: 15, rowH: 1.05 }));
caption(s, "柱A・Bは10月8日の三者ミーティング（占部先生・中島先生）で決定", 0.6, 6.35, 12.1);

// ---- Pillar A results
s = page("柱Aで分かっていること（12ケース）");
s.addChart(pres.charts.LINE, SEASONS.map(([w, n]) => ({ name: n, labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(get(g, w).bev_trip_share_pct * 10) / 10) })),
  chart({ x: 0.6, y: 1.5, w: 5.9, h: 4.6, lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 7, chartColors: [BLUE_DARK, BLUE_LIGHT, GREY],
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 20, showValAxisTitle: true, valAxisTitle: "電気バスが担当した便 [%]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
s.addChart(pres.charts.BAR, [
  { name: "電気代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "electricity_cost") / 1e3) / 10) },
  { name: "燃料代", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "fuel_cost") / 1e3) / 10) },
  { name: "上限の超過費用", labels: LIMITS.map((g) => `${g} kW`), values: LIMITS.map((g) => Math.round(avg(g, "contract_overage_cost") / 1e3) / 10) }],
  chart({ x: 6.8, y: 1.5, w: 5.9, h: 4.6, barDir: "col", barGrouping: "stacked", chartColors: [BLUE, GREY, "CFCFCF"], valAxisMinVal: 0,
    showValAxisTitle: true, valAxisTitle: "運用費 [万円/週]", showCatAxisTitle: true, catAxisTitle: "受電上限" }));
caption(s, "図1　受電上限と電気バスの担当便", 0.6, 6.15, 5.9);
caption(s, "図2　受電上限と1週間の運用費（3週平均、車両使用費は除く）", 6.8, 6.15, 5.9);
s.addNotes("受電上限を800 kWから90 kWに下げても、電気バスの担当便は92.0〜96.5%でほぼ一定でした。運用費は1週間あたり約11万円から約87万円に増えましたが、増分はほぼすべて上限の超過費用（仮に500円/kWh）で、燃料使用量は約155 L/週で変わりませんでした。");

// ---- Pillar A interpretation
s = page("柱Aの結果の解釈と、いま確かめていること");
const rng = (b) => { const v = iceHour.map((r) => r.bands[b].diesel / r.bands[b].total * 100); return `${Math.min(...v).toFixed(0)}〜${Math.max(...v).toFixed(0)}%`; };
heading(s, "結果", 1.5);
bullets(s, [
  "受電上限を下げても電気バスの担当便は減らず、費用は上限の超過費用として増えた。燃料使用量（約155 L/週）は変わらない",
  `燃料バスが担当したのは主に早朝（5〜6時台、${rng("05-06")}）と深夜（22時以降、${rng("22-")}）の便で、日中は${rng("07-21")}`],
  { x: 0.6, y: 1.95, w: 12.1, h: 1.9, fontSize: 16 });
heading(s, "原因の見立て（推測、検証中）", 3.95);
bullets(s, [
  "便割当の段階では、充電をすべて太陽光と蓄電池でまかなえる（買電0 kWh）と見込んでいた",
  "実際の充電計画では、1週間に2,137〜4,236 kWhを買電していた。2段階で解く際の見込みのずれが、燃料バスへの振り替えが起きない一因と考えている",
  "受電上限を「超過を許さない上限」にした試行計算（冬・90／200／400 kW）を実行中"],
  { x: 0.6, y: 4.4, w: 12.1, h: 2.5, fontSize: 16 });

// ---- Link to Prof. Nishiyama's research
s = page("西山先生のご研究との接点（ご指導いただきたい理由）");
heading(s, "先生のご研究（大学の教員紹介より）", 1.5);
bullets(s, [
  "路線バスの活性化方策、自治体の地域交通計画やバス会社のアドバイザー",
  "電池・モーター・インバータを床下に配置した電動低床バスの試作",
  "ユニバーサルデザインとエコデザイン（環境低負荷デザイン）の融合、社会調査手法"],
  { x: 0.6, y: 1.95, w: 12.1, h: 1.7, fontSize: 16 });
heading(s, "本研究に足りない視点", 3.8);
bullets(s, [
  "これまでの評価は、受電電力・費用・CO₂といった事業者の電力側の指標が中心で、利用者へのサービスの質や現場の運用の実情はほとんど扱っていない",
  "時刻表は所与で、ダイヤの変更（減便・増便）や車両の種類（低床・バリアフリー）による違いも扱っていない",
  "電気バスの導入を、利用者・事業者・地域にとっての価値として説明する視点をいただきたい"],
  { x: 0.6, y: 4.25, w: 12.1, h: 2.6, fontSize: 16 });

// ---- Pillar C candidates: public transport and urban life
s = page("軸Cの候補（1）公共交通・都市生活の視点");
s.addTable([
  [H("候補"), H("問い"), H("今のモデルでできるか"), H("必要になるもの")],
  [B("N1 ダイヤの変化と電動化"), "運転士不足による減便や、利用に合わせた増便をしたとき、電気バスに任せられる便・受電電力・費用・CO₂はどう変わるか", "できる。変更したダイヤを別の入力として明示的に作る", "現実的なダイヤ変更の案（事業者の考え方）"],
  [B("N2 車両の使い分け（バリアフリー）"), "低床・フルフラットの電気バスを、高齢者や車いす利用の多い便に優先して割り当てると、費用や充電にどう影響するか", "便ごとに使える車両を指定する制約の追加が必要", "利用者の多い便・時間帯のデータ"],
  [B("N3 非常時の電気バス活用"), "災害時に電気バスを避難所などへの給電に回すと、翌日の運行と両立できる台数・電力量はどれだけか", "外部への給電の扱いを加えるモデルの拡張が必要", "給電先の需要と、非常時の運行の想定"],
  [B("N4 利用者・事業者の受け止め"), "充電のための車両の入れ替えや待機など、最適化が示す運用を、事業者や利用者はどう受け止めるか", "最適化の結果をそのまま使える", "事業者へのヒアリング、利用者アンケート"]],
  tableOpts({ x: 0.6, y: 1.45, w: 12.1, colW: [2.6, 4.3, 2.7, 2.5], fontSize: 12, rowH: [0.45, 1.05, 1.05, 1.05, 1.05] }));
caption(s, "N1〜N4は先生のご専門に沿って考えた案で、まだ詳しく検討していない", 0.6, 6.25, 12.1);

// ---- Pillar C candidates
s = page("軸Cの候補（2）電力・費用の視点");
s.addTable([
  [H("候補"), H("問い"), H("今のモデルでできるか"), H("近い先行研究")],
  [B("C1 日本の料金体系での評価（当初案）"), "基本料金（30分デマンド・実量制）を考えると、充電計画と費用はどう変わるか", "基本料金は計算済み。30分平均の扱いは未対応", "Hendriksら（豪）、Causturら（ルクセンブルク）"],
  [B("C2 時間帯別のCO₂係数・電気料金"), "時間帯で変わるCO₂係数や料金に合わせて充電時刻を変えると、CO₂と費用はどう変わるか", "入力の仕組みはある。データの準備が必要", "井原・紙屋（早稲田）"],
  [B("C3 導入台数・受電設備容量の段階的な評価"), "電気バスの台数や受電設備の容量をどう段階的に増やすと、費用とCO₂のバランスがよいか", "台数を変えた計算はできる。ケース数が多くなる", "Sistigら（独）、Bhidyaら（米）、Stumpeら（独）"],
  [B("C4 系統側との連携"), "営業所の蓄電池や充電の調整で、系統側の要請（需要抑制など）にどこまで応えられるか", "逆潮流（売電・V2G）は未対応。モデルの拡張が必要", "阿部・前・松橋（東大）"],
  [B("C5 天候・太陽光予測の不確実性"), "太陽光の予測が外れたとき、毎時の見直しでどこまで吸収できるか", "できる（過去に日別の天候で試算あり）", "太陽光・蓄電池付きの充電計画は研究例が多い"]],
  tableOpts({ x: 0.6, y: 1.45, w: 12.1, colW: [2.9, 3.9, 2.8, 2.5], fontSize: 12, rowH: [0.45, 0.92, 0.92, 0.92, 0.92, 0.92] }));
caption(s, "C1は前倒しで計算済み：基本料金を目的関数に含めると、冬の受電ピークが25〜50%下がった（16ケース）", 0.6, 6.62, 12.1, 0.33);

// ---- Closing
s = page("ご助言いただきたいこと（再掲）");
bullets(s, [
  "公共交通・バスの現場から見て、N1〜N4やC1〜C5のうち、意味があり面白い問いはどれか",
  "利用者へのサービスの質を、どのような指標・データで評価すればよいか",
  "バス事業者へのヒアリングや利用者の調査で、最適化の結果を現場の視点から補う方法",
  "柱A・柱Bとのつながりとして、自然な組み立て方はあるか"],
  { x: 0.6, y: 1.7, w: 12.1, h: 3.2, fontSize: 19 });
heading(s, "補足：数値の扱い", 5.0);
bullets(s, [
  "結果はいずれも制限時間内に得られた計画。便割当は最適性を確認できていない（充電計画は12ケース中11ケースで最適）",
  "上限の超過費用（500円/kWh）と電力のCO₂係数（0.5 kg/kWh）は仮の値"],
  { x: 0.6, y: 5.45, w: 12.1, h: 1.4, fontSize: 15 });

(async () => {
  const out = path.join(__dirname, "西山先生へのご相談_研究の現状と軸C.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
