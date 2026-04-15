# 移除 configs/ 目录，简化配置为纯 .env 模式

## TL;DR

> **Quick Summary**: 删除 `configs/` 目录及 YAML 配置加载逻辑，所有配置统一从 `.env` 文件读取。
> 
> **Deliverables**:
> - 删除 `configs/` 目录
> - 从 `config.py` 移除 `yaml` 依赖和 `from_yaml` 方法
> - 从 `agent.py` 改用 `AppConfig()` 替代 `AppConfig.from_yaml()`
> - 从 `pyproject.toml` 移除 `pyyaml` 依赖
> - 更新文档（README.md、AGENTS.md、PROJECT.md）中的配置优先级说明
> 
> **Estimated Effort**: Quick
> **Parallel Execution**: YES - 1 wave
> **Critical Path**: Task 1 → Task 4

---

## Context

### Original Request
用户要求移除 `configs/` 目录，所有配置参数只从 `.env` 文件读取。之前 `from_yaml()` 方法存在配置优先级 bug（YAML 值覆盖了 .env），处理起来复杂且不必要——pydantic-settings 本身已经支持 `环境变量 > .env 文件 > 默认值` 的优先级链。

### Research Findings
- `configs/default.yaml` 是唯一需要删除的文件
- `yaml` / `pyyaml` 仅在 `config.py` 的 `from_yaml` 方法中使用
- 测试代码中不引用 `from_yaml` 或 `configs/`
- `pyyaml` 是 `pyproject.toml` 中的显式依赖，不是间接依赖

---

## Work Objectives

### Core Objective
移除 YAML 配置层，让 pydantic-settings 直接从 `.env` + 环境变量读取所有配置。

### Concrete Deliverables
- `configs/` 目录已删除
- `config.py` 不再 import yaml、不再有 `from_yaml` 方法
- `agent.py` 使用 `AppConfig()` 而非 `AppConfig.from_yaml()`
- `pyproject.toml` 不再有 `pyyaml` 依赖
- 文档中配置优先级描述已更新

### Definition of Done
- [x] `uv run pytest tests/ -v` 全部 48 个测试通过
- [x] `uv run ruff check src/ tests/` 无错误
- [x] `uv run lifeops <<< "你好"` 正常启动并返回响应

### Must Have
- 配置优先级：环境变量 > .env 文件 > 代码默认值
- `clear_proxy_env()` 函数保留（修 403 bug 时加的）
- 所有现有 .env 配置项继续生效

### Must NOT Have (Guardrails)
- 不改变配置字段名或 env 变量名
- 不改变 `.env` 文件格式
- 不引入新的配置层

---

## Verification Strategy

- **Test Decision**: 无新功能需要 TDD，用现有 48 个测试 + 手动启动验证
- **QA Policy**: Agent 启动验证 + ruff lint

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (All independent — can run together):
├── Task 1: 删除 configs/ 目录
├── Task 2: config.py 移除 yaml 和 from_yaml
├── Task 3: agent.py 改用 AppConfig()
├── Task 4: pyproject.toml 移除 pyyaml 依赖
└── Task 5: 更新文档（README, AGENTS.md, PROJECT.md）

Wave FINAL:
└── Task 6: 运行测试 + 启动验证
```

---

## TODOs

---

- [x] 1. 删除 configs/ 目录

  **What to do**:
  - 执行 `rm -rf configs/`

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `configs/default.yaml` — 唯一内容

  **Acceptance Criteria**:
  - [ ] `ls configs/` 返回 "No such file or directory"

  **Commit**: NO (group with task 5)

---

- [x] 2. config.py 移除 yaml import 和 from_yaml 方法

  **What to do**:
  - 删除 `import yaml` 行
  - 删除整个 `from_yaml` classmethod（第77-96行）
  - 最终文件的 import 部分应为：
    ```python
    from __future__ import annotations
    import os
    from pathlib import Path
    from pydantic import Field
    from pydantic_settings import BaseSettings
    ```
  - `AppConfig` 类止于 `model_config` 字典，即第75行之后就是文件末尾

  **Must NOT do**:
  - 不删除 `Path` 和 `PROJECT_ROOT`——`_ENV_FILE` 仍需要
  - 不删除 `clear_proxy_env` 函数
  - 不修改 `LLMConfig`、`ContextConfig` 内部

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 6
  - **Blocked By**: None

  **References**:
  - `src/lifeops/core/config.py` — 当前完整文件

  **Acceptance Criteria**:
  - [ ] `uv run python -c "from lifeops.core.config import AppConfig; print(AppConfig().llm.model)"` 输出 `glm-4-flash`
  - [ ] 文件中不含 `yaml` 或 `from_yaml`

  **Commit**: NO (group with task 5)

---

- [x] 3. agent.py 改用 AppConfig() 替代 from_yaml

  **What to do**:
  - 将 `config = AppConfig.from_yaml("configs/default.yaml")` 改为 `config = AppConfig()`

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 6
  - **Blocked By**: None

  **References**:
  - `src/lifeops/agent.py:186`

  **Acceptance Criteria**:
  - [ ] 文件中不含 `from_yaml` 或 `configs/`

  **Commit**: NO (group with task 5)

---

- [x] 4. pyproject.toml 移除 pyyaml 依赖

  **What to do**:
  - 从 dependencies 列表中删除 `"pyyaml>=6.0",` 这一行
  - 运行 `uv sync` 更新锁文件

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 6
  - **Blocked By**: None

  **References**:
  - `pyproject.toml:12` — `"pyyaml>=6.0",`

  **Acceptance Criteria**:
  - [ ] `grep pyyaml pyproject.toml` 无输出
  - [ ] `uv sync` 成功

  **Commit**: NO (group with task 5)

---

- [x] 5. 更新文档中的配置优先级说明

  **What to do**:
  - `AGENTS.md`: 把 `优先级为 环境变量 > .env 文件 > configs/default.yaml` 改为 `优先级为 环境变量 > .env 文件 > 默认值`
  - `README.md`: 把 `优先级: 环境变量 > .env 文件 > configs/default.yaml` 改为 `优先级: 环境变量 > .env 文件 > 默认值`
  - `PROJECT.md`: 
    - 把 `配置优先级: 环境变量 > .env 文件 > configs/default.yaml` 改为 `配置优先级: 环境变量 > .env 文件 > 默认值`
    - 从文件结构树中删除 `├── configs/default.yaml` 行

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `AGENTS.md:22`
  - `README.md` — 搜索 "configs/default.yaml"
  - `PROJECT.md:61` 和 `PROJECT.md:124`

  **Acceptance Criteria**:
  - [ ] 三个文件中不含 `configs/default.yaml`
  - [ ] 优先级描述均为 `环境变量 > .env 文件 > 默认值`

  **Commit**: YES — group with tasks 1-4
  - Message: `refactor(config): remove yaml config layer, use .env only`
  - Files: `src/lifeops/core/config.py`, `src/lifeops/agent.py`, `pyproject.toml`, `AGENTS.md`, `README.md`, `PROJECT.md`
  - Pre-commit: `uv run pytest tests/ -v && uv run ruff check src/ tests/`

---

- [x] 6. 运行测试 + 启动验证

  **What to do**:
  - 运行 `uv run pytest tests/ -v` — 全部 48 个测试必须通过
  - 运行 `uv run ruff check src/ tests/` — 无错误
  - 运行 `uv run lifeops <<< "你好"` — 正常返回响应，无报错
  - 确认 `uv sync` 无报错（pyyaml 已移除）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave FINAL
  - **Blocks**: None
  - **Blocked By**: Tasks 1-5

  **References**: N/A

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/ -v` → 48 passed
  - [ ] `uv run ruff check src/ tests/` → All checks passed
  - [ ] `uv run lifeops <<< "你好"` → 输出含中文回复，无错误

  **Commit**: NO — verification only

---

## Final Verification Wave

- [x] F1. **Plan Compliance Audit** — 确认所有改动与计划一致，无遗漏
- [x] F2. **Code Quality Review** — ruff + 测试全绿
- [x] F3. **Real Manual QA** — lifeops 启动正常
- [x] F4. **Scope Fidelity Check** — 无多余改动

---

## Commit Strategy

- **1**: `refactor(config): remove yaml config layer, use .env only` — config.py, agent.py, pyproject.toml, configs/, AGENTS.md, README.md, PROJECT.md

---

## Success Criteria

### Verification Commands
```bash
uv run pytest tests/ -v          # Expected: 48 passed
uv run ruff check src/ tests/     # Expected: All checks passed
uv run lifeops <<< "你好"          # Expected: 正常中文回复，无错误
ls configs/                        # Expected: No such file or directory
```

### Final Checklist
- [x] configs/ 目录已删除
- [x] config.py 不含 yaml 和 from_yaml
- [x] agent.py 使用 AppConfig() 而非 from_yaml
- [x] pyproject.toml 不含 pyyaml
- [x] 所有文档不含 configs/default.yaml