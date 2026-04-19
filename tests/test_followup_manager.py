from datetime import date

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
