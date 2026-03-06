import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // ODPT Explorer BFF (Node/Express :3001) — must be listed BEFORE "/api"
      "/api/odpt": {
        target: "http://localhost:3001",
        changeOrigin: true,
      },
      // Existing FastAPI BFF (:8000)
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
