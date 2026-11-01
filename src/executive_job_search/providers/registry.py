"""Employer board registry. Tokens are operator-supplied only; none are invented or shipped."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ..models import BoardConfig, SourceStatus

SUPPORTED = ("greenhouse", "lever")
_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")


def load_registry(path: Path) -> tuple[list[BoardConfig], list[SourceStatus]]:
    """Parse the registry. Returns (usable boards, problems). A missing file yields an empty registry."""
    p = Path(path)
    if not p.exists():
        return [], []
    try:
        doc: Any = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return [], [SourceStatus(source=str(p), status="invalid_config", detail=f"YAML error: {exc}")]
    entries = doc.get("boards") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return [], ([] if not doc else [SourceStatus(source=str(p), status="invalid_config", detail="expected top-level 'boards:' list")])
    boards: list[BoardConfig] = []
    problems: list[SourceStatus] = []
    seen: set[str] = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or "provider" not in e or "token" not in e:
            problems.append(SourceStatus(source=f"entry[{i}]", status="invalid_config", detail="needs 'provider' and 'token'"))
            continue
        provider, token = str(e["provider"]).lower(), str(e["token"])
        key = f"{provider}:{token}"
        if not e.get("enabled", True):
            continue
        if provider not in SUPPORTED:
            problems.append(SourceStatus(source=key, status="unsupported", detail=f"provider {provider!r} is not supported (supported: {', '.join(SUPPORTED)})"))
            continue
        if not _TOKEN.match(token):
            problems.append(SourceStatus(source=key, status="invalid_config", detail="token has invalid characters"))
            continue
        if key in seen:
            continue
        seen.add(key)
        boards.append(BoardConfig(provider=provider, token=token, company=e.get("company"), region=str(e.get("region", "global")).lower()))
    return boards, problems
