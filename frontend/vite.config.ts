import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  server: {
    port: 5173,
    // The API is same-origin in development so the browser never deals with
    // CORS, and the production build can be served from the same host.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // The live suite needs a running backend and its own jsdom origin, so
    // it runs from src/test/live.config.ts via `pnpm test:live`.
    exclude: ["**/node_modules/**", "**/dist/**", "**/*.live.test.tsx"],
  },
});
