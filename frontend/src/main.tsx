import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryProvider } from "@/app/QueryProvider";
import { AppRouter } from "@/app/Router";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryProvider>
      <AppRouter />
    </QueryProvider>
  </StrictMode>,
);
