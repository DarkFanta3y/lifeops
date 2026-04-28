from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lifeops.agent import Agent, DEFAULT_SYSTEM_PROMPT
from lifeops.core.config import AppConfig, LLMConfig, SkillsConfig
from lifeops.llm.types import ChatResponse, MessageRole, ToolCallResult
from lifeops.tools.base import ToolDefinition, ToolParams, ToolResult


@pytest.fixture
def mock_config():
    return AppConfig(llm=LLMConfig(api_key="test-key", model="gpt-4o"))


def make_config_with_skills(tmp_path):
    return AppConfig(
        llm=LLMConfig(api_key="test-key", model="gpt-4o"),
        skills=SkillsConfig(
            enabled=True,
            project_dir=str(tmp_path / "project-skills"),
            user_dir=str(tmp_path / "user-skills"),
            implicit_match_enabled=False,
        ),
    )


def write_skill(root, name, body):
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(body, encoding="utf-8")
    return skill_file


def test_agent_initialization(mock_config: AppConfig):
    agent = Agent(mock_config)
    assert agent.config == mock_config
    assert len(agent.tools.list_definitions()) > 0
    assert agent.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert len(agent.messages) == 0


def test_agent_initialization_adds_skill_catalog_to_l1(tmp_path):
    config = make_config_with_skills(tmp_path)
    write_skill(
        tmp_path / "project-skills",
        "weekly-review",
        """---
name: weekly-review
description: 整理本周记录。
---

# Weekly Review
""",
    )

    agent = Agent(config)

    catalog = agent.context.get_content("skills_catalog")
    assert catalog is not None
    assert "weekly-review - 整理本周记录。" in catalog


def test_agent_custom_system_prompt(mock_config: AppConfig):
    custom_prompt = "You are a cooking assistant."
    agent = Agent(mock_config, system_prompt=custom_prompt)
    assert agent.system_prompt == custom_prompt


def test_agent_reset(mock_config: AppConfig):
    agent = Agent(mock_config)
    agent.messages.append(MagicMock())
    assert len(agent.messages) == 1

    agent.reset()
    assert len(agent.messages) == 0


def test_agent_reset_preserves_skill_catalog_and_clears_active_skills(tmp_path):
    config = make_config_with_skills(tmp_path)
    write_skill(
        tmp_path / "project-skills",
        "weekly-review",
        """---
name: weekly-review
description: 整理本周记录。
---

# Weekly Review
""",
    )
    agent = Agent(config)
    agent.skill_manager.activate("weekly-review")

    agent.reset()

    assert agent.context.get_content("skills_catalog") is not None
    assert agent.context.get_content("skill:weekly-review") is None


def test_agent_add_tool(mock_config: AppConfig):
    agent = Agent(mock_config)
    initial_count = len(agent.tools.list_definitions())

    class CustomParams(ToolParams):
        input: str

    tool_def = ToolDefinition(
        name="custom_tool",
        description="A custom tool",
        parameters_model=CustomParams,
    )

    async def custom_handler(params: dict) -> ToolResult:
        return ToolResult(success=True, output="custom result")

    agent.add_tool(tool_def, custom_handler)

    assert len(agent.tools.list_definitions()) == initial_count + 1
    assert agent.tools.get_definition("custom_tool") is not None


@pytest.mark.asyncio
async def test_agent_simple_response(mock_config: AppConfig):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello! How can I help you?"
    mock_response.choices[0].message.tool_calls = None

    with patch("lifeops.agent.LLMClient") as MockLLM:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.chat = AsyncMock(
            return_value=ChatResponse(
                content="Hello! How can I help you?",
                tool_calls=None,
            )
        )
        MockLLM.return_value = mock_llm_instance

        agent = Agent(mock_config)
        agent.llm = mock_llm_instance

        result = await agent.run("Hi there!")
        assert result == "Hello! How can I help you?"
        assert len(agent.messages) == 2
        assert agent.messages[0].role == MessageRole.USER


@pytest.mark.asyncio
async def test_agent_explicit_skill_trigger_injects_full_skill_into_l2(tmp_path):
    config = make_config_with_skills(tmp_path)
    write_skill(
        tmp_path / "project-skills",
        "weekly-review",
        """---
name: weekly-review
description: 整理本周记录。
---

# Weekly Review

1. 读取相关笔记。
2. 生成下周行动计划。
""",
    )
    call_messages = []

    async def mock_chat(messages, tools=None, **kwargs):
        call_messages.append(messages)
        return ChatResponse(content="已完成", tool_calls=None)

    agent = Agent(config)
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(side_effect=mock_chat)
    agent.llm = mock_llm
    agent.skill_matcher.llm = mock_llm

    result = await agent.run("请用 $weekly-review 做复盘")

    assert result == "已完成"
    assert "# Weekly Review" in agent.context.get_content("skill:weekly-review")
    system_message = call_messages[0][0]
    assert system_message.role == MessageRole.SYSTEM
    assert "已激活 Skill: weekly-review" in system_message.content
    assert "生成下周行动计划" in system_message.content


@pytest.mark.asyncio
async def test_agent_does_not_inject_skill_body_without_trigger(tmp_path):
    config = make_config_with_skills(tmp_path)
    write_skill(
        tmp_path / "project-skills",
        "weekly-review",
        """---
name: weekly-review
description: 整理本周记录。
---

# Weekly Review
""",
    )
    agent = Agent(config)
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(return_value=ChatResponse(content="普通回复", tool_calls=None))
    agent.llm = mock_llm
    agent.skill_matcher.llm = mock_llm

    await agent.run("你好")

    assert agent.context.get_content("skill:weekly-review") is None


@pytest.mark.asyncio
async def test_agent_tool_call_loop(mock_config: AppConfig):
    call_count = 0

    async def mock_chat(messages, tools=None, **kwargs):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return ChatResponse(
                content=None,
                tool_calls=[
                    ToolCallResult(
                        id="call_1",
                        name="bash",
                        arguments='{"command":"echo hello"}',
                        type="function",
                    )
                ],
            )
        else:
            return ChatResponse(content="The command output: hello", tool_calls=None)

    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(side_effect=mock_chat)
    mock_llm.model = "gpt-4o"

    agent = Agent(mock_config)
    agent.llm = mock_llm

    result = await agent.run("Run echo hello")
    assert "hello" in result.lower() or "command" in result.lower()


@pytest.mark.asyncio
async def test_agent_sends_sanitized_tool_result_to_next_llm_call(mock_config: AppConfig):
    call_messages = []

    async def mock_chat(messages, tools=None, **kwargs):
        call_messages.append(messages)
        if len(call_messages) == 1:
            return ChatResponse(
                content=None,
                tool_calls=[
                    ToolCallResult(
                        id="call_1",
                        name="custom_tool",
                        arguments='{"input":"openai/codex"}',
                        type="function",
                    )
                ],
            )
        return ChatResponse(content="查到了", tool_calls=None)

    async def custom_handler(params: dict) -> ToolResult:
        return ToolResult(success=True, output="repo \ud83d\ude80")

    class CustomParams(ToolParams):
        input: str

    agent = Agent(mock_config)
    agent.add_tool(
        ToolDefinition(
            name="custom_tool",
            description="A custom tool",
            parameters_model=CustomParams,
        ),
        custom_handler,
    )

    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(side_effect=mock_chat)
    agent.llm = mock_llm

    result = await agent.run("查仓库")

    tool_message = next(msg for msg in call_messages[1] if msg.role == MessageRole.TOOL)
    assert result == "查到了"
    assert tool_message.content == "repo 🚀"
    assert tool_message.content.encode("utf-8")


@pytest.mark.asyncio
async def test_agent_unknown_tool(mock_config: AppConfig):
    async def mock_chat(messages, tools=None, **kwargs):
        return ChatResponse(
            content=None,
            tool_calls=[
                ToolCallResult(
                    id="call_1", name="nonexistent_tool", arguments="{}", type="function"
                )
            ],
        )

    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(side_effect=mock_chat)

    agent = Agent(mock_config)
    agent.llm = mock_llm

    await agent.run("Use nonexistent tool")
    assert len(agent.messages) > 0
