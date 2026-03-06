import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchJson } from "@/api/client";

/**
 * ODPT Explorer Page
 *
 * Communicates with the Node/TS BFF at :3001 (proxied via Vite as /api/odpt/*):
 *   GET  /api/odpt/proxy?resource=...&query=...&dump=0|1&forceRefresh=0|1&ttlSec=...
 *   POST /api/odpt/introspect   { records: [...] }
 *   POST /api/odpt/export/normalized
 *   POST /api/odpt/export/operational
 *   POST /api/odpt/export/save
 */

// ── Types ─────────────────────────────────────────────────────────────────────

type ProxyMeta = {
  url: string;
  count: number;
  maybeTruncated: boolean;
  dump: boolean;
  cacheHit: boolean;
  cacheKey: string;
};

type ProxyResponse = {
  meta: ProxyMeta;
  data: unknown[];
};

type FieldStat = {
  path: string;
  types: Record<string, number>;
  present: number;
  presentRate: number;
};

type IntrospectResponse = {
  sampleCount: number;
  fields: FieldStat[];
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function prettyJson(x: unknown): string {
  try {
    return JSON.stringify(x, null, 2);
  } catch {
    return String(x);
  }
}

function typesSummary(types: Record<string, number>): string {
  return Object.entries(types)
    .sort((a, b) => b[1] - a[1])
    .map(([t, n]) => `${t}:${n}`)
    .join(", ");
}

const RESOURCE_OPTIONS = [
  "odpt:BusroutePattern",
  "odpt:BusstopPole",
  "odpt:BusTimetable",
  "odpt:BusstopPoleTimetable",
] as const;

// ── Component ─────────────────────────────────────────────────────────────────

export function OdptExplorerPage() {
  const [resource, setResource] = useState<string>(RESOURCE_OPTIONS[0]);
  const [dump, setDump] = useState(false);
  const [query, setQuery] = useState("odpt:operator=odpt.Operator:TokyuBus");
  const [forceRefresh, setForceRefresh] = useState(false);
  const [ttlSec, setTtlSec] = useState(3600);
  const [includeStopTimetables, setIncludeStopTimetables] = useState(false);

  const [loading, setLoading] = useState(false);
  const [proxyRes, setProxyRes] = useState<ProxyResponse | null>(null);

  const [introspecting, setIntrospecting] = useState(false);
  const [introRes, setIntroRes] = useState<IntrospectResponse | null>(null);

  const [exporting, setExporting] = useState(false);
  const [exportRes, setExportRes] = useState<unknown | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveRes, setSaveRes] = useState<{
    savedTo: string;
    normalizedSavedTo?: string;
    meta: unknown;
  } | null>(null);

  const [error, setError] = useState<string | null>(null);

  // Reset downstream state when controls change
  useEffect(() => {
    setIntroRes(null);
    setExportRes(null);
    setSaveRes(null);
    setError(null);
  }, [resource, dump, query, forceRefresh, ttlSec, includeStopTimetables]);

  function buildExportPayload() {
    return {
      dump,
      forceRefresh,
      ttlSec,
      includeStopTimetables,
    };
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  async function runProxy() {
    setLoading(true);
    setError(null);
    setProxyRes(null);
    setIntroRes(null);
    try {
      const params = new URLSearchParams();
      params.set("resource", resource);
      params.set("query", query.trim());
      params.set("dump", dump ? "1" : "0");
      params.set("forceRefresh", forceRefresh ? "1" : "0");
      params.set("ttlSec", String(ttlSec));
      const body = await fetchJson<ProxyResponse>(
        `/api/odpt/proxy?${params.toString()}`,
      );
      setProxyRes(body);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function runIntrospect() {
    if (!proxyRes?.data?.length) {
      setError("先に Proxy Fetch を実行してください。");
      return;
    }
    setIntrospecting(true);
    setError(null);
    setIntroRes(null);
    try {
      const body = await fetchJson<IntrospectResponse>("/api/odpt/introspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ records: proxyRes.data }),
      });
      setIntroRes(body);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIntrospecting(false);
    }
  }

  async function runExportOperational() {
    setExporting(true);
    setError(null);
    setExportRes(null);
    try {
      const body = await fetchJson<unknown>("/api/odpt/export/operational", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildExportPayload()),
      });
      setExportRes(body);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  }

  async function runSaveToDisk() {
    setSaving(true);
    setError(null);
    setSaveRes(null);
    try {
      const body = await fetchJson<{
        savedTo?: string;
        normalizedSavedTo?: string;
        meta?: unknown;
      }>("/api/odpt/export/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildExportPayload()),
      });
      setSaveRes({
        savedTo: body.savedTo ?? "",
        normalizedSavedTo: body.normalizedSavedTo,
        meta: body.meta,
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  // ── Derived ────────────────────────────────────────────────────────────────

  const preview = useMemo(() => {
    if (!proxyRes?.data) return "";
    return prettyJson(proxyRes.data.slice(0, 20));
  }, [proxyRes]);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">
            ODPT Explorer
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Resource と Query を試しながら JSON 構造（必須 / 任意フィールド、参照 ID、配列構造）を把握する開発ツール。
          </p>
        </div>
        <Link
          to="/scenarios"
          className="text-sm text-primary-600 hover:underline"
        >
          ← シナリオ一覧へ
        </Link>
      </div>

      {/* Controls card */}
      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-6">
          {/* Resource selector */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Resource
            </label>
            <select
              value={resource}
              onChange={(e) => setResource(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              {RESOURCE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          {/* Dump mode */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Dump mode
            </label>
            <label className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={dump}
                onChange={(e) => setDump(e.target.checked)}
                className="accent-primary-500"
              />
              <span>.json（全量側）</span>
            </label>
            <p className="text-xs text-slate-400">
              1000 件上限に当たるなら ON
            </p>
          </div>

          {/* Cache controls */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Cache
            </label>
            <label className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={forceRefresh}
                onChange={(e) => setForceRefresh(e.target.checked)}
                className="accent-primary-500"
              />
              <span>Force refresh</span>
            </label>
            <input
              type="number"
              value={ttlSec}
              min={60}
              step={60}
              onChange={(e) => setTtlSec(Number(e.target.value) || 60)}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            <p className="text-xs text-slate-400">
              TTL 秒。例: 3600 = 1 時間
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Optional data
            </label>
            <label className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={includeStopTimetables}
                onChange={(e) => setIncludeStopTimetables(e.target.checked)}
                className="accent-primary-500"
              />
              <span>BusstopPoleTimetable を含める</span>
            </label>
            <p className="text-xs text-slate-400">
              OFF 推奨。ON は取得件数が多く、時間がかかることがあります。
            </p>
          </div>

          {/* Proxy / Introspect actions */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Actions
            </label>
            <button
              onClick={runProxy}
              disabled={loading}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
            >
              {loading ? "Fetching…" : "Proxy Fetch"}
            </button>
            <button
              onClick={runIntrospect}
              disabled={introspecting || !proxyRes?.data?.length}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40 transition-colors"
            >
              {introspecting ? "Introspecting…" : "Introspect"}
            </button>
          </div>

          {/* Export operational + Save to disk */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Master-course 用
            </label>
            <button
              onClick={runExportOperational}
              disabled={exporting}
              className="w-full rounded-lg border border-primary-300 bg-primary-50 px-3 py-2 text-sm font-medium text-primary-700 hover:bg-primary-100 disabled:opacity-40 transition-colors"
            >
              {exporting ? "Exporting…" : "Export Operational"}
            </button>
            <button
              onClick={runSaveToDisk}
              disabled={saving}
              className="w-full rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-40 transition-colors"
            >
              {saving ? "Saving…" : "Save to Disk"}
            </button>
            <p className="text-xs text-slate-400">
              Stop / Pattern / Trip / Index を operational dataset として返す
              <br />
              Save to Disk は normalized / operational の両方を書き込む
            </p>
          </div>
        </div>

        {/* Query textarea */}
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
            Query（そのまま送る）
          </label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            placeholder="例: odpt:operator=odpt.Operator:TokyuBus"
          />
          <p className="text-xs text-slate-400">
            例:{" "}
            <code className="rounded bg-slate-100 px-1">
              odpt:operator=odpt.Operator:TokyuBus
            </code>{" "}
            /{" "}
            <code className="rounded bg-slate-100 px-1">
              odpt:busroutePattern=odpt.BusroutePattern:TokyuBus.XXX
            </code>{" "}
            （&amp; 区切りで追加可）
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <span className="font-semibold">Error: </span>
            {error}
          </div>
        )}

        {/* Proxy meta */}
        {proxyRes?.meta && (
          <div className="rounded-lg border border-border bg-surface px-4 py-3 space-y-1 text-sm">
            <div className="flex flex-wrap gap-4 text-slate-700">
              <span>
                <span className="font-semibold">count:</span>{" "}
                {proxyRes.meta.count}
              </span>
              <span>
                <span className="font-semibold">dump:</span>{" "}
                {String(proxyRes.meta.dump)}
              </span>
              <span>
                <span className="font-semibold">maybeTruncated:</span>{" "}
                {String(proxyRes.meta.maybeTruncated)}
              </span>
              <span>
                <span className="font-semibold">cacheHit:</span>{" "}
                {String(proxyRes.meta.cacheHit)}
              </span>
            </div>
            <p className="truncate text-xs text-slate-400">
              <span className="font-semibold">URL: </span>
              <code>{proxyRes.meta.url}</code>
            </p>
            <p className="truncate text-xs text-slate-400">
              <span className="font-semibold">cacheKey: </span>
              <code>{proxyRes.meta.cacheKey}</code>
            </p>
            {proxyRes.meta.maybeTruncated && !proxyRes.meta.dump && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                取得件数が 1000 件です。検索 API の上限で欠損している可能性があります。
                Dump mode を ON にして再取得してください。
              </div>
            )}
          </div>
        )}
      </div>

      {/* Results: Proxy preview + Introspect */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* JSON Preview */}
        <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
          <h2 className="text-sm font-semibold text-slate-700">
            Proxy 結果プレビュー（先頭 20 件）
          </h2>
          <pre className="overflow-auto rounded-lg border border-border bg-slate-50 p-3 text-xs leading-relaxed max-h-[520px]">
            {preview || "（まだ取得していません）"}
          </pre>
        </div>

        {/* Introspect */}
        <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
          <h2 className="text-sm font-semibold text-slate-700">
            Introspect（フィールド一覧）
          </h2>
          {!introRes ? (
            <p className="text-sm text-slate-400">
              Introspect を実行すると、必須っぽいフィールドや型が出ます。
            </p>
          ) : (
            <>
              <p className="text-xs text-slate-500">
                sampleCount:{" "}
                <span className="font-semibold">{introRes.sampleCount}</span>（先頭サンプルで解析）
              </p>
              <div className="overflow-auto rounded-lg border border-border max-h-[460px]">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="sticky top-0 bg-slate-50 text-left text-slate-600">
                      <th className="px-3 py-2 font-semibold border-b border-border">
                        path
                      </th>
                      <th className="px-3 py-2 font-semibold border-b border-border w-20">
                        rate
                      </th>
                      <th className="px-3 py-2 font-semibold border-b border-border">
                        types
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {introRes.fields.slice(0, 200).map((f) => (
                      <tr
                        key={f.path}
                        className="border-b border-slate-50 hover:bg-slate-50"
                      >
                        <td className="px-3 py-1.5 font-mono text-slate-700">
                          {f.path}
                        </td>
                        <td className="px-3 py-1.5 text-slate-600">
                          {(f.presentRate * 100).toFixed(0)}%
                        </td>
                        <td className="px-3 py-1.5 text-slate-500">
                          {typesSummary(f.types)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-slate-400">
                上位ほど「ほぼ必須」。
                <code className="rounded bg-slate-100 px-1">owl:sameAs</code>,{" "}
                <code className="rounded bg-slate-100 px-1">odpt:*</code>,{" "}
                <code className="rounded bg-slate-100 px-1">dc:title</code>,{" "}
                <code className="rounded bg-slate-100 px-1">geo:*</code>{" "}
                の出現率を見ると把握が速い。
              </p>
            </>
          )}
        </div>
      </div>

      {/* Export operational */}
      <div className="rounded-xl border border-border bg-surface-raised p-5 space-y-3">
        <h2 className="text-sm font-semibold text-slate-700">
          Export Operational（Stop / RoutePattern / Trip / Index）
        </h2>
        {!exportRes ? (
          <p className="text-sm text-slate-400">
            「Export Operational」を押すと、配車準備に使う operational JSON が返ります。
          </p>
        ) : (
          <pre className="overflow-auto rounded-lg border border-border bg-slate-50 p-3 text-xs leading-relaxed max-h-[520px]">
            {prettyJson(exportRes)}
          </pre>
        )}
      </div>

      {/* Save to disk result */}
      {saveRes && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 space-y-2">
          <h2 className="text-sm font-semibold text-emerald-800">
            Saved to Disk
          </h2>
          <p className="text-xs text-emerald-700">operational_dataset.json</p>
          <p className="text-xs font-mono text-emerald-700 break-all">
            {saveRes.savedTo}
          </p>
          {saveRes.normalizedSavedTo && (
            <>
              <p className="text-xs text-emerald-700">normalized_dataset.json</p>
              <p className="text-xs font-mono text-emerald-700 break-all">
                {saveRes.normalizedSavedTo}
              </p>
            </>
          )}
          <pre className="overflow-auto rounded-lg border border-emerald-200 bg-white p-3 text-xs leading-relaxed max-h-[200px]">
            {prettyJson(saveRes.meta)}
          </pre>
        </div>
      )}
    </div>
  );
}
