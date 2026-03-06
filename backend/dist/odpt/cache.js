"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.makeCacheKey = makeCacheKey;
exports.readCache = readCache;
exports.writeCache = writeCache;
exports.deleteCache = deleteCache;
const node_crypto_1 = __importDefault(require("node:crypto"));
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
const CACHE_DIR = node_path_1.default.join(process.cwd(), ".cache", "odpt");
function ensureDir(dirPath) {
    node_fs_1.default.mkdirSync(dirPath, { recursive: true });
}
function hashKey(key) {
    return node_crypto_1.default.createHash("sha256").update(key).digest("hex");
}
function cachePath(key) {
    ensureDir(CACHE_DIR);
    return node_path_1.default.join(CACHE_DIR, `${hashKey(key)}.json`);
}
function makeCacheKey(input) {
    return JSON.stringify({
        resource: input.resource,
        query: input.query,
        dump: input.dump,
    });
}
function readCache(key) {
    const filePath = cachePath(key);
    if (!node_fs_1.default.existsSync(filePath)) {
        return null;
    }
    try {
        const raw = JSON.parse(node_fs_1.default.readFileSync(filePath, "utf-8"));
        if (new Date(raw.expiresAt) < new Date()) {
            return null;
        }
        return raw.payload;
    }
    catch {
        return null;
    }
}
function writeCache(key, payload, ttlSec) {
    const now = new Date();
    const expiresAt = new Date(now.getTime() + ttlSec * 1000);
    const envelope = {
        createdAt: now.toISOString(),
        expiresAt: expiresAt.toISOString(),
        key,
        payload,
    };
    const filePath = cachePath(key);
    node_fs_1.default.writeFileSync(filePath, JSON.stringify(envelope, null, 2), "utf-8");
}
function deleteCache(key) {
    const filePath = cachePath(key);
    if (node_fs_1.default.existsSync(filePath)) {
        node_fs_1.default.unlinkSync(filePath);
    }
}
