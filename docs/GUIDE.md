LifeOps开发指南

---

## 第一部分：概念关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT 智能体                                 │
│  (持有目标、具有规划能力、能够迭代推理的 LLM 实例)               │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ SYSTEM PROMPT: 角色定义、工作流程、约束条件               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          ↓                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ CONTEXT WINDOW: 当前会话的可用空间 (~200K tokens)         │   │
│  │                                                            │   │
│  │  ├─ L1: 元数据层（始终在上下文）                          │   │
│  │  │   ├─ Skill 目录 (~100 tokens/skill)                    │   │
│  │  │   ├─ Tool 列表 (~200 tokens)                           │   │
│  │  │   └─ 最近对话历史                                      │   │
│  │  │                                                         │   │
│  │  ├─ L2: 活跃层（按需加载）                                │   │
│  │  │   ├─ Skill SKILL.md 完整体 (~5K tokens)               │   │
│  │  │   ├─ 检索到的 RAG 文档 (~10K tokens)                   │   │
│  │  │   └─ 相关记忆 (~3K tokens)                             │   │
│  │  │                                                         │   │
│  │  └─ L3: 溢出层（实时加载）                                │   │
│  │      ├─ Skill 参考文件、脚本                              │   │
│  │      └─ 工具执行结果                                      │   │
│  │                                                            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ MEMORY SYSTEM                                              │   │
│  │ ├─ STM (短期): 对话窗口中                                   │   │
│  │ ├─ LTM (长期): 向量DB 中，按需检索                         │   │
│  │ └─ Working: 任务进行中的临时状态                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ SKILL SYSTEM                                               │   │
│  │ ├─ Discovery: 启动时扫描所有 Skill 元数据                  │   │
│  │ ├─ Matching: 通过 description 隐式匹配                      │   │
│  │ └─ Loading: 触发时加载 SKILL.md 完整体                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TOOL CALLING & FUNCTION CALLING                            │   │
│  │ ├─ 内置工具: Bash, FileRead, FileEdit, WebSearch          │   │
│  │ ├─ MCP 工具: 通过 MCP 协议暴露的外部工具                   │   │
│  │ └─ 自定义工具: 在应用代码中定义的函数                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ MCP (Model Context Protocol) 层                            │   │
│  │ ├─ Stdio: 本地进程通信                                     │   │
│  │ ├─ HTTP: 远程服务器通信                                    │   │
│  │ └─ SSE: 服务器推送事件                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ RAG SYSTEM                                                 │   │
│  │ ├─ 向量数据库 (Pinecone, Weaviate, pgvector)              │   │
│  │ ├─ 检索器 (embedding search)                               │   │
│  │ └─ 重排器 (relevance validation)                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 第二部分：完整数据流（一次完整的 Agent 请求）

### 场景：用户要求"分析我们过去3个月的销售数据，并推荐优化方案"

### 时间轴：

```
T0: 初始化阶段 (Agent Session Start)
═══════════════════════════════════════════════════════════════════

1️⃣ 加载 L1 元数据（~1-2秒）
   
   系统动作：
   ├─ 扫描 Skill 目录：
   │  ├─ sales-analyzer (description: "分析销售数据和趋势")
   │  ├─ database-query (description: "查询公司数据库")
   │  ├─ market-insights (description: "获取市场竞争信息")
   │  └─ report-generator (description: "生成专业报告")
   │
   ├─ 注册工具（Tool Calling）：
   │  ├─ query_database(sql: str) -> DataFrame
   │  ├─ web_search(query: str) -> SearchResults  [via MCP]
   │  ├─ calculate_metrics(data: str) -> Metrics
   │  └─ save_report(content: str, format: str)
   │
   └─ 加载系统提示词
      "You are a business analyst agent. Use available skills 
       and tools to analyze data and provide actionable insights..."

   ❌ NOT 加载到上下文：
      ├─ Skill 的完整 SKILL.md 内容
      ├─ 历史销售数据详情
      └─ 市场分析报告内容


2️⃣ 上下文窗口初始状态
   
   [系统提示词 (~500 tokens)]
   + [Skill 元数据目录 (~400 tokens)]
   + [工具列表定义 (~300 tokens)]
   + [最近的对话历史 (~1000 tokens)]
   ────────────────────────────────────
   = 总计 ~2200 tokens （剩余 ~198K tokens）



T1: 用户请求进入 (~50ms)
═══════════════════════════════════════════════════════════════════

User Input: "分析我们过去3个月的销售数据，并推荐优化方案"

Agent 接收：
  ├─ 解析意图：
  │  ├─ Primary Goal: 销售数据分析
  │  ├─ Secondary: 推荐优化方案
  │  └─ Time Range: 3个月
  │
  ├─ 匹配 Skill：
  │  ├─ sales-analyzer: ✅ 匹配（description 包含"销售"、"数据"）
  │  ├─ database-query: ✅ 匹配（需要查询历史数据）
  │  ├─ market-insights: ⚠️ 部分匹配（优化需要了解市场）
  │  └─ report-generator: ✅ 匹配（最终需要生成报告）
  │
  └─ 决定动作：
     因为需要多个 Skill 的协调，Agent 创建一个计划

     Plan:
     1. [LOAD Skill] 加载 "database-query" 来查询销售数据
     2. [TOOL CALL] 执行 query_database("SELECT * FROM sales...")
     3. [LOAD Skill] 加载 "sales-analyzer" 来分析数据
     4. [TOOL CALL] 执行 calculate_metrics(sales_data)
     5. [LOAD Skill] 加载 "market-insights" 获取竞争信息（可选）
     6. [LOAD Skill] 加载 "report-generator" 生成最终报告
     7. [RETURN] 返回分析结果


T2: 第一个 Skill 触发 (~100ms) 
═══════════════════════════════════════════════════════════════════

动作：加载 "database-query" Skill

从文件系统读取 L2 内容：
  
  .claude/skills/database-query/
  ├─ SKILL.md ✅ 读入上下文 (~3000 tokens)
  │   内容：
  │   """
  │   # 数据库查询 Skill
  │   
  │   当需要从公司数据库检索数据时使用此 Skill。
  │   
  │   ## 查询步骤
  │   1. 分析需求中的时间范围和数据类型
  │   2. 构建 SQL 查询（使用 references/schema.sql）
  │   3. 执行查询（调用 query_database 工具）
  │   4. 验证返回的列和数据类型
  │   
  │   ## 常见查询
  │   - 按月份聚合销售额: SELECT DATE_TRUNC('month', date) ...
  │   - 按产品线分类: SELECT product_line, SUM(amount) ...
  │   """
  │
  ├─ references/ ⏳ 等待按需加载
  │   ├─ schema.sql （数据库架构）
  │   ├─ common-queries.md （常用查询模板）
  │   └─ performance-tips.md
  │
  └─ scripts/ ⏳ 等待执行
      └─ validate_query.py （验证 SQL 的脚本）


上下文变化：
  OLD: 2200 tokens
  + SKILL.md: +3000 tokens
  ────────────────
  NEW: 5200 tokens （剩余 ~195K tokens）


T3: Function Calling - 工具调用 (~200ms)
═══════════════════════════════════════════════════════════════════

Agent 的推理：
  
  观察 database-query 的 SKILL.md：
  "需要使用 references/schema.sql 来构建正确的 SQL"
  
  动作 1️⃣：加载 L3 资源
  ─────────────────────
  
  工具调用：load_skill_resource("database-query", "references/schema.sql")
  
  返回：
  """
  Schema:
  - sales (id, date, product_line, amount, salesperson_id)
  - products (id, line, category, margin)
  - salesperson (id, name, region, quota)
  """
  
  上下文 +500 tokens → 总计 5700 tokens


  动作 2️⃣：执行 query_database 工具 (MCP 层)
  ───────────────────────────────────────────
  
  Tool Call 构造：
  {
    "tool": "query_database",
    "parameters": {
      "sql": "SELECT 
                DATE_TRUNC('month', date) as month,
                SUM(amount) as total_sales,
                COUNT(*) as transaction_count,
                product_line
              FROM sales
              WHERE date >= NOW() - INTERVAL '3 months'
              GROUP BY month, product_line
              ORDER BY month DESC"
    }
  }
  
  MCP 流程：
  ├─ Agent SDK 序列化参数
  ├─ 通过 MCP 客户端发送到 MCP 服务器 (HTTP)
  │  POST https://api.company.com/mcp/query_database
  │  Authorization: Bearer $DB_TOKEN
  │
  ├─ MCP 服务器执行查询
  │  └─ 执行时间：~500ms
  │  └─ 返回：
  │     {
  │       "month": ["2024-01", "2024-02", "2024-03"],
  │       "total_sales": [150000, 165000, 172000],
  │       "transaction_count": [245, 268, 291],
  │       "product_line": ["A", "B", "C"]
  │     }
  │
  ├─ MCP 客户端截断超大输出
  │  大小检查：2KB < 上下文空间？✅ 是
  │  └─ 返回完整结果
  │
  └─ 工具结果注入到上下文：
     {
       "type": "tool_result",
       "content": "成功查询。数据显示过去3个月销售额分别为..."
     }
  
  上下文 +2000 tokens（结果摘要）→ 总计 7700 tokens


T4: RAG 系统介入 (~300ms)
═══════════════════════════════════════════════════════════════════

Agent 内部推理：
  "我已经有了销售数据，但要生成好的分析报告，
   我需要了解历史背景和市场趋势"

动作：触发 RAG 检索

RAG 流程：
  
  1️⃣ 查询构建
     Query: "过去3个月销售趋势分析，竞争对手信息，行业最佳实践"
  
  2️⃣ 嵌入 & 向量搜索
     embedding(Query) → [0.23, -0.15, 0.89, ...]
     
     向量数据库搜索（top-k = 5）：
     ├─ 文档1: "2024年行业报告-销售趋势分析" (相似度: 0.92)
     ├─ 文档2: "竞争对手基准测试" (相似度: 0.87)
     ├─ 文档3: "销售优化最佳实践" (相似度: 0.85)
     ├─ 文档4: "产品线性能历史数据" (相似度: 0.78)
     └─ 文档5: "市场调研报告" (相似度: 0.76)
  
  3️⃣ 重排 (Reranking)
     使用 Skill 中的 ranking_model 对结果重排：
     ✅ 文档1, 2, 3 相关度高，保留
     ⚠️ 文档4: 历史数据，但我们已有最新数据，可跳过
     ⚠️ 文档5: 相关性较低，跳过
  
  4️⃣ 上下文注入
     注入前处理：
     ├─ 检查 token 预算：当前 7700, 剩余 192.3K
     ├─ 分配给 RAG: 最多 15K tokens
     └─ 压缩策略：每个文档只保留 top-3 相关段落
     
     注入到上下文：
     [Recent RAG Context]
     - 行业报告指出销售增长平均 5% per month...
     - 竞争对手 Q1-Q3 销售额分别为...
     - 最佳实践建议在淡季进行促销...
     
     总计 +5000 tokens → 上下文 12700 tokens


T5: Memory 系统检查 (~150ms)
═══════════════════════════════════════════════════════════════════

Agent 检查长期记忆：

LTM 检索（向量相似度）：
  
  查询："销售分析相关的历史见解"
  
  匹配的记忆：
  ├─ Memory1: [用户偏好]
  │   "用户倾向于看月度对比和环比增长率"
  │   相似度: 0.88 | 信心度: 高 | 已验证
  │
  ├─ Memory2: [过往错误]
  │   "上次分析忽略了季节性因素，被指正"
  │   相似度: 0.85 | 信心度: 中 | 当前有效
  │
  └─ Memory3: [已过期]
  │   "Q1 销售预测" 
  │   相似度: 0.76 | 创建时间: 4个月前 | ❌ 已过期 (TTL exceeded)
  │   跳过此记忆
  
  决策：注入 Memory1 和 Memory2 到上下文
  
  [Memory Instructions]
  - 记住用户喜欢看环比增长率（上次分析时学到的）
  - 这次记得在最后加上季节性调整分析（避免重复错误）
  
  总计 +800 tokens → 上下文 13500 tokens


T6: 第二个 Skill 触发 (~100ms)
═══════════════════════════════════════════════════════════════════

加载 "sales-analyzer" Skill

.claude/skills/sales-analyzer/SKILL.md:
```
  # 销售分析 Skill

  分析销售数据，计算关键指标，识别趋势和异常。

  ## 分析步骤
  1. 计算核心指标（增长率、利润率、客户获取成本）
  2. 识别趋势线和季节性模式
  3. 对比基准值
  4. 识别异常（突发变化）

  ## 输出格式
  见 references/output-template.md
  ```

上下文 +3500 tokens → 总计 17000 tokens


T7: 自动化多 Tool 执行 (~400ms)
═══════════════════════════════════════════════════════════════════

Agent 决定并行执行多个工具（Function Calling）：

动作1️⃣：calculate_metrics (内置工具)
────────────────────────────────────
  工具: Python Code Execution
  
  执行：
  ```python
  import pandas as pd
  
  # 使用之前查询的销售数据
  sales_data = {/* 之前从数据库查询的数据 */}
  
  # 计算指标
  growth_rate = (172000 - 150000) / 150000 * 100  # 14.7%
  margin_trend = [...计算利润率趋势...]
  customer_metrics = [...计算客户相关指标...]
  ```

  执行时间：~50ms
  结果：{metrics_dict}
  上下文 +1200 tokens


动作2️⃣：web_search (MCP 工具)
───────────────────────────────
  查询："2024 销售优化最佳实践"

  MCP 调用：web_search_mcp_tool
  ├─ HTTP 请求到 Search MCP 服务器
  ├─ 执行时间：~300ms
  └─ 结果: 5个相关的网页摘要

  注入上下文 +800 tokens


T8: Skill 完整执行 - 报告生成 (~200ms)
═══════════════════════════════════════════════════════════════════

加载 "report-generator" Skill

行动：
  1. 加载 SKILL.md (~3500 tokens)
  2. 参考 references/report-template.md (~1000 tokens)
  3. 执行 scripts/generate_charts.py 
     (脚本本身不进上下文，只有输出：PNG base64 数据)

当前上下文状态：
  ├─ 系统提示: 500
  ├─ 用户输入: 200
  ├─ Skill 元数据: 400
  ├─ 已加载的 Skill 完整体: 7000
  ├─ RAG 文档: 5000
  ├─ 内存: 800
  ├─ 工具结果: 3000
  ├─ 脚本输出: 1500
  └─ 对话历史: 1000
  ────────────────────
  = 总计 ~19000 tokens （剩余 ~181K tokens）


T9: Agent 最终决策和生成 (~1000ms)
═══════════════════════════════════════════════════════════════════

Agent 综合所有信息：

输入到 Claude 模型：
  ✅ 系统提示词 (role, guidelines)
  ✅ 销售数据 (来自数据库查询)
  ✅ 计算的指标 (来自工具执行)
  ✅ 行业背景 (来自 RAG)
  ✅ 用户偏好 (来自 Memory)
  ✅ 脚本生成的图表 (来自 Skill 执行)
  ✅ Web 搜索结果 (来自 MCP)

生成逻辑：
  1. 使用记忆中的偏好格式（环比展示）
  2. 基于 Skill 的分析步骤进行分析
  3. 结合所有数据源得出结论
  4. 使用报告模板格式化输出
  5. 添加季节性调整（吸取之前的教训）

输出：
  """
  ## 销售分析报告（2024 Q1-Q3）

  ### 关键指标
  - 总销售额: $487,000 (环比增长 14.7%)
  - 增长趋势: 稳定上升，符合季节性预期
  - 利润率: 从 32% 提升到 35%

  ### 分析见解
  [完整分析报告]

  ### 优化建议
  [基于行业最佳实践和竞争对手分析的 5 项建议]

  [图表 1-3: 趋势线、对比分析、预测]
  """


T10: 后处理和记忆更新 (~200ms)
═══════════════════════════════════════════════════════════════════

任务完成后：

1️⃣ 精馏记忆（Memory Creation）

  精馏本次对话的关键见解：

  new_memory = {
    "type": "episodic",
    "content": "分析了 2024 Q1-Q3 销售数据",
    "key_insights": [
      "销售额稳定增长 14.7%",
      "季节性因素明显，需考虑促销策略",
      "利润率提升说明成本控制有效"
    ],
    "data_points": {
      "q1_sales": 150000,
      "q2_sales": 165000,
      "q3_sales": 172000
    },
    "created_at": "2024-12-15T10:30:00Z",
    "expires_at": "2025-03-15T10:30:00Z",  // 3个月有效期
    "source": "sales-analyzer-report"
  }

  向量化并存储到 LTM（向量数据库）
  embedding_vector = embed(content)
  vector_db.insert(id, embedding_vector, metadata)


2️⃣ 清理工作（Context Cleanup）

  ├─ 删除临时工作状态
  ├─ 保留关键结果用于下一个对话
  └─ 重置当前会话的上下文窗口


3️⃣ Skill 使用统计（可选）

  ├─ sales-analyzer: 1 次调用
  ├─ database-query: 1 次调用
  ├─ web_search (MCP): 1 次调用
  └─ 总 tokens 消耗: 19000


═══════════════════════════════════════════════════════════════════
总耗时：~3 秒
═══════════════════════════════════════════════════════════════════
```

---

## 第三部分：触发决策矩阵

### 在何时触发哪些功能

```
User Query 进入
    ↓
┌─ 第一步：需求理解
│
├─ 是否需要外部数据？
│  ├─ 是 → 触发 RAG
│  │      (向量搜索、文档检索)
│  │      ├─ 如果数据过时或不足
│  │      │  └─ 并行触发 Web Search (MCP)
│  │      └─ 结果注入到上下文
│  │
│  └─ 否 → 跳过 RAG
│
├─ 第二步：能力匹配
│
├─ 需要特定领域知识？
│  ├─ 是 → 触发 Skill Discovery
│  │      ├─ 扫描所有 Skill 的 description
│  │      ├─ 隐式匹配：description 是否与需求相符
│  │      ├─ 如果匹配
│  │      │  └─ 加载 Skill SKILL.md (L2)
│  │      │     ├─ 读取 references/ (L3) 仅当指令引用时
│  │      │     └─ 执行 scripts/ (输出只进上下文，代码不进)
│  │      │
│  │      └─ 显式调用：用户键入 /skill_name
│  │         └─ 立即加载，无论是否匹配
│  │
│  └─ 否 → 跳过 Skill
│
├─ 第三步：历史数据
│
├─ 需要历史信息或用户偏好？
│  ├─ 是 → 检查 Memory
│  │      ├─ 向量搜索 LTM
│  │      ├─ 过滤：
│  │      │  ├─ 检查 TTL (过期则删除)
│  │      │  ├─ 检查置信度 (低于阈值则注记)
│  │      │  └─ 衰减权重 (最近的优先)
│  │      └─ 注入到上下文
│  │
│  └─ 否 → 跳过 Memory
│
├─ 第四步：执行和集成
│
├─ 需要与外部系统交互？
│  ├─ 是 → 触发 Function Calling
│  │      ├─ 区分工具类型：
│  │      │  ├─ 内置工具 (Bash, FileRead, WebSearch)
│  │      │  │  └─ 直接执行，结果进上下文
│  │      │  │
│  │      │  └─ MCP 工具 (GitHub, Slack, Databases)
│  │      │     ├─ 序列化参数
│  │      │     ├─ 通过 MCP 客户端发送到 MCP 服务器
│  │      │     ├─ MCP 服务器执行（远程）
│  │      │     ├─ 校验输出大小 (> 上下文阈值则截断)
│  │      │     └─ 结果进上下文
│  │      │
│  │      └─ 并行调用多个工具（如果无依赖）
│  │
│  └─ 否 → 跳过 Function Calling
│
├─ 第五步：迭代推理
│
├─ 答案充分吗？
│  ├─ 否 → 
│  │      ├─ 检查是否需要更多信息
│  │      ├─ 重新触发 RAG 或 Skill（步骤1-4）
│  │      ├─ 或要求用户澄清
│  │      └─ 循环回到第一步
│  │
│  └─ 是 → 生成最终回复
│
└─ 第六步：后处理
   ├─ 精馏记忆（Memory Write）
   ├─ 保存关键见解到 LTM
   └─ 完成
```

---

## 第四部分：上下文配置示例

### 场景 1：轻量级查询（"明天天气如何？"）

```
当前可用上下文: 200K tokens

分配：
├─ 系统提示词: 500 tokens (~0.25%)
├─ 工具列表: 200 tokens (~0.1%)
├─ 用户查询: 10 tokens (~0.01%)
├─ 最近对话: 100 tokens (~0.05%)
├─ RAG 检索: 500 tokens (~0.25%) [天气数据]
└─ 其他: 0
───────────────────────────
总计: ~1300 tokens (~0.65%)

剩余: ~198.7K tokens （充分的缓冲）

不需要加载的：
  ❌ Skill （没有复杂分析）
  ❌ Memory （无历史相关性）
  ❌ MCP 工具 （简单查询）
```

### 场景 2：复杂分析（"分析竞争对手的产品策略并建议我们的应对"）

```
当前可用上下文: 200K tokens

分配：
├─ 系统提示词: 500 tokens
├─ 工具列表: 300 tokens
├─ Skill 元数据: 600 tokens (competitor-analyzer, strategy-advisor)
│
├─ 已加载 Skill 完整体: 8000 tokens
│  ├─ competitor-analyzer SKILL.md: 4000 tokens
│  ├─ strategy-advisor SKILL.md: 4000 tokens
│
├─ RAG 检索: 12000 tokens
│  ├─ 竞争对手公开信息: 5000
│  ├─ 历史战略文档: 4000
│  ├─ 行业分析报告: 3000
│
├─ Memory: 2000 tokens
│  ├─ 公司战略偏好: 800
│  ├─ 以前的失败教训: 1200
│
├─ Tool 执行结果: 3000 tokens
│  ├─ web_search 结果: 1500
│  ├─ 数据库查询结果: 1500
│
├─ 对话历史: 2000 tokens
│
└─ 工作空间: 4000 tokens (中间计算、推理过程)
───────────────────────────
总计: ~35400 tokens (~17.7%)

剩余: ~164.6K tokens

按需加载的：
  ✅ Skill references/（当指令提到时）
  ✅ 脚本执行（输出进上下文，代码不进）
  ✅ MCP 工具（并行查询竞争对手数据）
```

### 场景 3：迭代对话（3 轮交互）

```
轮次 1: 用户问 "Q1 销售额是多少？"
────────────────────────────
上下文使用: 2000 tokens
保存到 STM

↓ Agent 触发：
  ├─ RAG: 销售数据
  └─ Tool: query_database


轮次 2: 用户问 "对比一下竞争对手"
────────────────────────────
上下文使用: 4000 tokens + 2000 (轮次1的历史)
            = 6000 tokens

STM 管理：
  ├─ 保留: 轮次1的问答（维持对话连贯性）
  ├─ 压缩: 大的中间结果（替换为摘要）
  └─ 清理: 临时工作变量

↓ Agent 触发：
  ├─ Memory: 检查是否有竞争对手数据
  ├─ RAG: 竞争对手信息
  ├─ Skill: market-analyst
  └─ Tool: web_search


轮次 3: 用户问 "基于前两个分析，你的建议是？"
──────────────────────────────────
上下文使用：
  ├─ 轮次1和2的完整历史: 6000
  ├─ 新增信息: 2000
  ├─ 总计: 8000 tokens

智能压缩：
  ├─ 如果接近上下文上限
  │  └─ 使用 Skill 的 compress_context 工具
  │     (LangChain 的 SummarizerChain)
  │
  ├─ 压缩策略:
  │  ├─ 删除冗余的工具调用日志
  │  ├─ 保留关键见解和数据
  │  └─ 保留前两轮的核心问答

↓ Agent 触发：
  ├─ Memory: 写入本次分析结论到 LTM
  ├─ Skill: report-generator
  └─ Tool: 无需新的外部调用
```

---

## 第五部分：成熟系统的最佳实践

### 1️⃣ 上下文窗口管理

```javascript
// 伪代码
class ContextManager {
  private maxTokens = 200000;
  private current = 0;
  
  canLoad(tokenSize) {
    // 保留 10% 作为缓冲
    const threshold = this.maxTokens * 0.9;
    return this.current + tokenSize <= threshold;
  }
  
  addL1Metadata(tokens) {
    // L1 始终加载
    this.current += tokens;
  }
  
  addL2OnDemand(skillName, tokens) {
    // L2 检查容量
    if (this.canLoad(tokens)) {
      this.current += tokens;
      return true;
    } else {
      // 压缩或移除旧的 Skill
      this.compressOldSkills();
      this.current += tokens;
      return true;
    }
  }
  
  executeL3(scriptName, tokens) {
    // L3 脚本本身不进上下文
    // 只有输出进上下文，且需要校验
    if (tokens > this.maxTokens * 0.05) {
      // 输出过大，截断或保存为文件
      return truncateAndReference(output);
    }
    return output;
  }
}
```

### 2️⃣ Skill 触发的精确匹配

```javascript
// Skill 触发的评分机制
function scoreSkillRelevance(query, skill) {
  const scores = {
    nameMatch: 0.2,
    descriptionMatch: 0.6,
    triggerPhrase: 0.2
  };
  
  let total = 0;
  
  // 检查 trigger_phrases
  if (skill.trigger_phrases.some(phrase => 
      query.toLowerCase().includes(phrase))) {
    total += scores.triggerPhrase;
  }
  
  // 语义相似度
  const simScore = cosineSimilarity(
    embed(query),
    embed(skill.description)
  );
  total += simScore * scores.descriptionMatch;
  
  // 名称匹配
  if (query.includes(skill.name)) {
    total += scores.nameMatch;
  }
  
  return total; // 0-1
}

// 只加载 score > 0.5 的 Skill
const relevantSkills = allSkills
  .map(s => ({ skill: s, score: scoreSkillRelevance(query, s) }))
  .filter(x => x.score > 0.5)
  .sort((a, b) => b.score - a.score);

relevantSkills.forEach(({ skill }) => loadSkill(skill));
```

### 3️⃣ 工具执行的超时和重试

```javascript
async function executeToolWithRetry(
  toolName,
  params,
  options = {}
) {
  const {
    maxRetries = 3,
    timeout = 5000,
    backoff = 'exponential'
  } = options;
  
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const result = await Promise.race([
        executeToolDirect(toolName, params),
        sleep(timeout).then(() => {
          throw new TimeoutError();
        })
      ]);
      
      // 验证结果
      if (!validateToolOutput(result)) {
        throw new ValidationError();
      }
      
      return result;
      
    } catch (error) {
      if (attempt === maxRetries - 1) throw error;
      
      // 指数退避：500ms, 1000ms, 2000ms
      const delay = timeout * Math.pow(2, attempt);
      await sleep(delay);
    }
  }
}
```

### 4️⃣ 记忆的智能检索和衰减

```javascript
async function retrieveMemories(query) {
  const now = Date.now();
  
  // 1. 向量搜索
  const candidates = await memoryDB.search(
    embed(query),
    { limit: 10 }
  );
  
  // 2. 过滤和评分
  const memories = candidates
    .filter(m => {
      // 移除过期的
      if (m.expiresAt && m.expiresAt < now) {
        return false;
      }
      return true;
    })
    .map(m => {
      // 应用衰减函数
      const ageInDays = (now - m.createdAt) / (1000 * 60 * 60 * 24);
      const decayFactor = Math.exp(-0.1 * ageInDays); // 半衰期 ~7 天
      
      return {
        ...m,
        score: m.similarity * decayFactor * m.confidence
      };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, 3); // 只保留 top-3
  
  return memories;
}
```

### 5️⃣ MCP 连接的健康检查

```javascript
class MCPConnectionManager {
  private servers = new Map();
  private healthCheckInterval = 30000; // 30 秒
  
  async connectServer(name, config) {
    const server = {
      name,
      config,
      status: 'connecting',
      lastHealthCheck: null,
      failureCount: 0
    };
    
    this.servers.set(name, server);
    
    try {
      await this.healthCheck(name);
      server.status = 'connected';
    } catch (error) {
      server.status = 'failed';
      console.error(`Failed to connect MCP server: ${name}`, error);
    }
  }
  
  async executeToolWithFallback(
    serverName,
    toolName,
    params
  ) {
    const server = this.servers.get(serverName);
    
    if (server.status !== 'connected') {
      // 尝试重新连接
      await this.connectServer(serverName, server.config);
    }
    
    try {
      const result = await executeRemoteTool(
        server.config,
        toolName,
        params
      );
      
      server.failureCount = 0;
      return result;
      
    } catch (error) {
      server.failureCount++;
      server.status = 'failed';
      
      if (server.failureCount >= 3) {
        console.error(
          `MCP server ${serverName} failed 3 times, marking as unavailable`
        );
        server.status = 'unavailable';
      }
      
      // 返回降级响应
      throw new MCPToolUnavailableError(
        `Tool ${toolName} unavailable (${serverName} down)`
      );
    }
  }
}
```

---

## 第六部分：完整的数据流图

```
┌────────────────────────────────────────────────────────────────────┐
│                         User Input                                  │
│                  ("分析销售数据并推荐优化")                         │
└────────────────┬─────────────────────────────────────────────────────┘
                 │
                 ▼
        ┌────────────────────┐
        │  Intent Parsing    │
        │  (Agent 理解需求)   │
        │                    │
        │ Goal: 销售分析      │
        │ Tools: 数据库, 工具 │
        └────────┬───────────┘
                 │
          ┌──────┴──────┐
          ▼             ▼
    ┌──────────────┐  ┌─────────────────┐
    │  Skill       │  │  Memory Search  │
    │  Discovery   │  │  (向量相似度)    │
    │              │  │                 │
    │ 匹配度:0.92  │  │ 用户偏好记忆    │
    │ 加载SKILL.md │  │ 历史见解 等      │
    └──────┬───────┘  └────────┬────────┘
           │                   │
           │            ┌──────▼─────────┐
           │            │ Apply Decay    │
           │            │ Check TTL      │
           │            │ Filter Results │
           │            └────────┬───────┘
           │                     │
           ├─────────────────────┤
           ▼
    ┌──────────────────────┐
    │  Context Assembly    │
    │                      │
    │ L1: System + Tools   │
    │ L2: Skill SKILL.md   │
    │ L3: RAG Results      │
    │ L4: Memory           │
    │                      │
    │ Total: 19000 tokens  │
    └──────────┬───────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
    ┌──────────┐   ┌──────────────────┐
    │  Tool    │   │  RAG Retrieval   │
    │ Calling  │   │                  │
    │          │   │ Vector Search    │
    │ (MCP)    │   │ Reranking        │
    │          │   │ Dedup            │
    │ Result:  │   │                  │
    │ ────────►    Result: 5 docs     │
    │ DataFrame    """                │
    │          │   行业报告            │
    └────┬─────┘   竞争对手分析        │
         │         最佳实践 ...       │
         │         """               │
         │         └──────┬──────────┘
         │                │
         ├────────────────┤
         ▼
    ┌─────────────────┐
    │ LLM Inference   │
    │ (Claude Model)  │
    │                 │
    │ 综合所有输入:   │
    │ - 销售数据      │
    │ - 指标计算      │
    │ - 行业背景      │
    │ - 用户偏好      │
    │ - Skill 指导    │
    │                 │
    │ 生成回复...     │
    └────────┬────────┘
             │
             ▼
    ┌──────────────────┐
    │  Post Processing │
    │                  │
    │ 1. Memory Write  │
    │    精馏新见解    │
    │                  │
    │ 2. Truncate      │
    │    清理上下文    │
    │                  │
    │ 3. Log          │
    │    记录使用情况  │
    └────────┬─────────┘
             │
             ▼
      ┌─────────────────┐
      │  Final Output   │
      │  销售分析报告    │
      │  + 推荐方案      │
      └─────────────────┘
```

---

## 总结表格

| 组件 | 触发时机 | 加载方式 | 上下文占用 | 作用 |
|------|---------|---------|----------|------|
| **System Prompt** | 会话开始 | 静态 | 500 tokens | 定义 Agent 角色和行为 |
| **Tool List** | 会话开始 | 静态 | 200-300 tokens | 声明可用工具 |
| **Skill 元数据** | 会话开始 | 静态 | ~100 tokens/skill | 技能发现和匹配 |
| **Skill 完整体** | 隐式匹配 | 按需 L2 | ~3-5K tokens | 提供详细工作流程 |
| **Skill 资源** | 指令引用 | 按需 L3 | ~1-3K tokens | 提供参考数据 |
| **Skill 脚本** | 指令需要 | 执行（无上下文） | 仅输出 | 执行确定性任务 |
| **RAG 检索** | 需要外部知识 | 向量搜索 | ~5-15K tokens | 注入事实信息 |
| **Memory 检索** | 需要历史信息 | 向量搜索 + 衰减 | ~1-3K tokens | 持久化学习 |
| **Function Call** | Agent 决策 | 远程执行 | 仅结果 | 与外部系统交互 |
| **MCP 工具** | Function Call | MCP 协议 | 结果 + 校验 | 标准化工具协议 |

