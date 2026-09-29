"""Arabic message catalog access (reports/templates/messages.ar.json)."""

from __future__ import annotations

import json
import string
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "reports" / "templates" / "messages.ar.json"


class MissingMessage(KeyError):
    pass


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def raw(path: str) -> Any:
    node: Any = catalog()
    parts = path.split(".")
    i = 0
    while i < len(parts):
        if not isinstance(node, dict):
            raise MissingMessage(path)
        rest = ".".join(parts[i:])
        if rest in node:  # keys may themselves contain dots (action ids: "ga4.connect")
            return node[rest]
        if parts[i] not in node:
            raise MissingMessage(path)
        node = node[parts[i]]
        i += 1
    return node


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def t(path: str, **params: Any) -> str:
    """Render a template. Missing placeholders raise (no half-rendered text)."""
    tmpl = raw(path)
    if not isinstance(tmpl, str):
        raise MissingMessage(path)
    missing = placeholders(tmpl) - params.keys()
    if missing:
        raise KeyError(f"{path}: missing params {sorted(missing)}")
    return tmpl.format(**params)


def has(path: str) -> bool:
    try:
        return isinstance(raw(path), str)
    except MissingMessage:
        return False
