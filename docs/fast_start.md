your-agent-project/
├── README.md                    # 项目概述
├── PROJECT.md                   ← 你在这里，项目进度追踪
├── xx.md                    ← OpenCode 配置文件
│
├── src/
│   ├── agent.py                # Agent 主类
│   ├── core/
│   │   ├── skill_system.py      # Skill 加载和匹配
│   │   ├── memory_system.py     # 记忆管理
│   │   ├── rag_system.py        # 向量检索
│   │   └── tool_registry.py     # 工具注册
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── builtin_tools.py     # 内置工具（Bash, FileRead等）
│   │   ├── mcp_tools.py         # MCP 工具连接
│   │   └── custom_tools.py      # 自定义工具
│   │
│   ├── skills/
│   │   ├── skill_base.py        # Skill 基类
│   │   └── examples/            # 示例 Skill
│   │
│   └── utils/
│       ├── context_manager.py   # 上下文窗口管理
│       ├── logging.py           # 日志系统
│       └── config.py            # 配置管理
│
├── tests/
│   ├── test_skills.py
│   ├── test_memory.py
│   ├── test_rag.py
│   └── test_integration.py
│
└── docs/
    ├── architecture.md          # 架构文档
    ├── api.md                   # API 文档
    └── examples.md              # 使用示例