"""Build the public mirror (github.com/AtlasRoX/TribosAI) from this repository's main branch.

The public repository carries the code, tests, website and user documentation, never the internal material: audit
reports, earlier repair prompts, planning notes, the private benchmark records and agent-only instructions. This
script makes that a repeatable step instead of a hand edit:

1. A git worktree is opened on the public branch (`--remote`/`--branch`, default `tribosai/main`).
2. Every file of `main` that is not excluded (EXCLUDE) is copied in; files the public repository curates itself
   (PUBLIC_OWNED) keep their public version; files that `main` no longer has are removed.
3. Transforms: `
` blocks are cut from every text file; CHANGELOG.md loses its
   links to private commits and the entries about internal records; AGENTS.md loses its pointers to internal reports.
4. Checks: no excluded path, no private block or private link left, no secret-looking string added. A failed check
   stops the script before anything is committed.

Nothing is committed or pushed unless asked:

    uv run python scripts/sync_public.py                      # build the worktree and report
    uv run python scripts/sync_public.py --commit "feat: ..."  # also commit there
    uv run python scripts/sync_public.py --commit "..." --push --tag v1.4.0   # and push (fast-forward only)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Internal material: never published.
EXCLUDE = re.compile(
    r"^(?:\.agent/|CLAUDE\.md$|AUDIT_REPORT\.md$|TRIBOS_COMPLETE_AUDIT_AND_REPAIR_CHANGELOG\.md$|"
    r"Tribos_Codebase_Audit_and_Repair_Prompt.*\.md$|math_agent_research_recommendations\.md$|"
    r"docs/history/|docs/plans/|docs/benchmarks/|"
    r"docs/(?:AGENTIC_ENGINEERING_HARNESS_GAP_ANALYSIS|AUDIT_REPAIR_REPORT|AUDIT_ROUND3_REPORT|CHANGES_SUMMARY|"
    r"PERFECT_AGENTIC_HARNESS_AND_MEMORY_ARCHITECTURE|SCIENTIFIC_EXECUTION_REPAIR|TRIBOS_REMEDIATION)\.md$)"
)
# Files the public repository keeps in its own version (navigation without the internal documents).
PUBLIC_OWNED = frozenset({"docs/index.md", "mkdocs.yml", "docs/agentic/README.md"})
# Changelog entries about internal records, dropped from the public changelog.
INTERNAL_ENTRY = re.compile(r"benchmark failure analysis|pilot report|GPQA record|audit report|repair prompt", re.I)
PRIVATE_LINK = re.compile(r"\s*\(\[`[0-9a-f]{7}`\]\(https://github\.com/AtlasRoX/Tribos-Alpha/commit/[0-9a-f]+\)\)")
PRIVATE_BLOCK = re.compile(r"\n?
\n?", re.S)
SECRET = re.compile(
    r"(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}|sk-[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9_\-]{10,}|"
    r"ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY", re.I)
TEXT_SUFFIXES = {".md", ".py", ".toml", ".yml", ".yaml", ".json", ".html", ".css", ".js", ".mjs", ".ts", ".tsx",
                 ".txt", ".cfg", ".ini", ".example", ".lock", ""}


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.strip()[:500]}")
    return out.stdout


def show(rev: str, path: str) -> bytes:
    out = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True)
    if out.returncode != 0:
        raise SystemExit(f"cannot read {rev}:{path}")
    return out.stdout


def public_changelog(text: str) -> str:
    # Entries and headings are blocks separated by blank lines; an entry is a block starting with "- ".
    blocks = text.split("\n\n")
    kept = [b for b in blocks if not (b.lstrip().startswith("- ") and INTERNAL_ENTRY.search(b.lstrip().split("\n", 1)[0]))]
    text = PRIVATE_LINK.sub("", "\n\n".join(kept))
    return re.sub(r"### [A-Za-z ]+\n\n(?=###|## |\Z)", "", text)  # sections left empty


def public_agents(text: str) -> str:
    return re.sub(r" The current audit and its remediation log are in \[AUDIT_REPORT\.md\][^\n]*", "", text)


def transform(path: str, data: bytes) -> bytes:
    if Path(path).suffix not in TEXT_SUFFIXES:
        return data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    text = PRIVATE_BLOCK.sub("\n", text)
    if path == "CHANGELOG.md":
        text = public_changelog(text)
    if path == "AGENTS.md":
        text = public_agents(text)
    return text.encode("utf-8")


def build(worktree: Path, source: str) -> list[str]:
    """Write the public tree into the worktree; the paths that changed."""
    main_files = [p for p in git("ls-tree", "-r", "--name-only", source).splitlines() if not EXCLUDE.match(p)]
    public_files = set(git("ls-files", cwd=worktree).splitlines())
    for path in main_files:
        if path in PUBLIC_OWNED and path in public_files:
            continue
        target = worktree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(transform(path, show(source, path)))
    gone = sorted(public_files - set(main_files) - PUBLIC_OWNED)
    for path in gone:
        (worktree / path).unlink(missing_ok=True)
    git("add", "-A", cwd=worktree)
    return git("diff", "--cached", "--name-only", cwd=worktree).splitlines()


def check(worktree: Path) -> list[str]:
    """Problems that must stop the sync."""
    problems = []
    files = git("ls-files", cwd=worktree).splitlines()
    problems += [f"excluded path present: {p}" for p in files if EXCLUDE.match(p)]
    for path in files:
        if Path(path).suffix not in TEXT_SUFFIXES or path.endswith(".lock"):
            continue
        try:
            text = (worktree / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "
" in text:
            problems.append(f"private block left in {path}")
    changelog = (worktree / "CHANGELOG.md").read_text(encoding="utf-8") if (worktree / "CHANGELOG.md").exists() else ""
    if "Tribos-Alpha/commit" in changelog:
        problems.append("CHANGELOG.md links to private commits")
    added = git("diff", "--cached", "-U0", cwd=worktree)
    for line in added.splitlines():
        if line.startswith("+") and not line.startswith("+++") and SECRET.search(line):
            problems.append(f"secret-looking string added: {line[:80]}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--remote", default="tribosai")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--source", default="main", help="the private branch or commit to publish")
    ap.add_argument("--worktree", default=str(ROOT.parent / "tribos-public-sync"))
    ap.add_argument("--commit", metavar="MESSAGE", help="commit the public tree with this message")
    ap.add_argument("--push", action="store_true", help="push the commit to REMOTE/BRANCH (fast-forward only)")
    ap.add_argument("--tag", help="also push this tag at the new public commit")
    args = ap.parse_args()

    git("fetch", args.remote, args.branch)
    worktree = Path(args.worktree)
    if worktree.exists():
        raise SystemExit(f"{worktree} exists: remove it (git worktree remove) or pass --worktree")
    git("worktree", "add", "--detach", str(worktree), f"{args.remote}/{args.branch}")
    changed = build(worktree, args.source)
    problems = check(worktree)
    print(f"public tree in {worktree}: {len(changed)} file(s) changed")
    for path in changed[:60]:
        print(f"  {path}")
    if problems:
        print("STOPPED, nothing committed:", *problems, sep="\n  ")
        return 1
    if not changed:
        print("nothing to publish")
        return 0
    if args.commit:
        git("commit", "-q", "-m", args.commit, cwd=worktree)
        print("committed", git("rev-parse", "--short", "HEAD", cwd=worktree).strip())
        if args.push:
            git("push", args.remote, f"HEAD:refs/heads/{args.branch}", cwd=worktree)
            print(f"pushed to {args.remote}/{args.branch}")
            if args.tag:
                git("push", args.remote, f"HEAD:refs/tags/{args.tag}", cwd=worktree)
                print(f"tagged {args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
