import fs from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";

/**
 * Both apps read config from the ROOT .env (one file, names from .env.example).
 * Only NEXT_PUBLIC_* values are exposed to the browser; secrets are never read here.
 * Real environment variables (e.g. on Render) take precedence over the file.
 */
function publicEnvFromRootDotenv(): Record<string, string> {
  const out: Record<string, string> = {};
  const file = path.resolve(process.cwd(), "..", ".env");
  if (fs.existsSync(file)) {
    for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*(NEXT_PUBLIC_[A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m) out[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  }
  for (const [k, v] of Object.entries(process.env)) {
    if (k.startsWith("NEXT_PUBLIC_") && v) out[k] = v;
  }
  return out;
}

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  env: publicEnvFromRootDotenv(),
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
