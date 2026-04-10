"""Domain constants and helpers for lightweight operational exceptions."""

from __future__ import annotations


class ExceptionCategory:
    ATTENDANCE = "attendance"
    TRAINING = "training"
    SYSTEM = "system"
    EQUIPMENT = "equipment"
    PROCESS = "process"
    INVENTORY_REPLENISHMENT = "inventory/replenishment"
    CONGESTION = "congestion"
    UNKNOWN = "unknown"


EXCEPTION_CATEGORIES: list[str] = [
    ExceptionCategory.ATTENDANCE,
    ExceptionCategory.TRAINING,
    ExceptionCategory.SYSTEM,
    ExceptionCategory.EQUIPMENT,
    ExceptionCategory.PROCESS,
    ExceptionCategory.INVENTORY_REPLENISHMENT,
    ExceptionCategory.CONGESTION,
    ExceptionCategory.UNKNOWN,
]

EXCEPTION_STATUSES: list[str] = ["open", "resolved"]


def normalize_exception_category(value: str, *, default: str = ExceptionCategory.UNKNOWN) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in EXCEPTION_CATEGORIES else default


def normalize_exception_status(value: str, *, default: str = "open") -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in EXCEPTION_STATUSES else default
