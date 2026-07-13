#!/usr/bin/env node

const fs = require("fs");

function fail(error) {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exit(1);
}

function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) {
    throw new Error("Usage: ua-tour-analyze.js <input.json> <output.json>");
  }

  const input = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const nodes = Array.isArray(input.nodes) ? input.nodes : [];
  const edges = Array.isArray(input.edges) ? input.edges : [];
  const layers = Array.isArray(input.layers) ? input.layers : [];
  const nodeById = new Map(nodes.map((node) => [node.id, node]));

  const fanIn = new Map(nodes.map((node) => [node.id, 0]));
  const fanOut = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    if (fanOut.has(edge.source)) fanOut.set(edge.source, fanOut.get(edge.source) + 1);
    if (fanIn.has(edge.target)) fanIn.set(edge.target, fanIn.get(edge.target) + 1);
  }

  const rank = (counts, field) => nodes
    .map((node) => ({id: node.id, [field]: counts.get(node.id), name: node.name}))
    .sort((a, b) => b[field] - a[field] || a.id.localeCompare(b.id))
    .slice(0, 20);
  const fanInRanking = rank(fanIn, "fanIn");
  const fanOutRanking = rank(fanOut, "fanOut");

  const sortedFanOut = [...fanOut.values()].sort((a, b) => a - b);
  const sortedFanIn = [...fanIn.values()].sort((a, b) => a - b);
  const percentile = (values, p) => values[Math.max(0, Math.ceil(values.length * p) - 1)] ?? 0;
  const highFanOutThreshold = percentile(sortedFanOut, 0.9);
  const lowFanInThreshold = percentile(sortedFanIn, 0.25);
  const entryNames = new Set([
    "index.ts", "index.js", "main.ts", "main.js", "app.ts", "app.js", "server.ts",
    "server.js", "mod.rs", "main.go", "main.py", "main.rs", "manage.py", "app.py",
    "wsgi.py", "asgi.py", "run.py", "__main__.py", "Application.java", "Main.java",
    "Program.cs", "config.ru", "index.php", "App.swift", "Application.kt", "main.cpp", "main.c",
  ]);
  const depthOfPath = (path) => String(path || "").split("/").filter(Boolean).length;
  const entryPointCandidates = nodes.map((node) => {
    let score = 0;
    const path = node.filePath || node.name || "";
    if (node.type === "file") {
      if (entryNames.has(node.name)) score += 3;
      if (depthOfPath(path) <= 2) score += 1;
      if ((fanOut.get(node.id) || 0) >= highFanOutThreshold) score += 1;
      if ((fanIn.get(node.id) || 0) <= lowFanInThreshold) score += 1;
    } else if (node.type === "document") {
      if (path === "README.md") score += 5;
      else if (/^[^/]+\.md$/i.test(path)) score += 2;
    }
    return {id: node.id, score, name: node.name, summary: node.summary};
  }).filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || (fanOut.get(b.id) || 0) - (fanOut.get(a.id) || 0) || a.id.localeCompare(b.id))
    .slice(0, 5);

  const codeEntry = entryPointCandidates.find((candidate) => nodeById.get(candidate.id)?.type === "file");
  const traversal = {startNode: codeEntry?.id || null, order: [], depthMap: {}, byDepth: {}};
  if (codeEntry) {
    const adjacency = new Map();
    for (const edge of edges) {
      if (!["imports", "calls"].includes(edge.type)) continue;
      if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) continue;
      if (!adjacency.has(edge.source)) adjacency.set(edge.source, []);
      adjacency.get(edge.source).push(edge.target);
    }
    for (const values of adjacency.values()) values.sort();
    const queue = [codeEntry.id];
    traversal.depthMap[codeEntry.id] = 0;
    for (let i = 0; i < queue.length; i += 1) {
      const current = queue[i];
      traversal.order.push(current);
      const depth = traversal.depthMap[current];
      const key = String(depth);
      if (!traversal.byDepth[key]) traversal.byDepth[key] = [];
      traversal.byDepth[key].push(current);
      for (const target of adjacency.get(current) || []) {
        if (Object.hasOwn(traversal.depthMap, target)) continue;
        traversal.depthMap[target] = depth + 1;
        queue.push(target);
      }
    }
  }

  const inventory = (types) => nodes.filter((node) => types.includes(node.type)).map((node) => ({
    id: node.id, name: node.name, type: node.type, summary: node.summary,
  }));
  const nonCodeFiles = {
    documentation: inventory(["document"]),
    infrastructure: inventory(["service", "pipeline", "resource"]),
    data: inventory(["table", "schema", "endpoint"]),
    config: inventory(["config"]),
  };

  const relationship = new Map();
  for (const edge of edges) {
    if (!["imports", "calls"].includes(edge.type)) continue;
    if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) continue;
    relationship.set(`${edge.source}\u0000${edge.target}\u0000${edge.type}`, true);
  }
  const clusters = [];
  const usedPairs = new Set();
  for (const edge of edges) {
    if (!["imports", "calls"].includes(edge.type)) continue;
    if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) continue;
    if (edge.source === edge.target) continue;
    if (!relationship.has(`${edge.target}\u0000${edge.source}\u0000${edge.type}`)) continue;
    const pair = [edge.source, edge.target].sort();
    const pairKey = pair.join("\u0000");
    if (usedPairs.has(pairKey)) continue;
    usedPairs.add(pairKey);
    const members = new Set(pair);
    let expanded = true;
    while (expanded && members.size < 5) {
      expanded = false;
      for (const candidate of nodes.map((node) => node.id).sort()) {
        if (members.has(candidate)) continue;
        let connections = 0;
        for (const member of members) {
          const connected = ["imports", "calls"].some((type) =>
            relationship.has(`${candidate}\u0000${member}\u0000${type}`) ||
            relationship.has(`${member}\u0000${candidate}\u0000${type}`));
          if (connected) connections += 1;
        }
        if (connections >= 2) {
          members.add(candidate);
          expanded = true;
          if (members.size >= 5) break;
        }
      }
    }
    const memberList = [...members].sort();
    const edgeCount = edges.filter((item) => members.has(item.source) && members.has(item.target)).length;
    clusters.push({nodes: memberList, edgeCount});
  }
  const uniqueClusters = [...new Map(clusters.map((cluster) => [cluster.nodes.join("\u0000"), cluster])).values()]
    .sort((a, b) => b.edgeCount - a.edgeCount || a.nodes.join().localeCompare(b.nodes.join()))
    .slice(0, 10);

  const nodeSummaryIndex = Object.fromEntries(nodes.map((node) => [node.id, {
    name: node.name, type: node.type, summary: node.summary,
  }]));
  const results = {
    scriptCompleted: true,
    entryPointCandidates,
    fanInRanking,
    fanOutRanking,
    bfsTraversal: traversal,
    nonCodeFiles,
    clusters: uniqueClusters,
    layers: {count: layers.length, list: layers.map(({id, name, description}) => ({id, name, description}))},
    nodeSummaryIndex,
    totalNodes: nodes.length,
    totalEdges: edges.length,
  };
  fs.writeFileSync(outputPath, `${JSON.stringify(results, null, 2)}\n`);
}

try {
  main();
} catch (error) {
  fail(error);
}
