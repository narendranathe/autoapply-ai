import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";
import fs from "fs";

// Vite plugin: copy Chrome extension static files to dist after build.
function copyExtensionStaticFiles() {
  return {
    name: "copy-extension-static",
    closeBundle() {
      // manifest.json — required at dist root
      fs.copyFileSync("manifest.json", "dist/manifest.json");

      // icons/ — required for browser action icons
      if (fs.existsSync("icons")) {
        fs.cpSync("icons", "dist/icons", { recursive: true });
      }
    },
  };
}

// Chrome MV3 multi-entry build.
// Each entry compiles to its own output file in dist/.
export default defineConfig({
  plugins: [react(), copyExtensionStaticFiles()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        // Background service worker (no DOM)
        "background/worker": resolve(__dirname, "src/background/worker.ts"),
        // Content script (injected into every page)
        "content/detector": resolve(__dirname, "src/content/detector.ts"),
        // Side panel React app
        "sidepanel/index": resolve(__dirname, "src/sidepanel/index.html"),
        // Options / settings page
        "src/options/index": resolve(__dirname, "src/options/index.html"),
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: "[name].[ext]",
      },
    },
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
});
