import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const CACHE_DIR = path.join(process.cwd(), ".cache", "odpt");

export type CacheEnvelope = {
  createdAt: string;
  expiresAt: string;
  key: string;
  payload: unknown;
};

function ensureDir(dirPath: string): void {
  fs.mkdirSync(dirPath, { recursive: true });
}

function hashKey(key: string): string {
  return crypto.createHash("sha256").update(key).digest("hex");
}

function cachePath(key: string): string {
  ensureDir(CACHE_DIR);
  return path.join(CACHE_DIR, `${hashKey(key)}.json`);
}

export function makeCacheKey(input: {
  resource: string;
  query: string;
  dump: boolean;
}): string {
  return JSON.stringify({
    resource: input.resource,
    query: input.query,
    dump: input.dump,
  });
}

export function readCache<T>(key: string): T | null {
  const filePath = cachePath(key);
  if (!fs.existsSync(filePath)) {
    return null;
  }

  try {
    const raw = JSON.parse(fs.readFileSync(filePath, "utf-8")) as CacheEnvelope;
    if (new Date(raw.expiresAt) < new Date()) {
      return null;
    }
    return raw.payload as T;
  } catch {
    return null;
  }
}

export function writeCache<T>(key: string, payload: T, ttlSec: number): void {
  const now = new Date();
  const expiresAt = new Date(now.getTime() + ttlSec * 1000);

  const envelope: CacheEnvelope = {
    createdAt: now.toISOString(),
    expiresAt: expiresAt.toISOString(),
    key,
    payload,
  };

  const filePath = cachePath(key);
  fs.writeFileSync(filePath, JSON.stringify(envelope, null, 2), "utf-8");
}

export function deleteCache(key: string): void {
  const filePath = cachePath(key);
  if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
  }
}
