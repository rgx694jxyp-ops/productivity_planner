from datetime import date

from services.attention_scoring_service import AttentionSummary
from services.today_page_meaning_service import build_today_queue_render_plan, build_today_surface_meaning


def test_surface_meaning_builds_stale_status_banner_and_freshness():
    meaning = build_today_surface_meaning(
        goal_status=[{"EmployeeID": "E1", "goal_status": "on_goal", "trend": "steady"}],
        import_summary={"days": 3, "trust": {"status": "valid", "confidence_score": 88}},
        home_sections={},
        has_queue_items=True,
        as_of_date="2026-04-09",
        today_value=date(2026, 4, 12),
    )

    assert meaning.state_flags["stale_data"] is True
    assert "Latest data is 3 days old" in meaning.status_line
    assert "3 days" in meaning.stale_banner
    assert "3 days old" in meaning.freshness_note


def test_surface_meaning_weak_data_mode_for_partial_trust():
    meaning = build_today_surface_meaning(
        goal_status=[{"EmployeeID": "E1", "goal_status": "below_goal", "trend": "insufficient_data"}],
        import_summary={"days": 2, "trust": {"status": "partial", "confidence_score": 62}},
        home_sections={},
        has_queue_items=True,
        as_of_date="2026-04-12",
        today_value=date(2026, 4, 12),
    )

    assert meaning.weak_data_mode is True
    assert meaning.state_flags["partial_data"] is True
    assert meaning.status_line == "Early-signal mode: limited history, directional evidence only."


def test_queue_render_plan_promotes_secondary_when_weak_data(monkeypatch):
    class _Card:
        def __init__(self, employee_id: str):
            self.employee_id = employee_id
            self.process_id = "Receiving"
            self.state = "EARLY_TREND"
            self.line_1 = "E1 · Receiving"
            self.line_2 = "Not enough history yet"
            self.line_3 = ""
            self.line_4 = ""
            self.line_5 = "Low confidence"
            self.expanded_lines = []
            self.freshness_line = ""
            self.collapsed_hint = ""
            self.collapsed_evidence = ""
            self.collapsed_issue = ""

    class _QueueVm:
        main_section_title = "What needs attention today"
        primary_cards = []
        secondary_cards = [_Card("E1")]
        suppressed = []

    monkeypatch.setattr("services.today_page_meaning_service.build_today_queue_view_model", lambda **kwargs: _QueueVm())

    plan = build_today_queue_render_plan(
        attention=AttentionSummary(ranked_items=[], is_healthy=True, healthy_message="", suppressed_count=0, total_evaluated=0),
        suppressed_cards=[],
        today_value=date(2026, 4, 12),
        is_stale=False,
        weak_data_mode=True,
        show_secondary_open=True,
    )

    assert len(plan.primary_cards) == 1
    assert len(plan.secondary_cards) == 0
    assert plan.weak_data_note == "Early signals are shown below. Confidence is limited until more history is available."
    assert plan.primary_placeholder == ""
