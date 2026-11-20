import { cpSync, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const srcDist = resolve(here, "..", "dist");
const targetStatic = resolve(here, "..", "..", "gis_agent", "server", "static");

if (!existsSync(srcDist)) {
  console.error("frontend/dist does not exist; run vite build first.");
  process.exit(1);
}

rmSync(targetStatic, { recursive: true, force: true });
mkdirSync(targetStatic, { recursive: true });
cpSync(srcDist, targetStatic, { recursive: true });
writeFileSync(resolve(targetStatic, ".gitkeep"), "");
console.log(`Synced ${srcDist} -> ${targetStatic}`);
