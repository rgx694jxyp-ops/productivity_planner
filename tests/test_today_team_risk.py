from pages.today import _render_today_team_risk_block
from services.today_view_model_service import TodayQueueCardViewModel, TodayTeamRiskViewModel, build_today_team_risk_view_model


def _card(
    employee_id: str,
    line_2: str,
    line_3: str = "",
    *,
    normalized_action_state_detail: str = "",
) -> TodayQueueCardViewModel:
    return TodayQueueCardViewModel(
        employee_id=employee_id,
        process_id="Receiving",
        state="CURRENT",
        line_1=f"{employee_id} · Receiving",
        line_2=line_2,
        line_3=line_3,
        line_4="Latest snapshot only",
        line_5="Confidence: Medium",
        expanded_lines=[],
        signal_key=f"signal:{employee_id}",
        normalized_action_state_detail=normalized_action_state_detail,
    )


def test_team_risk_includes_department_below_target_bullet():
    vm = build_today_team_risk_view_model(
        goal_status=[
            {"Department": "Receiving", "Average UPH": 41, "Target UPH": 50, "trend": "stable"},
            {"Department": "Receiving", "Average UPH": 44, "Target UPH": 50, "trend": "stable"},
            {"Department": "Packing", "Average UPH": 57, "Target UPH": 55, "trend": "stable"},
        ],
        cards=[],
    )

    assert vm is not None
    assert "Receiving is running below target today" in list(vm.bullets or [])


def test_team_risk_includes_declining_employee_count_bullet():
    vm = build_today_team_risk_view_model(
        goal_status=[
            {"Department": "Packing", "Average UPH": 51, "Target UPH": 55, "trend": "declining"},
            {"Department": "Packing", "Average UPH": 49, "Target UPH": 55, "trend": "declining"},
            {"Department": "Packing", "Average UPH": 46, "Target UPH": 55, "trend": "declining"},
        ],
        cards=[],
    )

    assert vm is not None
    assert "3 Packing employees are declining" in list(vm.bullets or [])


def test_team_risk_includes_overdue_follow_up_bullet():
    vm = build_today_team_risk_view_model(
        goal_status=[],
        cards=[
            _card("E1", "Follow-up not completed", normalized_action_state_detail="Overdue"),
            _card("E2", "Follow-up not completed", normalized_action_state_detail="Overdue"),
        ],
    )

    assert vm is not None
    assert "2 overdue follow-ups" in list(vm.bullets or [])


def test_team_risk_has_no_system_or_debug_language_and_caps_at_three_bullets():
    vm = build_today_team_risk_view_model(
        goal_status=[
            {"Department": "Receiving", "Average UPH": 41, "Target UPH": 50, "trend": "declining"},
            {"Department": "Packing", "Average UPH": 49, "Target UPH": 55, "trend": "declining"},
            {"Department": "Packing", "Average UPH": 46, "Target UPH": 55, "trend": "declining"},
            {"Department": "Packing", "Average UPH": 45, "Target UPH": 55, "trend": "declining"},
        ],
        cards=[
            _card("E1", "Follow-up not completed", normalized_action_state_detail="Overdue"),
            _card("E2", "Follow-up not completed", normalized_action_state_detail="Overdue"),
        ],
    )

    assert vm is not None
    payload = "\n".join(vm.bullets).lower()
    assert "system" not in payload
    assert "debug" not in payload
    assert len(list(vm.bullets or [])) <= 3


def test_render_team_snapshot_uses_new_label_and_hides_when_empty(monkeypatch):
    rendered: list[str] = []

    class _Expander:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "pages.today.st.expander",
        lambda label, expanded=False: rendered.append(f"expander:{label}:{expanded}") or _Expander(),
    )
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **_kwargs: rendered.append(str(text)))

    _render_today_team_risk_block(TodayTeamRiskViewModel(bullets=["Receiving is running below target today"]))

    assert "expander:Team snapshot:False" in rendered
    assert "- Receiving is running below target today" in rendered

    rendered.clear()
    _render_today_team_risk_block(None)
    assert rendered == []
