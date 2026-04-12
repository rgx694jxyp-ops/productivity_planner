from services.daily_snapshot_service import (
    build_daily_employee_snapshots,
    get_latest_snapshot_goal_status,
    recompute_daily_employee_snapshots,
    snapshots_to_goal_status_rows,
    snapshots_to_history_rows,
)


def test_build_daily_employee_snapshots_generates_expected_fields(monkeypatch):
    monkeypatch.setattr(
        "services.daily_snapshot_service.resolve_target_context",
        lambda **kwargs: {"target_uph": 95.0, "target_source_label": "process target", "process_name": "Packing"},
    )
    activity_rows = [
        {"employee_id": "E1", "activity_date": "2026-04-01", "process_name": "pack", "units": 400, "hours": 5, "productivity_value": 80, "data_quality_status": "valid"},
        {"employee_id": "E1", "activity_date": "2026-04-02", "process_name": "Packing", "units": 410, "hours": 5, "productivity_value": 82, "data_quality_status": "valid"},
        {"employee_id": "E1", "activity_date": "2026-04-03", "process_name": "Packing", "units": 470, "hours": 5, "productivity_value": 94, "data_quality_status": "valid"},
    ]

    snapshots = build_daily_employee_snapshots(activity_records=activity_rows, tenant_id="tenant-a", lookback_days=5, comparison_days=2)

    assert len(snapshots) == 3
    latest = snapshots[-1]
    assert latest["employee_id"] == "E1"
    assert latest["process_name"] == "Packing"
    assert latest["expected_uph"] == 95.0
    assert latest["trend_state"] in {"improving", "stable", "insufficient_data", "below_expected", "declining", "inconsistent"}
    assert latest["confidence_label"] in {"High", "Medium", "Low"}
    assert "included day(s)" in latest["data_completeness_note"].lower()


def test_snapshot_adapters_produce_goal_status_and_history_rows(monkeypatch):
    monkeypatch.setattr(
        "services.daily_snapshot_service.get_employees",
        lambda: [{"emp_id": "E1", "name": "Alex", "department": "Packing"}],
    )
    snapshot_rows = [
        {
            "snapshot_date": "2026-04-03",
            "employee_id": "E1",
            "process_name": "Packing",
            "performance_uph": 94,
            "recent_average_uph": 90,
            "prior_average_uph": 82,
            "expected_uph": 95,
            "goal_status": "below_goal",
            "trend_state": "improving",
            "recent_trend_history": ["down", "up"],
            "recent_goal_status_history": ["below_goal", "below_goal"],
            "included_day_count": 3,
            "workload_units": 470,
            "workload_hours": 5,
            "confidence_label": "Medium",
            "data_completeness_note": "Partial data",
            "repeat_count": 2,
            "pattern_marker": "similar_pattern",
            "raw_metrics": {"target_context": {"target_source_label": "process target"}},
        }
    ]

    goal_status = snapshots_to_goal_status_rows(snapshot_rows)
    history_rows = snapshots_to_history_rows(snapshot_rows)

    assert goal_status[0]["Employee Name"] == "Alex"
    assert goal_status[0]["Average UPH"] == 90
    assert goal_status[0]["Target UPH"] == 95
    assert goal_status[0]["recent_average_uph"] == 90
    assert goal_status[0]["prior_average_uph"] == 82
    assert goal_status[0]["expected_uph"] == 95
    assert goal_status[0]["included_day_count"] == 3
    assert goal_status[0]["data_completeness_status"] == "limited"
    assert history_rows[0]["work_date"] == "2026-04-03"
    assert history_rows[0]["uph"] == 94


def test_recompute_daily_employee_snapshots_is_idempotent(monkeypatch):
    deleted = []
    upserted = []
    monkeypatch.setattr(
        "services.daily_snapshot_service.get_recent_activity_records",
        lambda **kwargs: [
            {"employee_id": "E1", "activity_date": "2026-04-01", "process_name": "Packing", "units": 400, "hours": 5, "productivity_value": 80, "data_quality_status": "valid"},
            {"employee_id": "E1", "activity_date": "2026-04-02", "process_name": "Packing", "units": 410, "hours": 5, "productivity_value": 82, "data_quality_status": "valid"},
        ],
    )
    monkeypatch.setattr(
        "services.daily_snapshot_service.resolve_target_context",
        lambda **kwargs: {"target_uph": 90.0, "target_source_label": "default target", "process_name": "Packing"},
    )
    monkeypatch.setattr(
        "services.daily_snapshot_service.daily_employee_snapshots_repo.delete_daily_employee_snapshots",
        lambda **kwargs: deleted.append(kwargs),
    )
    monkeypatch.setattr(
        "services.daily_snapshot_service.daily_employee_snapshots_repo.batch_upsert_daily_employee_snapshots",
        lambda rows: upserted.append(rows),
    )

    first = recompute_daily_employee_snapshots(tenant_id="tenant-a", from_date="2026-04-01", to_date="2026-04-02")
    second = recompute_daily_employee_snapshots(tenant_id="tenant-a", from_date="2026-04-01", to_date="2026-04-02")

    assert first["inserted"] == second["inserted"]
    assert len(deleted) == 2
    assert len(upserted) == 2
    assert upserted[0] == upserted[1]


def test_get_latest_snapshot_goal_status_rebuilds_when_missing(monkeypatch):
    calls = {"list": 0}
    monkeypatch.setattr(
        "services.daily_snapshot_service.get_employees",
        lambda: [{"emp_id": "E1", "name": "Alex", "department": "Packing"}],
    )

    def _list_snapshots(**kwargs):
        calls["list"] += 1
        if calls["list"] == 1:
            return []
        return [
            {
                "snapshot_date": "2026-04-03",
                "employee_id": "E1",
                "process_name": "Packing",
                "performance_uph": 94,
                "recent_average_uph": 90,
                "prior_average_uph": 82,
                "expected_uph": 95,
                "goal_status": "below_goal",
                "trend_state": "improving",
                "recent_trend_history": ["down", "up"],
                "recent_goal_status_history": ["below_goal", "below_goal"],
                "included_day_count": 3,
                "workload_units": 470,
                "workload_hours": 5,
                "confidence_label": "Medium",
                "data_completeness_note": "Partial data",
                "repeat_count": 2,
                "pattern_marker": "similar_pattern",
                "raw_metrics": {"target_context": {"target_source_label": "process target"}},
            }
        ]

    monkeypatch.setattr("services.daily_snapshot_service.daily_employee_snapshots_repo.list_daily_employee_snapshots", _list_snapshots)
    monkeypatch.setattr("services.daily_snapshot_service.recompute_daily_employee_snapshots", lambda **kwargs: {"inserted": 1})

    goal_status, history_rows, snapshot_date = get_latest_snapshot_goal_status(tenant_id="tenant-a")

    assert snapshot_date == "2026-04-03"
    assert goal_status[0]["EmployeeID"] == "E1"
    assert history_rows[0]["emp_id"] == "E1"