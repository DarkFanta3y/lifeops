#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  console.error("Usage: node ua-arch-analyze.js <input.json> <output.json>");
  process.exit(1);
}

const patterns = new Map([
  ["routes", "api"], ["api", "api"], ["controllers", "api"], ["endpoints", "api"],
  ["handlers", "api"], ["serializers", "api"], ["controller", "api"], ["routers", "api"],
  ["blueprints", "api"], ["services", "service"], ["core", "service"], ["lib", "service"],
  ["domain", "service"], ["logic", "service"], ["signals", "service"], ["internal", "service"],
  ["composables", "service"], ["mailers", "service"], ["jobs", "service"],
  ["channels", "service"], ["models", "data"], ["db", "data"], ["data", "data"],
  ["persistence", "data"], ["repository", "data"], ["entities", "data"],
  ["entity", "data"], ["migrations", "data"], ["sql", "data"], ["database", "data"],
  ["schema", "data"], ["components", "ui"], ["views", "ui"], ["pages", "ui"],
  ["ui", "ui"], ["layouts", "ui"], ["screens", "ui"], ["middleware", "middleware"],
  ["plugins", "middleware"], ["interceptors", "middleware"], ["guards", "middleware"],
  ["utils", "utility"], ["helpers", "utility"], ["common", "utility"],
  ["shared", "utility"], ["tools", "utility"], ["templatetags", "utility"],
  ["pkg", "utility"], ["config", "config"], ["constants", "config"], ["env", "config"],
  ["settings", "config"], ["management", "config"], ["commands", "config"],
  ["__tests__", "test"], ["test", "test"], ["tests", "test"], ["spec", "test"],
  ["specs", "test"], ["types", "types"], ["interfaces", "types"], ["schemas", "types"],
  ["contracts", "types"], ["dtos", "types"], ["dto", "types"], ["request", "types"],
  ["response", "types"], ["hooks", "hooks"], ["store", "state"], ["state", "state"],
  ["reducers", "state"], ["actions", "state"], ["slices", "state"], ["assets", "assets"],
  ["static", "assets"], ["public", "assets"], ["cmd", "entry"], ["bin", "entry"],
  ["docs", "documentation"], ["documentation", "documentation"], ["wiki", "documentation"],
  ["deploy", "infrastructure"], ["deployment", "infrastructure"],
  ["infra", "infrastructure"], ["infrastructure", "infrastructure"],
  [".github", "ci-cd"], [".gitlab", "ci-cd"], [".circleci", "ci-cd"],
  ["k8s", "infrastructure"], ["kubernetes", "infrastructure"],
  ["helm", "infrastructure"], ["charts", "infrastructure"], ["terraform", "infrastructure"],
  ["tf", "infrastructure"], ["docker", "infrastructure"],
]);

function commonDirectoryPrefix(paths) {
  if (paths.length === 0) return [];
  const directories = paths.map((filePath) => filePath.split("/").slice(0, -1));
  const prefix = [];
  for (let index = 0; index < Math.min(...directories.map((parts) => parts.length)); index += 1) {
    const segment = directories[0][index];
    if (!directories.every((parts) => parts[index] === segment)) break;
    prefix.push(segment);
  }
  return prefix;
}

function extensionGroup(filePath) {
  const base = path.basename(filePath);
  if (/((^|[._-])(test|spec)([._-]|$))|(^test_.*\.py$)|(_test\.go$)|(Test\.java$)|(_spec\.rb$)|(Test\.php$)|(Tests\.cs$)/i.test(base)) return "test";
  if (/config/i.test(base)) return "config";
  const extension = path.extname(base).replace(/^\./, "");
  return extension || "root";
}

function filePattern(filePath) {
  const normalized = filePath.replace(/\\/g, "/");
  const base = path.basename(normalized);
  if (/((^|[._-])(test|spec)([._-]|$))|(^test_.*\.py$)|(_test\.go$)|(Test\.java$)|(_spec\.rb$)|(Test\.php$)|(Tests\.cs$)/i.test(base)) return "test";
  if (/\.d\.ts$/i.test(base)) return "types";
  if (["index.ts", "index.js", "__init__.py"].includes(base)) return "entry";
  if (base === "manage.py" || ["config.ru", "Application.java", "Program.cs"].includes(base)) return "entry";
  if (["wsgi.py", "asgi.py"].includes(base)) return "config";
  if (/^cmd\/[^/]+\/main\.go$/.test(normalized) || /^src\/(main|lib)\.rs$/.test(normalized)) return "entry";
  if (["Cargo.toml", "go.mod", "Gemfile", "pom.xml", "build.gradle", "composer.json"].includes(base)) return "config";
  if (/^Dockerfile(?:\..*)?$/.test(base) || /^docker-compose\..+/.test(base)) return "infrastructure";
  if (/\.(tf|tfvars)$/i.test(base) || base === "Makefile") return "infrastructure";
  if (/^\.github\/workflows\//.test(normalized) || base === ".gitlab-ci.yml" || base === "Jenkinsfile") return "ci-cd";
  if (/\.sql$/i.test(base)) return "data";
  if (/\.(graphql|gql|proto)$/i.test(base)) return "types";
  if (/\.(md|rst)$/i.test(base)) return "documentation";
  return null;
}

function directoryPattern(filePath) {
  for (const segment of filePath.replace(/\\/g, "/").split("/").slice(0, -1)) {
    if (patterns.has(segment.toLowerCase())) return patterns.get(segment.toLowerCase());
  }
  return null;
}

try {
  const input = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const { fileNodes, importEdges, allEdges } = input;
  if (!Array.isArray(fileNodes) || !Array.isArray(importEdges) || !Array.isArray(allEdges)) {
    throw new Error("Input must contain fileNodes, importEdges, and allEdges arrays");
  }

  const byId = new Map(fileNodes.map((node) => [node.id, node]));
  if (byId.size !== fileNodes.length) throw new Error("Duplicate file node IDs found");
  const prefixParts = commonDirectoryPrefix(fileNodes.map((node) => node.filePath || node.name));
  const relativeParts = fileNodes.map((node) => (node.filePath || node.name).split("/").slice(prefixParts.length));
  const flat = relativeParts.every((parts) => parts.length <= 1);
  const groupFor = new Map();
  const directoryGroups = {};
  fileNodes.forEach((node, index) => {
    const parts = relativeParts[index];
    const group = flat ? extensionGroup(node.filePath || node.name) : (parts.length > 1 ? parts[0] : "root");
    groupFor.set(node.id, group);
    (directoryGroups[group] ||= []).push(node.id);
  });

  const nodeTypeGroups = {};
  for (const node of fileNodes) (nodeTypeGroups[node.type] ||= []).push(node.id);

  const fileFanIn = Object.fromEntries(fileNodes.map((node) => [node.id, 0]));
  const fileFanOut = Object.fromEntries(fileNodes.map((node) => [node.id, 0]));
  const importAdjacency = Object.fromEntries(fileNodes.map((node) => [node.id, []]));
  const interGroupCounts = new Map();
  const groupImportsFrom = Object.fromEntries(Object.keys(directoryGroups).map((group) => [group, new Set()]));
  const groupImportedBy = Object.fromEntries(Object.keys(directoryGroups).map((group) => [group, new Set()]));
  for (const edge of importEdges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
    fileFanOut[edge.source] += 1;
    fileFanIn[edge.target] += 1;
    importAdjacency[edge.source].push(edge.target);
    const from = groupFor.get(edge.source);
    const to = groupFor.get(edge.target);
    if (from !== to) {
      interGroupCounts.set(`${from}\u0000${to}`, (interGroupCounts.get(`${from}\u0000${to}`) || 0) + 1);
      groupImportsFrom[from].add(to);
      groupImportedBy[to].add(from);
    }
  }

  const interGroupImports = [...interGroupCounts.entries()].map(([key, count]) => {
    const [from, to] = key.split("\u0000");
    return { from, to, count };
  }).sort((a, b) => b.count - a.count || a.from.localeCompare(b.from) || a.to.localeCompare(b.to));

  const intraGroupDensity = {};
  for (const group of Object.keys(directoryGroups)) {
    let internalEdges = 0;
    let totalEdges = 0;
    for (const edge of importEdges) {
      const sourceGroup = groupFor.get(edge.source);
      const targetGroup = groupFor.get(edge.target);
      if (sourceGroup === group || targetGroup === group) {
        totalEdges += 1;
        if (sourceGroup === group && targetGroup === group) internalEdges += 1;
      }
    }
    intraGroupDensity[group] = { internalEdges, totalEdges, density: totalEdges ? internalEdges / totalEdges : 0 };
  }

  const patternMatches = {};
  for (const group of Object.keys(directoryGroups)) {
    patternMatches[group] = patterns.get(group.toLowerCase()) || null;
  }

  const crossCounts = new Map();
  const nonCodeConnections = [];
  for (const edge of allEdges) {
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    if (!source || !target) continue;
    const key = `${source.type}\u0000${target.type}\u0000${edge.type}`;
    crossCounts.set(key, (crossCounts.get(key) || 0) + 1);
    if (source.type !== "file" || target.type !== "file") {
      nonCodeConnections.push({ source: edge.source, target: edge.target, edgeType: edge.type });
    }
  }
  const crossCategoryEdges = [...crossCounts.entries()].map(([key, count]) => {
    const [fromType, toType, edgeType] = key.split("\u0000");
    return { fromType, toType, edgeType, count };
  }).sort((a, b) => b.count - a.count);

  const paths = fileNodes.map((node) => node.filePath || node.name);
  const infraFiles = paths.filter((filePath) => {
    const p = filePath.toLowerCase();
    return /(^|\/)dockerfile(?:\.|$)/.test(p) || /docker-compose/.test(p) || /(^|\/)(k8s|kubernetes|helm|charts|terraform|tf)(\/|$)/.test(p) || /\.tf(vars)?$/.test(p) || /^\.github\/workflows\//.test(p) || /(^|\/)(\.gitlab-ci\.yml|jenkinsfile)$/.test(p);
  });
  const deploymentTopology = {
    hasDockerfile: paths.some((p) => /(^|\/)Dockerfile(?:\.|$)/.test(p)),
    hasCompose: paths.some((p) => /docker-compose/i.test(p)),
    hasK8s: paths.some((p) => /(^|\/)(k8s|kubernetes|helm|charts)(\/|$)/i.test(p)),
    hasTerraform: paths.some((p) => /(^|\/)(terraform|tf)(\/|$)|\.tf(vars)?$/i.test(p)),
    hasCI: paths.some((p) => /^\.github\/workflows\/|(^|\/)\.gitlab-ci\.yml$|(^|\/)Jenkinsfile$/i.test(p)),
    infraFiles,
  };

  const dataPipeline = {
    schemaFiles: paths.filter((p) => /(^|\/)(schema[^/]*\.(sql|graphql|gql|proto|prisma)|schemas?\/)|\.(graphql|gql|proto|prisma)$/i.test(p)),
    migrationFiles: paths.filter((p) => /(^|\/)migrations?\//i.test(p)),
    dataModelFiles: fileNodes.filter((node) => /data-model|数据模型|orm|database|sqlite|persistence|memory/i.test(`${node.filePath} ${(node.tags || []).join(" ")} ${node.summary || ""}`)).map((node) => node.filePath),
    apiHandlerFiles: fileNodes.filter((node) => /api-handler|端点|路由|fastapi|http/i.test(`${node.filePath} ${(node.tags || []).join(" ")} ${node.summary || ""}`)).map((node) => node.filePath),
  };

  const documentNodes = fileNodes.filter((node) => node.type === "document" || /\.(md|rst)$/i.test(node.filePath || ""));
  const documentedGroups = new Set();
  for (const documentNode of documentNodes) {
    const documentPath = documentNode.filePath || "";
    const documentGroup = groupFor.get(documentNode.id);
    if (/README\.md$/i.test(documentPath) && documentGroup) documentedGroups.add(documentGroup);
    const text = `${documentNode.summary || ""} ${(documentNode.tags || []).join(" ")}`.toLowerCase();
    for (const group of Object.keys(directoryGroups)) {
      if (text.includes(group.toLowerCase())) documentedGroups.add(group);
    }
  }
  const allGroups = Object.keys(directoryGroups);
  const docCoverage = {
    groupsWithDocs: documentedGroups.size,
    totalGroups: allGroups.length,
    coverageRatio: allGroups.length ? documentedGroups.size / allGroups.length : 0,
    undocumentedGroups: allGroups.filter((group) => !documentedGroups.has(group)),
  };

  const dependencyDirection = [];
  const processedPairs = new Set();
  for (const { from, to } of interGroupImports) {
    const pair = [from, to].sort().join("\u0000");
    if (processedPairs.has(pair)) continue;
    processedPairs.add(pair);
    const forward = interGroupCounts.get(`${from}\u0000${to}`) || 0;
    const reverse = interGroupCounts.get(`${to}\u0000${from}`) || 0;
    if (forward > reverse) dependencyDirection.push({ dependent: from, dependsOn: to, forward, reverse });
    else if (reverse > forward) dependencyDirection.push({ dependent: to, dependsOn: from, forward: reverse, reverse: forward });
    else dependencyDirection.push({ dependent: from, dependsOn: to, forward, reverse, bidirectional: true });
  }

  const filesPerGroup = Object.fromEntries(Object.entries(directoryGroups).map(([group, ids]) => [group, ids.length]));
  const nodeTypeCounts = Object.fromEntries(Object.entries(nodeTypeGroups).map(([type, ids]) => [type, ids.length]));
  const semanticSignals = Object.fromEntries(fileNodes.map((node) => [node.id, {
    filePath: node.filePath,
    type: node.type,
    summary: node.summary || "",
    tags: node.tags || [],
    directoryPattern: directoryPattern(node.filePath || ""),
    filePattern: filePattern(node.filePath || ""),
  }]));

  const results = {
    scriptCompleted: true,
    commonPathPrefix: prefixParts.length ? `${prefixParts.join("/")}/` : "",
    directoryGroups,
    nodeTypeGroups,
    importAdjacency,
    directoryAdjacency: Object.fromEntries(Object.keys(directoryGroups).map((group) => [group, {
      importsFrom: [...groupImportsFrom[group]].sort(),
      importedBy: [...groupImportedBy[group]].sort(),
    }])),
    crossCategoryEdges,
    nonCodeConnections,
    interGroupImports,
    intraGroupDensity,
    patternMatches,
    deploymentTopology,
    dataPipeline,
    docCoverage,
    dependencyDirection,
    fileStats: { totalFileNodes: fileNodes.length, filesPerGroup, nodeTypeCounts },
    fileFanIn,
    fileFanOut,
    semanticSignals,
  };
  fs.writeFileSync(outputPath, `${JSON.stringify(results, null, 2)}\n`);
} catch (error) {
  console.error(error.stack || String(error));
  process.exit(1);
}
