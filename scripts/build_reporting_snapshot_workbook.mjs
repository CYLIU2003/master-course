import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [payloadPath, outputPath, previewDir, verificationPath] = process.argv.slice(2);
if (!payloadPath || !outputPath || !previewDir || !verificationPath) {
  throw new Error(
    "usage: build_reporting_snapshot_workbook.mjs " +
      "PAYLOAD_JSON OUTPUT_XLSX PREVIEW_DIR VERIFICATION_JSON",
  );
}

const payload = JSON.parse(await fs.readFile(payloadPath, "utf8"));
const digest = String(payload.reporting_snapshot_sha256 || "");
if (!/^[0-9a-f]{64}$/.test(digest)) {
  throw new Error("reporting_snapshot_sha256 must be a lowercase SHA-256 digest");
}

const workbook = Workbook.create();
const sheetNames = [
  "Summary",
  "Vehicle Assignment",
  "Energy Balance",
  "Cost Breakdown",
  "Validation",
  "Hourly Energy",
  "Hourly SOC",
  "Provenance",
];
const sheets = Object.fromEntries(
  sheetNames.map((name) => [name, workbook.worksheets.add(name)]),
);

const COLORS = {
  navy: "#17324D",
  teal: "#2A9D8F",
  orange: "#E69F00",
  blue: "#4C78A8",
  gray: "#EEF2F5",
  darkGray: "#5F6B73",
  white: "#FFFFFF",
  green: "#E7F5EC",
  red: "#FDECEC",
};

function colName(index) {
  let n = index + 1;
  let result = "";
  while (n > 0) {
    const remainder = (n - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    n = Math.floor((n - 1) / 26);
  }
  return result;
}

function scalar(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

function compactScalar(value, maxLength = 150) {
  const normalized = scalar(value);
  if (typeof normalized !== "string" || normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 3)}...`;
}

function styleTitle(sheet, range, title) {
  sheet.mergeCells(range);
  const titleRange = sheet.getRange(range);
  titleRange.values = [[title]];
  titleRange.format = {
    fill: COLORS.navy,
    font: { bold: true, color: COLORS.white, size: 16 },
    verticalAlignment: "center",
  };
  titleRange.format.rowHeight = 30;
}

function formatHeader(range) {
  range.format = {
    fill: COLORS.navy,
    font: { bold: true, color: COLORS.white },
    wrapText: true,
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: "#B8C2CC" },
  };
  range.format.rowHeight = 28;
}

function chooseFormat(column) {
  const name = column.toLowerCase();
  if (name.includes("percent")) return "0.000%";
  if (name.endsWith("_count") || name === "step_index") return "#,##0";
  if (name.includes("_jpy") || name.includes("cost")) return "#,##0.00";
  if (name.includes("_kwh") || name.includes("_kw") || name.includes("_kg")) {
    return "#,##0.000";
  }
  if (name.includes("_km") || name.includes("_l")) return "#,##0.000";
  if (name.includes("ratio")) return "0.0000";
  return null;
}

function writeTableSheet({
  sheet,
  title,
  rows,
  columns,
  tableName,
  widths = {},
  freezeColumns = 1,
}) {
  sheet.showGridLines = false;
  styleTitle(sheet, `A1:${colName(Math.max(columns.length - 1, 0))}1`, title);
  sheet.mergeCells(`A2:${colName(Math.max(columns.length - 1, 0))}2`);
  sheet.getRange("A2").values = [[`Reporting snapshot SHA-256: ${digest}`]];
  sheet.getRange("A2").format = {
    fill: COLORS.gray,
    font: { color: COLORS.darkGray, name: "Consolas", size: 8 },
  };
  const matrix = [
    columns,
    ...rows.map((row) => columns.map((column) => scalar(row[column]))),
  ];
  const endRow = matrix.length + 2;
  const endCol = colName(columns.length - 1);
  const range = sheet.getRange(`A3:${endCol}${endRow}`);
  range.values = matrix;
  formatHeader(sheet.getRange(`A3:${endCol}3`));
  if (rows.length > 0) {
    const table = sheet.tables.add(`A3:${endCol}${endRow}`, true, tableName);
    table.style = "TableStyleMedium2";
  }
  for (let index = 0; index < columns.length; index += 1) {
    const column = columns[index];
    const letter = colName(index);
    const body = sheet.getRange(`${letter}4:${letter}${endRow}`);
    const numberFormat = chooseFormat(column);
    if (numberFormat) body.format.numberFormat = numberFormat;
    const defaultWidth = column === "case_label"
      ? 29
      : column.includes("path") || column.includes("source")
        ? 34
        : column === "trip_id"
          ? 52
          : column === "route_id"
            ? 29
            : column.includes("scheduled_")
              ? 23
              : column === "assigned_vehicle_id"
                ? 36
                : column === "assigned_vehicle_type"
                  ? 18
                  : column === "assigned_depot_id"
                    ? 18
        : column.includes("id")
          ? 24
          : chooseFormat(column)
            ? 18
            : 16;
    sheet.getRange(`${letter}:${letter}`).format.columnWidth =
      widths[column] || defaultWidth;
  }
  sheet.getRange(`A3:${endCol}${endRow}`).format.verticalAlignment = "top";
  sheet.freezePanes.freezeRows(3);
  if (freezeColumns > 0) sheet.freezePanes.freezeColumns(freezeColumns);
  return { endRow, endCol };
}

function selectedRows(rows, columns) {
  return rows.map((row) =>
    Object.fromEntries(columns.map((column) => [column, row[column] ?? null])),
  );
}

// Summary sheet: source values are visible; comparison differences are formulas.
{
  const sheet = sheets.Summary;
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:H1", "Controlled PV pair - Rolling execution report");
  sheet.getRange("A3:A7").values = [
    ["Release scope"],
    ["Progress presentation"],
    ["Research submission"],
    ["Snapshot SHA-256"],
    ["Cost basis"],
  ];
  for (let row = 3; row <= 7; row += 1) sheet.mergeCells(`B${row}:H${row}`);
  sheet.getRange("B3").values = [[payload.release_scope]];
  sheet.getRange("B4").values = [[payload.progress_presentation_ready ? "READY" : "BLOCKED"]];
  sheet.getRange("B5").values = [[payload.research_submission_ready ? "READY" : "NOT ASSESSED (presentation bundle)"]];
  sheet.getRange("B6").values = [[digest]];
  sheet.getRange("B7").values = [["Accepted 24-hour Rolling executed-day accounting"]];
  sheet.getRange("A3:A7").format = {
    fill: COLORS.gray,
    font: { bold: true, color: COLORS.navy },
  };
  sheet.getRange("B4").format = {
    fill: payload.progress_presentation_ready ? COLORS.green : COLORS.red,
    font: { bold: true, color: payload.progress_presentation_ready ? "#1B5E20" : "#B71C1C" },
  };
  sheet.getRange("B6").format.font = { name: "Consolas", size: 8 };

  const columns = [
    "case_label",
    "served_trip_count",
    "bev_trip_count",
    "ice_trip_count",
    "used_bev_count",
    "used_ice_count",
    "pv_generated_kwh",
    "grid_import_kwh",
    "accounting_total_cost_jpy",
    "total_co2_kg",
    "certified_gap_percent",
  ];
  const headers = [
    "Case",
    "Served trips",
    "BEV trips",
    "ICE trips",
    "Used BEVs",
    "Used ICEs",
    "PV generated (kWh)",
    "Grid import (kWh)",
    "Accounting total (JPY)",
    "CO2 (kg)",
    "Certified gap (%)",
  ];
  sheet.getRange("A10:K13").values = [
    headers,
    ...payload.summary_rows.map((row) => columns.map((column) => scalar(row[column]))),
    ["Low PV minus high PV", null, null, null, null, null, null, null, null, null, null],
  ];
  formatHeader(sheet.getRange("A10:K10"));
  sheet.getRange("B13:K13").formulas = [[
    "=B12-B11",
    "=C12-C11",
    "=D12-D11",
    "=E12-E11",
    "=F12-F11",
    "=G12-G11",
    "=H12-H11",
    "=I12-I11",
    "=J12-J11",
    "=K12-K11",
  ]];
  sheet.getRange("A13:K13").format = {
    fill: COLORS.gray,
    font: { bold: true, color: COLORS.navy },
    borders: { preset: "doubleBottom", style: "thin", color: COLORS.navy },
  };
  sheet.getRange("B11:F13").format.numberFormat = "#,##0";
  sheet.getRange("G11:H13").format.numberFormat = "#,##0.000";
  sheet.getRange("I11:I13").format.numberFormat = "#,##0.00";
  sheet.getRange("J11:K13").format.numberFormat = "#,##0.000";

  sheet.mergeCells("A16:E16");
  sheet.getRange("A16").values = [["Day-ahead solver quality"]];
  sheet.getRange("A16:E16").format = {
    fill: COLORS.gray,
    font: { bold: true, color: COLORS.navy },
  };
  sheet.getRange("A17:E19").values = [
    ["Case", "Raw status", "Presentation label", "Raw gap (%)", "Certified gap (%)"],
    ...payload.summary_rows.map((row) => [
      row.case_label,
      row.raw_solver_status,
      row.solution_quality_label,
      row.gurobi_raw_gap_percent,
      row.certified_gap_percent,
    ]),
  ];
  formatHeader(sheet.getRange("A17:E17"));
  sheet.getRange("D18:E19").format.numberFormat = "#,##0.000";
  sheet.getRange("A:A").format.columnWidth = 29;
  sheet.getRange("B:B").format.columnWidth = 18;
  sheet.getRange("C:C").format.columnWidth = 28;
  sheet.getRange("D:F").format.columnWidth = 13;
  sheet.getRange("G:K").format.columnWidth = 18;
  sheet.getRange("M:M").format.columnWidth = 29;
  sheet.getRange("N:O").format.columnWidth = 14;

  sheet.getRange("M2:O4").values = [
    ["Case", "BEV", "ICE"],
    [payload.summary_rows[0].case_label, null, null],
    [payload.summary_rows[1].case_label, null, null],
  ];
  sheet.getRange("N3:O4").formulas = [
    ["=E11", "=F11"],
    ["=E12", "=F12"],
  ];
  const dispatchChart = sheet.charts.add("bar", sheet.getRange("M2:O4"));
  dispatchChart.title = "Used vehicle composition";
  dispatchChart.hasLegend = true;
  dispatchChart.yAxis = { numberFormatCode: "0" };
  dispatchChart.setPosition("M6", "T20");

  sheet.getRange("M22:O24").values = [
    ["Case", "Electricity", "Fuel"],
    [payload.summary_rows[0].case_label, null, null],
    [payload.summary_rows[1].case_label, null, null],
  ];
  sheet.getRange("N23:O24").formulas = [
    ["='Cost Breakdown'!C4", "='Cost Breakdown'!E4"],
    ["='Cost Breakdown'!C5", "='Cost Breakdown'!E5"],
  ];
  const costChart = sheet.charts.add("bar", sheet.getRange("M22:O24"));
  costChart.title = "Variable energy cost (JPY/day)";
  costChart.hasLegend = true;
  costChart.yAxis = { numberFormatCode: "#,##0" };
  costChart.setPosition("M26", "T40");
  sheet.freezePanes.freezeRows(1);
}

const assignmentColumns = [
  "case",
  "trip_id",
  "route_id",
  "route_family_code",
  "scheduled_departure",
  "scheduled_arrival",
  "assigned_vehicle_id",
  "assigned_vehicle_type",
  "assigned_depot_id",
  "served_flag",
  "distance_km",
  "energy_used_kwh",
  "fuel_used_l",
  "deadhead_before_km",
  "deadhead_after_km",
  "operator_id",
];
writeTableSheet({
  sheet: sheets["Vehicle Assignment"],
  title: `Final trip assignment (${payload.summary_rows
    .map((row) => row.served_trip_count)
    .join(" / ")} served trips)`,
  rows: selectedRows(payload.assignment_rows, assignmentColumns),
  columns: assignmentColumns,
  tableName: "VehicleAssignmentTable",
  freezeColumns: 3,
});

const energyColumns = [
  "case_label",
  "pv_generated_kwh",
  "pv_to_bus_kwh",
  "pv_to_bess_kwh",
  "pv_curtailed_kwh",
  "bess_to_bus_kwh",
  "grid_import_kwh",
  "grid_to_bus_kwh",
  "grid_to_bess_kwh",
  "peak_grid_kw",
  "pv_balance_residual_kwh",
  "grid_balance_residual_kwh",
];
const energyLayout = writeTableSheet({
  sheet: sheets["Energy Balance"],
  title: "Executed Rolling energy balance",
  rows: selectedRows(payload.energy_rows, energyColumns),
  columns: energyColumns,
  tableName: "EnergyBalanceTable",
});
sheets["Energy Balance"].getRange(`K4:L${energyLayout.endRow}`).format = {
  fill: COLORS.green,
  font: { color: "#1B5E20" },
};

const costColumns = [
  "case_label",
  "accounting_total_cost_jpy",
  "electricity_cost_jpy",
  "demand_cost_jpy",
  "fuel_cost_jpy",
  "vehicle_usage_cost_jpy",
  "co2_cost_jpy",
  "battery_degradation_cost_jpy",
  "contract_overage_cost_jpy",
  "accounting_component_sum_jpy",
  "accounting_residual_jpy",
  "vehicle_usage_cost_jpy_per_used_bus",
  "used_vehicle_day_count",
  "published_cost_basis",
  "internal_search_objective_excluded",
];
writeTableSheet({
  sheet: sheets["Cost Breakdown"],
  title: "Canonical executed-day cost (internal search objective excluded)",
  rows: selectedRows(payload.cost_rows, costColumns),
  columns: costColumns,
  tableName: "CostBreakdownTable",
  widths: {
    published_cost_basis: 44,
    internal_search_objective_excluded: 26,
  },
});

const validationColumns = [
  "scope",
  "gate",
  "status",
  "observed",
  "expected",
  "source",
];
const validationData = payload.validation_rows.map((row) => ({
  ...row,
  observed: compactScalar(row.observed, 90),
  expected: compactScalar(row.expected, 90),
}));
const validationLayout = writeTableSheet({
  sheet: sheets.Validation,
  title: "Release validation gates",
  rows: selectedRows(validationData, validationColumns),
  columns: validationColumns,
  tableName: "ValidationGateTable",
  widths: {
    scope: 12,
    gate: 48,
    status: 10,
    observed: 48,
    expected: 40,
    source: 52,
  },
  freezeColumns: 3,
});
sheets.Validation.getRange(`D4:F${validationLayout.endRow}`).format.wrapText = true;
sheets.Validation.getRange(`A4:F${validationLayout.endRow}`).format.rowHeight = 36;

const hourlyEnergyColumns = [
  "case",
  "step_index",
  "time",
  "pv_generated_kwh",
  "pv_to_bus_kwh",
  "pv_to_bess_kwh",
  "pv_curtailed_kwh",
  "bess_to_bus_kwh",
  "grid_to_bus_kwh",
  "grid_to_bess_kwh",
  "charging_kw_max",
  "grid_kw_max",
];
writeTableSheet({
  sheet: sheets["Hourly Energy"],
  title: "Hourly energy flows from accepted Rolling execution",
  rows: selectedRows(payload.hourly_rows, hourlyEnergyColumns),
  columns: hourlyEnergyColumns,
  tableName: "HourlyEnergyTable",
  freezeColumns: 4,
});

const hourlySocColumns = [
  "case",
  "step_index",
  "time",
  "bess_end_soc_kwh",
  "bev_soc_min_kwh",
  "bev_soc_mean_kwh",
];
writeTableSheet({
  sheet: sheets["Hourly SOC"],
  title: "Hourly BESS and BEV SOC evidence from accepted Rolling execution",
  rows: selectedRows(payload.hourly_rows, hourlySocColumns),
  columns: hourlySocColumns,
  tableName: "HourlySocTable",
  freezeColumns: 4,
});

const provenanceColumns = [
  "role",
  "path",
  "size_bytes",
  "sha256",
];
writeTableSheet({
  sheet: sheets.Provenance,
  title: "Canonical source lineage",
  rows: selectedRows(payload.provenance_rows, provenanceColumns),
  columns: provenanceColumns,
  tableName: "ProvenanceTable",
  widths: { role: 38, path: 58, sha256: 68 },
  freezeColumns: 2,
});

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const summaryInspection = await workbook.inspect({
  kind: "table",
  range: "Summary!A1:K20",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 12,
  maxChars: 5000,
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
    const message = String(record.message || "");
    const match = message.match(/Cell search matched (\d+) entries\./);
    if (record.kind === "notice" && match) {
      const matchCount = Number(match[1]);
      if (matchCount !== 0) {
        throw new Error(`Workbook formula error scan found ${matchCount} entries`);
      }
      return matchCount;
    }
  }
  throw new Error(
    "Workbook formula error scan did not return a recognized match-count notice",
  );
}

const formulaErrorCount = requireZeroFormulaErrors(formulaErrors.ndjson);

const previewRecords = [];
const previewRanges = {
  Summary: "A1:T40",
  "Vehicle Assignment": "A1:Q18",
  "Energy Balance": "A1:M6",
  "Cost Breakdown": "A1:P6",
  Validation: "A1:G20",
  "Hourly Energy": "A1:M18",
  "Hourly SOC": "A1:G18",
  Provenance: "A1:E18",
};
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
