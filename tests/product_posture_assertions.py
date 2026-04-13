"""Shared test-only assertions for product-posture contract enforcement."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


FORBIDDEN_PHRASES = [
    "should",
    "take action",
    "investigate now",
    "coach this employee",
    "start with",
    "fix first",
    "needs attention",
    "intervene",
    "recommended action",
]


def _flatten_text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        out: list[str] = []
        for v in value.values():
            out.extend(_flatten_text_values(v))
        return out
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_text_values(item))
        return out
    return [str(value)]


def assert_no_prescriptive_language(text: Any) -> None:
    blob = "\n".join(_flatten_text_values(text)).lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in blob


def assert_no_prescriptive_language_in_mapping(mapping: Mapping[str, Any], keys: list[str] | None = None) -> None:
    if keys is None:
        target = dict(mapping)
    else:
        target = {key: mapping.get(key) for key in keys}
    assert_no_prescriptive_language(target)


def assert_contains_required_patterns(text: str, required_patterns: list[str]) -> None:
    lowered = str(text or "").lower()
    for pattern in required_patterns:
        assert str(pattern).lower() in lowered


def assert_mapping_values_contain_required_patterns(mapping: Mapping[str, Any], required_by_key: Mapping[str, list[str]]) -> None:
    for key, patterns in required_by_key.items():
        assert_contains_required_patterns(str(mapping.get(key, "") or ""), list(patterns or []))
