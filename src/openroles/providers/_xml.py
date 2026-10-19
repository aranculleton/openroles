"""XML from a job board, parsed only when it cannot carry a nasty surprise.

A feed has no business declaring a DTD or entities, and entity expansion is how an
XML document turns a few kilobytes into gigabytes. One that declares either is refused
before it is parsed.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

from ..models import clean


def parse(text: str) -> Optional[ET.Element]:
    """The document's root, or None when it is not XML or declares a DTD or entities."""
    head = (text or "")[:4096].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in (text or "").upper():
        return None
    try:
        return ET.fromstring((text or "").encode("utf-8"))
    except ET.ParseError:
        return None


def text_of(el: Optional[ET.Element], path: str = "") -> str:
    """The text at `path` under `el` (the element itself when no path), whitespace collapsed."""
    if el is None:
        return ""
    found = el.find(path) if path else el
    return clean(found.text) if found is not None and found.text else ""
