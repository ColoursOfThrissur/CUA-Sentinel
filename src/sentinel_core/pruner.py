"""Sentinel Data Pruning & Storage Hygiene Engine.
Provides automated retention enforcement, database compacting (VACUUM),
mistake deduplication, and workspace artifact lifecycle management.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentinel_core.config import RetentionConfig
from sentinel_core.db import SentinelDB

logger = logging.getLogger("SentinelPruner")


@dataclass
class PruneResult:
    tasks_pruned: int = 0
    transitions_pruned: int = 0
    attempts_pruned: int = 0
    effects_pruned: int = 0
    mistakes_pruned: int = 0
    dag_runs_pruned: int = 0
    audit_events_pruned: int = 0
    workspace_files_removed: int = 0
    workspace_dirs_removed: int = 0
    workspace_bytes_reclaimed: int = 0
    db_size_before_bytes: int = 0
    db_size_after_bytes: int = 0
    vacuumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks_pruned": self.tasks_pruned,
            "transitions_pruned": self.transitions_pruned,
            "attempts_pruned": self.attempts_pruned,
            "effects_pruned": self.effects_pruned,
            "mistakes_pruned": self.mistakes_pruned,
            "dag_runs_pruned": self.dag_runs_pruned,
            "audit_events_pruned": self.audit_events_pruned,
            "workspace_files_removed": self.workspace_files_removed,
            "workspace_dirs_removed": self.workspace_dirs_removed,
            "workspace_bytes_reclaimed": self.workspace_bytes_reclaimed,
            "db_size_before_bytes": self.db_size_before_bytes,
            "db_size_after_bytes": self.db_size_after_bytes,
            "db_bytes_reclaimed": max(0, self.db_size_before_bytes - self.db_size_after_bytes),
            "vacuumed": self.vacuumed,
        }


class StoragePruner:
    """Manages database data retention, error ledger deduplication, and workspace hygiene."""

    @staticmethod
    def get_storage_summary(db: SentinelDB, workspaces_dir: Path | str | None = None) -> dict[str, Any]:
        """Calculates storage footprint across database tables and workspace directories."""
        db_file = Path(db.db_path)
        db_size = db_file.stat().st_size if db_file.exists() else 0
        wal_file = db_file.with_name(f"{db_file.name}-wal")
        if wal_file.exists():
            db_size += wal_file.stat().st_size

        tables = [
            "tasks", "task_transitions", "attempts", "side_effect_ledger",
            "audit_events", "mistake_ledger", "skills", "agents",
            "agent_releases", "dag_runs", "dag_steps"
        ]
        counts: dict[str, int] = {}
        for tbl in tables:
            try:
                row = db.execute_one(f"SELECT COUNT(*) as cnt FROM {tbl}")
                counts[tbl] = row["cnt"] if row else 0
            except Exception:
                counts[tbl] = 0

        # Workspace stats
        ws_file_count = 0
        ws_size_bytes = 0
        if workspaces_dir:
            ws_path = Path(workspaces_dir).resolve()
            if ws_path.exists():
                for root, _, files in os.walk(ws_path):
                    for f in files:
                        p = os.path.join(root, f)
                        try:
                            ws_size_bytes += os.path.getsize(p)
                            ws_file_count += 1
                        except OSError:
                            pass

        return {
            "database_path": str(db_file),
            "database_size_bytes": db_size,
            "database_size_mb": round(db_size / (1024 * 1024), 2),
            "table_counts": counts,
            "workspace_file_count": ws_file_count,
            "workspace_size_bytes": ws_size_bytes,
            "workspace_size_mb": round(ws_size_bytes / (1024 * 1024), 2),
        }

    @classmethod
    def prune_database(
        cls,
        db: SentinelDB,
        max_task_age_days: int = 7,
        max_tasks_count: int = 500,
        deduplicate_mistakes: bool = True,
        prune_audit_events_days: int = 14,
        prune_dag_runs_days: int = 7,
        vacuum: bool = True,
    ) -> PruneResult:
        """Prunes stale tasks, duplicate mistakes, and compacts database file."""
        res = PruneResult()
        db_file = Path(db.db_path)
        res.db_size_before_bytes = db_file.stat().st_size if db_file.exists() else 0
        now = time.time()
        task_cutoff = now - (max_task_age_days * 86400)
        dag_cutoff = now - (prune_dag_runs_days * 86400)
        audit_cutoff = now - (prune_audit_events_days * 86400)

        # 1. Prune terminal tasks older than cutoff
        with db.transaction() as cur:
            # Query candidate tasks for deletion
            cur.execute(
                """
                SELECT id FROM tasks 
                WHERE state IN ('Succeeded', 'Failed', 'Cancelled')
                  AND created_at < ?
                """,
                (task_cutoff,),
            )
            old_task_ids = [r["id"] for r in cur.fetchall()]

            # Also check if terminal tasks exceed max_tasks_count
            cur.execute(
                """
                SELECT COUNT(*) as cnt FROM tasks 
                WHERE state IN ('Succeeded', 'Failed', 'Cancelled')
                """
            )
            total_terminal = cur.fetchone()["cnt"]
            if total_terminal - len(old_task_ids) > max_tasks_count:
                excess = (total_terminal - len(old_task_ids)) - max_tasks_count
                cur.execute(
                    """
                    SELECT id FROM tasks 
                    WHERE state IN ('Succeeded', 'Failed', 'Cancelled')
                      AND id NOT IN ({seq})
                    ORDER BY created_at ASC
                    LIMIT ?
                    """.format(seq=",".join("?" for _ in old_task_ids) if old_task_ids else "''"),
                    (*old_task_ids, excess) if old_task_ids else (excess,),
                )
                old_task_ids.extend([r["id"] for r in cur.fetchall()])

            if old_task_ids:
                # Delete tasks (SQLite foreign keys ON DELETE CASCADE automatically clears attempts, transitions, side effects)
                # Using batch delete in chunks of 200
                chunk_size = 200
                for i in range(0, len(old_task_ids), chunk_size):
                    chunk = old_task_ids[i:i + chunk_size]
                    cur.execute(
                        f"DELETE FROM tasks WHERE id IN ({','.join('?' for _ in chunk)})",
                        chunk,
                    )
                res.tasks_pruned = len(old_task_ids)

            # 2. Prune old terminal DAG runs
            cur.execute(
                """
                SELECT id FROM dag_runs
                WHERE state IN ('Succeeded', 'Failed', 'Cancelled')
                  AND created_at < ?
                """,
                (dag_cutoff,),
            )
            old_dag_ids = [r["id"] for r in cur.fetchall()]
            if old_dag_ids:
                chunk_size = 200
                for i in range(0, len(old_dag_ids), chunk_size):
                    chunk = old_dag_ids[i:i + chunk_size]
                    cur.execute(
                        f"DELETE FROM dag_runs WHERE id IN ({','.join('?' for _ in chunk)})",
                        chunk,
                    )
                res.dag_runs_pruned = len(old_dag_ids)

            # 3. Prune old audit events
            cur.execute("DELETE FROM audit_events WHERE ts < ?", (audit_cutoff,))
            res.audit_events_pruned = cur.rowcount if cur.rowcount > 0 else 0

            # 4. Deduplicate mistake ledger (keep only the newest entry per error signature)
            if deduplicate_mistakes:
                cur.execute(
                    """
                    DELETE FROM mistake_ledger
                    WHERE id NOT IN (
                        SELECT MAX(id)
                        FROM mistake_ledger
                        GROUP BY error_category, error_signature
                    )
                    """
                )
                res.mistakes_pruned = cur.rowcount if cur.rowcount > 0 else 0

        # 5. Database Vacuum & Compact
        if vacuum:
            try:
                # VACUUM cannot run inside a transaction; execute on raw connection
                conn = db._get_connection()
                try:
                    conn.execute("VACUUM;")
                    conn.execute("PRAGMA optimize;")
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    res.vacuumed = True
                finally:
                    conn.close()
            except Exception as e:
                logger.warning(f"Database VACUUM encountered notice: {e}")

        res.db_size_after_bytes = db_file.stat().st_size if db_file.exists() else 0
        return res

    @classmethod
    def prune_workspaces(
        cls,
        workspaces_dir: Path | str,
        active_task_ids: set[str] | None = None,
        max_age_hours: float = 24.0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Scans workspace directory to remove orphan artifacts and stale temporary directories."""
        ws_path = Path(workspaces_dir).resolve()
        if not ws_path.exists():
            return {"files_removed": 0, "dirs_removed": 0, "bytes_reclaimed": 0}

        now = time.time()
        age_cutoff = now - (max_age_hours * 3600)
        active_ids = active_task_ids or set()

        files_to_delete: list[Path] = []
        dirs_to_delete: list[Path] = []
        bytes_to_reclaim = 0

        for root, dirs, files in os.walk(ws_path):
            root_path = Path(root)
            # Check if this subfolder is an ephemeral test folder or inspection folder
            rel = root_path.relative_to(ws_path)
            parts = rel.parts
            if parts and (
                parts[0].startswith("test_") or
                parts[0].endswith("_inspection")
            ):
                try:
                    mtime = root_path.stat().st_mtime
                    if mtime < age_cutoff:
                        if root_path not in dirs_to_delete and root_path != ws_path:
                            dirs_to_delete.append(root_path)
                except OSError:
                    pass

            for f in files:
                f_path = root_path / f
                # Detect task artifact file pattern: task_<id>.* or task_cli_<id>.*
                f_stem = f_path.stem
                is_task_file = f_stem.startswith("task_") or f_stem.startswith("task_cli_")
                try:
                    st = f_path.stat()
                    f_size = st.st_size
                    f_mtime = st.st_mtime

                    # If it's a task file and task is no longer in active/retained set
                    if is_task_file:
                        tid = f_stem
                        if tid not in active_ids and f_mtime < age_cutoff:
                            files_to_delete.append(f_path)
                            bytes_to_reclaim += f_size
                    elif f_path.suffix in {".obj", ".mtl", ".png", ".txt", ".blend", ".blend1"} and f_mtime < age_cutoff:
                        # Stale temporary 3D/inspection file
                        if not any(f_path.is_relative_to(d) for d in dirs_to_delete):
                            files_to_delete.append(f_path)
                            bytes_to_reclaim += f_size
                except OSError:
                    pass

        if not dry_run:
            # Delete identified files
            deleted_files = 0
            for f in files_to_delete:
                try:
                    if f.exists() and f.is_file():
                        f.unlink()
                        deleted_files += 1
                except OSError:
                    pass

            # Delete identified directories
            deleted_dirs = 0
            for d in dirs_to_delete:
                try:
                    if d.exists() and d.is_dir():
                        shutil.rmtree(d, ignore_errors=True)
                        deleted_dirs += 1
                except OSError:
                    pass

            return {
                "files_removed": deleted_files,
                "dirs_removed": deleted_dirs,
                "bytes_reclaimed": bytes_to_reclaim,
            }

        return {
            "files_removed": len(files_to_delete),
            "dirs_removed": len(dirs_to_delete),
            "bytes_reclaimed": bytes_to_reclaim,
        }

    @classmethod
    def prune_all(
        cls,
        db: SentinelDB,
        workspaces_dir: Path | str,
        retention_config: RetentionConfig | None = None,
    ) -> PruneResult:
        """Executes full retention cycle across database and workspace storage."""
        cfg = retention_config or RetentionConfig()
        if not cfg.enabled:
            logger.info("Storage pruning skipped: retention is disabled in config.")
            return PruneResult()

        # 1. Prune database
        res = cls.prune_database(
            db=db,
            max_task_age_days=cfg.max_task_age_days,
            max_tasks_count=cfg.max_tasks_count,
            deduplicate_mistakes=cfg.deduplicate_mistakes,
            prune_audit_events_days=cfg.max_task_age_days * 2,
            prune_dag_runs_days=cfg.max_task_age_days,
            vacuum=cfg.vacuum_db_on_prune,
        )

        # 2. Prune workspace artifacts if enabled
        if cfg.prune_orphan_workspaces:
            # Gather active / retained task IDs from database
            rows = db.execute_read("SELECT id FROM tasks")
            retained_task_ids = {r["id"] for r in rows}

            ws_res = cls.prune_workspaces(
                workspaces_dir=workspaces_dir,
                active_task_ids=retained_task_ids,
                max_age_hours=float(cfg.max_task_age_days * 24),
                dry_run=False,
            )
            res.workspace_files_removed = ws_res["files_removed"]
            res.workspace_dirs_removed = ws_res["dirs_removed"]
            res.workspace_bytes_reclaimed = ws_res["bytes_reclaimed"]

        return res
