/** Vitest config for the live integration suite.
 *
 *  Separate from the unit config because these talk to a real server: they
 *  need a jsdom origin that matches the dev server so relative /api URLs
 *  resolve through its proxy, and they must not run by default. */

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const APP_URL = process.env.APP_URL ?? "http://localhost:5173";

export default defineConfig({
  plugins: [react()],
  // Node's fetch does not resolve a relative URL against the jsdom
  // location, so the suite needs an absolute base pointing at the dev
  // server -- which proxies to Django exactly as the browser does.
  define: { "import.meta.env.VITE_API_BASE": JSON.stringify(`${APP_URL}/api/v1`) },
  resolve: { alias: { "@": new URL("../", import.meta.url).pathname } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.live.test.tsx"],
    environmentOptions: {
      jsdom: { url: APP_URL },
    },
    testTimeout: 30_000,
    hookTimeout: 30_000,
    // Shared server state, so no parallelism.
    fileParallelism: false,
  },
});
