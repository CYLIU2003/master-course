import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const distDir = join(process.cwd(), "dist", "assets");

function walk(dir) {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walk(fullPath));
    } else {
      files.push(fullPath);
    }
  }
  return files;
}

const files = walk(distDir);
let jsBytes = 0;
let cssBytes = 0;
let largestJs = { name: null, bytes: 0 };

for (const file of files) {
  const size = statSync(file).size;
  if (file.endsWith(".js")) {
    jsBytes += size;
    if (size > largestJs.bytes) {
      largestJs = { name: file, bytes: size };
    }
  }
  if (file.endsWith(".css")) {
    cssBytes += size;
  }
}

console.log(JSON.stringify({
  assetDir: distDir,
  jsBytes,
  cssBytes,
  totalBytes: jsBytes + cssBytes,
  largestJs,
}, null, 2));
