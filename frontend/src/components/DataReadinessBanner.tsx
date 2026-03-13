import { useAppState } from "@/hooks/use-app-state";

export function DataReadinessBanner() {
  const { readiness, missingArtifacts, integrityError } = useAppState();

  if (readiness === "built-ready") return null;

  const messages: Record<string, string> = {
    "no-seed":
      "Seed data failed to load. Check data/seed/tokyu/ and restart the app.",
    "seed-only":
      "Built dataset not found. Run data-prep to generate timetable data before running optimization.",
    "integrity-error": `Built dataset integrity check failed: ${integrityError ?? "unknown error"}. Regenerate with data-prep.`,
    incomplete: `Some built artifacts are missing: ${(missingArtifacts || []).join(", ")}. Run data-prep to regenerate.`,
  };

  const message = messages[readiness] ?? "Data is not fully ready.";

  return (
    <div
      role="alert"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 100,
        background: "#b91c1c",
        color: "#fff",
        padding: "10px 16px",
        fontSize: "0.875rem",
        fontWeight: 500,
      }}
    >
      {`⚠ ${message}`}
    </div>
  );
}
