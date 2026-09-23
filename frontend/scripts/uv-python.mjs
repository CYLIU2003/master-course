import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const bundled = resolve(root, "output/cluster-deployment/bootstrap/uv.exe");
const uv = process.env.UV_EXECUTABLE || (existsSync(bundled) ? bundled : "uv");
const result = spawnSync(uv, ["run", "--project", resolve(root, "tools/cluster/environment"),
  "--locked", "python", ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, UV_PROJECT_ENVIRONMENT: process.env.UV_PROJECT_ENVIRONMENT || resolve(root, ".venv-cluster") },
});
if (result.error) console.error("uvをインストールするか、UV_EXECUTABLEにuvのパスを指定してください。");
process.exit(result.status ?? 1);
