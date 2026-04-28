from __future__ import annotations

from datetime import datetime

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


def _install_streamlit_stubs(
    monkeypatch,
    session_state,
    *,
    radio_calls=None,
    captions=None,
    infos=None,
    markdowns=None,
    button_click_keys=None,
):
    radio_calls = radio_calls if radio_calls is not None else []
    captions = captions if captions is not None else []
    infos = infos if infos is not None else []
    markdowns = markdowns if markdowns is not None else []
    click_keys = set(button_click_keys or [])

    monkeypatch.setattr(team.st, "session_state", session_state)
    monkeypatch.setattr(team.st, "columns", lambda spec, **kwargs: [_Ctx() for _ in range(len(spec) if isinstance(spec, list) else int(spec))])
    monkeypatch.setattr(team.st, "markdown", lambda text, *args, **kwargs: markdowns.append(str(text)))
    monkeypatch.setattr(team.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(team.st, "line_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(team.st, "expander", lambda *args, **kwargs: _Ctx())
    monkeypatch.setattr(team.st, "caption", lambda text, *args, **kwargs: captions.append(str(text)))
    monkeypatch.setattr(team.st, "info", lambda text, *args, **kwargs: infos.append(str(text)))
    monkeypatch.setattr(team.st, "rerun", lambda: None)

    def _button(_label, key=None, **kwargs):
        return bool(key in click_keys)

    monkeypatch.setattr(team.st, "button", _button)

    def _text_input(_label, key=None, value="", **kwargs):
        if key and key not in session_state:
            session_state[key] = value
        return session_state.get(key, value)

    def _selectbox(_label, options, key=None, **kwargs):
        options = list(options)
        format_func = kwargs.get("format_func")
        formatted_options = [
            str(format_func(option)) if callable(format_func) else str(option)
            for option in options
        ]
        radio_calls.append({"label": _label, "key": key, "options": options})
        radio_calls[-1]["formatted_options"] = formatted_options
        if key and session_state.get(key) not in options:
            session_state[key] = options[0]
        return session_state.get(key)

    def _radio(label, options, key=None, **kwargs):
        options = list(options)
        format_func = kwargs.get("format_func")
        formatted_options = [
            str(format_func(option)) if callable(format_func) else str(option)
            for option in options
        ]
        radio_calls.append({"label": label, "key": key, "options": options})
        radio_calls[-1]["formatted_options"] = formatted_options
        if key and session_state.get(key) not in options:
            session_state[key] = options[0]
        return session_state.get(key)

    monkeypatch.setattr(team.st, "text_input", _text_input)
    monkeypatch.setattr(team.st, "selectbox", _selectbox)
    monkeypatch.setattr(team.st, "radio", _radio)

    return radio_calls, captions, infos, markdowns


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


def _roster_formatted_labels_for(radio_calls):
    for call in radio_calls:
        if call.get("key") == "team_selected_emp_id":
            return call.get("formatted_options") or []
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
    radio_calls, _captions, _infos, _markdowns = _install_streamlit_stubs(monkeypatch, session_state)
    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows())

    team.page_team()

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


def test_page_team_selector_shows_all_employees_and_includes_trend_label(monkeypatch):
    session_state = _SessionState(
        {
            "tenant_id": "tenant-1",
            "user_email": "user@example.com",
            "team_selected_emp_id": "E3",
            "team_time_window_days": 30,
        }
    )
    radio_calls, _captions, _infos, _markdowns = _install_streamlit_stubs(monkeypatch, session_state)

    def _history(tenant_id="", employee_id="", days=30):
        if str(employee_id) == "E3":
            return [
                {"snapshot_date": "2026-04-17T00:00:00", "performance_uph": 90},
                {"snapshot_date": "2026-04-18T00:00:00", "performance_uph": 95},
                {"snapshot_date": "2026-04-19T00:00:00", "performance_uph": 100},
            ]
        return [
            {"snapshot_date": "2026-04-17T00:00:00", "performance_uph": 100},
            {"snapshot_date": "2026-04-18T00:00:00", "performance_uph": 100},
            {"snapshot_date": "2026-04-19T00:00:00", "performance_uph": 100},
        ]

    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows(), history=_history)

    team.page_team()

    assert _roster_options_for(radio_calls) == ["E1", "E2", "E3"]
    labels = _roster_formatted_labels_for(radio_calls)
    assert any(label.startswith("Sam") and "Improving" in label for label in labels)
    assert session_state["team_selected_emp_id"] == "E3"


def test_page_team_invalid_selected_employee_falls_back_to_first_option(monkeypatch):
    session_state = _SessionState(
        {
            "tenant_id": "tenant-1",
            "user_email": "user@example.com",
            "team_selected_emp_id": "E999",
        }
    )
    radio_calls, captions, _infos, _markdowns = _install_streamlit_stubs(monkeypatch, session_state)
    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows())

    team.page_team()

    assert _roster_options_for(radio_calls) == ["E1", "E2", "E3"]
    assert session_state["team_selected_emp_id"] == "E1"
    assert not any("No employees match these filters" in caption for caption in captions)


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
    assert sorted(calls["history"]) == sorted(
        [
            ("tenant-1", "E1", 30),
            ("tenant-1", "E2", 30),
            ("tenant-1", "E3", 30),
        ]
    )


def test_page_team_roster_trend_matches_detail_trend_for_same_employee(monkeypatch):
    session_state = _SessionState(
        {
            "tenant_id": "tenant-1",
            "user_email": "user@example.com",
            "team_selected_emp_id": "E2",
        }
    )
    radio_calls, captions, _infos, _markdowns = _install_streamlit_stubs(monkeypatch, session_state)

    history_by_employee = {
        "E1": [
            {"snapshot_date": "2026-04-17T00:00:00", "performance_uph": 99},
            {"snapshot_date": "2026-04-18T00:00:00", "performance_uph": 99},
            {"snapshot_date": "2026-04-19T00:00:00", "performance_uph": 99},
        ],
        "E2": [
            {"snapshot_date": "2026-04-17T00:00:00", "performance_uph": 110},
            {"snapshot_date": "2026-04-18T00:00:00", "performance_uph": 100},
            {"snapshot_date": "2026-04-19T00:00:00", "performance_uph": 90},
        ],
        "E3": [
            {"snapshot_date": "2026-04-17T00:00:00", "performance_uph": 90},
            {"snapshot_date": "2026-04-18T00:00:00", "performance_uph": 95},
            {"snapshot_date": "2026-04-19T00:00:00", "performance_uph": 100},
        ],
    }

    def _history(tenant_id="", employee_id="", days=30):
        return list(history_by_employee.get(str(employee_id), []))

    _install_team_page_dependencies(
        monkeypatch,
        roster_rows=_goal_status_rows(),
        history=_history,
    )

    team.page_team()

    roster_labels = _roster_formatted_labels_for(radio_calls)
    e2_roster_label = ""
    for label in roster_labels:
        if label.startswith("Jamie"):
            e2_roster_label = label
            break

    assert "Declining" in e2_roster_label
    assert any("Declining" in caption for caption in captions)


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


def test_compute_window_trend_metrics_uses_slope_for_label_when_directions_match():
    chart_rows = [
        {"Date": "2026-04-20", "UPH": 100.0},
        {"Date": "2026-04-21", "UPH": 102.0},
        {"Date": "2026-04-22", "UPH": 104.0},
    ]

    metrics = team._compute_window_trend_metrics(chart_rows)

    assert metrics["slope_direction"] == "positive"
    assert metrics["change_direction"] == "positive"
    assert metrics["label"] == "Improving"


def test_compute_window_trend_metrics_hides_label_on_direction_mismatch():
    chart_rows = [
        {"Date": "2026-04-20", "UPH": 100.0},
        {"Date": "2026-04-21", "UPH": 0.0},
        {"Date": "2026-04-22", "UPH": 100.0},
        {"Date": "2026-04-23", "UPH": 99.0},
    ]

    metrics = team._compute_window_trend_metrics(chart_rows)
    summary = team._format_window_trend_summary(metrics, 14)

    assert metrics["slope_direction"] == "positive"
    assert metrics["change_direction"] == "negative"
    assert metrics["label"] is None
    assert summary == "-1.0% over the last 14 days"


def test_window_trend_summary_uses_percent_only_when_label_suppressed():
    summary = team._format_window_trend_summary(
        {
            "change_pct": -3.5,
            "label": None,
        },
        14,
    )

    assert summary == "-3.5% over the last 14 days"


def test_get_follow_up_status_overdue_overrides_other_states():
    status = team.get_follow_up_status(
        {
            "row": {
                "follow_up_due_at": "2026-04-01T09:00:00",
                "follow_up_due": "pending",
                "next_follow_up_at": "2026-05-04T09:00:00",
            },
            "notes": [],
            "action_rows": [],
        }
    )

    assert status["primary"] == "Follow-up overdue"


def test_get_follow_up_status_due_today_overrides_scheduled():
    status = team.get_follow_up_status(
        {
            "row": {
                "follow_up_due_at": datetime.utcnow().date().isoformat(),
                "next_follow_up_at": "2026-05-04T09:00:00",
            },
            "notes": [],
            "action_rows": [],
        }
    )

    assert status["primary"] == "Follow-up due today"


def test_get_follow_up_status_scheduled_displays_formatted_date():
    status = team.get_follow_up_status(
        {
            "row": {"follow_up_due_at": "2026-05-04T09:00:00"},
            "notes": [],
            "action_rows": [],
        }
    )

    assert status["primary"] == "Follow-up scheduled for May 4 at 9:00 AM"


def test_get_follow_up_status_no_follow_up_case():
    status = team.get_follow_up_status(
        {
            "row": {"follow_up_due": ""},
            "notes": [],
            "action_rows": [],
        }
    )

    assert status["primary"] == "No follow-up scheduled"
    assert status["secondary"] is None


def test_get_follow_up_status_only_one_secondary_line_appears():
    status = team.get_follow_up_status(
        {
            "row": {"last_follow_up_at": "2026-04-01T09:00:00"},
            "notes": [{"created_at": "2026-04-27T09:00:00", "note": "Reviewed"}],
            "action_rows": [{"event_at": "2026-04-27T10:00:00", "notes": "Another entry"}],
        }
    )

    assert status["secondary"] in {"Reviewed recently", "Last checked Apr 27"}
    assert isinstance(status["secondary"], str)
    assert "|" not in str(status["secondary"])
    assert " and " not in str(status["secondary"]).lower()


def test_get_follow_up_status_has_no_duplicate_or_conflicting_text():
    status = team.get_follow_up_status(
        {
            "row": {"follow_up_due_at": "2026-05-04T09:00:00", "last_follow_up_at": "2026-05-04T09:00:00"},
            "notes": [],
            "action_rows": [],
        }
    )

    primary = str(status.get("primary") or "")
    secondary = str(status.get("secondary") or "")
    assert primary.startswith("Follow-up scheduled for")
    assert "Follow-up overdue" not in secondary
    assert "Follow-up due today" not in secondary
    # no more than two lines total by contract (primary + optional single secondary)
    assert isinstance(status.get("primary"), str)
    assert status.get("secondary") is None or isinstance(status.get("secondary"), str)


def test_team_handoff_auto_selects_employee_and_shows_banner_once(monkeypatch):
    session_state = _SessionState(
        {
            "tenant_id": "tenant-1",
            "user_email": "user@example.com",
            "_today_to_team_handoff": {
                "employee_id": "E2",
                "reason": "Declining performance over 14 days",
                "signal_id": "sig-1",
                "signal_key": "key-1",
                "follow_up_status": "Follow-up due May 4",
            },
        }
    )
    _radio_calls, _captions, _infos, markdowns = _install_streamlit_stubs(monkeypatch, session_state)
    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows())

    team.page_team()

    assert session_state["team_selected_emp_id"] == "E2"
    assert any("From Today:" in line for line in markdowns)
    assert "_today_to_team_handoff" not in session_state

    markdowns_second: list[str] = []
    _install_streamlit_stubs(monkeypatch, session_state, markdowns=markdowns_second)
    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows())
    team.page_team()
    assert not any("From Today:" in line for line in markdowns_second)


def test_team_return_button_sets_today_focus_payload(monkeypatch):
    session_state = _SessionState(
        {
            "tenant_id": "tenant-1",
            "user_email": "user@example.com",
            "team_selected_emp_id": "E2",
        }
    )
    _install_streamlit_stubs(
        monkeypatch,
        session_state,
        button_click_keys={"team_bridge_to_today_E2"},
    )
    _install_team_page_dependencies(monkeypatch, roster_rows=_goal_status_rows())

    team.page_team()

    assert session_state["goto_page"] == "today"
    assert session_state["cn_selected_emp"] == "E2"
    assert session_state["_team_to_today_focus"]["employee_id"] == "E2"


def test_get_trend_status_declining_pairs_severity_by_target_position():
    below_target = team.get_trend_status(
        {
            "trend_metrics": {"label": "Declining", "slope_direction": "negative"},
            "avg_uph": 82.0,
            "target_uph": 100.0,
        }
    )
    near_or_above_target = team.get_trend_status(
        {
            "trend_metrics": {"label": "Declining", "slope_direction": "negative"},
            "avg_uph": 100.0,
            "target_uph": 100.0,
        }
    )

    assert below_target["label"] == "Declining"
    assert below_target["direction"] == "negative"
    assert below_target["severity"] == "Needs attention this week"
    assert near_or_above_target["label"] == "Declining"
    assert near_or_above_target["severity"] == "Monitor"


def test_get_trend_status_improving_never_maps_to_needs_attention():
    below_target = team.get_trend_status(
        {
            "trend_metrics": {"label": "Improving", "slope_direction": "positive"},
            "avg_uph": 92.0,
            "target_uph": 100.0,
        }
    )
    above_target = team.get_trend_status(
        {
            "trend_metrics": {"label": "Improving", "slope_direction": "positive"},
            "avg_uph": 108.0,
            "target_uph": 100.0,
        }
    )

    assert below_target["severity"] == "Monitor"
    assert above_target["severity"] == "No immediate action"
    assert below_target["severity"] != "Needs attention this week"
    assert above_target["severity"] != "Needs attention this week"


def test_get_trend_status_label_and_severity_mapping_never_mismatch():
    scenarios = [
        ({"label": "Declining", "slope_direction": "negative"}, 84.0, 100.0, "Needs attention this week"),
        ({"label": "Declining", "slope_direction": "negative"}, 100.0, 100.0, "Monitor"),
        ({"label": "Holding steady", "slope_direction": "flat"}, 96.0, 100.0, "Monitor"),
        ({"label": "Holding steady", "slope_direction": "flat"}, 101.0, 100.0, "No immediate action"),
        ({"label": "Improving", "slope_direction": "positive"}, 95.0, 100.0, "Monitor"),
        ({"label": "Improving", "slope_direction": "positive"}, 106.0, 100.0, "No immediate action"),
    ]

    for trend_metrics, avg_uph, target_uph, expected_severity in scenarios:
        trend_status = team.get_trend_status(
            {
                "trend_metrics": trend_metrics,
                "avg_uph": avg_uph,
                "target_uph": target_uph,
            }
        )
        assert trend_status["severity"] == expected_severity
