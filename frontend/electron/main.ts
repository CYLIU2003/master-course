import { app, BrowserWindow, dialog, protocol } from "electron";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createHmac, randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";

const here = path.dirname(fileURLToPath(import.meta.url));
const smoke = process.argv.includes("--smoke");
let backend: ChildProcessWithoutNullStreams | undefined;
let backendPort = 0;
let backendError = "";
let stopping = false;
let exitStatus = 0;
const token = randomBytes(32).toString("hex");
protocol.registerSchemesAsPrivileged([
  {
    scheme: "research",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
    },
  },
]);

async function workspace(): Promise<string> {
  if (process.env.EV_BUS_WORKSPACE)
    return path.resolve(process.env.EV_BUS_WORKSPACE);
  if (!app.isPackaged) return path.resolve(here, "../..");
  const config = path.join(app.getPath("userData"), "workspace.json");
  if (existsSync(config)) {
    const saved: unknown = JSON.parse(readFileSync(config, "utf8"));
    if (
      typeof saved === "string" &&
      existsSync(path.join(saved, "bff/desktop_server.py"))
    )
      return saved;
  }
  const choice = await dialog.showOpenDialog({
    title: "研究リポジトリ master-course を選択",
    properties: ["openDirectory"],
  });
  if (choice.canceled || !choice.filePaths[0])
    throw new Error("研究リポジトリが選択されていません");
  mkdirSync(path.dirname(config), { recursive: true });
  writeFileSync(config, JSON.stringify(choice.filePaths[0]));
  return choice.filePaths[0];
}

async function startBackend(root: string): Promise<void> {
  const python =
    process.env.EV_BUS_PYTHON ??
    path.join(
      root,
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
  if (
    !existsSync(python) ||
    !existsSync(path.join(root, "bff/desktop_server.py"))
  )
    throw new Error(
      "Python 環境または BFF がありません。README のセットアップを実行してください。",
    );
  backend = spawn(python, ["-u", "-m", "bff.desktop_server"], {
    cwd: root,
    windowsHide: true,
    env: { ...process.env, EV_DESKTOP_TOKEN: token, PYTHONUTF8: "1" },
    stdio: ["pipe", "pipe", "pipe"],
  });
  const child = backend;
  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error("BFF 起動が90秒以内に完了しませんでした")),
      90_000,
    );
    const finish = (error?: Error) => {
      clearTimeout(timeout);
      error ? reject(error) : resolve();
    };
    child.on("error", (error) => finish(error));
    child.on("exit", (code) => {
      backendPort = 0;
      backendError = `BFF が終了しました (${code})`;
      if (!stopping) finish(new Error(backendError));
    });
    // Never forward child logs: upstream libraries may log sensitive configuration.
    child.stderr.on("data", () => undefined);
    createInterface({ input: child.stdout }).on("line", (line) => {
      if (!line.startsWith("DESKTOP_READY ")) return;
      try {
        const info: { port?: number; pid?: number; proof?: string } =
          JSON.parse(line.slice(14));
        // Windows virtualenv launchers may keep a wrapper PID above Python.
        const proof = createHmac("sha256", token)
          .update(`${info.port}:${info.pid}`)
          .digest("hex");
        if (
          info.proof !== proof ||
          !Number.isInteger(info.port) ||
          !info.port ||
          info.port < 1 ||
          info.port > 65535
        )
          throw new Error("Invalid BFF handshake");
        backendPort = info.port;
        finish();
      } catch {
        finish(new Error("BFF 起動情報が不正です"));
      }
    });
  });
}

const mime: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};
async function handle(request: Request): Promise<Response> {
  const url = new URL(request.url);
  if (url.host !== "app") return new Response("Forbidden", { status: 403 });
  if (url.pathname.startsWith("/api/")) {
    if (!backendPort)
      return Response.json(
        { detail: backendError || "BFF disconnected" },
        { status: 503 },
      );
    try {
      const headers = new Headers({ Authorization: `Bearer ${token}` });
      const contentType = request.headers.get("content-type");
      if (contentType) headers.set("Content-Type", contentType);
      const upstream = await fetch(
        `http://127.0.0.1:${backendPort}${url.pathname}${url.search}`,
        {
          method: request.method,
          headers,
          body: ["GET", "HEAD"].includes(request.method)
            ? undefined
            : await request.arrayBuffer(),
          redirect: "error",
          signal: request.signal,
        },
      );
      return new Response(upstream.body, {
        status: upstream.status,
        headers: {
          "content-type":
            upstream.headers.get("content-type") ?? "application/json",
        },
      });
    } catch {
      return Response.json(
        { detail: "BFF との通信に失敗しました。アプリを再起動してください。" },
        { status: 502 },
      );
    }
  }
  if (request.method !== "GET")
    return new Response("Method not allowed", { status: 405 });
  const base = path.resolve(here, "../dist");
  let file: string;
  try {
    file = path.resolve(
      base,
      "." +
        decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname),
    );
  } catch {
    return new Response("Bad path", { status: 400 });
  }
  if (!file.startsWith(base + path.sep))
    return new Response("Forbidden", { status: 403 });
  try {
    return new Response(readFileSync(file), {
      headers: {
        "content-type": mime[path.extname(file)] ?? "application/octet-stream",
      },
    });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}

async function stopBackend(): Promise<void> {
  if (!backend || backend.exitCode !== null) return;
  const child = backend;
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      if (child.pid && child.exitCode === null) {
        if (process.platform === "win32")
          spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
            windowsHide: true,
            stdio: "ignore",
          }).on("exit", () => resolve());
        else {
          child.kill("SIGTERM");
          resolve();
        }
      } else resolve();
    }, 5000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    child.stdin.end("shutdown\n");
  });
}

app.on("before-quit", (event) => {
  if (!stopping) {
    event.preventDefault();
    stopping = true;
    void stopBackend().finally(() => app.exit(exitStatus));
  }
});
app.on("window-all-closed", () => app.quit());
if (!app.requestSingleInstanceLock()) app.quit();
else
  void app
    .whenReady()
    .then(async () => {
      const root = await workspace();
      await startBackend(root);
      const window = new BrowserWindow({
        width: 1440,
        height: 960,
        minWidth: 900,
        minHeight: 650,
        show: !smoke,
        backgroundColor: "#f5f6f2",
        webPreferences: {
          partition: smoke ? "desktop-smoke" : "persist:ev-research",
          sandbox: true,
          contextIsolation: true,
          nodeIntegration: false,
          webSecurity: true,
        },
      });
      await window.webContents.session.protocol.handle("research", handle);
      window.removeMenu();
      window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      window.webContents.on("will-navigate", (event, target) => {
        if (!target.startsWith("research://app/")) event.preventDefault();
      });
      window.webContents.session.setPermissionRequestHandler(
        (_contents, _permission, callback) => callback(false),
      );
      window.webContents.session.setPermissionCheckHandler(() => false);
      await window.loadURL("research://app/");
      if (smoke) {
        const deadline = Date.now() + 30_000;
        while (Date.now() < deadline) {
          const ready: boolean = await window.webContents.executeJavaScript(
            "document.body.dataset.ready === 'true'",
          );
          if (ready) break;
          await new Promise((resolve) => setTimeout(resolve, 250));
        }
        const body: string = await window.webContents.executeJavaScript(
          "document.body.innerText",
        );
        const ready: boolean = await window.webContents.executeJavaScript(
          "document.body.dataset.ready === 'true'",
        );
        if (!ready || !body.includes("シナリオ"))
          throw new Error("Renderer smoke failed");
        const output = path.join(root, "output/desktop-smoke");
        mkdirSync(output, { recursive: true });
        writeFileSync(
          path.join(output, "desktop.png"),
          (await window.webContents.capturePage()).toPNG(),
        );
        const hasScenario: boolean = await window.webContents.executeJavaScript(
          "Boolean(document.querySelector('.scenario'))",
        );
        if (hasScenario) {
          await window.webContents.executeJavaScript(
            "document.querySelector('.scenario').click()",
          );
          const scenarioDeadline = Date.now() + 60_000;
          let opened = false;
          while (Date.now() < scenarioDeadline) {
            opened = await window.webContents.executeJavaScript(
              "Boolean(document.querySelector('.metrics')) && !document.querySelector('[role=alert]')",
            );
            if (opened) break;
            await new Promise((resolve) => setTimeout(resolve, 250));
          }
          if (!opened) throw new Error("Scenario overview smoke failed");
          writeFileSync(
            path.join(output, "overview.png"),
            (await window.webContents.capturePage()).toPNG(),
          );
          await window.webContents.executeJavaScript(
            "Array.from(document.querySelectorAll('.tabs button')).find(button => button.textContent === 'データを確認').click()",
          );
          const tableDeadline = Date.now() + 60_000;
          let tableReady = false;
          while (Date.now() < tableDeadline) {
            tableReady = await window.webContents.executeJavaScript(
              "Boolean(document.querySelector('.workspace > .data-panel')) && !Array.from(document.querySelectorAll('.table-status')).some(node => node.textContent.includes('読み込み')) && !document.querySelector('[role=alert]')",
            );
            if (tableReady) break;
            await new Promise((resolve) => setTimeout(resolve, 250));
          }
          if (!tableReady) throw new Error("Table smoke failed");
          const renderedRows: number =
            await window.webContents.executeJavaScript(
              "document.querySelectorAll('.workspace > .data-panel .table-row').length",
            );
          if (renderedRows > 50)
            throw new Error("Virtual table rendered too many rows");
          writeFileSync(
            path.join(output, "table.png"),
            (await window.webContents.capturePage()).toPNG(),
          );
        }
        writeFileSync(
          path.join(output, "smoke.json"),
          JSON.stringify({
            ok: true,
            electron: process.versions.electron,
            workspace: root,
            authenticatedBackend: true,
          }),
        );
        app.quit();
      }
    })
    .catch((error) => {
      console.error(String(error));
      if (!smoke) dialog.showErrorBox("EV Bus Research", String(error));
      exitStatus = 1;
      app.quit();
    });
