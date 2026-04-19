import pytest

from core import app_flow
from core import billing_cache
import cache as app_cache
import goals
from services import daily_snapshot_service
from services import today_home_service


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def _raise_runtime_error(*args, **kwargs):
    raise RuntimeError("simulated failure")


def test_enforce_subscription_access_blocks_when_entitlement_lookup_errors(monkeypatch):
    """Protects against fail-open access when entitlement lookup crashes."""
    session_state = _SessionState(
        {
            "tenant_id": "tenant-a",
            "user_id": "user-1",
            "user_email": "ops@example.com",
        }
    )
    shown = {"subscription_page": 0}

    monkeypatch.setattr(app_flow.st, "session_state", session_state)
    monkeypatch.setattr(app_flow.st, "secrets", {})
    monkeypatch.setattr(app_flow, "log_app_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_flow, "log_operational_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_flow, "verify_checkout_and_activate", lambda tenant_id, user_id: False)
    monkeypatch.setattr("services.billing_service.get_subscription_entitlement", _raise_runtime_error)
    monkeypatch.setattr(
        "core.dependencies.show_subscription_page",
        lambda: shown.__setitem__("subscription_page", shown["subscription_page"] + 1),
    )

    assert app_flow.enforce_subscription_access() is False
    assert shown["subscription_page"] == 1
    assert session_state.get("_sub_active") is False


def test_bust_cache_clears_today_and_snapshot_read_caches(monkeypatch):
    """Protects cross-part cache coherence after writes and explicit refresh."""
    call_counts = {"today_signals": 0, "snapshot_reads": 0}

    monkeypatch.setattr(app_cache.st, "session_state", _SessionState())

    def _fake_read_precomputed_today_signals(*, tenant_id, signal_date):
        call_counts["today_signals"] += 1
        return {
            "tenant_id": tenant_id,
            "as_of_date": signal_date.isoformat(),
            "home_sections": {},
            "attention_summary": None,
            "queue_items": [],
            "goal_status": [],
            "import_summary": {},
        }

    def _fake_list_daily_employee_snapshots(**kwargs):
        call_counts["snapshot_reads"] += 1
        return []

    monkeypatch.setattr(
        "services.daily_signals_service.read_precomputed_today_signals",
        _fake_read_precomputed_today_signals,
    )
    monkeypatch.setattr(
        daily_snapshot_service.daily_employee_snapshots_repo,
        "list_daily_employee_snapshots",
        _fake_list_daily_employee_snapshots,
    )

    today_home_service.get_today_signals.cache_clear()
    daily_snapshot_service._clear_latest_snapshot_cache()

    # Prime both caches.
    today_home_service.get_today_signals(tenant_id="tenant-a", as_of_date="2026-04-19")
    today_home_service.get_today_signals(tenant_id="tenant-a", as_of_date="2026-04-19")
    daily_snapshot_service.get_latest_snapshot_goal_status(
        tenant_id="tenant-a",
        days=30,
        rebuild_if_missing=False,
    )
    daily_snapshot_service.get_latest_snapshot_goal_status(
        tenant_id="tenant-a",
        days=30,
        rebuild_if_missing=False,
    )

    assert call_counts["today_signals"] == 1
    assert call_counts["snapshot_reads"] == 1

    # Regression guard: explicit cache bust should invalidate both read paths.
    app_cache.bust_cache()

    today_home_service.get_today_signals(tenant_id="tenant-a", as_of_date="2026-04-19")
    daily_snapshot_service.get_latest_snapshot_goal_status(
        tenant_id="tenant-a",
        days=30,
        rebuild_if_missing=False,
    )

    assert call_counts["today_signals"] == 2
    assert call_counts["snapshot_reads"] == 2


def test_clear_billing_cache_clears_live_fallback_subscription_keys(monkeypatch):
    """Protects against stale Stripe fallback cache surviving explicit billing cache clears."""
    session_state = _SessionState(
        {
            "_sub_active": True,
            "_live_subscription_fallback_tenant-a": {"plan": "pro", "_source": "stripe_fallback"},
            "_live_subscription_fallback_ts_tenant-a": 1710000000.0,
            "_live_subscription_fallback_tenant-b": {"plan": "starter", "_source": "stripe_fallback"},
            "_live_subscription_fallback_ts_tenant-b": 1710000100.0,
        }
    )
    bust_calls = {"count": 0}

    monkeypatch.setattr(billing_cache.st, "session_state", session_state)
    monkeypatch.setattr(
        billing_cache,
        "bust_cache",
        lambda: bust_calls.__setitem__("count", bust_calls["count"] + 1),
    )

    billing_cache.clear_billing_cache()

    assert "_live_subscription_fallback_tenant-a" not in session_state
    assert "_live_subscription_fallback_ts_tenant-a" not in session_state
    assert "_live_subscription_fallback_tenant-b" not in session_state
    assert "_live_subscription_fallback_ts_tenant-b" not in session_state
    assert bust_calls["count"] == 1


def test_load_goals_raises_when_storage_read_fails(monkeypatch):
    """Protects against silent empty-goals fallback masking persistent read failures."""
    monkeypatch.setattr("database.load_goals_db", _raise_runtime_error)

    with pytest.raises(RuntimeError):
        goals.load_goals("tenant-a")


def test_save_goals_raises_when_storage_write_fails(monkeypatch):
    """Protects against silent goal-save failures that appear successful to callers."""
    monkeypatch.setattr("database.save_goals_db", _raise_runtime_error)

    with pytest.raises(RuntimeError):
        goals.save_goals({"dept_targets": {"Packing": 90}}, "tenant-a")
