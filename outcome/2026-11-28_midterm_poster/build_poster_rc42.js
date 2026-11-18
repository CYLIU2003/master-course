// Midterm (2026-11-28) A0 portrait poster with the rc42 results (19dc0780; 48 runs = 2 tariffs x 12 cases x 2 initial
// assignments, all VERIFIED; 3 summer electric-first runs rerun once at 24 GiB after a 14 GiB memory_limit, rc42m24).
// 2026-11-18 (user): "とりあえず新しい結果でポスターを作成してみて、２通りか３通りで、日本語と英語版それぞれ" — the advisor
// has not yet chosen which tariff the poster leads with, so three variants are built (POSTER_VARIANT):
//   a = tariff A (17.43 JPY/kWh + basic charge) main, B as a comparison;
//   b = tariff B (30 JPY/kWh incl. basic charge) main, A as a comparison;
//   c = A and B side by side.
// Data: ../2026-11-12_three_party/deck_data_rc42_{et,ct}.json (prepare_deck_data_rc42.py). Reported total =
// total_cost_fuel_consumed - CO2 kg x 1 JPY (the CO2 cost stays in the objective only, 2026-11-16) + the weekly basic
// charge (tariff A only; 0 for B, whose unit price already includes it). Layout: poster_layout_v5.js (v4 type sizes).
const path = require("path");
const fs = require("fs");
const LANG = process.env.POSTER_LANG === "en" ? "en" : "ja";
const VARIANT = process.env.POSTER_VARIANT || "a";
if (!["a", "b", "c"].includes(VARIANT)) throw new Error(`POSTER_VARIANT must be a, b or c: ${VARIANT}`);
const FONT = LANG === "en" ? "Arial" : "Yu Gothic";
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(path.join(process.env.PPTX_SKILL, "scripts", "apply_theme.js"));
const { flowDiagram } = require("./poster_figs.js");

const CO2_YEN_PER_KG = 1;
const load = (series) => {
  const D = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", `deck_data_rc42_${series}.json`), "utf8"));
  if (D.tariff_series !== series) throw new Error(`tariff series mismatch: ${D.tariff_series} != ${series}`);
  const bad = [...D.cases, ...D.pairs].filter((r) => r.status !== "VERIFIED");
  if (bad.length || D.cases.length !== 12 || D.pairs.length !== 24) throw new Error(`${series}: not all 12 cases / 24 runs VERIFIED`);
  [...D.cases, ...D.pairs].forEach((r) => {
    if (r.tariff_series !== series) throw new Error(`row tariff mismatch in ${series}`);
    r.total_cost_reported = r.total_cost_fuel_consumed - r.total_co2_kg * CO2_YEN_PER_KG + r.basic_charge_week_jpy; });
  const pair = (g, w, st) => D.pairs.find((x) => x.grid_limit_kw === g && x.week === w && x.start === st);
  const get = (g, w) => D.cases.find((r) => r.grid_limit_kw === g && r.week === w);
  return { series, D, cases: D.cases, pairs: D.pairs, pair, get,
    maxTimeouts: Math.max(...D.pairs.map((r) => r.rolling_time_limit_steps)),
    steps: [Math.min(...D.pairs.map((r) => r.rolling_steps)), Math.max(...D.pairs.map((r) => r.rolling_steps))] };
};
const ET = load("et"), CT = load("ct");
if (JSON.stringify(ET.D.limits) !== JSON.stringify(CT.D.limits)) throw new Error("limits differ between tariffs");
const LIMITS = ET.D.limits;
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const MAIN = VARIANT === "b" ? CT : ET, OTHER = VARIANT === "b" ? ET : CT;

const BLUE = "0485D7", BLUE_DARK = "0268B0", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD";
const THEME = { name: "TCU white", headFontFace: FONT, bodyFontFace: FONT,
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.defineLayout({ name: "A0_PORTRAIT", width: 33.11, height: 46.81 });
pres.layout = "A0_PORTRAIT";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = LANG === "en" ? `Midterm poster 2026-11-28 (rc42, variant ${VARIANT})` : `中間発表ポスター 2026-11-28（rc42・案${VARIANT}）`;
const M = 1.6, W = 33.11 - 2 * M, GAP = 0.9, COL = (W - GAP) / 2, LX = M, RX = M + COL + GAP;
const s = pres.addSlide();
s.background = { color: "FFFFFF" };
const text = (t, o) => { if (!(o.h > 0) || o.y + o.h > 46.81 - 1.2) throw new Error(`text box off the page: y=${o.y} h=${o.h}`); return s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 42, fontFace: FONT, lineSpacingMultiple: 1.15, ...o }); };
const section = (label, x, y, w) => {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 1.25, fill: { color: BLUE }, line: { color: BLUE } });
  text(label, { x: x + 0.35, y, w: w - 0.5, h: 1.25, valign: "middle", fontSize: 50, bold: true, color: "FFFFFF" });
  return y + 1.6;
};
const chart = () => ({ showTitle: false, catAxisLabelColor: SUB, valAxisLabelColor: SUB, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 32, valAxisLabelFontSize: 28, valGridLine: { color: GRID, size: 1.5 }, catGridLine: { style: "none" },
  legendFontFace: "+mn-lt", legendFontSize: 32, legendColor: INK, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 30, dataLabelColor: INK,
  showLegend: true, legendPos: "t", valAxisTitleFontFace: "+mn-lt", catAxisTitleFontFace: "+mn-lt" });
const caption = (t, x, y, w, h = 0.9, fs = 30) => text(t, { x, y, w, h, fontSize: fs, color: SUB });
const eqSize = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "eq", "sizes.json"), "utf8"));

require("./poster_layout_v5.js")({ FONT, LANG, VARIANT, s, pres, path, text, section, chart, caption, flowDiagram, M, W, COL, LX, RX,
  BLUE, BLUE_DARK, GREY, INK, SUB, GRID, LIMITS, SE, MAIN, OTHER, ET, CT, eqSize });

(async () => {
  const out = path.join(__dirname, process.env.POSTER_OUT || `midterm_poster_A0_rc42_${VARIANT}${LANG === "en" ? "_en" : ""}.pptx`);
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
