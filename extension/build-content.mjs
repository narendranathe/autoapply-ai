/**
 * build-content.mjs — Builds each Chrome content script as a self-contained IIFE.
 *
 * Chrome content scripts cannot use ES module `import` statements, so each
 * must be bundled with all dependencies inlined (no shared chunks).
 */

import { build } from "vite";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const contentScripts = ["detector", "floatingPanel", "gmailContent"];

for (const script of contentScripts) {
  console.log(`\nBuilding content script: ${script}...`);
  await build({
    configFile: false,
    build: {
      outDir: resolve(__dirname, "dist"),
      emptyOutDir: false,
      rollupOptions: {
        input: { [`content/${script}`]: resolve(__dirname, `src/content/${script}.ts`) },
        output: {
          format: "iife",
          name: `__aap_${script}`,
          dir: resolve(__dirname, "dist"),
          entryFileNames: "[name].js",
        },
      },
    },
    resolve: {
      alias: {
        "@": resolve(__dirname, "src"),
      },
    },
  });
}

console.log("\nAll content scripts built successfully.");
