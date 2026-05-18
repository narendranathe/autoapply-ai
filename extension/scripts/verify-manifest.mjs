/**
 * verify-manifest.mjs — Post-build guard for the production Chrome extension.
 *
 * Fails the build if `dist/manifest.json` retains any loopback host permission
 * (localhost / 127.0.0.1) or any loopback CSP whitelist entry. Chrome flags
 * those as sensitive on store review, so a published bundle must never ship
 * them.
 */

import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const manifestPath = resolve(__dirname, "..", "dist", "manifest.json");

if (!existsSync(manifestPath)) {
  console.error(`verify-manifest: ${manifestPath} not found — run \`npm run build\` first.`);
  process.exit(1);
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const hostPermissions = Array.isArray(manifest.host_permissions)
  ? manifest.host_permissions
  : [];

const hostOffenders = hostPermissions.filter(
  (entry) => entry.includes("localhost") || entry.includes("127.0.0.1")
);

if (hostOffenders.length > 0) {
  console.error(
    `verify-manifest: production manifest contains loopback host_permissions: ${JSON.stringify(
      hostOffenders
    )}`
  );
  process.exit(1);
}

// P1-E (#198 round 2): also scan the CSP. ``connect-src`` (and friends)
// must not whitelist loopback origins in production.
const csp = manifest.content_security_policy?.extension_pages ?? "";
if (csp.includes("localhost") || csp.includes("127.0.0.1")) {
  console.error(
    `verify-manifest: production CSP contains loopback origin: ${csp}`
  );
  process.exit(1);
}

console.log("verify-manifest: dist/manifest.json passes loopback guard.");
