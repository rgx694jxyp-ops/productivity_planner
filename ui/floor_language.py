"""UI-facing language translations and confidence messaging."""

from services.plain_language_service import describe_attention_level


def translate_to_floor_language(technical_term: str, context: dict | None = None) -> str:
    """Convert technical jargon to supervisor-friendly language."""
    translations = {
        "trend declining": "Performance dropping - 3 days in a row",
        "variance high": "Output is inconsistent day to day",
        "risk score: 7": "Needs attention soon",
        "goal_status": "Performance vs target",
        "below_goal": "Below their target",
        "on_goal": "Meeting their target",
        "streak": "Days in a row below target",
        "change_pct": "Performance change",
        "rolling average": "Average over last week",
    }
    return translations.get(technical_term.lower(), technical_term)


def risk_to_human_language(risk_level: str, context: dict | None = None) -> str:
    """Convert risk color codes to actionable language."""
    return describe_attention_level(str(risk_level))


def human_confidence_message(
    data_age_minutes: int | None,
    days_of_data: int,
    has_trend: bool = False,
) -> str:
    """Convert technical uncertainty into human-friendly guidance."""
    if data_age_minutes is None or days_of_data == 0:
        return "Limited data - still enough to guide decisions. Upload more data for stronger patterns."

    if data_age_minutes <= 5 and days_of_data >= 7 and has_trend:
        return f"✓ Fresh data with good history - safe to act immediately. (Updated {data_age_minutes}m ago)"

    if data_age_minutes <= 60 and days_of_data >= 7:
        return f"✓ Solid data - good basis for decisions. (Updated {data_age_minutes}m ago)"

    if data_age_minutes <= 240 and days_of_data >= 3:
        return f"⚠ Reasonable data - validate before major decisions. (Updated {data_age_minutes}m ago)"

    if days_of_data < 3:
        return "Limited history - use as a starting point. Add more days for trend patterns."

    if data_age_minutes > 1440:
        return "Data is getting stale. Refresh to see latest patterns."

    return "Data looks good - trends are reliable."
