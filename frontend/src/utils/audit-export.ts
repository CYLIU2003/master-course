import { downloadCsvRows, downloadJsonFile } from "@/utils/download";

export type AuditExportEnvelope = {
  scenarioId: string;
  scenarioName?: string;
  auditType: string;
  datasetFingerprint?: string | null;
  snapshotId?: string | null;
  sourceType?: string | null;
  scope?: { depotId?: string | null; serviceId?: string | null } | null;
  highlights?: Record<string, unknown>;
  audit?: Record<string, unknown> | null;
};

export function exportAuditJson(filename: string, envelopes: AuditExportEnvelope[]): void {
  downloadJsonFile(filename, envelopes);
}

export function exportAuditCsv(filename: string, envelopes: AuditExportEnvelope[]): void {
  const rows = envelopes.map((item) => ({
    scenario_id: item.scenarioId,
    scenario_name: item.scenarioName ?? "",
    audit_type: item.auditType,
    dataset_fingerprint: item.datasetFingerprint ?? "",
    snapshot_id: item.snapshotId ?? "",
    source_type: item.sourceType ?? "",
    depot_id: item.scope?.depotId ?? item.audit?.depot_id ?? "",
    service_id: item.scope?.serviceId ?? item.audit?.service_id ?? "",
    case_type: item.audit?.case_type ?? "",
    highlights: JSON.stringify(item.highlights ?? {}),
    input_counts: JSON.stringify((item.audit?.input_counts as Record<string, unknown> | undefined) ?? {}),
    output_counts: JSON.stringify((item.audit?.output_counts as Record<string, unknown> | undefined) ?? {}),
    audit_json: JSON.stringify(item.audit ?? {}),
  }));
  downloadCsvRows(filename, rows);
}
