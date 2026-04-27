from __future__ import annotations

from pages import team


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def caption(self, *_args, **_kwargs):
        return None

    def markdown(self, *_args, **_kwargs):
        return None

    def write(self, *_args, **_kwargs):
        return None


class _FakeProfile:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def stage(self, _name):
        return _Ctx()

    def set(self, *_args, **_kwargs):
        return None

    def observe_rows(self, *_args, **_kwargs):
        return None

    def query(self, *_args, **_kwargs):
        return None


def _goal_status_rows() -> list[dict]:
    return [
        {
            "EmployeeID": "E1",
            "Employee Name": "Alex",
            "Department": "Packing",
            "Average UPH": 82,
            "Target UPH": 100,
            "trend": "declining",
            "goal_status": "below_goal",
            "change_pct": -8.0,
        },
        {
            "EmployeeID": "E2",
            "Employee Name": "Jamie",
            "Department": "Packing",
            "Average UPH": 101,
            "Target UPH": 100,
            "trend": "stable",
            "goal_status": "at_goal",
            "change_pct": 0.0,
        },
        {
            "EmployeeID": "E3",
            "Employee Name": "Sam",
            "Department": "Shipping",
            "Average UPH": 109,
            "Target UPH": 100,
            "trend": "improving",
            "goal_status": "at_goal",
            "change_pct": 9.0,
        },
    ]


def _install_streamlit_stubs(monkeypatch, session_state, *, radio_calls=None, captions=None, infos=None):
    radio_calls = radio_calls if radio_calls is not None else []
    captions = captions if captions is not None else []
    infos = infos if infos is not None else []

    monkeypatch.setattr(team.st, "session_state", session_state)
    monkeypatch.setattr(team.st, "columns", lambda spec, **kwargs: [_Ctx() for _ in range(len(spec) if isinstance(spec, list) else int(spec))])
    monkeypatch.setattr(team.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(team.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(team.st, "line_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(team.st, "expander", lambda *args, **kwargs: _Ctx())
    monkeypatch.setattr(team.st, "caption", lambda text, *args, **kwargs: captions.append(str(text)))
    monkeypatch.setattr(team.st, "info", lambda text, *args, **kwargs: infos.append(str(text)))

    def _text_input(_label, key=None, value="", **kwargs):
        if key and key not in session_state:
            session_state[key] = value
        return session_state.get(key, value)

    def _selectbox(_label, options, key=None, **kwargs):
        options = list(options)
        if key and session_state.get(key) not in options:
            session_state[key] = options[0]
        return session_state.get(key)

    def _radio(label, options, key=None, **kwargs):
        options = list(options)
        radio_calls.append({"label": label, "key": key, "options": options})
        if key and session_state.get(key) not in options:
            session_state[key] = options[0]
        return session_state.get(key)

    monkeypatch.setattr(team.st, "text_input", _text_input)
    monkeypatch.setattr(team.st, "selectbox", _selectbox)
    monkeypatch.setattr(team.st, "radio", _radio)

    return radio_calls, captions, infos


def _install_team_page_dependencies(
    monkeypatch,
    *,
    roster_rows: list[dict],
    notes=None,
    timeline=None,
    exceptions=None,
    history=None,
):
    monkeypatch.setattr(team, "require_db", lambda: True)
    monkeypatch.setattr(team, "_render_team_page_styles", lambda: None)
    monkeypatch.setattr(team, "profile_block", lambda *args, **kwargs: _FakeProfile())
    monkeypatch.setattr(team, "_load_team_roster_snapshot", lambda **kwargs: (list(roster_rows), "2026-04-19", "snapshot"))
    monkeypatch.setattr(team, "_cached_coaching_notes_for", notes or (lambda employee_id: []))
    monkeypatch.setattr(team, "get_employee_action_timeline", timeline or (lambda employee_id, tenant_id="": []))
    monkeypatch.setattr(team, "list_recent_operational_exceptions", exceptions or (lambda tenant_id="", employee_id="", limit=25: []))
    monkeypatch.setattr(team, "get_employee_snapshot_history", history or (lambda tenant_id="", employee_id="", days=30: []))


def _roster_options_for(radio_calls):
    for call in radio_calls:
        if call.get("key") == "team_selected_emp_id":
            return call.get("options") or []
    return []


def test_load_team_roster_snapshot_uses_non_rebuilding_snapshot_fetch(monkeypatch):
    session_state = _SessionState()
    monkeypatch.setattr(team.st, "session_state", session_state)

    calls = []

    def _fake_get_latest_snapshot_goal_status(**kwargs):
        calls.append(dict(kwargs))
        return ([{"EmployeeID": "E1"}], [], "2026-04-19")

    monkeypatch.setattr(team, "get_latest_snapshot_goal_status", _fake_get_latest_snapshot_goal_status)

    rows, snapshot_date, source = team._load_team_roster_snapshot(tenant_id="tenant-1", days=30)

    assert rows == [{"EmployeeID": "E1"}]
    assert snapshot_date == "2026-04-19"
    assert source == "snapshot"
    assert calls == [{"tenant_id": "tenant-1", "days": 30, "rebuild_if_missing": False}]
    assert session_state["goal_status"] == [{"EmployeeID": "E1"}]
    assert session_state["_latest_snapshot_date"] == "2026-04-19"
    assert session_state["_goal_history_tenant"] == "tenant-1"


def test_page_team_initializes_default_filters_and_selects_first_employee_when_unset(monkeypatch):
    session_state = _SessionState({"tenant_id": "tenant-1", "user_email": "user@example.com"})
    radio_calls, _captions, _infos = _install_streamlit_stubs(monkeypatch, session_state)
    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows())

    team.page_team()

    assert session_state["team_employee_search"] == ""
    assert session_state["team_department_filter"] == "all"
    assert session_state["team_status_filter"] == "all"
    assert session_state["team_time_window_days"] == 14
    assert session_state["team_selected_emp_id"] == "E1"
    assert _roster_options_for(radio_calls) == ["E1", "E2", "E3"]


def test_page_team_keeps_existing_selection_when_valid(monkeypatch):
    session_state = _SessionState(
        {
            "tenant_id": "tenant-1",
            "user_email": "user@example.com",
            "team_selected_emp_id": "E2",
        }
    )
    _install_streamlit_stubs(monkeypatch, session_state)
    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows())

    team.page_team()

    assert session_state["team_selected_emp_id"] == "E2"


def test_page_team_roster_filters_reduce_visible_options(monkeypatch):
    session_state = _SessionState(
        {
            "tenant_id": "tenant-1",
            "user_email": "user@example.com",
            "team_employee_search": "sam",
            "team_department_filter": "Shipping",
            "team_status_filter": "improved recently",
            "team_time_window_days": 30,
        }
    )
    radio_calls, _captions, _infos = _install_streamlit_stubs(monkeypatch, session_state)
    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows())

    team.page_team()

    assert _roster_options_for(radio_calls) == ["E3"]
    assert session_state["team_selected_emp_id"] == "E3"


def test_page_team_empty_filter_result_falls_back_to_full_roster(monkeypatch):
    session_state = _SessionState(
        {
            "tenant_id": "tenant-1",
            "user_email": "user@example.com",
            "team_employee_search": "missing-name",
        }
    )
    radio_calls, captions, _infos = _install_streamlit_stubs(monkeypatch, session_state)
    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows())

    team.page_team()

    assert _roster_options_for(radio_calls) == ["E1", "E2", "E3"]
    assert any("No employees match these filters" in caption for caption in captions)


def test_page_team_scopes_selected_employee_detail_loads_and_notes_use_employee_id(monkeypatch):
    session_state = _SessionState(
        {
            "tenant_id": "tenant-1",
            "user_email": "user@example.com",
            "team_selected_emp_id": "E2",
        }
    )
    _install_streamlit_stubs(monkeypatch, session_state)

    calls = {"notes": [], "timeline": [], "exceptions": [], "history": []}

    def _notes(employee_id):
        calls["notes"].append(employee_id)
        assert employee_id != "Jamie"
        return [{"created_at": "2026-04-19T10:00:00", "note": "Investigated prior shift."}]

    def _timeline(employee_id, tenant_id=""):
        calls["timeline"].append((employee_id, tenant_id))
        return [{"event_at": "2026-04-19T09:00:00", "event_type": "coached", "notes": "Reviewed workflow."}]

    def _exceptions(tenant_id="", employee_id="", limit=25):
        calls["exceptions"].append((tenant_id, employee_id, limit))
        return [{"id": "X1", "created_at": "2026-04-18T09:00:00", "category": "scanner_issue", "summary": "Scanner lag."}]

    def _history(tenant_id="", employee_id="", days=30):
        calls["history"].append((tenant_id, employee_id, days))
        return [{"snapshot_date": "2026-04-19T00:00:00", "performance_uph": 101}]

    _install_team_page_dependencies(
        monkeypatch,
        roster_rows=_goal_status_rows(),
        notes=_notes,
        timeline=_timeline,
        exceptions=_exceptions,
        history=_history,
    )

    team.page_team()

    assert calls["notes"] == ["E2"]
    assert calls["timeline"] == [("E2", "tenant-1")]
    assert calls["exceptions"] == [("tenant-1", "E2", 25)]
    assert calls["history"] == [("tenant-1", "E2", 30)]


def test_page_team_normal_render_uses_snapshot_without_recompute(monkeypatch):
    session_state = _SessionState({"tenant_id": "tenant-1", "user_email": "user@example.com"})
    _install_streamlit_stubs(monkeypatch, session_state)

    snapshot_calls = []

    def _snapshot_goal_status(**kwargs):
        snapshot_calls.append(dict(kwargs))
        return (_goal_status_rows(), [], "2026-04-19")

    monkeypatch.setattr(team, "require_db", lambda: True)
    monkeypatch.setattr(team, "_render_team_page_styles", lambda: None)
    monkeypatch.setattr(team, "profile_block", lambda *args, **kwargs: _FakeProfile())
    monkeypatch.setattr(team, "get_latest_snapshot_goal_status", _snapshot_goal_status)
    monkeypatch.setattr(team, "_cached_coaching_notes_for", lambda employee_id: [])
    monkeypatch.setattr(team, "get_employee_action_timeline", lambda employee_id, tenant_id="": [])
    monkeypatch.setattr(team, "list_recent_operational_exceptions", lambda tenant_id="", employee_id="", limit=25: [])
    monkeypatch.setattr(team, "get_employee_snapshot_history", lambda tenant_id="", employee_id="", days=30: [])

    team.page_team()

    assert len(snapshot_calls) == 1
    assert snapshot_calls[0]["tenant_id"] == "tenant-1"
    assert snapshot_calls[0]["days"] == 30
    assert snapshot_calls[0]["rebuild_if_missing"] is False


def test_normalize_recent_activity_timeline_filters_noise_and_dedupes_by_type_and_timestamp():
    notes = [
        {"created_at": "2026-04-19T10:00:00", "note": "Observed change in pace."},
        {"created_at": "2026-04-19T10:00:00", "note": "Observed change in pace."},
        {"created_at": "2026-04-19T09:00:00", "note": "reason=Today queue completion follow_up_required=yes"},
    ]
    action_rows = [
        {"action_id": "A2", "event_at": "2026-04-20T11:00:00", "event_type": "follow_up_logged", "next_follow_up_at": "2026-04-22"},
        {"action_id": "A3", "event_at": "2026-04-20T12:00:00", "event_type": "resolved", "status": "completed"},
        {"action_id": "A4", "event_at": "2026-04-20T10:00:00", "event_type": "some_internal_code", "notes": "debug payload"},
    ]
    exception_rows = [
        {"id": "X1", "created_at": "2026-04-18T08:30:00", "category": "scanner_issue", "summary": "bad"},
        {"id": "X2", "created_at": "2026-04-20T13:00:00", "category": "scanner_issue", "summary": ""},
    ]

    timeline = team._normalize_recent_activity_timeline(
        notes=notes,
        action_rows=action_rows,
        exception_rows=exception_rows,
        limit=10,
    )

    assert len(timeline) == 4
    assert [item["event_type"] for item in timeline] == [
        "Issue recorded",
        "Issue resolved",
        "Follow-up scheduled",
        "Note added",
    ]
    assert all(item["event_type"] in {"Issue recorded", "Note added", "Follow-up scheduled", "Issue resolved"} for item in timeline)
    assert len({(item["event_type"], item["event_at"].isoformat()) for item in timeline}) == len(timeline)


def test_normalize_recent_activity_timeline_limits_to_most_recent_five_events():
    notes = [
        {"created_at": "2026-04-20T08:00:00", "note": "Note one."},
        {"created_at": "2026-04-20T07:00:00", "note": "Note two."},
    ]
    action_rows = [
        {"action_id": "A1", "event_at": "2026-04-20T12:00:00", "event_type": "resolved", "status": "completed"},
        {"action_id": "A2", "event_at": "2026-04-20T11:00:00", "event_type": "follow_up_logged", "next_follow_up_at": "2026-04-22"},
        {"action_id": "A3", "event_at": "2026-04-20T10:00:00", "event_type": "resolved", "status": "completed"},
        {"action_id": "A4", "event_at": "2026-04-20T09:00:00", "event_type": "follow_up_logged", "next_follow_up_at": "2026-04-23"},
    ]
    exception_rows = [
        {"id": "X1", "created_at": "2026-04-20T13:00:00", "status": "open", "summary": "Scanner lag"},
    ]

    timeline = team._normalize_recent_activity_timeline(
        notes=notes,
        action_rows=action_rows,
        exception_rows=exception_rows,
        limit=5,
    )

    assert len(timeline) == 5
    assert timeline[0]["event_at"].isoformat().startswith("2026-04-20T13:00:00")
    assert timeline[-1]["event_at"].isoformat().startswith("2026-04-20T09:00:00")
