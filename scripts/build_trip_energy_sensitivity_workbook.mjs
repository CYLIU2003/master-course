import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [payloadPath, outputPath, previewDir, verificationPath] = process.argv.slice(2);
if (!payloadPath || !outputPath || !previewDir || !verificationPath) {
  throw new Error(
    "usage: build_trip_energy_sensitivity_workbook.mjs " +
      "PAYLOAD_JSON OUTPUT_XLSX PREVIEW_DIR VERIFICATION_JSON",
  );
}

const payload = JSON.parse(await fs.readFile(payloadPath, "utf8"));
const digest = String(payload.payload_sha256 || "");
if (!/^[0-9a-f]{64}$/.test(digest)) {
  throw new Error("payload_sha256 must be a lowercase SHA-256 digest");
}
if (!Array.isArray(payload.rows) || payload.rows.length !== 5) {
  throw new Error("exactly five trip-energy sensitivity rows are required");
}

const workbook = Workbook.create();
const sheetNames = [
  "Summary",
  "Executed KPIs",
  "Energy Flows",
  "Solver Evidence",
  "Provenance",
];
const sheets = Object.fromEntries(
  sheetNames.map((name) => [name, workbook.worksheets.add(name)]),
);

const COLORS = {
  navy: "#17324D",
  blue: "#2F6B9A",
  orange: "#D9822B",
  teal: "#2A9D8F",
  gold: "#D6A72C",
  gray: "#EEF2F5",
  darkGray: "#5F6B73",
  white: "#FFFFFF",
  green: "#E7F5EC",
  red: "#FDECEC",
};

function styleTitle(sheet, range, title) {
  sheet.mergeCells(range);
  const target = sheet.getRange(range);
  target.values = [[title]];
  target.format = {
    fill: COLORS.navy,
    font: { bold: true, color: COLORS.white, size: 16 },
    verticalAlignment: "center",
  };
  target.format.rowHeight = 30;
}

function formatHeader(range) {
  range.format = {
    fill: COLORS.navy,
    font: { bold: true, color: COLORS.white },
    wrapText: true,
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: "#B8C2CC" },
  };
  range.format.rowHeight = 30;
}

function setWidths(sheet, widths) {
  for (const [column, width] of Object.entries(widths)) {
    sheet.getRange(`${column}:${column}`).format.columnWidth = width;
  }
}

function styleSourceHash(sheet, range) {
  sheet.mergeCells(range);
  const target = sheet.getRange(range.split(":")[0]);
  target.values = [[`Reporting snapshot SHA-256: ${digest}`]];
  target.format = {
    fill: COLORS.gray,
    font: { color: COLORS.darkGray, name: "Consolas", size: 8 },
  };
}

// Source rows are ordered by scale, so scale 1.0 is the third data row.
const sourceRows = [...payload.rows].sort(
  (left, right) => Number(left.trip_energy_scale) - Number(right.trip_energy_scale),
);

{
  const sheet = sheets["Executed KPIs"];
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:U1", "Executed Rolling KPIs and formula-driven deltas");
  styleSourceHash(sheet, "A2:U2");
  const headers = [
    "Case ID",
    "Demand scale",
    "Served trips",
    "Unserved trips",
    "Used BEVs",
    "Used ICEs",
    "BEV trips",
    "ICE trips",
    "Total cost (JPY)",
    "Delta vs 1.0 (JPY)",
    "Delta vs 1.0 (%)",
    "CO2 (kg)",
    "CO2 delta (kg)",
    "Grid import (kWh)",
    "Grid delta (kWh)",
    "Min executed SOC (%)",
    "SOC margin (pp)",
    "Min SOC time",
    "Certified gap (%)",
    "Solve time (s)",
    "Wall time (s)",
  ];
  const raw = sourceRows.map((row) => [
    row.case_id,
    row.trip_energy_scale,
    row.trip_count_served,
    row.trip_count_unserved,
    row.used_bev_count,
    row.used_ice_count,
    row.bev_trip_count,
    row.ice_trip_count,
    row.total_cost_jpy,
    null,
    null,
    row.total_co2_kg,
    null,
    row.grid_import_kwh,
    null,
    row.rolling_min_bev_soc_percent,
    row.rolling_min_bev_soc_margin_percent,
    row.rolling_min_bev_soc_time,
    row.certified_mip_gap_percent,
    row.solve_time_seconds,
    row.wall_time_seconds,
  ]);
  sheet.getRange("A3:U8").values = [headers, ...raw];
  formatHeader(sheet.getRange("A3:U3"));
  for (let row = 4; row <= 8; row += 1) {
    sheet.getRange(`J${row}`).formulas = [[`=I${row}-$I$6`]];
    sheet.getRange(`K${row}`).formulas = [[`=IF($I$6=0,0,J${row}/$I$6)`]];
    sheet.getRange(`M${row}`).formulas = [[`=L${row}-$L$6`]];
    sheet.getRange(`O${row}`).formulas = [[`=N${row}-$N$6`]];
  }
  const table = sheet.tables.add("A3:U8", true, "ExecutedKpisTable");
  table.style = "TableStyleMedium2";
  sheet.getRange("B4:B8").format.numberFormat = "0.0";
  sheet.getRange("C4:H8").format.numberFormat = "#,##0";
  sheet.getRange("I4:J8").format.numberFormat = "#,##0.00";
  sheet.getRange("K4:K8").format.numberFormat = "0.000%";
  sheet.getRange("L4:Q8").format.numberFormat = "#,##0.000";
  sheet.getRange("S4:U8").format.numberFormat = "#,##0.000";
  setWidths(sheet, {
    A: 16,
    B: 13,
    C: 13,
    D: 13,
    E: 11,
    F: 11,
    G: 11,
    H: 11,
    I: 18,
    J: 18,
    K: 16,
    L: 14,
    M: 15,
    N: 17,
    O: 16,
    P: 20,
    Q: 15,
    R: 14,
    S: 17,
    T: 16,
    U: 16,
  });
  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(2);
}

{
  const sheet = sheets["Energy Flows"];
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:F1", "Accepted Rolling energy flows");
  styleSourceHash(sheet, "A2:F2");
  const headers = [
    "Demand scale",
    "PV generated (kWh)",
    "PV to bus (kWh)",
    "PV to BESS (kWh)",
    "BESS to bus (kWh)",
    "Grid import (kWh)",
  ];
  sheet.getRange("A3:F8").values = [
    headers,
    ...sourceRows.map((row) => [
      row.trip_energy_scale,
      row.pv_generated_kwh,
      row.pv_to_bus_kwh,
      row.pv_to_bess_kwh,
      row.bess_to_bus_kwh,
      row.grid_import_kwh,
    ]),
  ];
  formatHeader(sheet.getRange("A3:F3"));
  const table = sheet.tables.add("A3:F8", true, "EnergyFlowsTable");
  table.style = "TableStyleMedium2";
  sheet.getRange("A4:A8").format.numberFormat = "0.0";
  sheet.getRange("B4:F8").format.numberFormat = "#,##0.000";
  setWidths(sheet, { A: 14, B: 20, C: 18, D: 19, E: 19, F: 19 });
  const chart = sheet.charts.add("line", sheet.getRange("A3:F8"));
  chart.title = "Rolling energy flows by demand scale";
  chart.hasLegend = true;
  chart.xAxis = { axisType: "textAxis" };
  chart.yAxis = { numberFormatCode: "#,##0", min: 0 };
  chart.setPosition("A11", "J28");
  sheet.freezePanes.freezeRows(3);
}

{
  const sheet = sheets["Solver Evidence"];
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:J1", "Solver, physical, and executed-SOC evidence");
  styleSourceHash(sheet, "A2:J2");
  const headers = [
    "Demand scale",
    "Solver status",
    "Certified gap (%)",
    "Gap target met",
    "Solve time (s)",
    "Wall time (s)",
    "Min executed SOC (%)",
    "SOC margin (pp)",
    "Min SOC time",
    "Min SOC vehicle ID",
  ];
  sheet.getRange("A3:J8").values = [
    headers,
    ...sourceRows.map((row) => [
      row.trip_energy_scale,
      row.solver_status,
      row.certified_mip_gap_percent,
      row.mip_gap_target_met,
      row.solve_time_seconds,
      row.wall_time_seconds,
      row.rolling_min_bev_soc_percent,
      row.rolling_min_bev_soc_margin_percent,
      row.rolling_min_bev_soc_time,
      row.rolling_min_bev_soc_vehicle_id,
    ]),
  ];
  formatHeader(sheet.getRange("A3:J3"));
  const table = sheet.tables.add("A3:J8", true, "SolverEvidenceTable");
  table.style = "TableStyleMedium2";
  sheet.getRange("A4:A8").format.numberFormat = "0.0";
  sheet.getRange("C4:C8").format.numberFormat = "0.000";
  sheet.getRange("E4:H8").format.numberFormat = "#,##0.000";
  setWidths(sheet, {
    A: 14,
    B: 16,
    C: 18,
    D: 16,
    E: 16,
    F: 16,
    G: 20,
    H: 16,
    I: 14,
    J: 39,
  });
  sheet.getRange("D4:D8").format = {
    fill: COLORS.red,
    font: { bold: true, color: "#B71C1C" },
  };
  sheet.freezePanes.freezeRows(3);
}

{
  const sheet = sheets.Provenance;
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:C1", "Source lineage and claim boundary");
  styleSourceHash(sheet, "A2:C2");
  const baseRows = [
    ["status", payload.status, "Gap-limited reporting label"],
    ["claim_scope", payload.claim_scope, "Permitted interpretation"],
    ["source_run_git_sha", payload.source_run_git_sha, "Frozen solve source"],
    [
      "source_audit_builder_git_sha",
      payload.source_audit_builder_git_sha,
      "Clean re-audit implementation",
    ],
    [
      "source_execution_payload_sha256",
      payload.source_execution_payload_sha256,
      "Signed re-audit manifest payload",
    ],
    [
      "stable_control_fingerprint",
      payload.stable_control_fingerprint,
      "All five non-varied controls",
    ],
    [
      "prepared_trip_input_sha256",
      payload.prepared_trip_input_sha256,
      "Common immutable 264-trip input",
    ],
  ];
  for (const row of sourceRows) {
    baseRows.push([
      `${row.case_id}:prepared_input_id`,
      row.prepared_input_id,
      "Fresh Prepare identity",
    ]);
    baseRows.push([
      `${row.case_id}:job_id`,
      row.job_id,
      "Frontend/BFF optimization job",
    ]);
    baseRows.push([
      `${row.case_id}:rolling_soc_bundle_sha256`,
      row.rolling_soc_source_bundle_sha256,
      "Hash bundle for executed SOC evidence",
    ]);
  }
  sheet.getRange(`A3:C${baseRows.length + 3}`).values = [
    ["Field", "Value", "Meaning"],
    ...baseRows,
  ];
  formatHeader(sheet.getRange("A3:C3"));
  const table = sheet.tables.add(
    `A3:C${baseRows.length + 3}`,
    true,
    "ProvenanceTable",
  );
  table.style = "TableStyleMedium2";
  sheet.getRange(`A4:C${baseRows.length + 3}`).format.verticalAlignment = "top";
  sheet.getRange(`B4:B${baseRows.length + 3}`).format.wrapText = true;
  setWidths(sheet, { A: 40, B: 82, C: 38 });
  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(1);
}

{
  const sheet = sheets.Summary;
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:H1", "Trip-energy demand sensitivity - progress evidence");
  const eligible = payload.research_conclusion_eligible === true;
  sheet.getRange("A3:A8").values = [
    ["Evidence status"],
    ["Research conclusion"],
    ["Transition boundary"],
    ["Source solve SHA"],
    ["Re-audit SHA"],
    ["Snapshot SHA-256"],
  ];
  for (let row = 3; row <= 8; row += 1) sheet.mergeCells(`B${row}:H${row}`);
  sheet.getRange("B3").values = [[payload.status]];
  sheet.getRange("B4").values = [[eligible ? "ELIGIBLE" : "NOT ELIGIBLE"]];
  sheet.getRange("B5").values = [[
    payload.transition_boundary_certified ? "CERTIFIED" : "NOT CERTIFIED",
  ]];
  sheet.getRange("B6").values = [[payload.source_run_git_sha]];
  sheet.getRange("B7").values = [[payload.source_audit_builder_git_sha]];
  sheet.getRange("B8").values = [[digest]];
  sheet.getRange("A3:A8").format = {
    fill: COLORS.gray,
    font: { bold: true, color: COLORS.navy },
  };
  sheet.getRange("B3:B5").format = {
    fill: eligible ? COLORS.green : COLORS.red,
    font: { bold: true, color: eligible ? "#1B5E20" : "#B71C1C" },
  };
  sheet.getRange("B6:B8").format.font = { name: "Consolas", size: 8 };

  sheet.getRange("A10:H15").values = [
    [
      "Demand scale",
      "BEV trips",
      "ICE trips",
      "Used BEVs",
      "Used ICEs",
      "Cost (JPY)",
      "CO2 (kg)",
      "Min SOC (%)",
    ],
    ...sourceRows.map(() => [null, null, null, null, null, null, null, null]),
  ];
  formatHeader(sheet.getRange("A10:H10"));
  for (let index = 0; index < sourceRows.length; index += 1) {
    const summaryRow = 11 + index;
    const sourceRow = 4 + index;
    sheet.getRange(`A${summaryRow}:H${summaryRow}`).formulas = [[
      `='Executed KPIs'!B${sourceRow}`,
      `='Executed KPIs'!G${sourceRow}`,
      `='Executed KPIs'!H${sourceRow}`,
      `='Executed KPIs'!E${sourceRow}`,
      `='Executed KPIs'!F${sourceRow}`,
      `='Executed KPIs'!I${sourceRow}`,
      `='Executed KPIs'!L${sourceRow}`,
      `='Executed KPIs'!P${sourceRow}`,
    ]];
  }
  sheet.getRange("A11:A15").format.numberFormat = "0.0";
  sheet.getRange("B11:E15").format.numberFormat = "#,##0";
  sheet.getRange("F11:F15").format.numberFormat = "#,##0.00";
  sheet.getRange("G11:H15").format.numberFormat = "#,##0.000";
  setWidths(sheet, { A: 24, B: 12, C: 12, D: 12, E: 12, F: 18, G: 14, H: 15 });

  const dispatchChart = sheet.charts.add("line", sheet.getRange("A10:C15"));
  dispatchChart.title = "Observed BEV/ICE trip response";
  dispatchChart.hasLegend = true;
  dispatchChart.xAxis = { axisType: "textAxis" };
  dispatchChart.yAxis = { numberFormatCode: "#,##0", min: 0, max: 264 };
  dispatchChart.setPosition("J2", "Q15");
  sheet.getRange("S10:T15").values = [
    ["Demand scale", "Executed cost (JPY)"],
    ...sourceRows.map(() => [null, null]),
  ];
  for (let index = 0; index < sourceRows.length; index += 1) {
    const row = 11 + index;
    sheet.getRange(`S${row}:T${row}`).formulas = [[
      `=A${row}`,
      `=F${row}`,
    ]];
  }
  const costChart = sheet.charts.add("line", sheet.getRange("S10:T15"));
  costChart.title = "Executed cost rises with demand";
  costChart.hasLegend = false;
  costChart.xAxis = { axisType: "textAxis" };
  costChart.yAxis = { numberFormatCode: "#,##0", min: 0 };
  costChart.setPosition("J17", "Q30");

  sheet.mergeCells("A18:H20");
  sheet.getRange("A18").values = [[payload.claim_scope]];
  sheet.getRange("A18:H20").format = {
    fill: COLORS.gray,
    font: { color: COLORS.darkGray, italic: true },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.freezePanes.freezeRows(1);
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const summaryInspection = await workbook.inspect({
  kind: "table",
  range: "Summary!A1:H20",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 10,
  maxChars: 6000,
});
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
  maxChars: 5000,
});

function requireZeroFormulaErrors(ndjson) {
  const lines = String(ndjson || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  for (const line of lines) {
    let record;
    try {
      record = JSON.parse(line);
    } catch {
      continue;
    }
    const match = String(record.message || "").match(
      /Cell search matched (\d+) entries\./,
    );
    if (record.kind === "notice" && match) {
      const count = Number(match[1]);
      if (count !== 0) {
        throw new Error(`Workbook formula error scan found ${count} entries`);
      }
      return count;
    }
  }
  throw new Error("Workbook formula error scan returned no match-count notice");
}

const formulaErrorCount = requireZeroFormulaErrors(formulaErrors.ndjson);
const previewRanges = {
  Summary: "A1:Q30",
  "Executed KPIs": "A1:U8",
  "Energy Flows": "A1:J28",
  "Solver Evidence": "A1:J8",
  Provenance: "A1:C26",
};
const previewRecords = [];
for (let index = 0; index < sheetNames.length; index += 1) {
  const sheetName = sheetNames[index];
  const preview = await workbook.render({
    sheetName,
    range: previewRanges[sheetName],
    scale: 1,
    format: "png",
  });
  const safeName = sheetName.toLowerCase().replaceAll(" ", "_");
  const previewPath = path.join(
    previewDir,
    `${String(index + 1).padStart(2, "0")}_${safeName}.png`,
  );
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  previewRecords.push({ sheet: sheetName, path: previewPath });
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.writeFile(
  verificationPath,
  JSON.stringify(
    {
      status: "OK",
      reporting_snapshot_sha256: digest,
      sheet_count: sheetNames.length,
      sheet_names: sheetNames,
      preview_count: previewRecords.length,
      previews: previewRecords,
      summary_inspection: summaryInspection.ndjson,
      formula_error_scan: formulaErrors.ndjson,
      formula_error_count: formulaErrorCount,
    },
    null,
    2,
  ) + "\n",
  "utf8",
);
