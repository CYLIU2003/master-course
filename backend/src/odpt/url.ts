import { ODPT_BASE } from "./config";

export function buildOdptProxyUrl(params: {
  resource: string;
  query: string;
  token: string;
  dump?: boolean;
}): string {
  const { resource, query, token, dump } = params;
  // dump=true → <resource>.json endpoint (full-dump side)
  const suffix = dump ? `${resource}.json` : resource;
  const sep = query?.length ? "&" : "";
  return `${ODPT_BASE}${suffix}?${query}${sep}acl:consumerKey=${encodeURIComponent(token)}`;
}
