"""
Run the formal (Lean + Mathlib) eval suite: each statement is formalised, proved and checked by the Lean kernel with
the same loop the app uses (tribos.verify.formal.formalise_and_check: repairs, Mathlib search, blueprint, lemma
library).

Usage:
    python scripts/eval_formal.py [--model MODEL] [--ids id1,id2] [--out eval_runs/formal.jsonl]

Needs TRIBOS_LEAN_PATH (lake) and TRIBOS_LEAN_PROJECT (a Mathlib project) in .env, and a model key. A problem passes
only when Lean verifies the proof; the Lean statement is printed so faithfulness can be checked by eye.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from dotenv import load_dotenv

DATA = Path(__file__).resolve().parent.parent / "tribos" / "evals" / "formal" / "problems.jsonl"


async def run(model: str | None, ids: set[str], out: Path) -> int:
    from langchain_core.messages import HumanMessage, SystemMessage

    from tribos.utils.llm.llm_factory import get_llm
    from tribos.verify.formal.prove import formalise_and_check

    llm = get_llm(model_name=model)

    async def complete(system: str, user: str) -> str:
        reply = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        return str(getattr(reply, "content", reply))

    cases = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [c for c in cases if not ids or c["id"] in ids]
    passed = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for case in cases:
            start = time.perf_counter()
            res = await formalise_and_check(case["statement"], complete, mathlib=True,
                                            answer_hint=case.get("answer", "") if case.get("hard_mode") else "")
            ok = res["status"] == "verified"
            passed += ok
            row = {"id": case["id"], "difficulty": case["difficulty"], "status": res["status"],
                   "seconds": round(time.perf_counter() - start, 1), "repairs": res.get("repairs"),
                   "blueprint": res.get("blueprint"), "statement": res.get("statement"), "error": res.get("error")}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{'PASS' if ok else 'FAIL'} {case['id']:<32} {row['seconds']:>6}s  {str(res.get('statement'))[:90]}")
    print(f"\n{passed}/{len(cases)} verified by Lean; details in {out}")
    return 0 if passed == len(cases) else 1


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=None)
    parser.add_argument("--ids", default="")
    parser.add_argument("--out", type=Path, default=Path("eval_runs") / f"formal-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    args = parser.parse_args()
    return asyncio.run(run(args.model, {i for i in args.ids.split(",") if i}, args.out))


if __name__ == "__main__":
    raise SystemExit(main())
