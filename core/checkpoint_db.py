import sqlite3
import json
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

class CheckpointDB:
    """
    Thread-safe SQLite checkpoint store for pipeline runs.
    All public methods are async; they delegate blocking I/O 
    to a single-threaded ThreadPoolExecutor.
    """
    def __init__(self, db_path: str = "checkpoint.db"):
        self.db_path = db_path
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id      TEXT PRIMARY KEY,
                    vendor_name TEXT NOT NULL,
                    company_details_json TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'running',
                    started_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS step_results (
                    run_id          TEXT NOT NULL,
                    entity_name     TEXT NOT NULL,
                    step_name       TEXT NOT NULL,
                    status          TEXT NOT NULL,  -- 'completed' | 'failed'
                    step_result_json TEXT NOT NULL,
                    completed_at    TEXT NOT NULL,
                    PRIMARY KEY (run_id, entity_name, step_name)
                );

                CREATE TABLE IF NOT EXISTS supervisor_interventions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id          TEXT NOT NULL,
                    replan_json     TEXT NOT NULL,  -- steps_to_run, rationale
                    context_updates_json TEXT,       -- updated fields
                    applied_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS traversal_queue (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id          TEXT NOT NULL,
                    entity_name     TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    depth           INTEGER NOT NULL DEFAULT 1,
                    parent_entity   TEXT,
                    entity_role     TEXT NOT NULL DEFAULT 'supplier',
                    queued_at       TEXT NOT NULL,
                    processed_at    TEXT
                );
            """)
            conn.commit()
            
            # Migration: add entity_name column if missing (for existing DBs from old schema)
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(step_results)")}
            if "entity_name" not in existing_cols:
                conn.execute("ALTER TABLE step_results ADD COLUMN entity_name TEXT NOT NULL DEFAULT ''")
                conn.commit()
            
    async def _run_in_executor(self, func, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    # --- pipeline_runs ---
    def _start_run_sync(self, run_id, vendor_name, company_details_json):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pipeline_runs (run_id, vendor_name, company_details_json, status, started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, vendor_name, company_details_json, 'running', datetime.now().isoformat(), datetime.now().isoformat())
            )
            
    async def start_run(self, run_id, vendor_name, company_details_json):
        await self._run_in_executor(self._start_run_sync, run_id, vendor_name, company_details_json)
        
    def _update_run_status_sync(self, run_id, status):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE pipeline_runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, datetime.now().isoformat(), run_id)
            )

    async def complete_run(self, run_id):
        await self._run_in_executor(self._update_run_status_sync, run_id, 'completed')

    async def fail_run(self, run_id):
        await self._run_in_executor(self._update_run_status_sync, run_id, 'failed')

    def _get_interrupted_runs_sync(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT run_id, vendor_name, started_at FROM pipeline_runs WHERE status = 'running'")
            return [{"run_id": row[0], "vendor_name": row[1], "started_at": row[2]} for row in cursor.fetchall()]

    async def get_interrupted_runs(self) -> list[dict]:
        return await self._run_in_executor(self._get_interrupted_runs_sync)

    def _get_run_sync(self, run_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT run_id, vendor_name, company_details_json, status, started_at FROM pipeline_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "run_id": row[0],
                    "vendor_name": row[1],
                    "company_details_json": row[2],
                    "status": row[3],
                    "started_at": row[4]
                }
            return None

    async def get_run(self, run_id) -> dict | None:
        return await self._run_in_executor(self._get_run_sync, run_id)

    # --- step_results ---
    def _save_step_result_sync(self, run_id, entity_name, step_name, result_json):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO step_results (run_id, entity_name, step_name, status, step_result_json, completed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, entity_name, step_name, 'completed', result_json, datetime.now().isoformat())
            )

    async def save_step_result(self, run_id, entity_name, step_name, result_json):
        await self._run_in_executor(self._save_step_result_sync, run_id, entity_name, step_name, result_json)

    def _get_completed_steps_sync(self, run_id, entity_name):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT step_name, step_result_json FROM step_results WHERE run_id = ? AND entity_name = ?", (run_id, entity_name))
            return {row[0]: row[1] for row in cursor.fetchall()}

    async def get_completed_steps(self, run_id, entity_name) -> dict[str, str]:
        return await self._run_in_executor(self._get_completed_steps_sync, run_id, entity_name)

    # --- supervisor_interventions ---
    def _save_intervention_sync(self, run_id, replan_json, context_json):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO supervisor_interventions (run_id, replan_json, context_updates_json, applied_at) VALUES (?, ?, ?, ?)",
                (run_id, replan_json, context_json, datetime.now().isoformat())
            )

    async def save_intervention(self, run_id, replan_json, context_json):
        await self._run_in_executor(self._save_intervention_sync, run_id, replan_json, context_json)

    # --- traversal_queue ---
    def _enqueue_entity_sync(self, run_id, entity_name, depth, parent, role):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO traversal_queue (run_id, entity_name, depth, parent_entity, entity_role, queued_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, entity_name, depth, parent, role, datetime.now().isoformat())
            )

    async def enqueue_entity(self, run_id, entity_name, depth, parent, role):
        await self._run_in_executor(self._enqueue_entity_sync, run_id, entity_name, depth, parent, role)

    def _mark_in_progress_sync(self, run_id, entity_name):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE traversal_queue SET status = 'in_progress' WHERE run_id = ? AND entity_name = ? AND status = 'pending'",
                (run_id, entity_name)
            )

    async def mark_in_progress(self, run_id, entity_name):
        await self._run_in_executor(self._mark_in_progress_sync, run_id, entity_name)

    def _mark_processed_sync(self, run_id, entity_name, status):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE traversal_queue SET status = ?, processed_at = ? WHERE run_id = ? AND entity_name = ?",
                (status, datetime.now().isoformat(), run_id, entity_name)
            )

    async def mark_processed(self, run_id, entity_name, status):
        await self._run_in_executor(self._mark_processed_sync, run_id, entity_name, status)

    def _reset_in_progress_sync(self, run_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE traversal_queue SET status = 'pending' WHERE run_id = ? AND status IN ('in_progress', 'cancelled', 'failed')",
                (run_id,)
            )

    async def reset_in_progress(self, run_id):
        await self._run_in_executor(self._reset_in_progress_sync, run_id)

    def _get_pending_entities_sync(self, run_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT entity_name, depth, parent_entity, entity_role FROM traversal_queue WHERE run_id = ? AND status = 'pending'", (run_id,))
            return [{"entity_name": row[0], "depth": row[1], "parent_entity": row[2], "role": row[3]} for row in cursor.fetchall()]

    async def get_pending_entities(self, run_id) -> list[dict]:
        return await self._run_in_executor(self._get_pending_entities_sync, run_id)

    def _delete_runs_sync(self, run_ids: list[str]):
        if not run_ids:
            return
        with sqlite3.connect(self.db_path) as conn:
            placeholders = ','.join('?' * len(run_ids))
            conn.execute(f"DELETE FROM pipeline_runs WHERE run_id IN ({placeholders})", run_ids)
            conn.execute(f"DELETE FROM step_results WHERE run_id IN ({placeholders})", run_ids)
            conn.execute(f"DELETE FROM traversal_queue WHERE run_id IN ({placeholders})", run_ids)
            conn.execute(f"DELETE FROM supervisor_interventions WHERE run_id IN ({placeholders})", run_ids)

    async def delete_runs(self, run_ids: list[str]):
        await self._run_in_executor(self._delete_runs_sync, run_ids)
