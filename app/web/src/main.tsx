import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";
import { loadPrefs } from "./lib/prefs";
import { applyTheme, storedTheme } from "./lib/theme";

const client = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: true, retry: 1, staleTime: 5_000 } },
});

// Preferences first, then the theme, then the first paint: the window never flashes the
// default theme, and the panels open as they were left.
void loadPrefs().then(() => {
  applyTheme(storedTheme(), false);
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </React.StrictMode>,
  );
});
