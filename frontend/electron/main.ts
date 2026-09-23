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
  const uvPython = path.join(root, ".venv-cluster", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const python =
    process.env.EV_BUS_PYTHON ??
    (existsSync(uvPython) ? uvPython : path.join(
      root,
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    ));
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
          ...(upstream.headers.has("content-disposition")
            ? {
                "content-disposition": upstream.headers.get(
                  "content-disposition",
                )!,
              }
            : {}),
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
        const selectedScenario = process.env.EV_BUS_SMOKE_SCENARIO_ID;
        if (selectedScenario) {
          if (!/^[A-Za-z0-9_-]+$/.test(selectedScenario))
            throw new Error("Invalid smoke scenario ID");
          await window.webContents.executeJavaScript(
            `localStorage.setItem('ev-scenario', ${JSON.stringify(selectedScenario)})`,
          );
          await window.loadURL("research://app/");
        }
        // Hidden windows can pause CSS transitions midway between snapshots.
        await window.webContents.insertCSS(
          "*, *::before, *::after { transition: none !important; animation: none !important; }",
        );
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
        if (hasScenario || selectedScenario) {
          if (hasScenario)
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
          const visitedScreens: string[] = [];
          const screens = [
            "運行・計算設定",
            "車両",
            "営業所・充電設備",
            "路線・運行パターン",
            "PV・BESS設備",
            "気象・PVデータ",
            "データを確認",
            "実行",
            "グラフ・費用明細",
            "シナリオ比較",
          ];
          for (const label of screens) {
            await window.webContents.executeJavaScript(
              `Array.from(document.querySelectorAll('.workspace-nav button')).find(button => button.textContent === ${JSON.stringify(label)}).click()`,
            );
            const screenDeadline = Date.now() + 60_000;
            while (Date.now() < screenDeadline) {
              await new Promise((resolve) => setTimeout(resolve, 250));
              if (
                await window.webContents.executeJavaScript(
                  "document.body.dataset.fetching === '0'",
                )
              )
                break;
            }
            if (
              !(await window.webContents.executeJavaScript(
                "document.body.dataset.fetching === '0'",
              ))
            )
              throw new Error("Screen data timed out: " + label);
            const state: { alerts: string[]; rows: number; heading: string } =
              await window.webContents.executeJavaScript(
                `({ alerts: Array.from(document.querySelectorAll('[role=alert]')).filter(node => node.checkVisibility()).map(node => node.textContent), rows: Array.from(document.querySelectorAll('.table-row')).filter(node => node.checkVisibility()).length, heading: document.querySelector('header').textContent })`,
              );
            if (state.alerts.length)
              throw new Error(`${label}: ${state.alerts.join("; ")}`);
            if (state.rows > 100)
              throw new Error("Virtual table rendered too many rows");
            if (!state.heading.includes(label))
              throw new Error("Navigation failed: " + label);
            writeFileSync(
              path.join(output, `screen-${visitedScreens.length + 1}.png`),
              (await window.webContents.capturePage()).toPNG(),
            );
            visitedScreens.push(label);
          }
          await window.webContents.executeJavaScript(
            "Array.from(document.querySelectorAll('.workspace-nav button')).find(button => button.textContent === 'グラフ・費用明細').click()",
          );
          await new Promise((resolve) => setTimeout(resolve, 1000));
          const hasDownload: boolean =
            await window.webContents.executeJavaScript(
              "Boolean(document.querySelector('.artifact-list a'))",
            );
          if (hasDownload) {
            const done = new Promise<string>((resolve, reject) => {
              const timer = setTimeout(
                () => reject(new Error("Native artifact download timed out")),
                20_000,
              );
              window.webContents.session.once(
                "will-download",
                (_event, item) => {
                  const download = path.join(
                    output,
                    `download-${Date.now()}-${path.basename(item.getFilename())}`,
                  );
                  item.setSavePath(download);
                  item.once("done", (_event, state) => {
                    clearTimeout(timer);
                    if (state === "completed") resolve(download);
                    else reject(new Error("Artifact download: " + state));
                  });
                },
              );
            });
            await window.webContents.executeJavaScript(
              "document.querySelector('.artifact-list a').click()",
              true,
            );
            const download = await done;
            writeFileSync(
              path.join(output, "download.json"),
              JSON.stringify({
                path: download,
                bytes: readFileSync(download).length,
                nativeDownload: true,
              }),
            );
          }
          window.setSize(900, 760);
          for (const label of [
            "運行・計算設定",
            "車両",
            "PV・BESS設備",
            "グラフ・費用明細",
          ]) {
            await window.webContents.executeJavaScript(
              `Array.from(document.querySelectorAll('.workspace-nav button')).find(button => button.textContent === ${JSON.stringify(label)}).click()`,
            );
            await new Promise((resolve) => setTimeout(resolve, 500));
            const overflow: boolean =
              await window.webContents.executeJavaScript(
                "document.documentElement.scrollWidth > window.innerWidth + 1",
              );
            if (overflow)
              throw new Error("Horizontal page overflow at 900px: " + label);
          }
          writeFileSync(
            path.join(output, "compact.png"),
            (await window.webContents.capturePage()).toPNG(),
          );
          writeFileSync(
            path.join(output, "screens.json"),
            JSON.stringify({ visitedScreens }, null, 2),
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
