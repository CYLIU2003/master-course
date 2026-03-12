function escapeCsvValue(value: unknown): string {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function downloadTextFile(filename: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function downloadJsonFile(filename: string, value: unknown): void {
  downloadTextFile(
    filename,
    JSON.stringify(value, null, 2),
    "application/json;charset=utf-8;",
  );
}

export function downloadCsvRows(
  filename: string,
  rows: Array<Record<string, unknown>>,
): void {
  if (rows.length === 0) {
    downloadTextFile(filename, "", "text/csv;charset=utf-8;");
    return;
  }

  const headers = Array.from(
    rows.reduce((set, row) => {
      for (const key of Object.keys(row)) set.add(key);
      return set;
    }, new Set<string>()),
  );

  const lines = [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => escapeCsvValue(row[header])).join(",")),
  ];
  downloadTextFile(filename, lines.join("\n"), "text/csv;charset=utf-8;");
}
