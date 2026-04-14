import os

import pytest

from lifeops.core.config import AppConfig, LLMConfig


@pytest.fixture
def app_config():
    os.environ["LLM_API_KEY"] = "test-key"
    config = AppConfig(llm=LLMConfig(api_key="test-key"))
    yield config
    if "LLM_API_KEY" in os.environ:
        del os.environ["LLM_API_KEY"]