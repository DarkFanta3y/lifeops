#!/usr/bin/env node

const fs = require("fs");

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  console.error("Usage: node ua-arch-prepare.js <assembled-graph.json> <ua-arch-input.json>");
  process.exit(1);
}

try {
  const graph = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const fileLevelTypes = new Set([
    "file",
    "config",
    "document",
    "service",
    "pipeline",
    "table",
    "schema",
    "resource",
    "endpoint",
  ]);
  const fileNodes = graph.nodes.filter((node) => fileLevelTypes.has(node.type));
  const fileNodeIds = new Set(fileNodes.map((node) => node.id));
  const fileLevelEdges = graph.edges.filter(
    (edge) => fileNodeIds.has(edge.source) && fileNodeIds.has(edge.target),
  );
  const payload = {
    fileNodes,
    importEdges: fileLevelEdges.filter((edge) => edge.type === "imports"),
    allEdges: fileLevelEdges,
  };
  fs.writeFileSync(outputPath, `${JSON.stringify(payload, null, 2)}\n`);
} catch (error) {
  console.error(error.stack || String(error));
  process.exit(1);
}
