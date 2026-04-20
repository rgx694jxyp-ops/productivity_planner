from datetime import date

import pytest

import database
import followup_manager


class _LocalNow:
    def __init__(self, d: date):
        self._d = d

    def date(self) -> date:
        return self._d


def test_get_followups_for_range_defaults_use_tenant_local_today(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "services.settings_service.get_tenant_local_now",
        lambda tenant_id: _LocalNow(date(2026, 4, 19)),
    )

    def _fake_get_followups_db(from_date, to_date, tenant_id=""):
        captured["from_date"] = from_date
        captured["to_date"] = to_date
        captured["tenant_id"] = tenant_id
        return []

    monkeypatch.setattr("database.get_followups_db", _fake_get_followups_db)

    followup_manager.get_followups_for_range(tenant_id="tenant-a")

    assert captured["tenant_id"] == "tenant-a"
    assert captured["from_date"] == "2026-04-19"
    assert captured["to_date"] == "2026-05-19"


def test_get_followups_due_today_uses_tenant_local_date(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "services.settings_service.get_tenant_local_now",
        lambda tenant_id: _LocalNow(date(2026, 4, 21)),
    )

    def _fake_get_followups_db(from_date, to_date, tenant_id=""):
        captured["from_date"] = from_date
        captured["to_date"] = to_date
        return []

    monkeypatch.setattr("database.get_followups_db", _fake_get_followups_db)

    followup_manager.get_followups_due_today(tenant_id="tenant-a")

    assert captured["from_date"] == "2026-04-21"
    assert captured["to_date"] == "2026-04-21"


def test_get_followups_for_range_raises_when_tenant_local_date_unavailable(monkeypatch):
    monkeypatch.setattr(
        "services.settings_service.get_tenant_local_now",
        lambda _tenant_id: (_ for _ in ()).throw(RuntimeError("tenant clock unavailable")),
    )

    with pytest.raises(RuntimeError):
        followup_manager.get_followups_for_range(tenant_id="tenant-a")


def test_get_followups_db_returns_early_for_malformed_tenant_id(monkeypatch):
    log_calls = []

    def _unexpected_get_client():
        raise AssertionError("get_client should not be called for malformed tenant ids")

    monkeypatch.setattr(database, "get_client", _unexpected_get_client)
    monkeypatch.setattr(database, "log_warn", lambda event, message, **kwargs: log_calls.append((event, message, kwargs)))

    out = database.get_followups_db(from_date="2026-04-19", to_date="2026-04-20", tenant_id="tenant-a")

    assert out == []
    assert len(log_calls) == 1
    event, message, kwargs = log_calls[0]
    assert event == "followups_invalid_tenant_id"
    assert "not a valid UUID" in message
    assert kwargs["tenant_id"] == "tenant-a"
    assert kwargs["context"]["source"] == "database.get_followups_db"
