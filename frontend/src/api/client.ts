import type { ApiError } from "@/types";

const BASE_URL = "/api";

function extractErrorMessage(body: unknown): string | null {
  if (!body || typeof body !== "object") {
    return null;
  }

  const candidate = body as Partial<ApiError> & {
    error?: unknown;
    message?: unknown;
  };

  if (typeof candidate.detail === "string" && candidate.detail.trim()) {
    return candidate.detail;
  }
  if (typeof candidate.error === "string" && candidate.error.trim()) {
    return candidate.error;
  }
  if (typeof candidate.message === "string" && candidate.message.trim()) {
    return candidate.message;
  }

  return null;
}

function looksLikeJson(text: string): boolean {
  const trimmed = text.trim();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
}

async function parseResponseBody<T>(
  res: Response,
  allowEmptyBody: boolean,
): Promise<T | null> {
  const contentType = res.headers.get("content-type") ?? "";
  const text = await res.text();

  if (!res.ok) {
    let errorMessage = `HTTP ${res.status} ${res.statusText}`;

    if (text.trim()) {
      if (contentType.includes("application/json") || looksLikeJson(text)) {
        try {
          const body = JSON.parse(text) as ApiError | Record<string, unknown>;
          errorMessage = extractErrorMessage(body) ?? `${errorMessage} - ${text}`;
        } catch {
          errorMessage = `${errorMessage} - ${text}`;
        }
      } else {
        errorMessage = `${errorMessage} - ${text}`;
      }
    } else {
      errorMessage = `${errorMessage} - (empty body)`;
    }

    throw new Error(errorMessage);
  }

  if (res.status === 204 || !text.trim()) {
    if (allowEmptyBody || res.status === 204) {
      return null;
    }
    throw new Error("API returned empty body where JSON was expected");
  }

  if (
    !contentType.includes("application/json") &&
    !looksLikeJson(text)
  ) {
    throw new Error(
      `Expected application/json but got "${contentType || "unknown"}" with body: ${text.slice(0, 200)}`,
    );
  }

  try {
    return JSON.parse(text) as T;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Failed to parse JSON: ${message}. Body: ${text.slice(0, 200)}`,
    );
  }
}

export async function fetchJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(input, init);
  const body = await parseResponseBody<T>(res, false);
  return body as T;
}

export async function fetchMaybeJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T | null> {
  const res = await fetch(input, init);
  return parseResponseBody<T>(res, true);
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options?: { allowEmptyBody?: boolean },
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const input = `${BASE_URL}${path}`;
  const requestInit = { ...init, headers };
  const body = options?.allowEmptyBody
    ? await fetchMaybeJson<T>(input, requestInit)
    : await fetchJson<T>(input, requestInit);

  return (body ?? undefined) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) =>
    request<T>(path, { method: "DELETE" }, { allowEmptyBody: true }),
};
