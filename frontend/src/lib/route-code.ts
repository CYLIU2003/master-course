export function normalizeRouteCode(value?: string | null): string {
  if (!value) {
    return "";
  }
  return value
    .normalize("NFKC")
    .replace(/\s+/g, "")
    .trim();
}

type ParsedRouteCode = {
  prefix: string;
  number: number | null;
  suffix: string;
  normalized: string;
};

const jpLeadingPattern = /^([\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+)\s*(\d+)?/u;

function parseRouteCode(value?: string | null): ParsedRouteCode {
  const normalized = normalizeRouteCode(value);
  const jp = normalized.match(jpLeadingPattern);
  if (jp) {
    return {
      prefix: jp[1] ?? "",
      number: jp[2] ? Number(jp[2]) : null,
      suffix: normalized.slice(jp[0].length),
      normalized,
    };
  }
  const match = normalized.match(/^([^\d]*?)(\d+)?([^\d]*)$/u);
  if (!match) {
    return {
      prefix: normalized,
      number: null,
      suffix: "",
      normalized,
    };
  }

  return {
    prefix: match[1] ?? "",
    number: match[2] ? Number(match[2]) : null,
    suffix: match[3] ?? "",
    normalized,
  };
}

export function compareRouteCodeLike(
  left?: string | null,
  right?: string | null,
): number {
  const a = parseRouteCode(left);
  const b = parseRouteCode(right);

  const prefixCmp = a.prefix.localeCompare(b.prefix, "ja");
  if (prefixCmp !== 0) {
    return prefixCmp;
  }

  if (a.number !== null && b.number !== null && a.number !== b.number) {
    return a.number - b.number;
  }
  if (a.number !== null && b.number === null) {
    return -1;
  }
  if (a.number === null && b.number !== null) {
    return 1;
  }

  const suffixCmp = a.suffix.localeCompare(b.suffix, "ja");
  if (suffixCmp !== 0) {
    return suffixCmp;
  }

  return a.normalized.localeCompare(b.normalized, "ja");
}

export function extractRouteSeries(value?: string | null): {
  seriesCode: string;
  seriesPrefix: string;
  seriesNumber: number | null;
} {
  const parsed = parseRouteCode(value);
  return {
    seriesCode: parsed.number === null ? parsed.prefix : `${parsed.prefix}${parsed.number.toString().padStart(2, "0")}`,
    seriesPrefix: parsed.prefix,
    seriesNumber: parsed.number,
  };
}
