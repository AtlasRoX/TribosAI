"""
Export the claims of saved runs into a file a person labels, ready for scripts/calibrate_confidence.py.

Usage:
    python scripts/export_claims_for_labelling.py RUN.json [RUN2.json eval_runs/<run>/results.jsonl ...] --out claims.jsonl

Each input is a saved run (the API's "done" event or its "result"), or an eval run's results.jsonl; every claim found
under execution_artifacts.claim_confidence.claims is written as one line:

    {"answer_id": "...", "label": null, "features": {...}, "claim_text": "...", "claim_type": "...",
     "question": "...", "labeller": "", "synthetic": false}

Set "label" to 1 (the claim is correct) or 0 (it is not) and "labeller" to who judged it, then run
    python scripts/calibrate_confidence.py --labelled claims.jsonl
which refuses to fit until enough real claims from enough answers are labelled (docs/plans/
tribos-research-upgrade-plan.md 2.4). Rows still unlabelled are skipped there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _results(obj: Any) -> list[dict[str, Any]]:
    """Every run result (a dict with execution_artifacts) inside a loaded JSON value."""
    out: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        if isinstance(obj.get("execution_artifacts"), dict):
            out.append(obj)
        for value in obj.values():
            out.extend(_results(value))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(_results(value))
    return out


def _load(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


def export(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        for doc in _load(path):
            for result in _results(doc):
                question = str((result.get("query_context") or {}).get("query") or result.get("query") or "")
                answer = str(result.get("response") or "")
                answer_id = str(result.get("run_id") or result.get("thread_id")
                                or hashlib.sha256((question + answer).encode("utf-8")).hexdigest()[:16])
                claims = ((result.get("execution_artifacts") or {}).get("claim_confidence") or {}).get("claims") or []
                for claim in claims:
                    if not isinstance(claim, dict) or not isinstance(claim.get("features"), dict):
                        continue
                    key = (answer_id, str(claim.get("text") or ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({"answer_id": answer_id, "label": None, "features": claim["features"],
                                 "claim_text": claim.get("text") or "", "claim_type": claim.get("claim_type") or "",
                                 "question": question[:500], "labeller": "", "synthetic": False})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = export(args.inputs)
    with args.out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    answers = len({r["answer_id"] for r in rows})
    print(f"wrote {len(rows)} claims from {answers} answers to {args.out}; label each 0 or 1, then run "
          f"scripts/calibrate_confidence.py --labelled {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
