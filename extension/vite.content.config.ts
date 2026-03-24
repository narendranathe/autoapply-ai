/**
 * vite.content.config.ts — Builds a single Chrome content script as a self-contained IIFE.
 *
 * Chrome content scripts cannot use ES module `import` statements, so they must be
 * bundled as IIFE with all dependencies inlined (no shared chunks).
 *
 * Usage (via package.json build:content script):
 *   CONTENT_SCRIPT=detector vite build --config vite.content.config.ts
 *   CONTENT_SCRIPT=floatingPanel vite build --config vite.content.config.ts
 *   CONTENT_SCRIPT=gmailContent vite build --config vite.content.config.ts
 */

import { defineConfig } from "vite";
import { resolve } from "path";

const script = process.env.CONTENT_SCRIPT ?? "detector";

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: false, // don't wipe dist — main build runs first
    lib: {
      entry: resolve(__dirname, `src/content/${script}.ts`),
      formats: ["iife"],
      name: `__aap_${script}`,
      fileName: () => `content/${script}`,
    },
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
});
