"""Durable Execution & Run Resumption Harness for Tribos.

Closes:
- F-18 / P2.5: First-class run resumption at an interrupted phase
- Checkpoint-at-phase state machine enabling pause, recover, and retry
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RunCheckpoint:
    id: str
    run_id: str
    phase_name: str
    phase_index: int
    created_at: float
    state_payload: dict[str, Any]
    status: str = "completed"  # completed | in_progress | failed


class DurableExecutionHarness:
    """Manages persistent checkpoints for multi-agent runs, allowing resumption across interruptions."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_dir = Path.home() / ".tribos_memory"
            db_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_dir / "checkpoints.sqlite3")
        else:
            self.db_path = str(db_path)
        self._init_db()

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS run_checkpoints (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    phase_name TEXT NOT NULL,
                    phase_index INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    state_json TEXT NOT NULL,
                    status TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chk_run ON run_checkpoints(run_id, phase_index);
                """
            )

    def save_checkpoint(
        self,
        run_id: str,
        phase_name: str,
        phase_index: int,
        state_payload: dict[str, Any],
        status: str = "completed",
    ) -> RunCheckpoint:
        """Save state checkpoint at the boundary of an execution phase."""
        cid = f"chk_{run_id}_{phase_name}_{phase_index}"
        now = time.time()
        chk = RunCheckpoint(
            id=cid,
            run_id=run_id,
            phase_name=phase_name,
            phase_index=phase_index,
            created_at=now,
            state_payload=state_payload,
            status=status,
        )
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO run_checkpoints (id, run_id, phase_name, phase_index, created_at, state_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chk.id,
                    chk.run_id,
                    chk.phase_name,
                    chk.phase_index,
                    chk.created_at,
                    json.dumps(chk.state_payload),
                    chk.status,
                ),
            )
        return chk

    def get_latest_checkpoint(self, run_id: str) -> RunCheckpoint | None:
        """Fetch the most recent valid checkpoint for a run."""
        with self._get_conn() as conn:
            r = conn.execute(
                "SELECT * FROM run_checkpoints WHERE run_id = ? ORDER BY phase_index DESC, created_at DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if not r:
                return None
            return RunCheckpoint(
                id=r["id"],
                run_id=r["run_id"],
                phase_name=r["phase_name"],
                phase_index=r["phase_index"],
                created_at=r["created_at"],
                state_payload=json.loads(r["state_json"]),
                status=r["status"],
            )

    def list_checkpoints(self, run_id: str) -> list[RunCheckpoint]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM run_checkpoints WHERE run_id = ? ORDER BY phase_index ASC",
                (run_id,),
            ).fetchall()
            return [
                RunCheckpoint(
                    id=r["id"],
                    run_id=r["run_id"],
                    phase_name=r["phase_name"],
                    phase_index=r["phase_index"],
                    created_at=r["created_at"],
                    state_payload=json.loads(r["state_json"]),
                    status=r["status"],
                )
                for r in rows
            ]

    def prepare_resumption(self, run_id: str, target_phase: str | None = None) -> dict[str, Any]:
        """Prepare resumption state and return the hydrated state along with the next phase to execute."""
        chk = self.get_latest_checkpoint(run_id)
        if not chk:
            raise ValueError(f"Cannot resume run '{run_id}': no checkpoints found")

        return {
            "run_id": run_id,
            "resumed_from_phase": chk.phase_name,
            "resumed_phase_index": chk.phase_index,
            "state_payload": chk.state_payload,
            "checkpoint_time": chk.created_at,
        }
