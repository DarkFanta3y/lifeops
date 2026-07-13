import fs from "node:fs";
import path from "node:path";

const projectRoot = "/Users/xin/Desktop/assests/lifeops";
const inputPath = path.join(projectRoot, ".understand-anything/tmp/ua-file-analyzer-input-9.json");
const extractionPath = path.join(projectRoot, ".understand-anything/tmp/ua-file-extract-results-9.json");
const batchesPath = path.join(projectRoot, ".understand-anything/intermediate/batches.json");
const outputPath = path.join(projectRoot, ".understand-anything/intermediate/batch-9.json");

const input = JSON.parse(fs.readFileSync(inputPath, "utf8"));
const extraction = JSON.parse(fs.readFileSync(extractionPath, "utf8"));
const batch = JSON.parse(fs.readFileSync(batchesPath, "utf8")).batches.find(
  (entry) => entry.batchIndex === 9,
);

if (!batch) throw new Error("batches.json 中不存在 batchIndex=9");
if (JSON.stringify(input.batchFiles) !== JSON.stringify(batch.files)) {
  throw new Error("batchFiles 未与 batchIndex=9 的 files 原样保持一致");
}
if (JSON.stringify(input.batchImportData) !== JSON.stringify(batch.batchImportData)) {
  throw new Error("batchImportData 未与 batchIndex=9 的原始值保持一致");
}

const fileMeta = {
  ".python-version": {
    summary: "固定项目使用 Python 3.13，确保本地开发、依赖解析与测试运行采用一致的解释器版本。",
    tags: ["运行环境", "python", "版本约束"],
    complexity: "simple",
  },
  ".understand-anything/.understandignore": {
    summary: "为代码知识图谱扫描提供忽略规则模板，汇集仓库现有忽略项、测试文件模式与常见语言产物的可选排除建议。",
    tags: ["扫描配置", "忽略规则", "代码分析"],
    complexity: "moderate",
  },
  ".understand-anything/config.json": {
    summary: "配置 Understand Anything 的图谱文本输出语言，当前指定为中文。",
    tags: ["配置", "本地化", "代码分析"],
    complexity: "simple",
  },
  "src/lifeops/__init__.py": {
    summary: "定义 lifeops 顶层 Python 包，并公开当前软件版本 0.1.0。",
    tags: ["包入口", "版本信息", "python"],
    complexity: "simple",
  },
  "src/lifeops/core/__init__.py": {
    summary: "声明 lifeops.core 核心包边界，为配置与上下文管理模块提供命名空间。",
    tags: ["包入口", "核心模块", "命名空间"],
    complexity: "simple",
  },
  "src/lifeops/memory/types.py": {
    summary: "定义对话摘要、用户偏好以及知识实体和关系的不可变数据模型，为记忆提取与知识表示提供统一结构。",
    tags: ["数据模型", "记忆系统", "知识图谱", "dataclass"],
    complexity: "simple",
    languageNotes: "使用 frozen dataclass 表达不可变值对象，并通过 default_factory 安全初始化列表和字典字段。",
  },
  "src/lifeops/rag/__init__.py": {
    summary: "作为 RAG 包入口，通过模块级 __getattr__ 延迟加载索引器与检索器，避免导入包时立即加载其实现依赖。",
    tags: ["包入口", "延迟加载", "rag", "检索"],
    complexity: "simple",
    languageNotes: "利用 PEP 562 的模块级 __getattr__ 实现惰性属性解析。",
  },
  "src/lifeops/utils/__init__.py": {
    summary: "声明通用工具包命名空间，供项目级辅助函数模块组织与扩展。",
    tags: ["包入口", "工具函数", "命名空间"],
    complexity: "simple",
  },
  "src/lifeops/web/__init__.py": {
    summary: "声明 lifeops.web 后端 Web 包边界，为 FastAPI 应用与接口模块提供命名空间。",
    tags: ["包入口", "web后端", "fastapi"],
    complexity: "simple",
  },
  "tests/evals/__init__.py": {
    summary: "将运行时可靠性评估组织为独立测试包，承载带 evals 标记的场景。",
    tags: ["测试包", "可靠性评估", "pytest"],
    complexity: "simple",
  },
  "tests/evals/test_runtime_reliability.py": {
    summary: "评估 Agent 在纯文本回答和危险 Bash 请求场景中的运行时可靠性，验证运行状态、策略拒绝及追踪事件。",
    tags: ["可靠性测试", "工具策略", "运行时追踪", "pytest"],
    complexity: "moderate",
  },
  "tests/fixtures/runtime_eval_cases.py": {
    summary: "定义运行时评估案例的数据结构与基础案例集，并校验案例名称唯一，便于数据驱动的可靠性评估。",
    tags: ["测试夹具", "评估案例", "数据驱动测试", "dataclass"],
    complexity: "simple",
  },
  "tests/helpers/fake_runtime.py": {
    summary: "提供脚本化 LLM 客户端与可记录调用的成功或失败工具处理器工厂，用于构造可预测的异步运行时测试。",
    tags: ["测试辅助", "模拟客户端", "工具处理器", "异步测试"],
    complexity: "simple",
    languageNotes: "异步生成器复用 chat 结果模拟流式 token，并由闭包捕获工厂状态记录工具调用。",
  },
  "tests/test_agent_failure_recovery.py": {
    summary: "验证 Agent 面对检索路由 JSON 解析失败和 RAG 检索异常时仍能降级处理，并记录可诊断的错误结果。",
    tags: ["故障恢复测试", "rag", "错误降级", "pytest"],
    complexity: "simple",
  },
  "tests/test_agent_tool_policy.py": {
    summary: "覆盖 Agent 层工具策略集成，确认危险命令在处理器执行前被拒绝，并在达到最大迭代次数时持久化失败状态。",
    tags: ["集成测试", "工具策略", "失败状态", "agent"],
    complexity: "moderate",
  },
  "tests/test_runtime_api.py": {
    summary: "测试 FastAPI 运行时接口的 SSE 完成事件、运行记录查询、缺失资源响应以及脱敏后的公开工具策略摘要。",
    tags: ["api测试", "sse", "运行记录", "安全脱敏"],
    complexity: "moderate",
  },
  "tests/test_runtime_errors.py": {
    summary: "验证运行时错误枚举可序列化，并确认 AgentRuntimeError 能转换为包含分类与上下文的追踪载荷。",
    tags: ["错误处理测试", "序列化", "运行时追踪"],
    complexity: "simple",
  },
  "tests/test_runtime_memory_context.py": {
    summary: "验证上下文压缩事件以及工具和技能使用事件可按运行 ID 从持久化存储中查询。",
    tags: ["记忆测试", "上下文压缩", "使用追踪", "持久化"],
    complexity: "simple",
  },
  "tests/test_runtime_store.py": {
    summary: "覆盖运行时存储的运行创建、追踪事件排序、大载荷截断和会话运行列表查询行为。",
    tags: ["存储测试", "运行记录", "事件排序", "载荷截断"],
    complexity: "simple",
  },
  "tests/test_tool_policy.py": {
    summary: "全面验证工具策略引擎对安全读取、危险 Bash、文件编辑、MCP 工具和不同策略模式的决策，并检查公开摘要不泄露敏感配置。",
    tags: ["单元测试", "工具策略", "安全规则", "配置校验"],
    complexity: "moderate",
  },
  "web/index.html": {
    summary: "提供 LifeOps React 控制台的中文 HTML 外壳，设置图标与视口，并把前端入口挂载到 root 容器。",
    tags: ["前端入口", "html", "react挂载"],
    complexity: "simple",
  },
  "web/package.json": {
    summary: "定义 LifeOps Web 控制台的 Vite 开发与构建脚本，以及 React、Ant Design 和 Markdown 渲染依赖。",
    tags: ["前端配置", "依赖管理", "构建系统", "vite"],
    complexity: "simple",
  },
  "web/src/styles.css": {
    summary: "集中定义 LifeOps 控制台的侧边栏、聊天、表格、Markdown、搜索与日志查看界面样式，并针对平板和移动端提供响应式布局。",
    tags: ["界面样式", "响应式设计", "聊天界面", "日志视图", "css"],
    complexity: "complex",
    languageNotes: "通过 900px 与 640px 媒体查询调整布局，并以 Ant Design 类选择器覆盖组件内部样式。",
  },
  "web/vite.config.js": {
    summary: "配置 Vite 使用 React 插件，并将本地开发服务器固定在 127.0.0.1:5173。",
    tags: ["构建配置", "开发服务器", "react", "vite"],
    complexity: "simple",
    languageNotes: "采用 ESM 与 defineConfig 提供编辑器友好的 Vite 配置类型推断。",
  },
};

const nodeMeta = {
  "src/lifeops/memory/types.py:ConversationSummary": ["承载一次对话的摘要、关键决策、行动项、主题、语气与可选向量表示。", ["数据模型", "对话摘要", "记忆"]],
  "src/lifeops/memory/types.py:UserPreference": ["表示从用户行为中提取的偏好键值，并附带置信度与证据。", ["数据模型", "用户偏好", "置信度"]],
  "src/lifeops/memory/types.py:KnowledgeEntity": ["表示知识图谱中的命名实体、实体类型及可扩展属性。", ["数据模型", "知识实体", "知识图谱"]],
  "src/lifeops/memory/types.py:KnowledgeRelation": ["描述两个知识实体之间的关系类型、置信度与扩展属性。", ["数据模型", "知识关系", "知识图谱"]],
  "src/lifeops/rag/__init__.py:__getattr__": ["按属性名惰性导入并返回 RAGIndexer 或 RAGRetriever，对未知名称抛出 AttributeError。", ["延迟加载", "包接口", "rag"]],
  "tests/evals/test_runtime_reliability.py:BashParams": ["定义可靠性评估中 Bash 工具所需的命令参数模型。", ["测试模型", "工具参数", "bash"]],
  "tests/evals/test_runtime_reliability.py:_make_agent": ["构造带临时 SQLite 存储、追踪器、平衡策略与脚本化 LLM 响应的测试 Agent。", ["测试工厂", "agent", "运行时"]],
  "tests/evals/test_runtime_reliability.py:test_plain_answer_no_tool_eval": ["验证无需工具的普通回答可完成运行，且不会产生工具请求事件。", ["可靠性测试", "纯文本回答", "运行状态"]],
  "tests/evals/test_runtime_reliability.py:test_dangerous_bash_denied_eval": ["验证删除根目录的 Bash 请求被策略拒绝、处理器未执行且拒绝事件被记录。", ["可靠性测试", "危险命令", "策略拒绝"]],
  "tests/fixtures/runtime_eval_cases.py:RuntimeEvalCase": ["定义数据驱动运行时评估案例的输入脚本、工具结果与预期状态和事件。", ["测试夹具", "评估模型", "dataclass"]],
  "tests/fixtures/runtime_eval_cases.py:test_runtime_eval_case_names_are_unique": ["校验所有运行时评估案例名称唯一，避免参数化测试发生歧义。", ["夹具校验", "唯一性", "pytest"]],
  "tests/helpers/fake_runtime.py:ScriptedLLMClient": ["按预设顺序返回聊天响应并支持 token 流式输出，用于确定性地替代真实 LLM 客户端。", ["测试替身", "llm客户端", "异步流"]],
  "tests/helpers/fake_runtime.py:FakeToolHandlerFactory": ["生成可记录参数的成功或失败异步工具处理器，便于断言工具调用行为。", ["测试工厂", "工具处理器", "调用记录"]],
  "tests/test_agent_failure_recovery.py:test_invalid_retrieval_route_json_does_not_block_reply": ["验证检索路由返回无效 JSON 时记录解析错误，同时继续生成用户可见回答。", ["故障恢复测试", "解析错误", "降级回答"]],
  "tests/test_agent_failure_recovery.py:test_rag_tool_failure_degrades_to_tool_result": ["验证 RAG 检索器抛出异常时转换为带 rag_error 元数据的失败工具结果。", ["故障恢复测试", "rag", "错误转换"]],
  "tests/test_agent_tool_policy.py:BashParams": ["定义 Agent 工具策略集成测试所使用的 Bash 命令参数模型。", ["测试模型", "工具参数", "bash"]],
  "tests/test_agent_tool_policy.py:test_agent_policy_denies_dangerous_tool_before_handler_runs": ["验证 Agent 在执行处理器前拒绝危险 Bash 调用，并写入工具策略决策事件。", ["集成测试", "策略拒绝", "执行拦截"]],
  "tests/test_agent_tool_policy.py:test_agent_records_run_failure_on_max_iterations": ["验证工具循环达到最大迭代次数时，Agent 返回失败提示并持久化失败类型。", ["集成测试", "迭代限制", "失败记录"]],
  "tests/test_runtime_api.py:make_config": ["构造面向 API 测试的临时应用配置，可切换工具策略模式并隔离存储路径。", ["测试工厂", "应用配置", "api测试"]],
  "tests/test_runtime_api.py:request": ["通过 ASGITransport 向内存中的 FastAPI 应用发起异步 HTTP 请求。", ["测试辅助", "http请求", "asgi"]],
  "tests/test_runtime_api.py:collect_sse_events": ["解析流式响应文本中的 data 行并反序列化为 SSE 事件列表。", ["测试辅助", "sse", "事件解析"]],
  "tests/test_runtime_api.py:test_chat_done_includes_run_id_and_run_api_returns_events": ["验证聊天完成事件包含运行 ID，且单个与列表运行接口能返回对应追踪事件。", ["api测试", "sse", "运行查询"]],
  "tests/test_runtime_api.py:test_missing_run_returns_404_and_policy_api_is_public_summary": ["验证缺失运行返回 404，并确认公开策略接口展示规则而不暴露 API key。", ["api测试", "错误响应", "安全脱敏"]],
  "tests/test_runtime_errors.py:test_runtime_error_types_are_serializable": ["确认运行时错误类型枚举可直接序列化为稳定字符串值。", ["错误测试", "序列化", "错误类型"]],
  "tests/test_runtime_errors.py:test_agent_runtime_error_converts_to_trace_payload": ["验证 AgentRuntimeError 转换出的追踪载荷保留错误类型、阶段、消息和上下文。", ["错误测试", "追踪载荷", "上下文"]],
  "tests/test_runtime_memory_context.py:test_compression_and_usage_events_can_be_queried_by_run_id": ["执行上下文压缩并记录工具与技能使用，验证三类事件均可按运行 ID 查询。", ["记忆测试", "上下文压缩", "使用追踪"]],
  "tests/test_runtime_store.py:test_runtime_types_can_be_imported": ["确认运行时公共类型可从预期模块正常导入。", ["导入测试", "运行时类型", "公共接口"]],
  "tests/test_runtime_store.py:test_runtime_store_creates_run_and_orders_trace_events": ["验证运行创建、状态更新及追踪事件按序号稳定排序。", ["存储测试", "事件排序", "运行状态"]],
  "tests/test_runtime_store.py:test_runtime_store_truncates_large_payload_and_lists_conversation_runs": ["验证超大事件载荷被截断，并可按会话倒序列出关联运行。", ["存储测试", "载荷截断", "会话查询"]],
  "tests/test_tool_policy.py:BashParams": ["定义工具策略单元测试中的 Bash 命令参数模型。", ["测试模型", "工具参数", "bash"]],
  "tests/test_tool_policy.py:make_context": ["根据规范工具名构造固定会话与运行信息的工具策略评估上下文。", ["测试辅助", "策略上下文", "工具命名"]],
  "tests/test_tool_policy.py:test_policy_allows_safe_read_and_safe_bash_prefixes": ["验证平衡模式允许符合安全前缀的只读 Bash 命令。", ["策略测试", "安全命令", "允许规则"]],
  "tests/test_tool_policy.py:test_policy_denies_dangerous_bash_without_executing": ["验证平衡模式拒绝破坏性的 git reset 命令并返回中文原因。", ["策略测试", "危险命令", "拒绝规则"]],
  "tests/test_tool_policy.py:test_policy_asks_for_file_edit_and_mcp_tools": ["验证文件编辑和 MCP 工具在平衡模式下需要用户确认。", ["策略测试", "用户确认", "mcp"]],
  "tests/test_tool_policy.py:test_policy_modes_and_config_validation": ["比较关闭与严格模式对高风险工具的决策，并拒绝无效策略模式配置。", ["策略测试", "模式切换", "配置校验"]],
  "tests/test_tool_policy.py:test_default_policy_summary_contains_public_rules_only": ["确认默认策略摘要公开允许与拒绝规则，同时排除 API key 等敏感字段。", ["策略测试", "公开摘要", "敏感信息"]],
};

const resultsByPath = new Map(extraction.results.map((result) => [result.path, result]));
const exportedNames = (result) => new Set((result.exports ?? []).map((item) => item.name));
const nodes = [];
const edges = [];

function fileNodeType(file) {
  if (file.fileCategory === "config") return "config";
  return "file";
}

for (const file of input.batchFiles) {
  const result = resultsByPath.get(file.path);
  const meta = fileMeta[file.path];
  if (!result) throw new Error(`结构提取结果缺少文件：${file.path}`);
  if (!meta) throw new Error(`文件元数据缺失：${file.path}`);
  const type = fileNodeType(file);
  nodes.push({
    id: `${type}:${file.path}`,
    type,
    name: path.basename(file.path),
    filePath: file.path,
    summary: meta.summary,
    tags: meta.tags,
    complexity: meta.complexity,
    ...(meta.languageNotes ? { languageNotes: meta.languageNotes } : {}),
  });

  const exports = exportedNames(result);
  const definitions = [
    ...(result.functions ?? []).map((definition) => ({ ...definition, type: "function" })),
    ...(result.classes ?? []).map((definition) => ({ ...definition, type: "class" })),
  ];
  for (const definition of definitions) {
    const lineCount = definition.endLine - definition.startLine + 1;
    const significant =
      exports.has(definition.name) ||
      (definition.type === "function" && lineCount >= 10) ||
      (definition.type === "class" && ((definition.methods?.length ?? 0) >= 2 || lineCount >= 20));
    if (!significant) continue;
    const metaKey = `${file.path}:${definition.name}`;
    const semantic = nodeMeta[metaKey];
    if (!semantic) throw new Error(`显著节点元数据缺失：${metaKey}`);
    const id = `${definition.type}:${file.path}:${definition.name}`;
    nodes.push({
      id,
      type: definition.type,
      name: definition.name,
      filePath: file.path,
      lineRange: [definition.startLine, definition.endLine],
      summary: semantic[0],
      tags: semantic[1],
      complexity: lineCount > 50 ? "moderate" : "simple",
    });
    const fileId = `${type}:${file.path}`;
    edges.push({ source: fileId, target: id, type: "contains", direction: "forward", weight: 1.0 });
    if (exports.has(definition.name)) {
      edges.push({ source: fileId, target: id, type: "exports", direction: "forward", weight: 0.8 });
    }
  }
}

for (const file of input.batchFiles) {
  if (file.fileCategory !== "code") continue;
  for (const targetPath of input.batchImportData[file.path]) {
    edges.push({
      source: `file:${file.path}`,
      target: `file:${targetPath}`,
      type: "imports",
      direction: "forward",
      weight: 0.7,
    });
  }
}

const nodeIds = new Set(nodes.map((node) => node.id));
if (nodeIds.size !== nodes.length) throw new Error("批次内存在重复节点 ID");
if (nodes.length > 60 || edges.length > 120) {
  throw new Error(`需要拆分输出：nodes=${nodes.length}, edges=${edges.length}`);
}
for (const node of nodes) {
  if (!node.summary || !Array.isArray(node.tags) || node.tags.length < 3 || !node.complexity) {
    throw new Error(`节点必填字段不完整：${node.id}`);
  }
}
for (const edge of edges) {
  if (edge.source === edge.target) throw new Error(`检测到自引用边：${edge.source}`);
  if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
    throw new Error(`单文件输出包含无法验证的边：${edge.source} -> ${edge.target}`);
  }
}
const expectedImports = input.batchFiles
  .filter((file) => file.fileCategory === "code")
  .reduce((sum, file) => sum + input.batchImportData[file.path].length, 0);
const actualImports = edges.filter((edge) => edge.type === "imports").length;
if (actualImports !== expectedImports) {
  throw new Error(`imports 边数量不匹配：expected=${expectedImports}, actual=${actualImports}`);
}

fs.writeFileSync(outputPath, `${JSON.stringify({ nodes, edges }, null, 2)}\n`);
console.log(JSON.stringify({ outputPath, nodes: nodes.length, edges: edges.length, imports: actualImports }));
