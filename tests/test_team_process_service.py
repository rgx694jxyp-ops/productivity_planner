from services.team_process_service import build_team_process_contexts


def test_build_team_process_contexts_surfaces_systemic_pattern_with_explanations():
    goal_status_rows = [
        {
            "EmployeeID": "E1",
            "Department": "Packing",
            "goal_status": "below_goal",
            "trend": "down",
            "Target UPH": 95,
            "recent_trend_history": ["down", "down", "up"],
            "recent_goal_status_history": ["below_goal", "below_goal", "below_goal"],
        },
        {
            "EmployeeID": "E2",
            "Department": "Packing",
            "goal_status": "below_goal",
            "trend": "flat",
            "Target UPH": 95,
            "recent_trend_history": ["down", "flat", "down"],
            "recent_goal_status_history": ["below_goal", "below_goal", "at_goal"],
        },
    ]
    history_rows = [
        {"emp_id": "E1", "department": "Packing", "work_date": "2026-04-01", "uph": 82, "units": 420, "hours_worked": 5},
        {"emp_id": "E2", "department": "Packing", "work_date": "2026-04-01", "uph": 84, "units": 430, "hours_worked": 5},
        {"emp_id": "E1", "department": "Packing", "work_date": "2026-04-02", "uph": 81, "units": 410, "hours_worked": 5},
        {"emp_id": "E2", "department": "Packing", "work_date": "2026-04-02", "uph": 83, "units": 425, "hours_worked": 5},
        {"emp_id": "E1", "department": "Packing", "work_date": "2026-04-03", "uph": 80, "units": 405, "hours_worked": 5},
        {"emp_id": "E2", "department": "Packing", "work_date": "2026-04-03", "uph": 82, "units": 420, "hours_worked": 5},
    ]

    out = build_team_process_contexts(goal_status_rows=goal_status_rows, history_rows=history_rows)

    assert out["has_notable_change"] is True
    assert out["cards"]
    card = out["cards"][0]
    assert card["process_name"] == "Packing"
    assert "below expected pace" in card["current_state"]
    assert card["major_signals"]
    assert card["comparison_breakdown"]["compared_to_target"].startswith("Compared to target")
    assert card["comparison_breakdown"]["compared_to_recent_performance"].startswith("Compared to recent performance")
    assert card["comparison_breakdown"]["compared_to_recent_average"].startswith("Compared to recent average")
    assert {"what_happened", "compared_to_what", "why_showing"}.issubset(card["major_signals"][0].keys())
    assert any("Similar pattern observed multiple times" in msg for msg in card["pattern_messages"])


def test_build_team_process_contexts_returns_healthy_when_no_major_change():
    goal_status_rows = [
        {
            "EmployeeID": "E1",
            "Department": "Shipping",
            "goal_status": "at_goal",
            "trend": "flat",
            "Target UPH": 90,
            "recent_trend_history": ["flat", "flat", "up"],
            "recent_goal_status_history": ["at_goal", "at_goal", "at_goal"],
        }
    ]
    history_rows = [
        {"emp_id": "E1", "department": "Shipping", "work_date": "2026-04-01", "uph": 91},
        {"emp_id": "E1", "department": "Shipping", "work_date": "2026-04-02", "uph": 92},
        {"emp_id": "E1", "department": "Shipping", "work_date": "2026-04-03", "uph": 90},
    ]

    out = build_team_process_contexts(goal_status_rows=goal_status_rows, history_rows=history_rows)

    assert out["has_notable_change"] is False
    assert "No meaningful team-level changes" in out["healthy_message"]
    assert out["cards"][0]["current_state"] == "holding steady"
