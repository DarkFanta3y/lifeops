#!/usr/bin/env node

const fs = require("fs");

const [resultsPath, outputPath] = process.argv.slice(2);
if (!resultsPath || !outputPath) {
  console.error("Usage: node ua-arch-assign.js <ua-arch-results.json> <layers.json>");
  process.exit(1);
}

try {
  const results = JSON.parse(fs.readFileSync(resultsPath, "utf8"));
  if (!results.scriptCompleted) throw new Error("Structural analysis did not complete");

  const layers = [
    {
      id: "layer:ui",
      name: "Web 控制台 UI 层",
      description: "承载 React/Vite 管理控制台的页面入口、交互组件、后端 API 客户端、滚动辅助与响应式样式。",
      nodeIds: [],
    },
    {
      id: "layer:api",
      name: "Web API 层",
      description: "提供 FastAPI 应用边界、SSE 对话流以及会话、记忆、RAG、Skill、Tool/MCP 和运行追踪接口。",
      nodeIds: [],
    },
    {
      id: "layer:agent-runtime",
      name: "Agent 编排与运行时层",
      description: "统筹 Agent 执行循环、分层上下文压缩、工具安全策略、错误模型与 trace 生命周期。",
      nodeIds: [],
    },
    {
      id: "layer:llm",
      name: "LLM 接入层",
      description: "封装 OpenAI 兼容的异步与流式调用，并定义消息、响应和工具调用协议模型。",
      nodeIds: [],
    },
    {
      id: "layer:extension",
      name: "工具与扩展集成层",
      description: "管理 Skill 的发现与匹配、内置工具注册执行，以及 MCP 客户端、适配器和外部 server 预设。",
      nodeIds: [],
    },
    {
      id: "layer:knowledge",
      name: "检索与长期记忆层",
      description: "实现 Markdown 知识索引与混合 RAG 检索，并负责跨会话摘要、偏好和知识图谱的学习与召回。",
      nodeIds: [],
    },
    {
      id: "layer:data",
      name: "数据持久化层",
      description: "维护 SQLite schema、综合数据访问、旧 JSONL 迁移与兼容历史存储，为会话和运行数据提供本地持久化。",
      nodeIds: [],
    },
    {
      id: "layer:utility",
      name: "共享工具层",
      description: "提供统一日志初始化与 Unicode 文本清洗等被多个后端子系统复用的基础能力。",
      nodeIds: [],
    },
    {
      id: "layer:project-support",
      name: "项目配置与文档层",
      description: "集中项目依赖、环境变量、Python 与 Vite 构建设置、图谱扫描配置及中文上手和架构说明。",
      nodeIds: [],
    },
    {
      id: "layer:test",
      name: "测试与可靠性评估层",
      description: "覆盖 Agent 降级、工具策略、运行追踪与存储、FastAPI SSE、安全脱敏和前端滚动边界行为。",
      nodeIds: [],
    },
  ];
  const byLayerId = new Map(layers.map((layer) => [layer.id, layer]));

  function layerFor(nodeId, signal) {
    const filePath = signal.filePath;
    if (
      signal.type === "config"
      || signal.type === "document"
      || filePath === ".python-version"
      || filePath === ".understand-anything/.understandignore"
      || filePath === "src/lifeops/core/config.py"
      || filePath === "web/vite.config.js"
    ) return "layer:project-support";
    if (filePath.startsWith("tests/") || filePath === "web/src/scroll.test.mjs") return "layer:test";
    if (filePath.startsWith("src/lifeops/web/")) return "layer:api";
    if (filePath.startsWith("web/")) return "layer:ui";
    if (
      filePath === "src/lifeops/agent.py"
      || filePath === "src/lifeops/__init__.py"
      || (filePath.startsWith("src/lifeops/core/") && filePath !== "src/lifeops/core/config.py")
      || filePath.startsWith("src/lifeops/runtime/")
    ) return "layer:agent-runtime";
    if (filePath.startsWith("src/lifeops/llm/")) return "layer:llm";
    if (filePath.startsWith("src/lifeops/skills/") || filePath.startsWith("src/lifeops/tools/")) return "layer:extension";
    if (filePath.startsWith("src/lifeops/rag/") || filePath.startsWith("src/lifeops/memory/")) return "layer:knowledge";
    if (filePath === "src/lifeops/history.py" || filePath.startsWith("src/lifeops/storage/")) return "layer:data";
    if (filePath.startsWith("src/lifeops/utils/")) return "layer:utility";
    throw new Error(`No semantic layer assignment for ${nodeId} (${filePath})`);
  }

  for (const [nodeId, signal] of Object.entries(results.semanticSignals)) {
    byLayerId.get(layerFor(nodeId, signal)).nodeIds.push(nodeId);
  }
  for (const layer of layers) layer.nodeIds.sort();

  const expectedIds = Object.keys(results.semanticSignals).sort();
  const assignedIds = layers.flatMap((layer) => layer.nodeIds);
  const uniqueIds = new Set(assignedIds);
  if (layers.length < 3 || layers.length > 10) throw new Error(`Invalid layer count: ${layers.length}`);
  if (layers.some((layer) => layer.nodeIds.length === 0)) throw new Error("Empty layer detected");
  if (assignedIds.length !== results.fileStats.totalFileNodes) {
    throw new Error(`Assigned ${assignedIds.length}, expected ${results.fileStats.totalFileNodes}`);
  }
  if (uniqueIds.size !== assignedIds.length) throw new Error("A file node was assigned more than once");
  if (JSON.stringify([...uniqueIds].sort()) !== JSON.stringify(expectedIds)) {
    throw new Error("Layer assignments do not exactly match the structural-analysis node IDs");
  }

  fs.writeFileSync(outputPath, `${JSON.stringify(layers, null, 2)}\n`);
} catch (error) {
  console.error(error.stack || String(error));
  process.exit(1);
}
