import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryProvider } from "@/app/QueryProvider";
import { AppRouter } from "@/app/Router";
import { initPerfObservers } from "@/utils/perf/perf-store";
import "./i18n";
import "./index.css";

if (import.meta.env.DEV) {
  initPerfObservers();
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryProvider>
      <AppRouter />
    </QueryProvider>
  </StrictMode>,
);
