// Report to Prof. Urabe and Prof. Nakajima on the consultation with Prof. Nishiyama (2026-11).
// Content = the student's own notes from the meeting (user message 2026-11-17); the mapping to pillar C is the student's proposal, labelled as such.
// No new numbers: the results shown to Prof. Nishiyama were provisional (DIAGNOSTIC) and are only referred to, not repeated.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const BLUE = "0485D7", BLUE_DARK = "0268B0", BLUE_PALE = "EEF5FB", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD", HEAD = "F2F2F2";
const THEME = { name: "TCU white", headFontFace: "Noto Sans JP", bodyFontFace: "Noto Sans JP",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "西山先生とのご相談の報告 2026-11";
const C = pres.SchemeColor;
pres.defineSlideMaster({ title: "PLAIN", background: { color: "FFFFFF" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.8, fontSize: 25, bold: true, color: C.text1, valign: "bottom", align: "left" }, text: "" } },
            { line: { x: 0.6, y: 1.3, w: 12.1, h: 0, line: { color: BLUE, width: 2.5 } } },
            { line: { x: 0.6, y: 7.0, w: 12.1, h: 0, line: { color: GRID, width: 0.75 } } },
            { text: { text: "2026年11月　劉 承洋", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: SUB, margin: 0 } } }],
  slideNumber: { x: 12.2, y: 7.05, w: 0.5, h: 0.3, fontSize: 10, color: SUB, align: "right" } });

const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 18, lineSpacingMultiple: 1.2, ...o });
const bullets = (s, items, o) => text(s, items.map((t, i) => ({ text: t, options: { bullet: { indent: 18 }, breakLine: i < items.length - 1 } })), { paraSpaceAfter: 6, ...o });
const caption = (s, t, x, y, w, h = 0.4) => text(s, t, { x, y, w, h, fontSize: 12, color: SUB });
const page = (title) => { const s = pres.addSlide({ masterName: "PLAIN" }); s.addText(title, { placeholder: "title" }); return s; };
const tableOpts = (o) => ({ fontSize: 14, color: INK, valign: "middle", border: { type: "solid", pt: 0.75, color: GRID }, ...o });
const H = (t) => ({ text: t, options: { bold: true, fill: { color: HEAD }, align: "center" } });
const heading = (s, t, x, y, w) => text(s, t, { x, y, w, h: 0.45, fontSize: 18, bold: true, color: BLUE_DARK, valign: "middle" });
const ICON = (n) => {
  for (const d of ["icons", "../2026-11-16_nishiyama_consult/icons", "../2026-11-28_midterm_poster/icons"]) {
    const p = path.join(__dirname, d, `${n}.png`);
    if (fs.existsSync(p)) return p;
  }
  throw new Error("icon " + n);
};
const icon = (s, n, x, y, w, alt) => s.addImage({ path: ICON(n), x, y, w, h: w, altText: alt || n });
const card = (s, x, y, w, h, fill = BLUE_PALE) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: GRID, width: 0.75 } });

// ---- 1. Title
let s = pres.addSlide();
s.background = { color: "FFFFFF" };
text(s, "占部先生・中島先生　ご報告", { x: 0.9, y: 1.2, w: 11.5, h: 0.5, fontSize: 18, color: SUB });
text(s, "西山先生とのご相談の報告", { x: 0.9, y: 1.8, w: 11.5, h: 1.4, fontSize: 34, bold: true, valign: "bottom" });
text(s, "いただいたご意見と、3本目の柱（柱C）への反映案", { x: 0.9, y: 3.3, w: 11.5, h: 0.5, fontSize: 20, color: SUB });
s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.0, w: 11.5, h: 0, line: { color: BLUE, width: 3 } });
text(s, "2026年11月\n東京都市大学 大学院 修士1年　劉 承洋", { x: 0.9, y: 4.25, w: 11.5, h: 1.0, fontSize: 17, color: SUB });

// ---- 2. What was presented and asked
s = page("西山先生にお見せしたこと、伺ったこと");
heading(s, "お見せした内容", 0.6, 1.55, 6.6);
s.addTable([
  [H(""), H("内容")],
  [{ text: "柱A", options: { bold: true, align: "center" } }, "電力の上限と、電気バスの担当便・費用・CO₂（暫定値）"],
  [{ text: "柱C ①", options: { bold: true, align: "center" } }, "運行していない電気バスや営業所の空きスペース、太陽光の電気を地域で使う"],
  [{ text: "柱C ②", options: { bold: true, align: "center" } }, "乗り降りしやすい電気バスを、高齢の方や車いすの方が多い便に優先して割り当てる"],
  [{ text: "柱C ③", options: { bold: true, align: "center" } }, "事業者へのヒアリングや利用者調査で、受け入れられる運用を先に調べて条件に入れる"]],
  tableOpts({ x: 0.6, y: 2.1, w: 6.6, colW: [1.1, 5.5], fontSize: 13, rowH: [0.42, 0.7, 0.85, 0.85, 0.85] }));
heading(s, "伺ったこと", 7.6, 1.55, 5.1);
card(s, 7.6, 2.1, 5.1, 3.7);
text(s, [
  { text: "1. 3つの案のうち、利用者や地域にとって意義が大きいのはどれか。見落としている視点はないか", options: { breakLine: true } },
  { text: "2. 数値の指標と、アンケートや対話などの調査をどう組み合わせるか", options: { breakLine: true } },
  { text: "3. 修士の残りの期間で、どのくらいの調査なら現実的か" }],
  { x: 7.85, y: 2.3, w: 4.65, h: 3.4, fontSize: 15, paraSpaceAfter: 12 });
caption(s, "相談に使った資料：outcome/2026-11-16_nishiyama_consult/西山先生へのご相談_最新結果と3本目の柱.pptx（本編9枚）。柱Aの数値は条件をそろえる前の暫定値で、研究の結論には使っていません。", 0.6, 6.2, 12.1, 0.6);

// ---- 3. Overview of the feedback
s = page("いただいたご意見は、大きく4つでした");
const OV = [
  [["driver", "minibus"], "運転士が足りない", "人の拘束時間まで含めて考える必要がある。大型免許を持つ人も減っており、小さいバスや別の形のサービスまで考える必要がある"],
  [["thermo"], "冷暖房の費用が増えていく", "気候変動で、冷房を使う期間が長くなり、強さも上がっている"],
  [["people", "parcel"], "バスを移動以外にも使う", "地域交流や仕事の場、貨物との混載、救急、窓口サービスなど"],
  [["talk", "check"], "事業者の意見で確かめる", "柱C案③のヒアリングを、異種EVバスについて行う。数学をやりすぎると現実から離れる"]];
OV.forEach(([ics, h, t], i) => {
  const x = 0.6 + (i % 2) * 6.15, y = 1.55 + Math.floor(i / 2) * 2.5;
  card(s, x, y, 5.95, 2.25);
  ics.forEach((n, k) => icon(s, n, x + 0.2 + k * 0.85, y + 0.2, 0.8));
  text(s, h, { x: x + 0.25 + ics.length * 0.85, y: y + 0.25, w: 5.6 - ics.length * 0.85, h: 0.7, fontSize: 19, bold: true, color: BLUE_DARK, valign: "middle" });
  text(s, t, { x: x + 0.25, y: y + 1.1, w: 5.45, h: 1.15, fontSize: 14 });
});
text(s, "西山先生は研究の内容に前向きで、東急バスへの相談も十分に可能とのことでした。", { x: 0.6, y: 6.55, w: 12.1, h: 0.4, fontSize: 16, bold: true, color: BLUE_DARK });

// ---- 3b. What went well: his view matched the student's concern (added 2026-11-17)
s = page("今回のご相談で良かった点");
[[0.6, "talk", "西山先生のお考え", "計算の結果だけでは、バス会社としても受け入れにくい。単なる最適化だけだと、そうなってしまう。"],
 [7.45, "plan", "私の懸念", "研究の結果が、実社会で使われないままになってしまうこと。"]].forEach(([x, n, h, t]) => {
  card(s, x, 1.6, 5.25, 2.6);
  icon(s, n, x + 0.25, 1.8, 0.85);
  text(s, h, { x: x + 1.3, y: 1.8, w: 3.8, h: 0.85, fontSize: 20, bold: true, color: BLUE_DARK, valign: "middle" });
  text(s, t, { x: x + 0.3, y: 2.85, w: 4.7, h: 1.2, fontSize: 17 });
});
s.addShape(pres.shapes.OVAL, { x: 6.05, y: 2.35, w: 1.2, h: 1.2, fill: { color: BLUE }, line: { color: BLUE } });
text(s, "一致", { x: 6.05, y: 2.35, w: 1.2, h: 1.2, fontSize: 20, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
s.addShape(pres.shapes.ISOSCELES_TRIANGLE, { x: 6.4, y: 4.45, w: 0.5, h: 0.3, rotate: 180, fill: { color: GREY }, line: { color: GREY } });
card(s, 0.6, 5.0, 12.1, 1.5, "DCEBF7");
icon(s, "people", 0.9, 5.3, 0.9);
icon(s, "driver", 1.9, 5.3, 0.9);
text(s, "今後も、利用者や運用者の視点まで含めた最適化が必要", { x: 3.1, y: 5.1, w: 9.4, h: 1.3, fontSize: 22, bold: true, color: BLUE_DARK, valign: "middle" });

// ---- 4. Drivers and HVAC
s = page("運転士の不足と、冷暖房の増加");
[[0.6, ["driver", "minibus"], "運転士の不足",
  ["人の拘束時間まで最適化できるか、それが負担の軽減になるかが、バス会社にとっていま難しい問題になっている。単純に人がいない",
   "大型免許を持つ人がかなり減ってきた。小型のバスで考えることや、別の形でのサービス提供まで含めて考える必要がある",
   "コミュニティバスでの対応や小さいバスの可能性もあるが、そもそも運転士が少なくなってきている"],
  "今の計算：コードには拘束時間をもとにした運転士費用の項目があります。今回の結果で使っていたかと、勤務のルールを条件として入れるかは、これから確認・検討します。"],
 [6.75, ["thermo"], "気候変動と冷暖房",
  ["気候変動で冷暖房の使用が増え、それがコストに影響する",
   "冷房を使う期間が長くなり、しかも強度が上がっている"],
  "今の計算：電気バスの電力量の計算には冷暖房の項目があります。季節や気温によって強さが変わる扱いになっているかは、これから確認します。"]].forEach(([x, ics, h, items, now]) => {
  ics.forEach((n, k) => icon(s, n, x + k * 0.75, 1.55, 0.7));
  heading(s, h, x + ics.length * 0.75 + 0.15, 1.65, 5.0);
  bullets(s, items, { x, y: 2.45, w: 5.95, h: 2.7, fontSize: 15 });
  card(s, x, 5.3, 5.95, 1.4, "F4F7FA");
  text(s, now, { x: x + 0.2, y: 5.38, w: 5.55, h: 1.25, fontSize: 13, color: SUB, valign: "middle" });
});

// ---- 5. Other uses of buses
s = page("バスや電気バスを、移動以外にも活かすアイデア");
const IDEAS = [
  ["people", "地域の場として使う", "コミュニティでの利用、地域交流の場や仕事の場として活用する"],
  ["parcel", "客貨混載の電気バス", "コンセントがあるので、移動中に荷物を冷やしたり、温度を安定させたりできる"],
  ["minibus", "オンデマンド輸送", "オンデマンドバスより一歩進めて、貨物を運ぶオンデマンド輸送"],
  ["ambulance", "救急車への応用", "バスを救急車として使い、救急室の手前まで運ぶ可能性"],
  ["atm", "待ち時間の活用", "地方であれば、空いているバスのスペースにATMや証明書発行機を置く"],
  ["building", "移動の抵抗を減らす", "建物の中での電動モビリティの利用拡大など、移動の抵抗を減らす手段を提供する"]];
IDEAS.forEach(([n, h, t], i) => {
  const x = 0.6 + (i % 3) * 4.1, y = 1.55 + Math.floor(i / 3) * 2.35;
  card(s, x, y, 3.9, 2.15);
  icon(s, n, x + 0.2, y + 0.2, 0.8);
  text(s, h, { x: x + 1.15, y: y + 0.2, w: 2.6, h: 0.8, fontSize: 17, bold: true, color: BLUE_DARK, valign: "middle" });
  text(s, t, { x: x + 0.2, y: y + 1.1, w: 3.5, h: 1.05, fontSize: 13 });
});
caption(s, "多くは柱C案①（運行していない電気バスや営業所を地域で使う）を広げる方向で、「移動の抵抗を減らす」は案②（乗り降りしやすい車両）にも関わると考えています（劉の整理）。", 0.6, 6.25, 12.1, 0.6);

// ---- 6. How to proceed
s = page("研究の進め方について");
[[0.6, "talk", "事業者へのヒアリング（柱C案③）",
  ["柱C案③として、異種EVバスについて事業者にヒアリングする",
   "地域による違いや、運用に対する制約などを聞く"]],
 [6.75, "check", "モデルが妥当かどうか",
  ["モデルが妥当かどうかには、バス会社の意見が必要になる",
   "結果的に、全体としての最適解が必要になってくる",
   "数学的なことをやりすぎると、現実から離れていく"]]].forEach(([x, n, h, items]) => {
  card(s, x, 1.55, 5.95, 3.7);
  icon(s, n, x + 0.25, 1.75, 0.85);
  text(s, h, { x: x + 1.3, y: 1.75, w: 4.45, h: 0.85, fontSize: 19, bold: true, color: BLUE_DARK, valign: "middle" });
  bullets(s, items, { x: x + 0.3, y: 2.9, w: 5.4, h: 3.1, fontSize: 16, paraSpaceAfter: 10 });
});
card(s, 0.6, 5.45, 12.1, 1.3, "DCEBF7");
text(s, [
  { text: "東急バスへの相談は十分に可能とのことでした。", options: { bold: true, color: BLUE_DARK, breakLine: true } },
  { text: "私としては、電気学会全国大会に講演を申し込んだあと、冊子の講演論文集ができてから、それを持ってヒアリングに伺いたいと考えています。" }],
  { x: 0.85, y: 5.52, w: 11.6, h: 1.16, fontSize: 16, valign: "middle", paraSpaceAfter: 4 });

// ---- 7. Proposed reflection (student's proposal)
s = page("柱Cへの反映（案）");
s.addTable([
  [H("ご意見"), H("関わるところ"), H("進め方の案")],
  ["事業者ヒアリング（異種EVバス、地域差、運用の制約）", "柱C案③", "講演論文集（冊子）を持って東急バスに伺い、聞いた制約を計算の条件に入れる。モデルの妥当性も見ていただく"],
  ["運転士の不足、拘束時間、小型車", "柱A・Bのモデル、柱C", "ヒアリングで現場の制約を確かめ、拘束時間を条件や費用に入れる範囲を決める"],
  ["冷暖房の増加", "柱A・Bのモデル", "冷暖房の電力の扱いを確認し、必要なら季節や気温による違いを比べる"],
  ["移動以外の使い方（地域の場、客貨混載、救急、窓口など）", "柱C案①", "候補を絞り、次の運行に必要な電池を残したまま使える量を計算する"],
  ["移動の抵抗を減らす", "柱C案②", "乗り降りしやすい車両の割当と合わせて考える"],
  ["計算結果だけでは受け入れにくい、数学をやりすぎない", "全体", "利用者や運用者の視点を条件や評価に入れ、モデルを複雑にする前に事業者の意見で妥当性を確かめる"]],
  tableOpts({ x: 0.6, y: 1.55, w: 12.1, colW: [4.3, 2.3, 5.5], fontSize: 13, rowH: [0.42, 0.72, 0.72, 0.62, 0.72, 0.62, 0.62] }));
caption(s, "西山先生のご意見をもとにした劉の整理案で、まだ決めたものではありません。進め方をご相談させてください。", 0.6, 6.45, 12.1);

// ---- 8. Questions to the supervisors
s = page("ご相談したいこと");
const Q = [
  "柱Cを、東急バスへのヒアリング（案③）から始めてよいでしょうか。電気学会全国大会の講演申込み後、冊子の講演論文集ができてから、それを持って伺う進め方を考えています。",
  "運転士の拘束時間や冷暖房の変化を、柱A・Bの計算にどこまで入れるべきでしょうか。11/28の中間発表は今の計算のまま進める予定です。",
  "移動以外の使い方のアイデアのうち、修士論文で扱う範囲をどのくらいに絞るのがよいでしょうか。"];
Q.forEach((q, i) => {
  const y = 1.65 + i * 1.6;
  card(s, 0.6, y, 12.1, 1.35);
  text(s, String(i + 1), { x: 0.85, y: y + 0.25, w: 0.7, h: 0.85, fontSize: 32, bold: true, color: BLUE, align: "center", valign: "middle" });
  text(s, q, { x: 1.8, y: y + 0.15, w: 10.7, h: 1.05, fontSize: 17, valign: "middle" });
});

(async () => {
  const out = path.join(__dirname, "西山先生とのご相談の報告_占部先生・中島先生.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
