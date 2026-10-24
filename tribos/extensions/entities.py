"""Extension module owned by ENTITIES (STEM entity resolution and normalization).

Registers evidence block decorators (`query_entities`) and prompt rules for resolved mathematical,
physical, and engineering entities (`concept`, `equation`, `quantity`, `constant`, `material`, `system`).
"""

from __future__ import annotations

from html import escape
from typing import Any

from . import hooks

PROMPT_RULE = (
    "When <query_entities> lists resolved concepts, equations, physical constants, quantities, materials, "
    "or dynamical systems, use their canonical names, symbols, and verified identifiers (such as NIST CODATA "
    "symbols, Materials Project mp-* IDs, OEIS A-numbers, or arXiv/DOI/Zbl identifiers) consistently."
)


def render_query_entities_xml(ctx: Any) -> str:
    """Render resolved STEM entities in the evidence block as `<query_entities>...</query_entities>`."""
    entities = list(getattr(ctx, "entities", None) or [])
    if not entities:
        return ""
    rows: list[str] = []
    for ent in entities:
        etype = str(getattr(ent, "type", "") or getattr(ent, "entity_type", "") or "concept")
        label = str(getattr(ent, "label", "") or getattr(ent, "canonical", "") or "")
        mention = str(getattr(ent, "mention", "") or "")
        ids: dict[str, Any] = getattr(ent, "ids", None) or {}
        attrs = [
            f'type="{escape(etype, quote=True)}"',
            f'label="{escape(label, quote=True)}"',
        ]
        if mention and mention.lower() != label.lower():
            attrs.append(f'mention="{escape(mention, quote=True)}"')
        for k, v in ids.items():
            if v:
                attrs.append(f'{escape(str(k), quote=True)}="{escape(str(v), quote=True)}"')
        desc = str(getattr(ent, "description", "") or "").strip()
        if desc:
            rows.append(f"<entity {' '.join(attrs)}>{escape(desc)}</entity>")
        else:
            rows.append(f"<entity {' '.join(attrs)}/>")
    if not rows:
        return ""
    return "<query_entities>" + "".join(rows) + "</query_entities>"


def register_hooks() -> None:
    hooks.register_evidence_decorator("query_entities", "entities", render_query_entities_xml)
    hooks.register_prompt_rule("entities", PROMPT_RULE)


register_hooks()


def register_tools(registry: Any) -> None:
    register_hooks()
    return None
