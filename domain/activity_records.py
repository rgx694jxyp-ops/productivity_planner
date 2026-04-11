"""Domain constants for normalized activity records."""

from __future__ import annotations


ACTIVITY_DATA_QUALITY_STATUSES: list[str] = [
    "valid",
    "partial",
    "low_confidence",
    "invalid",
    "excluded",
]

ACTIVITY_HANDLING_CHOICES: list[str] = [
    "",
    "review_details",
    "ignore_rows",
    "include_low_confidence",
    "map_or_correct",
]


def normalize_data_quality_status(value: str, *, default: str = "partial") -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in ACTIVITY_DATA_QUALITY_STATUSES else default


def normalize_handling_choice(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in ACTIVITY_HANDLING_CHOICES else ""
