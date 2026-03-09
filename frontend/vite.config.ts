import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

function parsePort(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const devHost = env.VITE_DEV_HOST || "0.0.0.0";
  const devPort = parsePort(env.VITE_DEV_PORT, 5173);
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";
  const odptProxyTarget = env.VITE_ODPT_PROXY_TARGET || "http://127.0.0.1:3001";

  return {
    plugins: [react(), tailwindcss()],
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes("node_modules")) {
              return undefined;
            }
            const modulePath = id.split("node_modules/")[1] ?? "";
            const packageName = modulePath.startsWith("@")
              ? modulePath.split("/").slice(0, 2).join("/")
              : modulePath.split("/")[0];
            if (
              packageName === "react" ||
              packageName === "react-dom" ||
              packageName === "react-router" ||
              packageName === "react-router-dom"
            ) {
              return "vendor-react";
            }
            if (packageName === "@tanstack/react-query" || packageName === "zustand") {
              return "vendor-state";
            }
            if (packageName === "i18next" || packageName === "react-i18next") {
              return "vendor-i18n";
            }
            if (packageName === "zod") {
              return "vendor-schema";
            }
            if (packageName === "leaflet") {
              return "vendor-map";
            }
            if (
              packageName === "cookie" ||
              packageName === "set-cookie-parser" ||
              packageName === "void-elements" ||
              packageName === "html-parse-stringify"
            ) {
              return undefined;
            }
            return `vendor-${packageName.replace(/[@/]/g, "-")}`;
          },
        },
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    server: {
      host: devHost,
      port: devPort,
      proxy: {
        // ODPT Explorer BFF (Node/Express :3001) — must be listed BEFORE "/api"
        "/api/odpt": {
          target: odptProxyTarget,
          changeOrigin: true,
        },
        // Existing FastAPI BFF (:8000)
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
