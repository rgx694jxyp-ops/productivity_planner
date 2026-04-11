from services.employee_detail_service import build_employee_detail_context


def test_build_employee_detail_context_includes_summary_basis_and_before_after():
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-04-01", "uph": 80, "units": 400, "hours_worked": 5},
        {"emp_id": "E1", "work_date": "2026-04-02", "uph": 82, "units": 410, "hours_worked": 5},
        {"emp_id": "E1", "work_date": "2026-04-03", "uph": 83, "units": 420, "hours_worked": 5},
        {"emp_id": "E1", "work_date": "2026-04-04", "uph": 90, "units": 460, "hours_worked": 5},
        {"emp_id": "E1", "work_date": "2026-04-05", "uph": 92, "units": 470, "hours_worked": 5},
        {"emp_id": "E1", "work_date": "2026-04-06", "uph": 94, "units": 480, "hours_worked": 5},
    ]
    goal_row = {
        "goal_status": "below_goal",
        "trend": "up",
        "Average UPH": 94,
        "Target UPH": 96,
        "recent_trend_history": ["down", "down", "up"],
        "recent_goal_status_history": ["below_goal", "below_goal", "below_goal"],
    }

    ctx = build_employee_detail_context(emp_id="E1", goal_row=goal_row, history_rows=history_rows, lookback_days=10, comparison_days=3)

    assert ctx["current_state"] == "moving up from recent pace"
    assert ctx["signal_summary"]["current_state"] == ctx["current_state"]
    assert ctx["why_this_is_showing"]["trigger"]
    assert "Configured target baseline" in ctx["what_this_is_based_on"]["baseline_used"]
    assert "Deterministic comparison" in ctx["comparison_logic"]
    assert ctx["comparison_breakdown"]["compared_to_target"].startswith("Compared to target")
    assert ctx["comparison_breakdown"]["compared_to_recent_performance"].startswith("Compared to recent performance")
    assert ctx["comparison_breakdown"]["compared_to_recent_average"].startswith("Compared to recent average")
    assert ctx["before_after_summary"]["label"] in {
        "improved compared to prior period",
        "still below expected",
        "no clear change yet",
    }
    assert ctx["pattern_history"]["has_pattern"] is True
    assert len(ctx["trend_points"]) > 0


def test_build_employee_detail_context_tracks_excluded_rows_for_transparency():
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-04-01", "uph": 80},
        {"emp_id": "E1", "work_date": "2026-04-02", "uph": 0},
        {"emp_id": "E1", "work_date": "", "uph": 82},
    ]

    ctx = build_employee_detail_context(emp_id="E1", goal_row={}, history_rows=history_rows, lookback_days=5, comparison_days=2)

    assert len(ctx["included_records"]) == 1
    assert len(ctx["excluded_records"]) == 2
    assert "Excluded records" in ctx["missing_data_note"]


def test_build_employee_detail_context_collects_source_references_when_available():
    history_rows = [
        {
            "emp_id": "E1",
            "work_date": "2026-04-01",
            "uph": 81,
            "units": 405,
            "hours_worked": 5,
            "source_file": "batch-a.csv",
            "import_job_id": "import-123",
        },
        {
            "emp_id": "E1",
            "work_date": "2026-04-02",
            "uph": 0,
            "source_file": "batch-a.csv",
            "import_job_id": "import-123",
        },
    ]

    ctx = build_employee_detail_context(emp_id="E1", goal_row={}, history_rows=history_rows, lookback_days=5, comparison_days=2)

    assert len(ctx["source_references"]) == 2
    assert ctx["source_references"][0]["Source File"] == "batch-a.csv"
