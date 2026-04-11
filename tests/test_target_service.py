from goals import build_goal_status
from services.target_service import (
    build_comparison_descriptions,
    list_configurable_processes,
    normalize_process_name,
    resolve_target_context,
)


def test_normalize_process_name_maps_common_aliases_to_default_processes():
    assert normalize_process_name("pack") == "Packing"
    assert normalize_process_name("receiving dock") == "Receiving"
    assert normalize_process_name("put-away") == "Putaway"


def test_resolve_target_context_honors_override_then_process_then_default():
    goals_data = {
        "default_target_uph": 88,
        "process_targets": {"Packing": 95},
        "employee_target_overrides": {"E1": {"target_uph": 101, "process_name": "Packing"}},
        "configured_processes": [],
        "dept_targets": {},
        "flagged_employees": {},
    }

    override = resolve_target_context(employee_id="E1", process_name="pack", goals_data=goals_data)
    process = resolve_target_context(employee_id="E2", process_name="Packing", goals_data=goals_data)
    fallback = resolve_target_context(employee_id="E3", process_name="Sorting", goals_data=goals_data)

    assert override["target_uph"] == 101.0
    assert override["target_source"] == "employee_override"
    assert process["target_uph"] == 95.0
    assert process["target_source"] == "process_target"
    assert fallback["target_uph"] == 88.0
    assert fallback["target_source"] == "default_target"


def test_list_configurable_processes_includes_defaults_and_custom_entries():
    names = list_configurable_processes({"configured_processes": [{"name": "Cycle Count", "aliases": ["counting"]}]})

    assert "Picking" in names
    assert "Packing" in names
    assert "Cycle Count" in names


def test_build_goal_status_uses_resolved_target_context(monkeypatch):
    monkeypatch.setattr(
        "goals.load_goals",
        lambda tenant_id="": {
            "default_target_uph": 90,
            "dept_targets": {"Packing": 95},
            "process_targets": {"Packing": 95},
            "employee_target_overrides": {"E1": {"target_uph": 100, "process_name": "Packing"}},
            "configured_processes": [],
            "flagged_employees": {},
        },
    )

    rows = [{"EmployeeID": "E1", "Department": "pack", "Average UPH": 94}]
    out = build_goal_status(rows, {"pack": 95}, {}, tenant_id="tenant-a")

    assert out[0]["Target UPH"] == 100.0
    assert out[0]["Target Source"] == "employee override"
    assert out[0]["Resolved Process"] == "Packing"
    assert out[0]["goal_status"] == "below_goal"


def test_build_comparison_descriptions_returns_target_recent_performance_and_average():
    descriptions = build_comparison_descriptions(
        target_context={"target_uph": 95, "target_source_label": "process target", "process_name": "Packing"},
        comparison_days=5,
        recent_avg=91,
        prior_avg=88,
    )

    assert descriptions["compared_to_target"].startswith("Compared to target")
    assert descriptions["compared_to_recent_performance"].startswith("Compared to recent performance")
    assert descriptions["compared_to_recent_average"].startswith("Compared to recent average")