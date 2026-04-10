from types import SimpleNamespace

from repositories import action_events_repo, actions_repo, billing_repo, operational_exceptions_repo


def test_actions_repo_create_action_returns_empty_dict_on_failure(monkeypatch):
    logged = []

    class _Client:
        def table(self, _name):
            raise RuntimeError("db write failed")

    monkeypatch.setattr(actions_repo, "get_client", lambda: _Client())
    monkeypatch.setattr(actions_repo, "get_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(actions_repo, "log_error", lambda *args, **kwargs: logged.append((args, kwargs)))

    out = actions_repo.create_action(
        employee_id="E1",
        employee_name="Alex",
        department="Pack",
        issue_type="performance",
        trigger_summary="Below baseline",
        action_type="coaching",
        success_metric="Improve",
        follow_up_due_at="2026-04-10",
    )

    assert out == {}
    assert logged


def test_action_events_repo_log_action_event_returns_empty_dict_on_failure(monkeypatch):
    logged = []

    class _Client:
        def table(self, _name):
            raise RuntimeError("insert failed")

    monkeypatch.setattr(action_events_repo, "get_client", lambda: _Client())
    monkeypatch.setattr(action_events_repo, "get_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(action_events_repo, "log_error", lambda *args, **kwargs: logged.append((args, kwargs)))

    out = action_events_repo.log_action_event("1", "created", "E1")

    assert out == {}
    assert logged


def test_billing_repo_update_subscription_state_returns_false_on_failure(monkeypatch):
    logged = []

    class _Query:
        def eq(self, *_args, **_kwargs):
            return self

        def execute(self):
            raise RuntimeError("update failed")

    class _Client:
        def table(self, _name):
            return SimpleNamespace(update=lambda _payload: _Query())

    monkeypatch.setattr(billing_repo, "get_client", lambda: _Client())
    monkeypatch.setattr(billing_repo, "get_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(billing_repo, "log_error", lambda *args, **kwargs: logged.append((args, kwargs)))

    ok = billing_repo.update_subscription_state({"status": "active"})

    assert ok is False
    assert logged


def test_operational_exceptions_repo_create_returns_empty_dict_on_failure(monkeypatch):
    logged = []

    class _Client:
        def table(self, _name):
            raise RuntimeError("db write failed")

    monkeypatch.setattr(operational_exceptions_repo, "get_client", lambda: _Client())
    monkeypatch.setattr(operational_exceptions_repo, "get_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(operational_exceptions_repo, "log_error", lambda *args, **kwargs: logged.append((args, kwargs)))

    out = operational_exceptions_repo.create_operational_exception(
        exception_date="2026-04-09",
        category="equipment",
        summary="Scanner outage",
        employee_id="E1",
    )

    assert out == {}
    assert logged