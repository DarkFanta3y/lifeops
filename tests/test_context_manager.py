
from lifeops.core.context_manager import ContextLayer, ContextManager


def test_context_manager_initialization():
    cm = ContextManager(max_tokens=200000)
    assert cm.max_tokens == 200000
    assert cm.used_tokens == 0
    assert cm.remaining_tokens == 200000


def test_add_l1_content():
    cm = ContextManager(max_tokens=200000)
    tokens = cm.add_content("system_prompt", "You are a helpful assistant", ContextLayer.L1, token_count=10)
    assert tokens == 10
    assert cm.used_tokens == 10


def test_add_l2_content():
    cm = ContextManager(max_tokens=200000)
    cm.add_content("system_prompt", "system", ContextLayer.L1, token_count=10)
    result = cm.add_content("skill_doc", "skill content", ContextLayer.L2, token_count=5000)
    assert result == 5000
    assert cm.used_tokens == 5010


def test_estimate_tokens():
    cm = ContextManager(max_tokens=200000)
    text = "hello world this is a test"
    tokens = cm.add_content("test", text, ContextLayer.L1)
    assert tokens > 0
    assert tokens == len(text) // 4


def test_context_budget_available():
    cm = ContextManager(max_tokens=1000, reserve_ratio=0.1)
    cm.add_content("system", "sys", ContextLayer.L1, token_count=500)
    assert cm.can_add(token_count=400) is True
    assert cm.can_add(token_count=401) is False


def test_remove_content():
    cm = ContextManager(max_tokens=1000)
    cm.add_content("skill_1", "content", ContextLayer.L2, token_count=200)
    cm.add_content("skill_2", "content2", ContextLayer.L2, token_count=300)
    assert cm.used_tokens == 500
    cm.remove_content("skill_1")
    assert cm.used_tokens == 300


def test_remove_nonexistent():
    cm = ContextManager(max_tokens=1000)
    result = cm.remove_content("nonexistent")
    assert result is False


def test_get_content():
    cm = ContextManager(max_tokens=200000)
    cm.add_content("key1", "value1", ContextLayer.L1, token_count=5)
    content = cm.get_content("key1")
    assert content == "value1"


def test_get_content_not_found():
    cm = ContextManager(max_tokens=200000)
    content = cm.get_content("nonexistent")
    assert content is None


def test_overwrite_content():
    cm = ContextManager(max_tokens=200000)
    cm.add_content("key1", "old_value", ContextLayer.L1, token_count=10)
    cm.add_content("key1", "new_value", ContextLayer.L1, token_count=20)
    assert cm.get_content("key1") == "new_value"
    assert cm.used_tokens == 20


def test_compress_l2():
    cm = ContextManager(max_tokens=1000, reserve_ratio=0.1)
    cm.add_content("system", "sys", ContextLayer.L1, token_count=100)
    cm.add_content("skill_1", "a" * 400, ContextLayer.L2, token_count=400)
    cm.add_content("skill_2", "b" * 400, ContextLayer.L2, token_count=400)

    assert cm.used_tokens == 900

    removed = cm.compress_l2(keep_keys={"skill_1"})
    assert len(removed) == 1
    assert removed[0][0] == "skill_2"
    assert cm.used_tokens == 500


def test_compress_l3():
    cm = ContextManager(max_tokens=200000)
    cm.add_content("tool_output_1", "result1", ContextLayer.L3, token_count=100)
    cm.add_content("tool_output_2", "result2", ContextLayer.L3, token_count=200)
    cm.add_content("system", "sys", ContextLayer.L1, token_count=50)

    removed = cm.compress_l3()
    assert len(removed) == 2
    assert cm.used_tokens == 50


def test_get_summary():
    cm = ContextManager(max_tokens=200000)
    cm.add_content("system", "sys", ContextLayer.L1, token_count=500)
    cm.add_content("skill", "sk", ContextLayer.L2, token_count=3000)

    summary = cm.get_summary()
    assert summary["total_used"] == 3500
    assert summary["remaining"] == 200000 - 3500
    assert summary["l1_tokens"] == 500
    assert summary["l2_tokens"] == 3000
    assert summary["l3_tokens"] == 0
    assert summary["l1_entries"] == 1
    assert summary["l2_entries"] == 1
    assert summary["l3_entries"] == 0


def test_get_layer_content():
    cm = ContextManager(max_tokens=200000)
    cm.add_content("sys1", "system1", ContextLayer.L1, token_count=100)
    cm.add_content("sys2", "system2", ContextLayer.L1, token_count=200)
    cm.add_content("skill1", "skill_content", ContextLayer.L2, token_count=500)

    l1 = cm.get_l1_content()
    assert len(l1) == 2
    l2 = cm.get_l2_content()
    assert len(l2) == 1