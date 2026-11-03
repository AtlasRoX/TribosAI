"""
Skills: short procedures added to the drafting prompt when a question matches (docs/plans/tribos-harness-landscape.md
item 11; the Agent Skills format K-Dense's scientific skills use).

A skill is a SKILL.md file: a front matter with `name`, `description` and `triggers` (one regular expression per line,
case-insensitive), then the procedure in Markdown. The built-in skills live in tribos/skills/builtin; TRIBOS_SKILLS_DIR
adds a folder of the operator's own (a skill there with the same name replaces the built-in one). At most MAX_SKILLS
match one question, the ones with the most trigger hits first.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

MAX_SKILLS = 2
BUILTIN_DIR = Path(__file__).parent / "builtin"
_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    triggers: tuple[re.Pattern[str], ...]
    body: str

    def hits(self, question: str) -> int:
        return sum(1 for t in self.triggers if t.search(question))


def parse_skill(text: str) -> Skill | None:
    m = _FRONT_RE.match(text.replace("\r\n", "\n"))
    if not m:
        return None
    meta: dict[str, list[str]] = {}
    key = ""
    for line in m.group(1).splitlines():
        if re.match(r"^\w+:", line):
            key, _, value = line.partition(":")
            key = key.strip()
            meta[key] = [value.strip()] if value.strip() else []
        elif key and line.strip().startswith("- "):
            meta[key].append(line.strip()[2:].strip())
    name = (meta.get("name") or [""])[0]
    if not name:
        return None
    triggers = []
    for raw in meta.get("triggers") or []:
        try:
            triggers.append(re.compile(raw.strip("'\""), re.I))
        except re.error:
            continue
    return Skill(name, (meta.get("description") or [""])[0], tuple(triggers), m.group(2).strip())


def _dirs() -> list[Path]:
    from ..config.settings import get_str

    extra = str(get_str("TRIBOS_SKILLS_DIR") or "").strip()
    return [BUILTIN_DIR] + ([Path(extra)] if extra else [])


@functools.lru_cache(maxsize=4)
def _load(dirs: tuple[str, ...]) -> tuple[Skill, ...]:
    found: dict[str, Skill] = {}
    for d in dirs:
        for path in sorted(Path(d).glob("**/SKILL.md")) + sorted(Path(d).glob("*.md")):
            if path.name != "SKILL.md" and path.parent != Path(d):
                continue
            try:
                skill = parse_skill(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            if skill is not None:
                found[skill.name] = skill
    return tuple(found.values())


def load_skills() -> tuple[Skill, ...]:
    return _load(tuple(str(d) for d in _dirs()))


def select_skills(question: str, limit: int = MAX_SKILLS) -> list[Skill]:
    scored = [(s.hits(question or ""), s) for s in load_skills()]
    return [s for n, s in sorted(scored, key=lambda x: -x[0]) if n > 0][:limit]


def skills_prompt(question: str) -> str:
    """The procedures of the matching skills, for the end of the drafting system prompt ("" when none match)."""
    chosen = select_skills(question)
    if not chosen:
        return ""
    parts = [f"### Skill: {s.name}\n{s.body}" for s in chosen]
    return "\n\nProcedures for this kind of question (follow them where they apply):\n\n" + "\n\n".join(parts)


__all__ = ["Skill", "load_skills", "parse_skill", "select_skills", "skills_prompt"]
