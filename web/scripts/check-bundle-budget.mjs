import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const ENTRY_GZIP_BUDGET = 300 * 1024;
const CHUNK_RAW_BUDGET = 500 * 1024;
const distDir = new URL("../dist/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL(".vite/manifest.json", distDir), "utf8"));
const entryKey = Object.keys(manifest).find(
  (key) => key === "src/main.jsx" || manifest[key].src === "src/main.jsx",
) || Object.keys(manifest).find((key) => manifest[key].isEntry);

if (!entryKey) throw new Error("Vite manifest 中缺少应用入口");

const staticFiles = new Set();
function collectStaticClosure(key) {
  const item = manifest[key];
  if (!item || staticFiles.has(item.file)) return;
  if (item.file.endsWith(".js")) staticFiles.add(item.file);
  for (const importedKey of item.imports || []) collectStaticClosure(importedKey);
}
collectStaticClosure(entryKey);

const entryGzipBytes = [...staticFiles].reduce((total, file) => {
  const contents = readFileSync(new URL(file, distDir));
  return total + gzipSync(contents).byteLength;
}, 0);

const assetDir = new URL("assets/", distDir);
const oversizedChunks = readdirSync(assetDir)
  .filter((file) => file.endsWith(".js"))
  .map((file) => ({ file, bytes: statSync(join(assetDir.pathname, file)).size }))
  .filter(({ bytes }) => bytes > CHUNK_RAW_BUDGET);

const formatKb = (bytes) => `${(bytes / 1024).toFixed(1)} KB`;
console.log(
  `Bundle budget: entry static gzip ${formatKb(entryGzipBytes)} / ${formatKb(ENTRY_GZIP_BUDGET)}`,
);

if (entryGzipBytes > ENTRY_GZIP_BUDGET || oversizedChunks.length > 0) {
  for (const chunk of oversizedChunks) {
    console.error(
      `Chunk ${chunk.file}: ${formatKb(chunk.bytes)} > ${formatKb(CHUNK_RAW_BUDGET)}`,
    );
  }
  process.exitCode = 1;
}
