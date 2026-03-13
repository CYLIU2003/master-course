import fs from "node:fs";
import path from "node:path";

type RuntimePaths = {
  odpt_snapshot_dir: string;
  transit_catalog_db_path: string;
  transit_db_tokyu: string;
  transit_db_toei: string;
  catalog_fast_dir: string;
};

const defaults: RuntimePaths = {
  odpt_snapshot_dir: "./data/odpt/tokyu",
  transit_catalog_db_path: "./outputs/transit_catalog.sqlite",
  transit_db_tokyu: "./data/odpt_tokyu.db",
  transit_db_toei: "./data/gtfs_toei.db",
  catalog_fast_dir: "./data/catalog-fast",
};

function repoRoot(): string {
  return path.resolve(__dirname, "../..");
}

export function loadRuntimePaths(): RuntimePaths {
  const configPath = path.resolve(repoRoot(), "config", "runtime_paths.json");
  try {
    const payload = JSON.parse(fs.readFileSync(configPath, "utf-8")) as Partial<RuntimePaths>;
    return { ...defaults, ...payload };
  } catch {
    return defaults;
  }
}

export function resolveRuntimePath(key: keyof RuntimePaths): string {
  const value = loadRuntimePaths()[key];
  return path.isAbsolute(value) ? value : path.resolve(repoRoot(), value);
}
