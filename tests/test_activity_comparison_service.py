from services.activity_comparison_service import compare_logged_activity, list_recent_activity_comparisons, summarize_activity_comparisons


def test_compare_logged_activity_detects_improvement_against_prior_period():
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-04-01", "uph": 80},
        {"emp_id": "E1", "work_date": "2026-04-02", "uph": 82},
        {"emp_id": "E1", "work_date": "2026-04-04", "uph": 92},
        {"emp_id": "E1", "work_date": "2026-04-05", "uph": 94},
    ]
    activity_row = {
        "employee_id": "E1",
        "event_type": "follow_through_logged",
        "event_at": "2026-04-03T08:00:00Z",
        "details": "Checked lane and reset start-up sequence.",
    }

    comparison = compare_logged_activity(activity_row, history_rows=history_rows, expected_uph=90.0)

    assert comparison["outcome_key"] == "improved_compared_to_prior_period"
    assert comparison["before_avg_uph"] == 81.0
    assert comparison["after_avg_uph"] == 93.0
    assert comparison["comparison_breakdown"]["compared_to_target"].startswith("Compared to target")
    assert comparison["comparison_breakdown"]["compared_to_recent_performance"].startswith("Compared to recent performance")
    assert comparison["comparison_breakdown"]["compared_to_recent_average"].startswith("Compared to recent average")
    assert "Log date:" in comparison["time_context"]
    assert "Data completeness:" in comparison["data_completeness_note"]


def test_compare_logged_activity_marks_still_below_expected_when_post_period_under_target():
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-04-01", "uph": 80},
        {"emp_id": "E1", "work_date": "2026-04-02", "uph": 82},
        {"emp_id": "E1", "work_date": "2026-04-04", "uph": 84},
        {"emp_id": "E1", "work_date": "2026-04-05", "uph": 85},
    ]
    activity_row = {"employee_id": "E1", "event_type": "coached", "event_at": "2026-04-03T08:00:00Z"}

    comparison = compare_logged_activity(activity_row, history_rows=history_rows, expected_uph=95.0)

    assert comparison["outcome_key"] == "still_below_expected"


def test_compare_logged_activity_returns_no_clear_change_with_insufficient_data():
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-04-01", "uph": 80},
        {"emp_id": "E1", "work_date": "2026-04-04", "uph": 84},
    ]
    activity_row = {"employee_id": "E1", "event_type": "coached", "event_at": "2026-04-03T08:00:00Z"}

    comparison = compare_logged_activity(activity_row, history_rows=history_rows, expected_uph=95.0)

    assert comparison["outcome_key"] == "no_clear_change_yet"
    assert comparison["confidence_label"] == "Low"
    assert comparison["is_weak_signal"] is True


def test_compare_logged_activity_includes_workload_context_when_units_and_hours_present():
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-04-01", "uph": 80, "units": 400, "hours_worked": 5},
        {"emp_id": "E1", "work_date": "2026-04-02", "uph": 82, "units": 410, "hours_worked": 5},
        {"emp_id": "E1", "work_date": "2026-04-04", "uph": 92, "units": 460, "hours_worked": 5},
        {"emp_id": "E1", "work_date": "2026-04-05", "uph": 94, "units": 470, "hours_worked": 5},
    ]
    activity_row = {"employee_id": "E1", "event_type": "coached", "event_at": "2026-04-03T08:00:00Z"}

    comparison = compare_logged_activity(activity_row, history_rows=history_rows, expected_uph=90.0)

    assert "Workload context: before" in comparison["workload_context"]


def test_list_recent_activity_comparisons_can_limit_to_latest_per_employee(monkeypatch):
    monkeypatch.setattr(
        "services.activity_comparison_service.action_events_repo.list_action_events",
        lambda **kwargs: [
            {"employee_id": "E1", "event_type": "follow_through_logged", "event_at": "2026-04-05T08:00:00Z", "details": "Recent"},
            {"employee_id": "E1", "event_type": "follow_through_logged", "event_at": "2026-04-03T08:00:00Z", "details": "Older"},
            {"employee_id": "E2", "event_type": "follow_through_logged", "event_at": "2026-04-05T09:00:00Z", "details": "Recent two"},
        ],
    )
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-03-29", "uph": 80},
        {"emp_id": "E1", "work_date": "2026-03-30", "uph": 82},
        {"emp_id": "E1", "work_date": "2026-04-06", "uph": 90},
        {"emp_id": "E1", "work_date": "2026-04-07", "uph": 92},
        {"emp_id": "E2", "work_date": "2026-03-29", "uph": 70},
        {"emp_id": "E2", "work_date": "2026-03-30", "uph": 72},
        {"emp_id": "E2", "work_date": "2026-04-06", "uph": 75},
        {"emp_id": "E2", "work_date": "2026-04-07", "uph": 74},
    ]

    comparisons = list_recent_activity_comparisons(
        tenant_id="tenant-a",
        history_rows=history_rows,
        expected_uph_by_employee={"E1": 88.0, "E2": 78.0},
        per_employee_latest_only=True,
        limit=5,
    )

    assert len(comparisons) == 2
    assert {row["employee_id"] for row in comparisons} == {"E1", "E2"}


def test_list_recent_activity_comparisons_can_exclude_weak_signals(monkeypatch):
    monkeypatch.setattr(
        "services.activity_comparison_service.action_events_repo.list_action_events",
        lambda **kwargs: [
            {"employee_id": "E1", "event_type": "follow_through_logged", "event_at": "2026-04-03T08:00:00Z"},
            {"employee_id": "E2", "event_type": "follow_through_logged", "event_at": "2026-04-03T09:00:00Z"},
        ],
    )
    history_rows = [
        {"emp_id": "E1", "work_date": "2026-03-27", "uph": 79},
        {"emp_id": "E1", "work_date": "2026-03-28", "uph": 80},
        {"emp_id": "E1", "work_date": "2026-04-01", "uph": 80},
        {"emp_id": "E1", "work_date": "2026-04-01", "uph": 80},
        {"emp_id": "E1", "work_date": "2026-04-02", "uph": 82},
        {"emp_id": "E1", "work_date": "2026-04-04", "uph": 90},
        {"emp_id": "E1", "work_date": "2026-04-05", "uph": 91},
        {"emp_id": "E1", "work_date": "2026-04-06", "uph": 92},
        {"emp_id": "E2", "work_date": "2026-04-01", "uph": 70},
        {"emp_id": "E2", "work_date": "2026-04-04", "uph": 71},
    ]

    comparisons = list_recent_activity_comparisons(
        tenant_id="tenant-a",
        history_rows=history_rows,
        include_weak_signals=False,
        limit=5,
    )

    assert len(comparisons) == 1
    assert comparisons[0]["employee_id"] == "E1"


def test_summarize_activity_comparisons_counts_outcomes():
    summary = summarize_activity_comparisons(
        [
            {"outcome_key": "improved_compared_to_prior_period"},
            {"outcome_key": "still_below_expected"},
            {"outcome_key": "no_clear_change_yet"},
            {"outcome_key": "no_clear_change_yet"},
        ]
    )

    assert summary["improved_count"] == 1
    assert summary["still_below_expected_count"] == 1
    assert summary["no_clear_change_count"] == 2