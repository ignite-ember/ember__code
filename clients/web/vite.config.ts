import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so the built assets load from file:// (Tauri),
// vscode-webview:// and jbcefbrowser:// origins, not just http.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    target: "es2022",
  },
});
