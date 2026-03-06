"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildOdptProxyUrl = buildOdptProxyUrl;
const config_1 = require("./config");
function buildOdptProxyUrl(params) {
    const { resource, query, token, dump } = params;
    // dump=true → <resource>.json endpoint (full-dump side)
    const suffix = dump ? `${resource}.json` : resource;
    const sep = query?.length ? "&" : "";
    return `${config_1.ODPT_BASE}${suffix}?${query}${sep}acl:consumerKey=${encodeURIComponent(token)}`;
}
