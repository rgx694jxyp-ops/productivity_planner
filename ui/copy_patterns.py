"""Reusable UI microcopy patterns for calm, observational, non-prescriptive text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ConfidenceLevel = Literal["high", "medium", "low"]


JARGON_REPLACEMENTS: dict[str, str] = {
    "pipeline": "import process",
    "anomaly": "data quality concern",
    "variance": "day-to-day spread",
    "rolling average": "recent average",
    "delta": "change",
    "risk score": "attention level",
    "intervention": "follow-up activity",
    "escalation path": "follow-up path",
}


@dataclass(frozen=True)
class ScreenCopy:
    heading: str
    description: str


SCREEN_DEFAULTS: dict[str, ScreenCopy] = {
    "today": ScreenCopy(
        heading="Needs Attention Today",
        description="Open follow-ups and due items for this shift, sorted by urgency.",
    ),
    "employee_detail": ScreenCopy(
        heading="Employee Detail",
        description="Performance and follow-up history for this person, with supporting evidence.",
    ),
    "team_process": ScreenCopy(
        heading="Team And Process Signals",
        description="Team-level patterns for this period, compared with normal range.",
    ),
    "import_data_trust": ScreenCopy(
        heading="Import And Data Trust",
        description="Import status, data quality, and confidence context for current signals.",
    ),
}


def normalize_jargon(text: str) -> str:
    """Replace known jargon terms with plain-language alternatives."""
    out = text
    for source, replacement in JARGON_REPLACEMENTS.items():
        out = out.replace(source, replacement)
        out = out.replace(source.title(), replacement.title())
        out = out.replace(source.upper(), replacement.upper())
    return out


def confidence_text(level: ConfidenceLevel, basis: str, caveat: str = "") -> str:
    """Build confidence copy with explicit evidence basis."""
    level_label = level.capitalize()
    message = f"Confidence: {level_label} ({basis})"
    if caveat.strip():
        message = f"{message}. {caveat.strip()}"
    return message


def empty_state_text(reason: str, condition: str) -> str:
    """Generate a contextual empty-state message."""
    return f"Nothing is currently shown here because {reason}. More results appear when {condition}."


def warning_state_text(issue: str, impact: str) -> str:
    """Generate calm warning copy with scope and effect."""
    return f"Some data may be incomplete: {issue}. This may affect {impact}."


def section_description(what: str, scope: str, time_window: str, baseline: str) -> str:
    """Generate a standard section description line."""
    return f"This view shows {what} for {scope} over {time_window}, compared with {baseline}."


def signal_summary(signal_statement: str, baseline: str, trigger: str) -> str:
    """Generate one-line summary microcopy for insight cards."""
    return f"{signal_statement}. Compared with {baseline}. Flagged because {trigger}."


def button_label(action: Literal["view", "open", "show", "log", "compare", "check"], object_text: str) -> str:
    """Generate short, destination-oriented button labels."""
    verb_map = {
        "view": "View",
        "open": "Open",
        "show": "Show",
        "log": "Log",
        "compare": "Compare",
        "check": "Check",
    }
    verb = verb_map[action]
    obj = " ".join(str(object_text or "").split())
    return f"{verb} {obj}".strip()
