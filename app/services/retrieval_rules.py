"""Load and evaluate data-driven retrieval rules from config/retrieval_rules.json.

This replaces the previous ~85 hard-coded per-question blocks scattered across
retrieval.py and llm.py. Rules live in one JSON file with three tables:

- query_synonyms:      term -> synonyms appended to the query (no ground truth)
- query_expansions:    "trigger+guard|guard" -> literal KB phrases that help recall
- entity_aliases:      entity -> related surface variants (used for evidence checks)

A trigger key like "认证+级别|等级|覆盖" means: fire when 认证 is present AND any
of 级别/等级/覆盖 is present. A key without "+" fires on substring presence alone.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval_rules.json"

_TRIGGER_SPLIT_RE = re.compile(r"\+")
_GUARD_SPLIT_RE = re.compile(r"\|")


@lru_cache(maxsize=1)
def load_rules() -> dict:
    try:
        data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"query_synonyms": {}, "query_expansions": {}, "entity_aliases": {}}
    return {
        "query_synonyms": {k: tuple(v) for k, v in data.get("query_synonyms", {}).items()},
        "query_expansions": {k: tuple(v) for k, v in data.get("query_expansions", {}).items()},
        "entity_aliases": {k: tuple(v) for k, v in data.get("entity_aliases", {}).items()},
    }


def clear_rules_cache() -> None:
    load_rules.cache_clear()


def _rule_matches(key: str, normalized: str) -> bool:
    """A rule key is "trigger[|alternative...][+guard|guard...]".

    Fires when any trigger phrase is present and (if guards exist) at least
    one guard phrase is also present.
    """
    parts = _TRIGGER_SPLIT_RE.split(key)
    triggers = _GUARD_SPLIT_RE.split(parts[0])
    guards = _GUARD_SPLIT_RE.split(parts[1]) if len(parts) > 1 else []
    if not any(trigger in normalized for trigger in triggers):
        return False
    if guards and not any(guard in normalized for guard in guards):
        return False
    return True


def query_synonyms() -> dict[str, tuple[str, ...]]:
    return load_rules()["query_synonyms"]


def entity_aliases() -> dict[str, tuple[str, ...]]:
    return load_rules()["entity_aliases"]


def base_expansion_terms_for(question: str) -> list[str]:
    """Expansion terms from rules whose trigger has NO guards (generic rules).

    Used to detect "excluded-subject content": when a guarded rule shadows the
    generic rule for this question, the generic rule's phrases are the subject
    the question explicitly excludes.
    """
    normalized = question.strip()
    terms: list[str] = []
    for key, values in load_rules()["query_expansions"].items():
        if len(_TRIGGER_SPLIT_RE.split(key)) == 1 and _rule_matches(key, normalized):
            for value in values:
                if value and value not in terms and value not in normalized:
                    terms.append(value)
    return terms


def expansion_terms_for(question: str) -> list[str]:
    """Return the literal expansion phrases whose trigger rules match the question.

    Rule precedence: when a rule's trigger has guards (i.e. a more specific
    variant of the same base trigger fired), the more specific rule shadows any
    plain rule whose trigger is contained in the specific rule's trigger. This
    lets a table carry both a broad rule and a narrow exception without both
    firing.
    """
    normalized = question.strip()
    matched: list[tuple[str, tuple[str, ...]]] = []
    for key, values in load_rules()["query_expansions"].items():
        if _rule_matches(key, normalized):
            matched.append((key, values))

    # Shadowing: drop plain rules whose trigger is a prefix of a fired
    # guarded rule's trigger part (specific beats generic).
    specific_triggers: list[str] = []
    for key, _ in matched:
        parts = _TRIGGER_SPLIT_RE.split(key)
        if len(parts) > 1:
            specific_triggers.extend(_GUARD_SPLIT_RE.split(parts[0]))
    shadowed: set[str] = set()
    for key, _ in matched:
        parts = _TRIGGER_SPLIT_RE.split(key)
        if len(parts) == 1:
            for trigger in _GUARD_SPLIT_RE.split(parts[0]):
                for spec in specific_triggers:
                    if spec.startswith(trigger):
                        shadowed.add(key)
                        break

    terms: list[str] = []
    for key, values in matched:
        if key in shadowed:
            continue
        for value in values:
            if value and value not in terms and value not in normalized:
                terms.append(value)
    return terms
