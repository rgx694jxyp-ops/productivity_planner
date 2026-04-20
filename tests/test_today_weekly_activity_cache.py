from pages import today


def test_weekly_activity_page_cache_hits_on_repeated_lookup(monkeypatch):
    monkeypatch.setattr(today.st, "session_state", {})

    calls = {"count": 0}

    def _fake_weekly_lookup(*, tenant_id: str, lookback_days: int, today_iso: str):
        calls["count"] += 1
        return {"reviewed_issues": 2}

    monkeypatch.setattr(today, "_cached_weekly_manager_activity_summary", _fake_weekly_lookup)

    first, first_hit = today._cached_weekly_manager_activity_summary_page(
        tenant_id="tenant-a",
        lookback_days=7,
        today_iso="2026-04-19",
    )
    second, second_hit = today._cached_weekly_manager_activity_summary_page(
        tenant_id="tenant-a",
        lookback_days=7,
        today_iso="2026-04-19",
    )

    assert first_hit is False
    assert second_hit is True
    assert calls["count"] == 1
    assert first == second
