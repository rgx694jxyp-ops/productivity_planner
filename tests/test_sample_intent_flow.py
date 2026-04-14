from urllib.parse import parse_qs, urlparse

import auth
from core import app_flow
from core.onboarding_intent import ONBOARDING_CORRELATION_QUERY_PARAM, ONBOARDING_QUERY_PARAM
from ui import landing


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _RerunTriggered(Exception):
    pass


def test_landing_sample_cta_sets_post_auth_sample_intent(monkeypatch):
    session_state = _SessionState()
    query_params = {}
    captured_events: list[tuple[str, dict]] = []

    class _Column:
        def __init__(self, clicked_label: str | None):
            self.clicked_label = clicked_label

        def button(self, label, **kwargs):
            return label == self.clicked_label

    monkeypatch.setattr(landing.st, "session_state", session_state)
    monkeypatch.setattr(landing.st, "query_params", query_params)
    monkeypatch.setattr(landing.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "image", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "video", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "columns", lambda n: [_Column("Try sample data"), _Column(None)] if n == 2 else [_Column(None) for _ in range(n)])
    monkeypatch.setattr(landing.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(landing, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing, "log_operational_event", lambda event_type, **kwargs: captured_events.append((event_type, kwargs)))
    monkeypatch.setattr(landing.os.path, "exists", lambda path: False)
    monkeypatch.setattr(landing.st, "rerun", lambda: (_ for _ in ()).throw(_RerunTriggered()))

    try:
        landing.show_landing_page()
    except _RerunTriggered:
        pass

    assert session_state["show_login"] is True
    assert session_state["_post_auth_intent"] == landing.SAMPLE_DATA_POST_AUTH_INTENT
    assert query_params[ONBOARDING_QUERY_PARAM] == landing.SAMPLE_DATA_POST_AUTH_INTENT
    assert query_params[ONBOARDING_CORRELATION_QUERY_PARAM]
    assert session_state["_onboarding_correlation_id"] == query_params[ONBOARDING_CORRELATION_QUERY_PARAM]
    assert [event for event, _ in captured_events[:2]] == [
        "landing_sample_cta_clicked",
        "onboarding_sample_intent_preserved",
    ]
    assert captured_events[0][1]["context"]["onboarding_correlation_id"] == query_params[ONBOARDING_CORRELATION_QUERY_PARAM]


def test_handle_public_query_actions_reopens_login_for_sample_reload(monkeypatch):
    session_state = _SessionState()
    query_params = {
        ONBOARDING_QUERY_PARAM: landing.SAMPLE_DATA_POST_AUTH_INTENT,
        ONBOARDING_CORRELATION_QUERY_PARAM: "corr-123",
    }
    captured_events: list[tuple[str, dict]] = []

    monkeypatch.setattr(app_flow.st, "session_state", session_state)
    monkeypatch.setattr(app_flow.st, "query_params", query_params)
    monkeypatch.setattr(app_flow, "log_operational_event", lambda event_type, **kwargs: captured_events.append((event_type, kwargs)))

    app_flow.handle_public_query_actions()

    assert session_state["show_login"] is True
    assert query_params[ONBOARDING_QUERY_PARAM] == landing.SAMPLE_DATA_POST_AUTH_INTENT
    assert session_state["_onboarding_correlation_id"] == "corr-123"
    assert captured_events[0][0] == "onboarding_sample_intent_preserved"
    assert captured_events[0][1]["context"]["onboarding_correlation_id"] == "corr-123"


def test_auth_redirect_url_preserves_sample_onboarding_param(monkeypatch):
    monkeypatch.setenv("AUTH_REDIRECT_URL", "https://example.com")
    monkeypatch.setattr(
        auth.st,
        "query_params",
        {
            ONBOARDING_QUERY_PARAM: landing.SAMPLE_DATA_POST_AUTH_INTENT,
            ONBOARDING_CORRELATION_QUERY_PARAM: "corr-123",
        },
    )
    monkeypatch.setattr(auth.st, "secrets", {})

    redirect_url = auth._auth_redirect_url()
    parsed = urlparse(redirect_url)

    assert parsed.scheme == "https"
    assert parsed.netloc == "example.com"
    assert parse_qs(parsed.query)[ONBOARDING_QUERY_PARAM] == [landing.SAMPLE_DATA_POST_AUTH_INTENT]
    assert parse_qs(parsed.query)[ONBOARDING_CORRELATION_QUERY_PARAM] == ["corr-123"]


def test_ensure_authenticated_session_routes_query_param_sample_users_to_existing_import_flow(monkeypatch):
    session_state = _SessionState(
        {
            "supabase_session": {"access_token": "token", "refresh_token": "refresh"},
        }
    )
    query_params = {
        ONBOARDING_QUERY_PARAM: landing.SAMPLE_DATA_POST_AUTH_INTENT,
        ONBOARDING_CORRELATION_QUERY_PARAM: "corr-123",
    }
    captured_events: list[tuple[str, dict]] = []

    monkeypatch.setattr(app_flow.st, "session_state", session_state)
    monkeypatch.setattr(app_flow.st, "query_params", query_params)
    monkeypatch.setattr(app_flow, "restore_session_from_cookies", lambda: False)
    monkeypatch.setattr(app_flow, "log_operational_event", lambda event_type, **kwargs: captured_events.append((event_type, kwargs)))

    assert app_flow.ensure_authenticated_session() is True
    assert session_state["goto_page"] == "import"
    assert session_state["import_entry_mode"] == "Try sample data"
    assert session_state["_auto_load_sample_on_import_once"] is True
    assert session_state["_onboarding_correlation_id"] == "corr-123"
    assert "_post_auth_intent" not in session_state
    assert ONBOARDING_QUERY_PARAM not in query_params
    assert captured_events[0][0] == "onboarding_sample_intent_consumed"
    assert captured_events[0][1]["context"]["onboarding_correlation_id"] == "corr-123"


def test_track_landing_event_maps_required_funnel_events(monkeypatch):
    session_state = _SessionState({"_onboarding_correlation_id": "corr-123"})
    query_params = {ONBOARDING_CORRELATION_QUERY_PARAM: "corr-123"}
    captured_events: list[tuple[str, dict]] = []

    monkeypatch.setattr(landing.st, "session_state", session_state)
    monkeypatch.setattr(landing.st, "query_params", query_params)
    monkeypatch.setattr(landing, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing, "log_operational_event", lambda event_type, **kwargs: captured_events.append((event_type, kwargs)))

    landing.track_landing_event("cta_click", "hero_try_sample_data")
    landing.track_landing_event("cta_click", "bottom_get_started")

    assert [event for event, _ in captured_events] == ["landing_sample_cta_clicked", "landing_generic_cta_clicked"]
    assert all(kwargs["context"]["onboarding_correlation_id"] == "corr-123" for _, kwargs in captured_events)


def test_sample_correlation_persists_across_reload_and_auth(monkeypatch):
    landing_state = _SessionState()
    landing_query = {}

    class _Column:
        def __init__(self, clicked_label: str | None):
            self.clicked_label = clicked_label

        def button(self, label, **kwargs):
            return label == self.clicked_label

    monkeypatch.setattr(landing.st, "session_state", landing_state)
    monkeypatch.setattr(landing.st, "query_params", landing_query)
    monkeypatch.setattr(landing.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "image", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "video", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.st, "columns", lambda n: [_Column("Try sample data"), _Column(None)] if n == 2 else [_Column(None) for _ in range(n)])
    monkeypatch.setattr(landing.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(landing, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing, "log_operational_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(landing.os.path, "exists", lambda path: False)
    monkeypatch.setattr(landing.st, "rerun", lambda: (_ for _ in ()).throw(_RerunTriggered()))

    try:
        landing.show_landing_page()
    except _RerunTriggered:
        pass

    correlation_id = landing_query[ONBOARDING_CORRELATION_QUERY_PARAM]
    resumed_state = _SessionState()
    resumed_query = dict(landing_query)

    monkeypatch.setattr(app_flow.st, "session_state", resumed_state)
    monkeypatch.setattr(app_flow.st, "query_params", resumed_query)
    monkeypatch.setattr(app_flow, "log_operational_event", lambda *args, **kwargs: None)
    app_flow.handle_public_query_actions()

    assert resumed_state["_onboarding_correlation_id"] == correlation_id

    auth_state = _SessionState({"supabase_session": {"access_token": "token", "refresh_token": "refresh"}})
    auth_query = dict(landing_query)

    monkeypatch.setattr(app_flow.st, "session_state", auth_state)
    monkeypatch.setattr(app_flow.st, "query_params", auth_query)
    monkeypatch.setattr(app_flow, "restore_session_from_cookies", lambda: False)
    monkeypatch.setattr(app_flow, "log_operational_event", lambda *args, **kwargs: None)

    assert app_flow.ensure_authenticated_session() is True
    assert auth_state["_onboarding_correlation_id"] == correlation_id


def test_ensure_authenticated_session_consumes_sample_intent_once(monkeypatch):
    session_state = _SessionState(
        {
            "supabase_session": {"access_token": "token", "refresh_token": "refresh"},
        }
    )
    query_params = {ONBOARDING_QUERY_PARAM: landing.SAMPLE_DATA_POST_AUTH_INTENT}

    monkeypatch.setattr(app_flow.st, "session_state", session_state)
    monkeypatch.setattr(app_flow.st, "query_params", query_params)
    monkeypatch.setattr(app_flow, "restore_session_from_cookies", lambda: False)

    assert app_flow.ensure_authenticated_session() is True
    assert session_state["goto_page"] == "import"
    assert session_state["import_entry_mode"] == "Try sample data"

    session_state.pop("goto_page", None)
    session_state.pop("import_entry_mode", None)

    assert app_flow.ensure_authenticated_session() is True
    assert "goto_page" not in session_state
    assert "import_entry_mode" not in session_state


def test_handle_public_query_actions_clears_sample_intent_for_generic_start(monkeypatch):
    session_state = _SessionState({"_post_auth_intent": landing.SAMPLE_DATA_POST_AUTH_INTENT})
    query_params = {"start": "1", ONBOARDING_QUERY_PARAM: landing.SAMPLE_DATA_POST_AUTH_INTENT}

    monkeypatch.setattr(app_flow.st, "session_state", session_state)
    monkeypatch.setattr(app_flow.st, "query_params", query_params)
    monkeypatch.setattr(app_flow, "track_landing_event", lambda *args, **kwargs: None)

    app_flow.handle_public_query_actions()

    assert session_state["show_login"] is True
    assert "_post_auth_intent" not in session_state
    assert "start" not in query_params
    assert ONBOARDING_QUERY_PARAM not in query_params


def test_ensure_authenticated_session_leaves_non_sample_users_unchanged(monkeypatch):
    session_state = _SessionState(
        {
            "supabase_session": {"access_token": "token", "refresh_token": "refresh"},
        }
    )

    monkeypatch.setattr(app_flow.st, "session_state", session_state)
    monkeypatch.setattr(app_flow.st, "query_params", {})
    monkeypatch.setattr(app_flow, "restore_session_from_cookies", lambda: False)

    assert app_flow.ensure_authenticated_session() is True
    assert "goto_page" not in session_state
    assert "import_entry_mode" not in session_state