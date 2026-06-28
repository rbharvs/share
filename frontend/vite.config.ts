import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dashboard SPA. In `mise run dev` the browser hits the local Access proxy at
// share.localhost:5174, which forwards to this Vite server; Vite in turn proxies
// `/api/*` to FastAPI on :8000, preserving the original Host so FastAPI still
// classifies the request as the dashboard origin (changeOrigin: false). The
// proxy-injected Cf-Access-Jwt-Assertion header is forwarded through untouched.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // The local Access proxy forwards Host: share.localhost:5174 through to Vite.
    allowedHosts: ["share.localhost", "localhost"],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        // Preserve the incoming Host so FastAPI's host gate sees the dashboard
        // origin (with its dev port) rather than the proxy target.
        changeOrigin: false,
      },
    },
  },
  build: {
    // Built assets are copied into the backend package (src/share/static) and
    // are gitignored; FastAPI serves them production-shape under `mise run preview`.
    outDir: "dist",
    emptyOutDir: true,
  },
});
