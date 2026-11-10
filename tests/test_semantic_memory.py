"""Tests for Semantic Mistake Memory and Cross-Task Retrieval (Pillar 3)."""
from pathlib import Path
import pytest

from sentinel_core.db import SentinelDB
from sentinel_adaptive.mistake_ledger import MistakeMemory


@pytest.fixture
def memory_db(tmp_path: Path):
    db_file = tmp_path / "test_memory.db"
    return SentinelDB(str(db_file))


def test_classify_and_record_semantic_mistake_fallback(memory_db):
    mem = MistakeMemory(memory_db)

    # Insert parent task record for foreign key integrity
    with memory_db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('task_1', 'Test', 'Running', 0, 0)")

    traceback_sample = """
Traceback (most recent call last):
  File "script.py", line 42, in <module>
    mat.diffuse_color = (1, 0, 0)
AttributeError: 'Material' object has no attribute 'diffuse_color'
"""
    # Test without LLM (fallback mode)
    mid = mem.classify_and_record_semantic_mistake(
        task_id="task_1",
        attempt_id="att_1",
        raw_traceback=traceback_sample,
        llm_gateway=None,
        domain="blender",
    )
    assert mid > 0

    mistakes = mem.get_task_mistakes("task_1")
    assert len(mistakes) == 1
    assert "AttributeError" in mistakes[0]["error_signature"]


def test_cross_task_anti_pattern_retrieval(memory_db):
    mem = MistakeMemory(memory_db)

    # Insert past task records
    with memory_db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('task_past_1', 'Past 3D Task', 'Failed', 0, 0)")
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('task_new_2', 'New 3D Task', 'Running', 0, 0)")

    # Record historic mistake from task_past_1
    mem.record_mistake(
        task_id="task_past_1",
        attempt_id="att_past",
        error_category="DEPRECATED_API",
        error_signature="ShaderNodeBsdfPrincipled",
        context={"domain": "blender"},
        lesson_learned="Do not access material.node directly; use mat.node_tree.nodes.",
    )

    # Format anti-pattern prompt for task_new_2 (which has 0 immediate failures)
    prompt = mem.format_anti_pattern_prompt(task_id="task_new_2", domain="blender")

    # Verify cross-task heuristic is present in the prompt
    assert "Cross-Task Historic Heuristics" in prompt
    assert "Do not access material.node directly" in prompt
