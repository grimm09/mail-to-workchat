from __future__ import annotations

import re
import string


MAX_RENDERED_CHARS = 100_000


def placeholders(value: str) -> set[str]:
    """Only named substitutions; no Python format expressions or width expansion."""
    result: set[str] = set()
    for _, name, spec, conversion in string.Formatter().parse(value):
        if name is None:
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) or spec or conversion:
            raise ValueError("unsafe placeholder syntax; use simple names only")
        result.add(name)
    return result


def render(value: str, values: dict[str, str]) -> str:
    placeholders(value)
    size = 0
    for literal, name, _, _ in string.Formatter().parse(value):
        size += len(literal) + (len(values[name]) if name is not None else 0)
        if size > MAX_RENDERED_CHARS:
            raise ValueError("rendered draft exceeds the size limit")
    return value.format_map(values)
