import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the engine so the overlay can use same-origin URLs.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
      "/api": "http://127.0.0.1:8000",
      "/samples": "http://127.0.0.1:8000",
    },
  },
});
