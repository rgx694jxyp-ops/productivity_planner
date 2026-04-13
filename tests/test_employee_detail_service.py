from services.employee_detail_service import build_employee_detail_context
from services.display_signal_factory import build_display_signal_from_employee_detail_context


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

    assert ctx["current_state"] == "Higher than recent pace"
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


def test_build_employee_detail_context_prefers_snapshot_signal_metadata_when_prior_window_missing():
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-04-19", "uph": 41.8, "units": 209, "hours_worked": 5},
    ]
    goal_row = {
        "EmployeeID": "E1",
        "Employee": "Devon Tran",
        "Department": "Picking",
        "goal_status": "below_goal",
        "trend": "declining",
        "trend_explanation": "Recent output is below the comparison range.",
        "Average UPH": 41.8,
        "Target UPH": 50,
        "confidence_label": "Medium",
        "data_completeness_status": "partial",
        "repeat_count": 2,
    }

    ctx = build_employee_detail_context(emp_id="E1", goal_row=goal_row, history_rows=history_rows, lookback_days=14, comparison_days=5)

    assert ctx["low_data_state"] is False
    assert ctx["signal_summary"]["trend_state"] == "declining"
    assert ctx["signal_summary"]["confidence_label"] == "Medium"
    assert ctx["pattern_history"]["repeat_count"] == 2


def test_employee_detail_display_signal_uses_target_baseline_when_prior_window_missing():
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-04-19", "uph": 41.8, "units": 209, "hours_worked": 5},
    ]
    goal_row = {
        "EmployeeID": "E1",
        "Employee": "Devon Tran",
        "Department": "Picking",
        "goal_status": "below_goal",
        "trend": "declining",
        "Average UPH": 41.8,
        "Target UPH": 50,
        "confidence_label": "Medium",
        "data_completeness_status": "partial",
        "repeat_count": 2,
    }

    ctx = build_employee_detail_context(emp_id="E1", goal_row=goal_row, history_rows=history_rows, lookback_days=14, comparison_days=5)
    signal = build_display_signal_from_employee_detail_context(
        detail_context=ctx,
        employee_name="Devon Tran",
        process="Picking",
    )

    assert signal.signal_label.value == "lower_than_recent_pace"
    assert signal.comparison_value == 50.0
    assert signal.confidence.value == "medium"
    assert signal.primary_label == "Lower than recent pace"


def test_employee_detail_context_exposes_employee_id_for_downstream_identity():
    """Protects against name-based fallback IDs that break cross-surface signal identity."""
    history_rows = [
        {"emp_id": "E55", "work_date": "2026-04-19", "uph": 44.2, "units": 221, "hours_worked": 5},
    ]
    goal_row = {
        "EmployeeID": "E55",
        "Employee": "Jordan Kim",
        "Department": "Packing",
        "trend": "declining",
        "Average UPH": 44.2,
        "Target UPH": 50,
        "confidence_label": "Medium",
    }

    ctx = build_employee_detail_context(
        emp_id="E55",
        goal_row=goal_row,
        history_rows=history_rows,
        lookback_days=14,
        comparison_days=5,
    )

    assert ctx.get("employee_id") == "E55"
