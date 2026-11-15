"""Unit Tests for Sentinel Data Pruning & Observability Storage Retention Engine."""
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from sentinel_core.config import RetentionConfig
from sentinel_core.db import SentinelDB
from sentinel_core.pruner import StoragePruner


@pytest.fixture
def temp_env():
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_sentinel.db"
    ws_dir = Path(temp_dir) / "workspaces"
    ws_dir.mkdir(parents=True, exist_ok=True)
    db = SentinelDB(db_path)
    yield db, ws_dir, temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_get_storage_summary(temp_env):
    db, ws_dir, _ = temp_env

    # Insert a task
    now = time.time()
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("task_test_1", "Test Task", "Succeeded", now, now),
        )

    # Create dummy workspace file
    dummy_file = ws_dir / "sample.obj"
    dummy_file.write_text("v 0 0 0\n", encoding="utf-8")

    summary = StoragePruner.get_storage_summary(db, ws_dir)
    assert summary["database_size_bytes"] > 0
    assert summary["table_counts"]["tasks"] == 1
    assert summary["workspace_file_count"] == 1
    assert summary["workspace_size_bytes"] > 0


def test_prune_database_tasks_and_cascade(temp_env):
    db, _, _ = temp_env
    now = time.time()
    old_ts = now - (10 * 86400)  # 10 days old

    with db.transaction() as cur:
        # Old terminal task (should be pruned)
        cur.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("task_old_1", "Old Succeeded Task", "Succeeded", old_ts, old_ts),
        )
        cur.execute(
            "INSERT INTO attempts (id, task_id, attempt_number, lease_token, status, started_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("att_1", "task_old_1", 1, 1001, "Committed", old_ts),
        )
        cur.execute(
            "INSERT INTO side_effect_ledger (attempt_id, effect_class, tool_name, intent_payload, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("att_1", "IDEMPOTENT_WRITE", "fs_write", "{}", "OUTCOME_RECORDED", old_ts),
        )

        # Recent terminal task (should NOT be pruned)
        cur.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("task_recent_1", "Recent Succeeded Task", "Succeeded", now, now),
        )

        # Old active/running task (should NEVER be pruned regardless of age)
        cur.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("task_running_old", "Old Running Task", "Running", old_ts, old_ts),
        )

    res = StoragePruner.prune_database(
        db=db,
        max_task_age_days=7,
        max_tasks_count=500,
        deduplicate_mistakes=True,
        vacuum=False,
    )

    assert res.tasks_pruned == 1

    # Verify task_old_1 is gone
    row = db.execute_one("SELECT * FROM tasks WHERE id = 'task_old_1'")
    assert row is None

    # Verify CASCADE deleted attempts and side effects
    att_row = db.execute_one("SELECT * FROM attempts WHERE id = 'att_1'")
    assert att_row is None
    eff_row = db.execute_one("SELECT * FROM side_effect_ledger WHERE attempt_id = 'att_1'")
    assert eff_row is None

    # Verify recent and running tasks are preserved
    assert db.execute_one("SELECT * FROM tasks WHERE id = 'task_recent_1'") is not None
    assert db.execute_one("SELECT * FROM tasks WHERE id = 'task_running_old'") is not None


def test_mistake_ledger_deduplication(temp_env):
    db, _, _ = temp_env
    now = time.time()

    with db.transaction() as cur:
        # Create a parent task for foreign key constraint
        cur.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("task_shared", "Shared Task", "Running", now, now),
        )
        # Insert 3 identical mistakes
        for i in range(3):
            cur.execute(
                """
                INSERT INTO mistake_ledger (task_id, error_category, error_signature, context, lesson_learned, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("task_shared", "BlenderSyntax", "NameError: bpy", f"Context {i}", f"Lesson {i}", now + i),
            )
        # Insert 1 distinct mistake
        cur.execute(
            """
            INSERT INTO mistake_ledger (task_id, error_category, error_signature, context, lesson_learned, ts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("task_shared", "Timeout", "TimeoutError: LLM", "ctx", "lesson", now),
        )

    res = StoragePruner.prune_database(
        db=db,
        max_task_age_days=30,
        deduplicate_mistakes=True,
        vacuum=False,
    )

    assert res.mistakes_pruned == 2
    # Verify exactly 2 distinct signatures remain
    rows = db.execute_read("SELECT * FROM mistake_ledger ORDER BY id ASC")
    assert len(rows) == 2
    # The remaining BlenderSyntax mistake should be the latest one (Lesson 2)
    latest_blender = [r for r in rows if r["error_category"] == "BlenderSyntax"][0]
    assert latest_blender["lesson_learned"] == "Lesson 2"


def test_prune_workspaces(temp_env):
    _, ws_dir, _ = temp_env
    old_time = time.time() - (48 * 3600)  # 48 hours ago

    # Active task file (should NOT be pruned)
    active_file = ws_dir / "task_100.obj"
    active_file.write_text("v 1 1 1", encoding="utf-8")
    os.utime(active_file, (old_time, old_time))

    # Orphan task file (should be pruned)
    orphan_file = ws_dir / "task_999.obj"
    orphan_file.write_text("v 2 2 2", encoding="utf-8")
    os.utime(orphan_file, (old_time, old_time))

    # Stale test subfolder (should be pruned)
    test_subfolder = ws_dir / "test_old_run"
    test_subfolder.mkdir()
    (test_subfolder / "detail.png").write_text("fake image", encoding="utf-8")
    os.utime(test_subfolder, (old_time, old_time))

    res = StoragePruner.prune_workspaces(
        workspaces_dir=ws_dir,
        active_task_ids={"task_100"},
        max_age_hours=24.0,
        dry_run=False,
    )

    assert res["files_removed"] >= 1
    assert res["dirs_removed"] >= 1
    assert active_file.exists()
    assert not orphan_file.exists()
    assert not test_subfolder.exists()


def test_prune_all_orchestration(temp_env):
    db, ws_dir, _ = temp_env
    cfg = RetentionConfig(
        enabled=True,
        max_task_age_days=7,
        max_tasks_count=100,
        prune_orphan_workspaces=True,
        deduplicate_mistakes=True,
        vacuum_db_on_prune=True,
    )

    res = StoragePruner.prune_all(db, ws_dir, cfg)
    assert res.vacuumed is True
    report = res.to_dict()
    assert "tasks_pruned" in report
    assert "workspace_bytes_reclaimed" in report
    assert "db_bytes_reclaimed" in report
