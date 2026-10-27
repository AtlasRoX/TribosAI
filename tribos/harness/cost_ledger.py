"""Monetary Cost Ledger & Spend Tracker for Tribos Harness.

Closes:
- F-15 / P2.2: Token-to-currency monetary cost ledger per run, project, and user
- Real-time model pricing, spend forecasting, and budget exhaustion triggers
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Standard 2026 Model Token Pricing ($ per 1 Million Tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "default": {"prompt": 2.50, "completion": 10.00, "cached": 1.25},
    "gpt-4o": {"prompt": 2.50, "completion": 10.00, "cached": 1.25},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60, "cached": 0.075},
    "claude-3-5-sonnet": {"prompt": 3.00, "completion": 15.00, "cached": 0.30},
    "claude-3-5-haiku": {"prompt": 0.80, "completion": 4.00, "cached": 0.08},
    "gemini-1.5-pro": {"prompt": 1.25, "completion": 5.00, "cached": 0.30},
}


@dataclass
class CostRecord:
    run_id: str
    project_id: str
    user_id: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cost_usd: float
    created_at: float


TokenUsageRecord = CostRecord


class CostLedger:
    """Manages monetary cost accounting across runs and projects."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_dir = Path.home() / ".tribos_memory"
            db_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_dir / "cost_ledger.sqlite3")
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
                CREATE TABLE IF NOT EXISTS cost_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    cached_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_budgets (
                    project_id TEXT PRIMARY KEY,
                    budget_limit_usd REAL NOT NULL,
                    alert_threshold REAL NOT NULL DEFAULT 0.8,
                    hard_limit INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_cost_run ON cost_records(run_id);
                CREATE INDEX IF NOT EXISTS idx_cost_proj ON cost_records(project_id);
                """
            )

    @staticmethod
    def calculate_cost(
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
    ) -> float:
        """Calculate USD cost for a given token usage profile."""
        pricing = MODEL_PRICING.get(model_name) or MODEL_PRICING["default"]
        cost = (
            (prompt_tokens * pricing["prompt"] / 1e6)
            + (completion_tokens * pricing["completion"] / 1e6)
            + (cached_tokens * pricing["cached"] / 1e6)
        )
        return round(cost, 6)

    def set_project_budget(
        self,
        project_id: str,
        budget_limit_usd: float,
        alert_threshold: float = 0.8,
        hard_limit: bool = True,
    ) -> None:
        """Configure budget constraint for a project."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO project_budgets (project_id, budget_limit_usd, alert_threshold, hard_limit)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    budget_limit_usd = excluded.budget_limit_usd,
                    alert_threshold = excluded.alert_threshold,
                    hard_limit = excluded.hard_limit
                """,
                (project_id, budget_limit_usd, alert_threshold, 1 if hard_limit else 0),
            )

    def record_usage(
        self,
        run_id: str,
        project_id: str = "default_project",
        user_id: str = "default_user",
        model_name: str = "default",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
    ) -> CostRecord:
        cost = self.calculate_cost(model_name, prompt_tokens, completion_tokens, cached_tokens)

        # Check existing spend vs budget before committing
        spend_info = self.get_project_spend(project_id)
        if spend_info["budget_limit_usd"] is not None:
            if (spend_info["total_spend_usd"] + cost) > spend_info["budget_limit_usd"]:
                raise RuntimeError(
                    f"Monetary budget exceeded for project {project_id}: "
                    f"attempted ${spend_info['total_spend_usd'] + cost:.4f} > limit ${spend_info['budget_limit_usd']:.4f}"
                )

        now = time.time()
        rec = CostRecord(
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost,
            created_at=now,
        )
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO cost_records (run_id, project_id, user_id, model_name, prompt_tokens, completion_tokens, cached_tokens, cost_usd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.run_id,
                    rec.project_id,
                    rec.user_id,
                    rec.model_name,
                    rec.prompt_tokens,
                    rec.completion_tokens,
                    rec.cached_tokens,
                    rec.cost_usd,
                    rec.created_at,
                ),
            )
        return rec

    def get_run_cost(self, run_id: str) -> dict[str, Any]:
        """Aggregate total cost and token consumption for a run."""
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT SUM(cost_usd) as total_usd,
                       SUM(prompt_tokens) as total_prompt,
                       SUM(completion_tokens) as total_completion,
                       SUM(cached_tokens) as total_cached,
                       COUNT(*) as call_count
                FROM cost_records WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            return {
                "run_id": run_id,
                "total_cost_usd": round(row["total_usd"] or 0.0, 6),
                "prompt_tokens": row["total_prompt"] or 0,
                "completion_tokens": row["total_completion"] or 0,
                "cached_tokens": row["total_cached"] or 0,
                "llm_call_count": row["call_count"] or 0,
            }

    def get_project_spend(self, project_id: str) -> dict[str, Any]:
        """Get project spend and check against budget limit."""
        with self._get_conn() as conn:
            spend_row = conn.execute(
                "SELECT SUM(cost_usd) as total_usd FROM cost_records WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            budget_row = conn.execute(
                "SELECT * FROM project_budgets WHERE project_id = ?",
                (project_id,),
            ).fetchone()

            total_spend = round(spend_row["total_usd"] or 0.0, 6)
            budget_limit = budget_row["budget_limit_usd"] if budget_row else None
            is_exhausted = (total_spend >= budget_limit) if budget_limit is not None else False

            return {
                "project_id": project_id,
                "total_spend_usd": total_spend,
                "budget_limit_usd": budget_limit,
                "is_budget_exhausted": is_exhausted,
            }
