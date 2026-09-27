import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  // `vite preview` serves the production build, which is what the Playwright
  // spec runs against. That matters: React StrictMode double-invokes effects in
  // development only, so a dev-server run would fire every mount-time request
  // twice and make request-count assertions meaningless.
  //
  // Preview does not inherit `server.proxy`, hence the second entry. It points
  // at the E2E backend port (8001, not 8000) so a running dev server is not
  // disturbed — see scripts/e2e-backend.mjs.
  preview: {
    proxy: {
      "/api": "http://127.0.0.1:8001",
    },
  },
});
