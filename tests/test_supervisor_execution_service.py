from datetime import date

from services.supervisor_execution_service import build_today_screen_payload


def test_generated_action_created_for_unhandled_below_goal_streak():
    gs = [
        {
            "EmployeeID": "E1",
            "Employee Name": "Alex",
            "Department": "Pack",
            "goal_status": "below_goal",
            "Average UPH": 80,
            "Target UPH": 100,
        }
    ]
    history = [
        {"EmployeeID": "E1", "Date": "2026-04-01", "UPH": 90},
        {"EmployeeID": "E1", "Date": "2026-04-02", "UPH": 85},
        {"EmployeeID": "E1", "Date": "2026-04-03", "UPH": 82},
        {"EmployeeID": "E1", "Date": "2026-04-04", "UPH": 79},
    ]

    payload = build_today_screen_payload(gs, history, [], today=date(2026, 4, 4))

    assert payload["summary"]["open_actions"] == 1
    assert payload["action_queue"][0]["source"] == "generated"
    assert "no action logged" in payload["action_queue"][0]["reason"].lower()



def test_overdue_action_is_prioritized_and_counted():
    actions = [
        {
            "id": 1,
            "emp_id": "E1",
            "employee_name": "Alex",
            "department": "Pack",
            "reason": "Follow up on prior coaching",
            "status": "in_progress",
            "due_date": "2026-04-01",
            "created_at": "2026-03-30T00:00:00Z",
        }
    ]

    payload = build_today_screen_payload([], [], actions, today=date(2026, 4, 4))

    assert payload["summary"]["overdue"] == 1
    assert payload["action_queue"][0]["status"] == "Overdue"



def test_repeat_offenders_detect_multiple_failed_cycles():
    actions = [
        {
            "id": 1,
            "emp_id": "E1",
            "employee_name": "Alex",
            "department": "Pack",
            "status": "closed",
            "outcome": "no_change",
            "created_at": "2026-03-01T00:00:00Z",
        },
        {
            "id": 2,
            "emp_id": "E1",
            "employee_name": "Alex",
            "department": "Pack",
            "status": "closed",
            "outcome": "worse",
            "created_at": "2026-03-10T00:00:00Z",
        },
    ]
    gs = [
        {
            "EmployeeID": "E1",
            "Employee Name": "Alex",
            "Department": "Pack",
            "Average UPH": 80,
            "Target UPH": 100,
        }
    ]

    payload = build_today_screen_payload(gs, [], actions, today=date(2026, 4, 4))

    assert len(payload["repeat_offenders"]) == 1
    assert payload["repeat_offenders"][0]["failed_cycles"] == 2



def test_ignored_high_performer_detected_without_recent_development_action():
    gs = [
        {
            "EmployeeID": "E9",
            "Employee Name": "Taylor",
            "Department": "Pack",
            "goal_status": "on_goal",
            "Average UPH": 120,
            "Target UPH": 100,
        }
    ]

    payload = build_today_screen_payload(gs, [], [], today=date(2026, 4, 4))

    assert len(payload["ignored_high_performers"]) == 1
    assert payload["ignored_high_performers"][0]["employee_name"] == "Taylor"
