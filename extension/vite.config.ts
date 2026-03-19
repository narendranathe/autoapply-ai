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

// Chrome MV3 main build: background service worker + sidepanel + options page.
// Content scripts are built separately in vite.content.config.ts as IIFE bundles
// because Chrome content scripts cannot use ES module import statements.
export default defineConfig({
  plugins: [react(), copyExtensionStaticFiles()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        // Background service worker (no DOM) — runs as ES module (manifest declares type:module)
        "background/worker": resolve(__dirname, "src/background/worker.ts"),
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
