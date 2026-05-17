import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";
import fs from "fs";

const LOCALHOST_NEEDLES = ["localhost", "127.0.0.1"];

function isLocalhostPattern(pattern: string): boolean {
  return LOCALHOST_NEEDLES.some((needle) => pattern.includes(needle));
}

/**
 * Strip every CSP directive value that points at loopback so the
 * production CSP never whitelists ``http://localhost:8000``.
 *
 * P1-E (#198 round 2): connect-src now exists; we apply the same prod
 * scrubbing it already applies to host_permissions.
 */
function stripLocalhostFromCspDirective(directiveValue: string): string {
  // ``directiveValue`` is the space-separated token list following the
  // directive name. Filter loopback origins; preserve order.
  return directiveValue
    .split(/\s+/)
    .filter((token) => token.length > 0 && !isLocalhostPattern(token))
    .join(" ");
}

function stripLocalhostFromCsp(csp: string): string {
  // CSP entries are semicolon-separated directives. Each directive is
  // "name token token...". Apply the strip to every token list.
  return csp
    .split(";")
    .map((directive) => {
      const trimmed = directive.trim();
      if (!trimmed) return "";
      const firstSpace = trimmed.indexOf(" ");
      if (firstSpace < 0) return trimmed; // bare directive (no tokens)
      const name = trimmed.slice(0, firstSpace);
      const rest = trimmed.slice(firstSpace + 1);
      const cleaned = stripLocalhostFromCspDirective(rest);
      return cleaned ? `${name} ${cleaned}` : name;
    })
    .filter((s) => s.length > 0)
    .join("; ");
}

// Strip localhost host_permissions AND CSP entries for production builds
// so the published extension never asks Chrome users for permission to
// query the developer's loopback API server.
function copyExtensionStaticFiles(mode: string) {
  return {
    name: "copy-extension-static",
    closeBundle() {
      const sourceManifest = JSON.parse(
        fs.readFileSync("manifest.json", "utf8")
      );

      if (mode === "production" && Array.isArray(sourceManifest.host_permissions)) {
        sourceManifest.host_permissions = sourceManifest.host_permissions.filter(
          (entry: string) => !isLocalhostPattern(entry)
        );
      }

      // P1-E: prod-strip loopback origins from extension_pages CSP too.
      if (
        mode === "production" &&
        sourceManifest.content_security_policy?.extension_pages
      ) {
        sourceManifest.content_security_policy.extension_pages =
          stripLocalhostFromCsp(sourceManifest.content_security_policy.extension_pages);
      }

      fs.writeFileSync(
        "dist/manifest.json",
        JSON.stringify(sourceManifest, null, 2) + "\n"
      );

      if (fs.existsSync("icons")) {
        fs.cpSync("icons", "dist/icons", { recursive: true });
      }
    },
  };
}

// Chrome MV3 main build: background service worker + sidepanel + options page.
// Content scripts are built separately in vite.content.config.ts as IIFE bundles
// because Chrome content scripts cannot use ES module import statements.
export default defineConfig(({ mode }) => ({
  plugins: [react(), copyExtensionStaticFiles(mode)],
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
}));
