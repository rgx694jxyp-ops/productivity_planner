import pytest

from services import action_lifecycle_service as svc


def test_log_action_event_raises_when_repository_returns_empty(monkeypatch):
    monkeypatch.setattr(svc.action_events_repo, "log_action_event", lambda **kwargs: {})
    monkeypatch.setattr(svc, "log_error", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError):
        svc.log_action_event(
            action_id="a-1",
            event_type="coached",
            employee_id="E1",
            tenant_id="tenant-a",
        )