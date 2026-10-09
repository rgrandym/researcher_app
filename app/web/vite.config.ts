import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Ports come from scripts/dev.sh (BACKEND_PORT / FRONTEND_PORT); defaults match it.
const backend = process.env.BACKEND_PORT ?? "8765";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: Number(process.env.FRONTEND_PORT ?? 5174),
    strictPort: true,
    proxy: {
      "/api/ws": { target: `ws://127.0.0.1:${backend}`, ws: true },
      "/api": `http://127.0.0.1:${backend}`,
    },
  },
});
