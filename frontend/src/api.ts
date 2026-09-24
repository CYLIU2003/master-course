import type { components } from "./generated/api";

export type Json = components["schemas"]["JsonValue"];
export type Row = Record<string, Json>;
export type Scenario = components["schemas"]["ScenarioSummary"];
export type Page<T> = Omit<components["schemas"]["DesktopPage"], "items"> & {
  items: T[];
};
export type Overview = components["schemas"]["ScenarioOverview"];
export type Prepared = components["schemas"]["PrepareReply"];
export type Job = components["schemas"]["JobReply"];

export async function api<T>(
  path: string,
  options: RequestInit = {},
  origin = "",
): Promise<T> {
  const response = await fetch(origin + "/api" + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const text = await response.text();
  if (response.status === 204) return undefined as T;
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`API ${response.status}: ${text.slice(0, 500)}`);
  }
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? payload.detail
        : payload;
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return payload as T;
}
export const post = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const remove = (path: string) => api<void>(path, { method: "DELETE" });
export const rows = (value: Json | undefined): Row[] =>
  Array.isArray(value)
    ? value.filter(
        (item): item is Row =>
          !!item && typeof item === "object" && !Array.isArray(item),
      )
    : [];
export const record = (value: Json | undefined): Row =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Row)
    : {};
export const strings = (value: Json | undefined): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
export const display = (value: Json | undefined): string =>
  value === undefined || value === null
    ? "未確認"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
export function gate(value: Json | undefined): string {
  if (
    value === true ||
    value === 1 ||
    value === "VALID" ||
    value === "ACCEPTED"
  )
    return "確認済み";
  if (
    value === false ||
    value === 0 ||
    value === "INVALID" ||
    value === "REJECTED"
  )
    return "未達";
  return display(value);
}
