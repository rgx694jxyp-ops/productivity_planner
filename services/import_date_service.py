"""Canonical date parsing and normalization for import flows."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from typing import Any


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%m/%d/%y",
    "%d/%m/%y",
)


def _candidate_date_texts(raw_text: str) -> list[str]:
    text = str(raw_text or "").strip()
    candidates = [text]
    if "T" in text:
        candidates.append(text.split("T", 1)[0].strip())
    if " " in text:
        candidates.append(text.split(" ", 1)[0].strip())
    if len(text) >= 10:
        candidates.append(text[:10].strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


@lru_cache(maxsize=4096)
def _parse_work_date_text(raw_text: str) -> str | None:
    text = str(raw_text or "").strip()
    if not text:
        return None

    try:
        normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
        return datetime.fromisoformat(normalized).date().isoformat()
    except Exception:
        pass

    for candidate in _candidate_date_texts(text):
        try:
            return date.fromisoformat(candidate).isoformat()
        except Exception:
            pass

        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def parse_work_date(value: Any) -> str | None:
    """Return canonical YYYY-MM-DD for supported inputs, else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _parse_work_date_text(str(value))
