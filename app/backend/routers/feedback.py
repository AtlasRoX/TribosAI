"""Answer feedback (thumbs up / down, an optional note): POST /api/feedback.

Each rating is one JSON line in `<TRIBOS_FEEDBACK_DIR>/feedback.jsonl` (default `<data>/feedback`), with the run id, the
question, the mode (framework) and model that answered, and a hashed user id. It is the labelled data a learned
router needs (which mode answered which kind of question well); a later rating of the same run replaces the earlier one
when the file is read (`latest_ratings`).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.backend.auth import get_current_user

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
_lock = threading.Lock()


class FeedbackIn(BaseModel):
    rating: Literal["up", "down", "none"]
    run_id: str | None = Field(default=None, max_length=80)
    thread_id: str | None = Field(default=None, max_length=200)
    message_id: str | None = Field(default=None, max_length=200)
    question: str = Field(default="", max_length=4000)
    framework: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=200)
    note: str = Field(default="", max_length=2000)


def feedback_path() -> Path:
    env = os.getenv("TRIBOS_FEEDBACK_DIR")
    if env:
        root = Path(env)
    else:
        from tribos.utils.paths import data_dir

        data = data_dir("feedback")
        if data is not None:
            root = data
        elif "PYTEST_CURRENT_TEST" in os.environ:
            root = Path(tempfile.gettempdir()) / "tribos_feedback_pytest"
        else:
            root = Path(__file__).resolve().parents[3] / "data" / "feedback"
    root.mkdir(parents=True, exist_ok=True)
    return root / "feedback.jsonl"


def latest_ratings(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """The latest rating per message (or run), as written by POST /api/feedback."""
    path = path or feedback_path()
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        out[str(row.get("message_id") or row.get("run_id") or len(out))] = row
    return out


@router.post("")
async def give_feedback(body: FeedbackIn, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    row = {**body.model_dump(), "user": hashlib.sha256(user_id.encode()).hexdigest()[:16], "at": time.time()}
    with _lock, feedback_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "rating": body.rating}
