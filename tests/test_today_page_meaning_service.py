from datetime import date

from services.attention_scoring_service import AttentionSummary
from services.today_page_meaning_service import (
    TodaySurfaceState,
    build_today_queue_render_plan,
    build_today_surface_meaning,
)


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
    assert meaning.surface_state == TodaySurfaceState.EARLY_SIGNAL


def test_surface_meaning_classifies_no_usable_data_state():
    meaning = build_today_surface_meaning(
        goal_status=[],
        import_summary={"days": 0, "trust": {"status": "invalid", "confidence_score": 0}},
        home_sections={},
        has_queue_items=False,
        as_of_date="",
        today_value=date(2026, 4, 12),
    )

    assert meaning.surface_state == TodaySurfaceState.NO_USABLE_DATA


def test_surface_meaning_classifies_no_strong_signals_state_with_usable_data():
    meaning = build_today_surface_meaning(
        goal_status=[{"EmployeeID": "E1", "goal_status": "on_goal", "trend": "steady", "Average UPH": 55}],
        import_summary={"days": 5, "trust": {"status": "valid", "confidence_score": 88}},
        home_sections={},
        has_queue_items=False,
        as_of_date="2026-04-12",
        today_value=date(2026, 4, 12),
    )

    assert meaning.surface_state == TodaySurfaceState.NO_STRONG_SIGNALS


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
        main_section_title = "Follow-ups Today"
        primary_cards = []
        secondary_cards = [_Card("E1")]
        suppressed = []
        auto_resolved_count = 0

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
    assert plan.weak_data_note == ""
    assert plan.start_note == "Open loops that need a manager decision, check-in, or closeout."
    assert plan.primary_placeholder == ""


def test_queue_render_plan_disables_legacy_ranking_fallback_by_default(monkeypatch):
    captured: dict[str, object] = {}

    class _QueueVm:
        main_section_title = "Follow-ups Today"
        primary_cards = []
        secondary_cards = []
        suppressed = []
        auto_resolved_count = 0

    def _fake_build_today_queue_view_model(**kwargs):
        captured.update(kwargs)
        return _QueueVm()

    monkeypatch.delenv("DPD_TODAY_ENABLE_LEGACY_RANKING_FALLBACK", raising=False)
    monkeypatch.setattr("services.today_page_meaning_service.build_today_queue_view_model", _fake_build_today_queue_view_model)

    build_today_queue_render_plan(
        attention=AttentionSummary(ranked_items=[], is_healthy=True, healthy_message="", suppressed_count=0, total_evaluated=0),
        decision_items=[],
        suppressed_cards=[],
        today_value=date(2026, 4, 12),
        is_stale=False,
        weak_data_mode=False,
        show_secondary_open=False,
    )

    assert captured.get("allow_legacy_attention_fallback") is False


def test_queue_render_plan_enables_legacy_ranking_fallback_with_env_flag(monkeypatch):
    captured: dict[str, object] = {}

    class _QueueVm:
        main_section_title = "Follow-ups Today"
        primary_cards = []
        secondary_cards = []
        suppressed = []
        auto_resolved_count = 0

    def _fake_build_today_queue_view_model(**kwargs):
        captured.update(kwargs)
        return _QueueVm()

    monkeypatch.setenv("DPD_TODAY_ENABLE_LEGACY_RANKING_FALLBACK", "1")
    monkeypatch.setattr("services.today_page_meaning_service.build_today_queue_view_model", _fake_build_today_queue_view_model)

    build_today_queue_render_plan(
        attention=AttentionSummary(ranked_items=[], is_healthy=True, healthy_message="", suppressed_count=0, total_evaluated=0),
        decision_items=[],
        suppressed_cards=[],
        today_value=date(2026, 4, 12),
        is_stale=False,
        weak_data_mode=False,
        show_secondary_open=False,
    )

    assert captured.get("allow_legacy_attention_fallback") is True


def test_queue_render_plan_uses_follow_through_quiet_state_copy(monkeypatch):
    class _QueueVm:
        main_section_title = "Follow-ups Today"
        primary_cards = []
        secondary_cards = []
        suppressed = []
        auto_resolved_count = 0

    monkeypatch.setattr("services.today_page_meaning_service.build_today_queue_view_model", lambda **kwargs: _QueueVm())

    plan = build_today_queue_render_plan(
        attention=AttentionSummary(ranked_items=[], is_healthy=True, healthy_message="", suppressed_count=0, total_evaluated=0),
        decision_items=[],
        suppressed_cards=[],
        today_value=date(2026, 4, 12),
        is_stale=False,
        weak_data_mode=False,
        show_secondary_open=False,
    )

    assert plan.section_title == "Follow-ups Today"
    assert plan.start_note == "Open loops that need a manager decision, check-in, or closeout."
    assert plan.primary_placeholder == (
        "No urgent performance issues today. Keep momentum by closing open follow-ups, "
        "recognizing recent improvement, or checking limited-data items."
    )
