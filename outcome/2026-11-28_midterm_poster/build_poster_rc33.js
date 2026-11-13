// Midterm (2026-11-28) A0 portrait poster (841 x 1189 mm), editable PowerPoint, rebuilt from rc20,
// 2026-11-07: the base case (900 kW, PV 1,000 kW) BEV-heavy vs ICE-heavy table replaces figs 2-3
// (rc29 d25cc724 winter pair, rc35 spring/summer; ../../output/midterm_20261128/rc23_eval/k900pair.md).
// 2026-11-08: winter pair replaced by rc33 7dc38d95 (g900/h900, rc23_eval/rc33_all.md); 90 kW winter pair and PV 0 from rc33.
// Data: ../2026-11-12_three_party/deck_data_rc20.json (prepare_deck_data.py, verified cases only, DIAGNOSTIC).
// Grid limits 90/200/400/600/900 kW (900 = all ten 90 kW chargers at once). 30 JPY/kWh is all-inclusive;
// the annual basic charge is a reference ("目安") only and is never added. Earlier versions:
// build_poster.js (rc8/rc9) and build_poster_rc18.js.
const path = require("path");
const fs = require("fs");
const pptxgen = require(path.join(process.env.DECK_NODE_MODULES, "pptxgenjs"));
const { applyTheme } = require(path.join(process.env.PPTX_SKILL, "scripts", "apply_theme.js"));
// 2026-11-10 (user request: images, graphs and tables): Figs. 2, 3 and 6 come from poster_figs.js.
const { systemDiagram, flowDiagram, hourlyFlow } = require("./poster_figs.js");

// 11/9: latest version (rc33/rc35) via ../2026-11-12_three_party/prepare_deck_data_latest.py; cheaper of the two
// start points per limit x season; diesel valued by the litres burnt (post-hoc, as in the deck).
const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "deck_data_latest.json"), "utf8"));
DATA.cases.forEach((r) => { if (r.status === "VERIFIED") {
  r.total_cost_accounting = r.total_cost; r.total_cost = r.total_cost_fuel_consumed; r.fuel_cost = r.ice_fuel_consumed_l * 150; } });
const cases = DATA.cases.filter((r) => r.status === "VERIFIED");
const iceHour = DATA.ice_by_hour;
const diesel = DATA.diesel;
const LIMITS = DATA.limits;
const SE = [["2025-01-06", "冬"], ["2025-04-07", "春"], ["2025-07-07", "夏"]];
const get = (g, w) => cases.find((r) => r.grid_limit_kw === g && r.week === w);
const avg = (g, k) => { const rs = cases.filter((r) => r.grid_limit_kw === g); return rs.reduce((a, r) => a + r[k], 0) / Math.max(rs.length, 1); };
const val = (g, w, k, f = (v) => v) => (get(g, w) ? f(get(g, w)[k]) : null);
const opex = (g) => (avg(g, "electricity_cost") + avg(g, "fuel_cost") + avg(g, "contract_overage_cost")) / 1e4;
// Reference only: annual basic charge if the contract power were max(limit, annual peak) (TEPCO EP, 2026-04, high voltage).
const BASIC_YEN_PER_KW = 2530;
const peakYear = (g) => Math.max(...cases.filter((r) => r.grid_limit_kw === g).map((r) => r.peak_grid_kw));
const basicYear = (g) => Math.max(g, peakYear(g)) * BASIC_YEN_PER_KW * 0.85 * 12;

const BLUE = "0485D7", BLUE_DARK = "0268B0", GREY = "9A9A9A", INK = "222222", SUB = "555555", GRID = "DDDDDD";
const THEME = { name: "TCU white", headFontFace: "Yu Gothic", bodyFontFace: "Yu Gothic",
  colors: { dk1: INK, lt1: "FFFFFF", dk2: BLUE_DARK, lt2: "F4F7FA", accent1: BLUE, accent2: GREY,
            accent3: "5B9BD5", accent4: "A5A5A5", accent5: "264478", accent6: "636363", hlink: BLUE, folHlink: BLUE_DARK } };

const pres = new pptxgen();
pres.defineLayout({ name: "A0_PORTRAIT", width: 33.11, height: 46.81 });
pres.layout = "A0_PORTRAIT";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "中間発表ポスター 2026-11-28";
const M = 1.6, W = 33.11 - 2 * M, GAP = 0.9, COL = (W - GAP) / 2, LX = M, RX = M + COL + GAP;
const s = pres.addSlide();
s.background = { color: "FFFFFF" };
const text = (t, o) => { if (!(o.h > 0) || o.y + o.h > 46.81 - 1.2) throw new Error(`text box off the page: y=${o.y} h=${o.h}`); return s.addText(t, { isTextBox: true, margin: 0, valign: "top", color: INK, fontSize: 42, fontFace: "Yu Gothic", lineSpacingMultiple: 1.15, ...o }); };
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

// Latest-version helpers (cheaper of the two start points per limit x season).
const SEASON_OF = Object.fromEntries(SE);
const lab = (r) => `${r.grid_limit_kw} kW${SEASON_OF[r.week]}`;
const iceWins = cases.filter((r) => r.selected_start === "ice"), bevWins = cases.filter((r) => r.selected_start === "bev");
const rngTxt = (a, d = 0) => !a.length ? "—" : Math.min(...a).toFixed(d) === Math.max(...a).toFixed(d) ? Math.min(...a).toFixed(d) : `${Math.min(...a).toFixed(d)}〜${Math.max(...a).toFixed(d)}`;
// 2026-11-09: 90 kW spring has no running job; its ICE-heavy run (rc35 a090s10) FAILED, so it is not "計算中".
// 400 kW summer: the BEV-heavy run (rc35 a400s10) FAILED; only the ICE-heavy start finished.
const STOPPED = new Map([["900/2025-07-07", "電気バス寄り（4回とも毎時の立て直しで停止）"]]);
const notDone = DATA.cases.filter((r) => r.status !== "VERIFIED");
const pend = notDone.filter((r) => !STOPPED.has(`${r.grid_limit_kw}/${r.week}`)).map((r) => `${r.grid_limit_kw} kW${SEASON_OF[r.week]}`);
const stopped = notDone.filter((r) => STOPPED.has(`${r.grid_limit_kw}/${r.week}`)).map((r) => `${r.grid_limit_kw} kW${SEASON_OF[r.week]}は${STOPPED.get(`${r.grid_limit_kw}/${r.week}`)}`);
const pairOf = (g, w, st) => DATA.pairs.find((x) => x.grid_limit_kw === g && x.week === w && x.start === st && x.status === "VERIFIED");
const pb90 = pairOf(90, "2025-01-06", "bev"), pi90 = pairOf(90, "2025-01-06", "ice");
const tcc = (r) => r.total_cost_fuel_consumed;
const shares = cases.map((r) => r.bev_trip_share_pct);
const shareRange = `${Math.min(...shares).toFixed(1)}〜${Math.max(...shares).toFixed(1)}%`;
const co2Cut = SE.filter(([w]) => get(900, w)).map(([w]) => 1 - get(900, w).total_co2_kg / Number(diesel.find((d) => d.week === w).co2_kg));
const maxTimeouts = Math.max(...DATA.rolling.map((r) => r.time_limit));
const bevGridPerKm = 1.316 * 30, icePerKm = 150 / 4.52, bevOverPerKm = 1.316 * 530;
const cutRange = `${Math.round(Math.min(...co2Cut) * 100)}〜${Math.round(Math.max(...co2Cut) * 100)}%`;
const w90 = get(90, "2025-01-06");
const man = (v) => (v / 1e4).toFixed(1);
const fmt = (v) => Math.round(v).toLocaleString("ja-JP");
const K9 = {
  wb: { cost: 4189120, share: 92.6, co2: 2470, pvUse: 19867, pvCut: 4709, over: 0 },
  wi: { cost: 4387150, share: 37.6, co2: 5949, pvUse: 14258, pvCut: 10318, over: 0 },
  sb: { cost: 4157225, share: 93.5, co2: 1945, pvUse: 22127, pvCut: 5692, over: 0 },
  // 2026-11-10: summer BEV-heavy is rerunning as rc36 a900u. The earlier rc35 a900s10f numbers were removed:
  // that launch carried no seed and default time limits, so it was not the same case as the other columns.
  // 2026-11-12: rc39 f900g (0e95d3b2, desktop-gsfgtj2; rc23-style evaluation by evaluate_multiface.py). 174/174 hourly
  // re-plans accepted, 0 time limits, physical validation VALID. Repeat f900p: 412.9, 95.6%, 1,476 kg.
  ub: { cost: 4129322, share: 96.1, bev: 32, ice: 7, co2: 1478, grid: 2329, pvUse: 24994, pvCut: 5195, over: 0, peak: 790 } };

// ---- 2026-11-13: layout after the advisor's comments of 11/12 (order, bar charts, objective, parameter table,
// "initial assignment" wording, outlook and road to the final). The previous layout is in git history (6e042411).
const eqSize = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "2026-11-12_three_party", "eq", "sizes.json"), "utf8"));
const VER = { "7dc38d95": "rc33", "9a0fe044": "rc35", "375dd6f2": "rc36", "0e95d3b2": "rc39" };
const versions = [...new Set(DATA.pairs.filter((r) => r.status === "VERIFIED").map((r) => VER[r.version] || r.version))].sort().join("・");
require("./poster_layout_v2_ja.js")({ s, pres, path, text, section, chart, caption, flowDiagram, M, W, COL, LX, RX, BLUE, BLUE_DARK, GREY, INK, SUB, GRID,
  cases, LIMITS, SE, SEASON_OF, lab, val, pairOf, iceWins, bevWins, rngTxt, man, fmt, pb90, pi90, eqSize, maxTimeouts, versions });

(async () => {
  const out = path.join(__dirname, process.env.POSTER_OUT || "midterm_poster_A0_rc33.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
