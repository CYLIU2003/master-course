"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.loadRuntimePaths = loadRuntimePaths;
exports.resolveRuntimePath = resolveRuntimePath;
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
const defaults = {
    odpt_snapshot_dir: "./data/odpt/tokyu",
    transit_catalog_db_path: "./outputs/transit_catalog.sqlite",
    transit_db_tokyu: "./data/odpt_tokyu.db",
    transit_db_toei: "./data/gtfs_toei.db",
    catalog_fast_dir: "./data/catalog-fast",
};
function repoRoot() {
    return node_path_1.default.resolve(__dirname, "../..");
}
function loadRuntimePaths() {
    const configPath = node_path_1.default.resolve(repoRoot(), "config", "runtime_paths.json");
    try {
        const payload = JSON.parse(node_fs_1.default.readFileSync(configPath, "utf-8"));
        return { ...defaults, ...payload };
    }
    catch {
        return defaults;
    }
}
function resolveRuntimePath(key) {
    const value = loadRuntimePaths()[key];
    return node_path_1.default.isAbsolute(value) ? value : node_path_1.default.resolve(repoRoot(), value);
}
