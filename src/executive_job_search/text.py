"""Text helpers: HTML to plain text, sentence splitting, excerpts, hashing."""
from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from typing import Optional

_BLOCK = {"p", "div", "br", "ul", "ol", "tr", "section", "h1", "h2", "h3", "h4", "h5", "h6"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "li":
            self.parts.append("\n• ")
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK or tag == "li":
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: Optional[str]) -> str:
    """Convert (possibly entity-escaped, as Greenhouse returns it) HTML to plain text."""
    if not raw:
        return ""
    s = raw
    if "&lt;" in s and "<" not in s:
        s = html.unescape(s)
    parser = _Extractor()
    parser.feed(s)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for chunk in re.split(r"\n+", text):
        chunk = chunk.strip(" •-\t")
        if not chunk:
            continue
        out.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", chunk) if s.strip())
    return out


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def excerpt(sentence: str, limit: int = 240) -> str:
    sentence = re.sub(r"\s+", " ", sentence).strip()
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"
