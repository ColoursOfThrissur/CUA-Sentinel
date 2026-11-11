"""Sentinel Database Connection Manager.
Manages SQLite in WAL mode with connection pooling, transactional context, and schema initialization.
"""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from sentinel_core.schema import SCHEMA_SQL


class SentinelDB:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            # Automatic schema migration: ensure 'Cancelled' is permitted in tasks state CHECK constraint
            row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
            if row and row[0] and "'Cancelled'" not in row[0]:
                conn.execute("PRAGMA foreign_keys=OFF;")
                new_sql = row[0].replace("'NeedsReconciliation')", "'NeedsReconciliation', 'Cancelled')")
                new_sql = new_sql.replace("CREATE TABLE tasks", "CREATE TABLE tasks_migrated_tmp")
                conn.execute(new_sql)
                conn.execute("INSERT INTO tasks_migrated_tmp SELECT * FROM tasks;")
                conn.execute("DROP TABLE tasks;")
                conn.execute("ALTER TABLE tasks_migrated_tmp RENAME TO tasks;")
                conn.execute("PRAGMA foreign_keys=ON;")

            # Migration for dag_runs
            dag_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='dag_runs'").fetchone()
            if dag_row and dag_row[0] and "'Cancelled'" not in dag_row[0]:
                conn.execute("PRAGMA foreign_keys=OFF;")
                new_sql = dag_row[0].replace("'Failed')", "'Failed', 'Cancelled')")
                new_sql = new_sql.replace("CREATE TABLE dag_runs", "CREATE TABLE dag_runs_migrated_tmp")
                conn.execute(new_sql)
                conn.execute("INSERT INTO dag_runs_migrated_tmp SELECT * FROM dag_runs;")
                conn.execute("DROP TABLE dag_runs;")
                conn.execute("ALTER TABLE dag_runs_migrated_tmp RENAME TO dag_runs;")
                conn.execute("PRAGMA foreign_keys=ON;")

            # Migration for dag_steps
            step_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='dag_steps'").fetchone()
            if step_row and step_row[0] and "'Cancelled'" not in step_row[0]:
                conn.execute("PRAGMA foreign_keys=OFF;")
                new_sql = step_row[0].replace("'Skipped')", "'Skipped', 'Cancelled')")
                new_sql = new_sql.replace("CREATE TABLE dag_steps", "CREATE TABLE dag_steps_migrated_tmp")
                conn.execute(new_sql)
                conn.execute("INSERT INTO dag_steps_migrated_tmp SELECT * FROM dag_steps;")
                conn.execute("DROP TABLE dag_steps;")
                conn.execute("ALTER TABLE dag_steps_migrated_tmp RENAME TO dag_steps;")
                conn.execute("PRAGMA foreign_keys=ON;")

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.cursor()
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute_read(self, sql: str, params: tuple | list | dict = ()) -> list[sqlite3.Row]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()

    def execute_one(self, sql: str, params: tuple | list | dict = ()) -> sqlite3.Row | None:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchone()
        finally:
            conn.close()
