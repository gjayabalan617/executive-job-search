"""seen_jobs.json compatibility file and process locks.

- Missing file is initialised as [].
- Malformed JSON (or a non-list top level) raises SeenFileError and the file is never overwritten.
- Existing entries are preserved verbatim (strings, dicts, or anything else); only new URLs are appended.
- Writes are atomic (temp file + fsync + os.replace) under an exclusive flock.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .urls import canonical_any


class SeenFileError(Exception):
    pass


class RunInProgress(Exception):
    pass


class FileLock:
    """Exclusive advisory lock. blocking=False raises RunInProgress when already held."""

    def __init__(self, path: Path, blocking: bool = True):
        self.path = Path(path)
        self.blocking = blocking
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            self._fh.close()
            self._fh = None
            raise RunInProgress(f"another run holds {self.path}")
        return self

    def __exit__(self, *exc):
        if self._fh:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


def _entry_url(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("url") or entry.get("canonical_url")
    return None


def _norm(url: str) -> str:
    try:
        return canonical_any(url)
    except Exception:  # unparseable legacy entries still compare verbatim
        return url


class SeenFile:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    def _read_unlocked(self) -> list:
        if not self.path.exists():
            self._atomic_write([])
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8") or "null")
        except json.JSONDecodeError as exc:
            raise SeenFileError(f"{self.path} is not valid JSON ({exc}); refusing to modify it") from exc
        if not isinstance(data, list):
            raise SeenFileError(f"{self.path} must contain a JSON list; refusing to modify it")
        return data

    def _atomic_write(self, entries: list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".seen_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def load(self) -> list:
        with FileLock(self._lock_path):
            return self._read_unlocked()

    def urls(self) -> set[str]:
        return {_norm(u) for u in (_entry_url(e) for e in self.load()) if u}

    def append(self, urls: Iterable[str]) -> int:
        with FileLock(self._lock_path):
            entries = self._read_unlocked()
            existing = {_norm(u) for u in (_entry_url(e) for e in entries) if u}
            new: list[str] = []
            for u in urls:
                if u not in existing:
                    existing.add(u)
                    new.append(u)
            if new:
                self._atomic_write(entries + new)
            return len(new)
