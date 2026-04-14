from pathlib import Path


def test_today_page_routes_follow_through_write_via_action_state_service():
    source = Path("pages/today.py").read_text(encoding="utf-8")

    assert "from services.action_state_service import build_employee_action_state_lookup, log_follow_through_event" in source


def test_legacy_today_queue_routes_touchpoint_and_recognition_via_action_state_service():
    source = Path("ui/today_queue.py").read_text(encoding="utf-8")

    assert "from services.action_state_service import log_action_event, log_recognition_event, save_action_touchpoint" in source


def test_signal_status_service_remains_outside_action_state_adapter():
    source = Path("services/today_signal_status_service.py").read_text(encoding="utf-8")

    assert "services.action_state_service" not in source
    assert "action_events_repo.log_action_event" in source


def test_exception_tracking_service_remains_outside_action_state_adapter():
    source = Path("services/exception_tracking_service.py").read_text(encoding="utf-8")

    assert "services.action_state_service" not in source
