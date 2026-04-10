"""Generate a reusable demo dataset for the supervisor productivity app."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "demo_data"
TENANT_ID = "demo-tenant"
START_DATE = date(2026, 3, 22)
HISTORY_DAYS = 18


@dataclass(frozen=True)
class Employee:
    employee_id: str
    employee_name: str
    department: str
    shift: str


EMPLOYEES: list[Employee] = [
    # ── Picking – Day ────────────────────────────────────────────────────
    Employee("EMP001", "Marcus Webb",     "Picking",   "Day"),
    Employee("EMP007", "Devon Tran",      "Picking",   "Day"),    # due-today follow-up
    Employee("EMP013", "Brianna Cole",    "Picking",   "Day"),
    Employee("EMP019", "Nate Okafor",     "Picking",   "Day"),
    Employee("EMP025", "Lindsey Marsh",   "Picking",   "Day"),
    Employee("EMP031", "Terrell Boyd",    "Picking",   "Day"),
    # ── Picking – Night ───────────────────────────────────────────────────
    Employee("EMP004", "Priya Kapoor",    "Picking",   "Night"),
    Employee("EMP010", "Will Nguyen",     "Picking",   "Night"),
    Employee("EMP016", "Cassie Ruiz",     "Picking",   "Night"),
    Employee("EMP022", "Damon Schultz",   "Picking",   "Night"),
    Employee("EMP028", "Aisha Grant",     "Picking",   "Night"),
    # ── Packing – Day ────────────────────────────────────────────────────
    Employee("EMP002", "Tina Holt",       "Packing",   "Day"),
    Employee("EMP005", "Sam Rivera",      "Packing",   "Day"),    # resolved win
    Employee("EMP011", "Avery Stone",     "Packing",   "Day"),    # recognition
    Employee("EMP017", "Greg Dominguez",  "Packing",   "Day"),
    Employee("EMP023", "Renae Howard",    "Packing",   "Day"),
    Employee("EMP029", "Brent Yates",     "Packing",   "Day"),
    # ── Packing – Night ───────────────────────────────────────────────────
    Employee("EMP008", "Dara Osei",       "Packing",   "Night"),
    Employee("EMP014", "Riley Chen",      "Packing",   "Night"),  # overdue follow-up
    Employee("EMP020", "Keisha Norris",   "Packing",   "Night"),
    Employee("EMP026", "Victor Salazar",  "Packing",   "Night"),  # recognition
    Employee("EMP032", "Dana Park",       "Packing",   "Night"),
    # ── Receiving – Day ──────────────────────────────────────────────────
    Employee("EMP003", "Jamie Carter",    "Receiving", "Day"),    # overdue follow-up
    Employee("EMP009", "Casey Patel",     "Receiving", "Day"),    # repeat no-improvement
    Employee("EMP015", "Yolanda Ferris",  "Receiving", "Day"),
    Employee("EMP021", "Marcus Brooks",   "Receiving", "Day"),    # due-today follow-up
    Employee("EMP027", "Elena Voss",      "Receiving", "Day"),
    # ── Receiving – Night ─────────────────────────────────────────────────
    Employee("EMP006", "Troy Mcallister", "Receiving", "Night"),
    Employee("EMP012", "Simone Adeyemi",  "Receiving", "Night"),
    Employee("EMP018", "Jordan Kim",      "Receiving", "Night"),  # repeat no-improvement (escalated)
    Employee("EMP024", "Rodney Hawkins",  "Receiving", "Night"),
    Employee("EMP030", "Fatima Oduya",    "Receiving", "Night"),
]

DEPARTMENT_BASELINE = {"Picking": 51.0, "Packing": 46.0, "Receiving": 40.0}
SHIFT_HOURS = {"Day": 8.0, "Night": 7.5}

# fmt: off
SCENARIO_SERIES: dict[str, list[float]] = {
    # EMP003 – Jamie Carter – overdue follow-up: slow steady decline despite target of 40
    "EMP003": [41, 40, 39, 38, 37, 36, 35, 34, 33, 32, 32, 31, 30, 30, 29, 29, 28, 28],
    # EMP014 – Riley Chen – overdue follow-up: started near target, drifted below 40 UPH
    "EMP014": [47, 46, 46, 45, 44, 43, 43, 42, 41, 40, 39, 38, 38, 37, 37, 36, 36, 35],
    # EMP007 – Devon Tran – due-today: dipped, partial rebound after coaching, not there yet
    "EMP007": [50, 49, 47, 45, 43, 41, 40, 40, 41, 42, 43, 43, 44, 44, 44, 45, 45, 46],
    # EMP021 – Marcus Brooks – due-today: flat underperformance, staging blocker suspected
    "EMP021": [39, 38, 38, 37, 37, 36, 36, 36, 35, 35, 36, 36, 36, 37, 37, 37, 38, 38],
    # EMP009 – Casey Patel – repeat no-improvement: coached twice, still falling
    "EMP009": [37, 36, 35, 35, 34, 33, 33, 32, 32, 31, 31, 30, 30, 29, 29, 29, 28, 28],
    # EMP018 – Jordan Kim – repeat no-improvement (escalated): coached three times, now escalated
    "EMP018": [38, 37, 36, 35, 35, 34, 33, 33, 32, 32, 32, 31, 31, 31, 31, 31, 30, 30],
    # EMP011 – Avery Stone – recognition: consistent top performer, no recognition logged
    "EMP011": [54, 55, 56, 57, 58, 59, 59, 60, 61, 61, 61, 62, 62, 62, 63, 63, 64, 64],
    # EMP026 – Victor Salazar – recognition: steadily increasing, development opportunity
    "EMP026": [52, 53, 53, 54, 55, 56, 56, 57, 57, 58, 59, 59, 60, 60, 61, 61, 62, 63],
    # EMP005 – Sam Rivera – resolved win: dipped, coached, recovered above baseline
    "EMP005": [40, 38, 36, 35, 34, 35, 37, 39, 41, 43, 45, 46, 47, 48, 48, 49, 49, 50],
}
# fmt: on


def iso_z(value: str) -> str:
    return datetime.fromisoformat(value).isoformat() + "Z"


def build_history_rows() -> list[dict]:
    rows: list[dict] = []
    for index, employee in enumerate(EMPLOYEES):
        for day_index in range(HISTORY_DAYS):
            work_date = START_DATE + timedelta(days=day_index)
            if employee.employee_id in SCENARIO_SERIES:
                uph = SCENARIO_SERIES[employee.employee_id][day_index]
            else:
                # Vary each non-scenario employee slightly but realistically:
                # offset = small per-employee constant offset from baseline
                # ripple = slow multi-day fatigue/recovery wave
                offset = ((index * 7 + 3) % 11) - 5  # range -5..+5
                ripple = round(1.4 * (((day_index + index * 3) % 9) - 4) / 4, 1)
                uph = round(DEPARTMENT_BASELINE[employee.department] + offset * 0.4 + ripple, 2)
            hours = SHIFT_HOURS[employee.shift]
            units = round(uph * hours)
            rows.append(
                {
                    "Date": work_date.isoformat(),
                    "Department": employee.department,
                    "EmployeeID": employee.employee_id,
                    "EmployeeName": employee.employee_name,
                    "Shift": employee.shift,
                    "UPH": f"{uph:.2f}",
                    "Units": units,
                    "HoursWorked": f"{hours:.2f}",
                }
            )
    return rows


def build_actions() -> list[dict]:
    return [
        {
            "id": 1001,
            "tenant_id": TENANT_ID,
            "employee_id": "EMP003",
            "employee_name": "Jamie Carter",
            "department": "Receiving",
            "issue_type": "follow_up_due",
            "trigger_source": "today",
            "trigger_summary": "Missed last 4 receiving targets after coaching",
            "status": "overdue",
            "priority": "high",
            "action_type": "coaching_followup",
            "success_metric": "Back to 40+ UPH for 3 straight shifts",
            "note": "Initial coaching completed; follow-up slipped.",
            "baseline_uph": 40.0,
            "latest_uph": 30.0,
            "improvement_delta": -4.0,
            "resolution_type": "",
            "resolution_note": "",
            "follow_up_due_at": "2026-04-05T09:00:00Z",
            "last_event_at": "2026-04-05T09:00:00Z",
            "resolved_at": None,
            "escalated_at": None,
            "created_at": "2026-03-31T14:00:00Z",
            "created_by": "demo.supervisor@example.com",
        },
        {
            "id": 1002,
            "tenant_id": TENANT_ID,
            "employee_id": "EMP014",
            "employee_name": "Riley Chen",
            "department": "Packing",
            "issue_type": "overdue_unresolved",
            "trigger_source": "today",
            "trigger_summary": "Packing accuracy coaching still needs a follow-up",
            "status": "overdue",
            "priority": "high",
            "action_type": "process_retraining",
            "success_metric": "Hold 45+ UPH with zero pack errors",
            "note": "Supervisor wanted a quick line-side reset, but it never got logged.",
            "baseline_uph": 45.0,
            "latest_uph": 38.0,
            "improvement_delta": -3.0,
            "resolution_type": "",
            "resolution_note": "",
            "follow_up_due_at": "2026-04-06T10:00:00Z",
            "last_event_at": "2026-04-06T10:00:00Z",
            "resolved_at": None,
            "escalated_at": None,
            "created_at": "2026-04-01T16:00:00Z",
            "created_by": "demo.supervisor@example.com",
        },
        {
            "id": 1003,
            "tenant_id": TENANT_ID,
            "employee_id": "EMP007",
            "employee_name": "Devon Tran",
            "department": "Picking",
            "issue_type": "follow_up_due",
            "trigger_source": "today",
            "trigger_summary": "New picker improved slightly and needs today follow-up",
            "status": "follow_up_due",
            "priority": "medium",
            "action_type": "coaching_followup",
            "success_metric": "Reach 48+ UPH before end of week",
            "note": "Coach completed on ladder path and scan pace.",
            "baseline_uph": 48.0,
            "latest_uph": 44.0,
            "improvement_delta": 2.0,
            "resolution_type": "",
            "resolution_note": "",
            "follow_up_due_at": "2026-04-08T13:00:00Z",
            "last_event_at": "2026-04-07T18:00:00Z",
            "resolved_at": None,
            "escalated_at": None,
            "created_at": "2026-04-03T15:00:00Z",
            "created_by": "demo.supervisor@example.com",
        },
        {
            "id": 1004,
            "tenant_id": TENANT_ID,
            "employee_id": "EMP021",
            "employee_name": "Marcus Brooks",
            "department": "Receiving",
            "issue_type": "follow_up_due",
            "trigger_source": "today",
            "trigger_summary": "Dock unload pace needs a same-day check-in",
            "status": "follow_up_due",
            "priority": "medium",
            "action_type": "workstation_check",
            "success_metric": "Stabilize at 39+ UPH with clean unload flow",
            "note": "Potential blocker is pallet staging, not effort.",
            "baseline_uph": 39.0,
            "latest_uph": 38.0,
            "improvement_delta": 1.0,
            "resolution_type": "",
            "resolution_note": "",
            "follow_up_due_at": "2026-04-08T15:00:00Z",
            "last_event_at": "2026-04-07T17:30:00Z",
            "resolved_at": None,
            "escalated_at": None,
            "created_at": "2026-04-04T14:00:00Z",
            "created_by": "demo.supervisor@example.com",
        },
        {
            "id": 1005,
            "tenant_id": TENANT_ID,
            "employee_id": "EMP009",
            "employee_name": "Casey Patel",
            "department": "Receiving",
            "issue_type": "repeat_no_improvement",
            "trigger_source": "today",
            "trigger_summary": "Three coaching cycles with no measurable improvement",
            "status": "in_progress",
            "priority": "high",
            "action_type": "escalate",
            "success_metric": "Decide whether to escalate support or move role",
            "note": "Repeated coaching has not changed output.",
            "baseline_uph": 39.0,
            "latest_uph": 30.0,
            "improvement_delta": -2.0,
            "resolution_type": "",
            "resolution_note": "",
            "follow_up_due_at": "2026-04-10T12:00:00Z",
            "last_event_at": "2026-04-07T16:00:00Z",
            "resolved_at": None,
            "escalated_at": None,
            "created_at": "2026-03-21T13:00:00Z",
            "created_by": "demo.supervisor@example.com",
        },
        {
            "id": 1006,
            "tenant_id": TENANT_ID,
            "employee_id": "EMP018",
            "employee_name": "Jordan Kim",
            "department": "Receiving",
            "issue_type": "repeat_no_improvement",
            "trigger_source": "today",
            "trigger_summary": "Two follow-ups logged worse after coaching",
            "status": "escalated",
            "priority": "high",
            "action_type": "escalate",
            "success_metric": "Move to formal support plan or role reset",
            "note": "Pattern says this is no longer a normal coaching item.",
            "baseline_uph": 38.0,
            "latest_uph": 32.0,
            "improvement_delta": -1.0,
            "resolution_type": "",
            "resolution_note": "",
            "follow_up_due_at": "2026-04-09T11:00:00Z",
            "last_event_at": "2026-04-07T15:30:00Z",
            "resolved_at": None,
            "escalated_at": "2026-04-07T15:30:00Z",
            "created_at": "2026-03-20T11:00:00Z",
            "created_by": "demo.supervisor@example.com",
        },
        {
            "id": 1007,
            "tenant_id": TENANT_ID,
            "employee_id": "EMP011",
            "employee_name": "Avery Stone",
            "department": "Packing",
            "issue_type": "high_performer_ignored",
            "trigger_source": "today",
            "trigger_summary": "Top performer has not been recognized in two weeks",
            "status": "new",
            "priority": "low",
            "action_type": "development_touchpoint",
            "success_metric": "Recognize win and discuss cross-training interest",
            "note": "High pack rate, steady quality, no recognition logged.",
            "baseline_uph": 46.0,
            "latest_uph": 62.0,
            "improvement_delta": 6.0,
            "resolution_type": "",
            "resolution_note": "",
            "follow_up_due_at": "2026-04-11T09:00:00Z",
            "last_event_at": "2026-04-06T12:00:00Z",
            "resolved_at": None,
            "escalated_at": None,
            "created_at": "2026-04-06T12:00:00Z",
            "created_by": "demo.supervisor@example.com",
        },
        {
            "id": 1008,
            "tenant_id": TENANT_ID,
            "employee_id": "EMP026",
            "employee_name": "Victor Salazar",
            "department": "Packing",
            "issue_type": "high_performer_ignored",
            "trigger_source": "today",
            "trigger_summary": "Consistent high output with no development conversation logged",
            "status": "new",
            "priority": "low",
            "action_type": "development_touchpoint",
            "success_metric": "Recognize output and ask about stretch role interest",
            "note": "Great numbers, but manager has not closed the loop.",
            "baseline_uph": 46.0,
            "latest_uph": 62.0,
            "improvement_delta": 5.0,
            "resolution_type": "",
            "resolution_note": "",
            "follow_up_due_at": "2026-04-12T09:30:00Z",
            "last_event_at": "2026-04-06T13:00:00Z",
            "resolved_at": None,
            "escalated_at": None,
            "created_at": "2026-04-06T13:00:00Z",
            "created_by": "demo.supervisor@example.com",
        },
        {
            "id": 1009,
            "tenant_id": TENANT_ID,
            "employee_id": "EMP005",
            "employee_name": "Sam Rivera",
            "department": "Packing",
            "issue_type": "low_performance_unaddressed",
            "trigger_source": "today",
            "trigger_summary": "Recovered after reset and coaching",
            "status": "resolved",
            "priority": "medium",
            "action_type": "coaching_followup",
            "success_metric": "Hold 46+ UPH for a full week",
            "note": "Resolved win used to show completed loop.",
            "baseline_uph": 46.0,
            "latest_uph": 49.0,
            "improvement_delta": 6.0,
            "resolution_type": "improved",
            "resolution_note": "Recovered after station reset and side-by-side coaching.",
            "follow_up_due_at": "2026-04-03T14:00:00Z",
            "last_event_at": "2026-04-05T17:00:00Z",
            "resolved_at": "2026-04-05T17:00:00Z",
            "escalated_at": None,
            "created_at": "2026-03-30T15:00:00Z",
            "created_by": "demo.supervisor@example.com",
        },
    ]


def build_action_events() -> list[dict]:
    return [
        {"id": 5001, "tenant_id": TENANT_ID, "action_id": 1001, "employee_id": "EMP003", "event_type": "created", "event_at": "2026-03-31T14:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Created after 4 missed targets.", "outcome": "not_applicable", "next_follow_up_at": "2026-04-05T09:00:00Z"},
        {"id": 5002, "tenant_id": TENANT_ID, "action_id": 1001, "employee_id": "EMP003", "event_type": "coached", "event_at": "2026-04-01T15:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Reviewed unload flow and scan rhythm.", "outcome": "pending", "next_follow_up_at": "2026-04-05T09:00:00Z"},
        {"id": 5003, "tenant_id": TENANT_ID, "action_id": 1002, "employee_id": "EMP014", "event_type": "created", "event_at": "2026-04-01T16:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Packing accuracy issue reopened.", "outcome": "not_applicable", "next_follow_up_at": "2026-04-06T10:00:00Z"},
        {"id": 5004, "tenant_id": TENANT_ID, "action_id": 1002, "employee_id": "EMP014", "event_type": "follow_up_logged", "event_at": "2026-04-03T16:30:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Minor improvement, needs another check.", "outcome": "no_change", "next_follow_up_at": "2026-04-06T10:00:00Z"},
        {"id": 5005, "tenant_id": TENANT_ID, "action_id": 1003, "employee_id": "EMP007", "event_type": "created", "event_at": "2026-04-03T15:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "New picker support started.", "outcome": "not_applicable", "next_follow_up_at": "2026-04-08T13:00:00Z"},
        {"id": 5006, "tenant_id": TENANT_ID, "action_id": 1003, "employee_id": "EMP007", "event_type": "coached", "event_at": "2026-04-05T14:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Focused on path discipline and scan pacing.", "outcome": "pending", "next_follow_up_at": "2026-04-08T13:00:00Z"},
        {"id": 5007, "tenant_id": TENANT_ID, "action_id": 1004, "employee_id": "EMP021", "event_type": "created", "event_at": "2026-04-04T14:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Dock pace slipped after lane change.", "outcome": "not_applicable", "next_follow_up_at": "2026-04-08T15:00:00Z"},
        {"id": 5008, "tenant_id": TENANT_ID, "action_id": 1004, "employee_id": "EMP021", "event_type": "coached", "event_at": "2026-04-06T14:30:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Checked staging flow and radio handoff.", "outcome": "pending", "next_follow_up_at": "2026-04-08T15:00:00Z"},
        {"id": 5009, "tenant_id": TENANT_ID, "action_id": 1005, "employee_id": "EMP009", "event_type": "created", "event_at": "2026-03-28T13:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Started coaching cycle after low output streak.", "outcome": "not_applicable", "next_follow_up_at": "2026-04-01T12:00:00Z"},
        {"id": 5010, "tenant_id": TENANT_ID, "action_id": 1005, "employee_id": "EMP009", "event_type": "coached", "event_at": "2026-03-30T13:30:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Reviewed unload sequence.", "outcome": "pending", "next_follow_up_at": "2026-04-01T12:00:00Z"},
        {"id": 5011, "tenant_id": TENANT_ID, "action_id": 1005, "employee_id": "EMP009", "event_type": "follow_up_logged", "event_at": "2026-04-01T12:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "No change after first coaching.", "outcome": "no_change", "next_follow_up_at": "2026-04-04T12:00:00Z"},
        {"id": 5012, "tenant_id": TENANT_ID, "action_id": 1005, "employee_id": "EMP009", "event_type": "coached", "event_at": "2026-04-04T12:30:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Reinforced pace checkpoints.", "outcome": "pending", "next_follow_up_at": "2026-04-07T16:00:00Z"},
        {"id": 5013, "tenant_id": TENANT_ID, "action_id": 1005, "employee_id": "EMP009", "event_type": "follow_up_logged", "event_at": "2026-04-07T16:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Still no improvement.", "outcome": "worse", "next_follow_up_at": "2026-04-10T12:00:00Z"},
        {"id": 5014, "tenant_id": TENANT_ID, "action_id": 1006, "employee_id": "EMP018", "event_type": "created", "event_at": "2026-03-29T11:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Started action after repeated misses.", "outcome": "not_applicable", "next_follow_up_at": "2026-04-02T11:00:00Z"},
        {"id": 5015, "tenant_id": TENANT_ID, "action_id": 1006, "employee_id": "EMP018", "event_type": "coached", "event_at": "2026-03-31T11:30:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Worked standard work checklist.", "outcome": "pending", "next_follow_up_at": "2026-04-02T11:00:00Z"},
        {"id": 5016, "tenant_id": TENANT_ID, "action_id": 1006, "employee_id": "EMP018", "event_type": "follow_up_logged", "event_at": "2026-04-02T11:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "No measurable change.", "outcome": "no_change", "next_follow_up_at": "2026-04-05T11:00:00Z"},
        {"id": 5017, "tenant_id": TENANT_ID, "action_id": 1006, "employee_id": "EMP018", "event_type": "coached", "event_at": "2026-04-05T11:30:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Second pass on workstation layout.", "outcome": "pending", "next_follow_up_at": "2026-04-07T15:30:00Z"},
        {"id": 5018, "tenant_id": TENANT_ID, "action_id": 1006, "employee_id": "EMP018", "event_type": "follow_up_logged", "event_at": "2026-04-07T15:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Performance slipped again.", "outcome": "worse", "next_follow_up_at": "2026-04-09T11:00:00Z"},
        {"id": 5019, "tenant_id": TENANT_ID, "action_id": 1006, "employee_id": "EMP018", "event_type": "escalated", "event_at": "2026-04-07T15:30:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Escalated after repeated no-improvement cycle.", "outcome": "no_change", "next_follow_up_at": "2026-04-09T11:00:00Z"},
        {"id": 5020, "tenant_id": TENANT_ID, "action_id": 1007, "employee_id": "EMP011", "event_type": "created", "event_at": "2026-04-06T12:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Recognition opportunity created automatically.", "outcome": "not_applicable", "next_follow_up_at": "2026-04-11T09:00:00Z"},
        {"id": 5021, "tenant_id": TENANT_ID, "action_id": 1008, "employee_id": "EMP026", "event_type": "created", "event_at": "2026-04-06T13:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Development touchpoint opportunity created automatically.", "outcome": "not_applicable", "next_follow_up_at": "2026-04-12T09:30:00Z"},
        {"id": 5022, "tenant_id": TENANT_ID, "action_id": 1009, "employee_id": "EMP005", "event_type": "created", "event_at": "2026-03-30T15:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Low performance trend flagged.", "outcome": "not_applicable", "next_follow_up_at": "2026-04-03T14:00:00Z"},
        {"id": 5023, "tenant_id": TENANT_ID, "action_id": 1009, "employee_id": "EMP005", "event_type": "coached", "event_at": "2026-04-01T15:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Reset station and clarified pack sequence.", "outcome": "pending", "next_follow_up_at": "2026-04-03T14:00:00Z"},
        {"id": 5024, "tenant_id": TENANT_ID, "action_id": 1009, "employee_id": "EMP005", "event_type": "follow_up_logged", "event_at": "2026-04-03T14:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Recovered above target.", "outcome": "improved", "next_follow_up_at": "2026-04-05T17:00:00Z"},
        {"id": 5025, "tenant_id": TENANT_ID, "action_id": 1009, "employee_id": "EMP005", "event_type": "resolved", "event_at": "2026-04-05T17:00:00Z", "performed_by": "demo.supervisor@example.com", "notes": "Closed as resolved after sustained improvement.", "outcome": "improved", "next_follow_up_at": None},
    ]


def build_storytelling() -> dict:
    return {
        "dataset_summary": {
            "employees": len(EMPLOYEES),
            "history_days": HISTORY_DAYS,
            "history_start": START_DATE.isoformat(),
            "history_end": (START_DATE + timedelta(days=HISTORY_DAYS - 1)).isoformat(),
            "preseeded_actions": 9,
        },
        "scenario_index": [
            {"employee_id": "EMP003", "employee_name": "Jamie Carter", "scenario": "Overdue follow-up", "story": "Supervisor coached Jamie, promised a follow-up, and the due date passed. Today shows the missed loop immediately."},
            {"employee_id": "EMP014", "employee_name": "Riley Chen", "scenario": "Overdue follow-up", "story": "Riley had one follow-up logged, but the next check never happened. This demonstrates queue persistence and overdue prioritization."},
            {"employee_id": "EMP007", "employee_name": "Morgan Lee", "scenario": "Due today", "story": "Morgan is a same-day follow-up: some improvement, but still not at target. Good for showing a fast coaching loop."},
            {"employee_id": "EMP021", "employee_name": "Taylor Brooks", "scenario": "Due today", "story": "Taylor is blocked by process friction, not effort. This helps tell a story about diagnosing blockers, not just pushing harder."},
            {"employee_id": "EMP009", "employee_name": "Casey Patel", "scenario": "Repeat no-improvement", "story": "Casey has multiple no-change and worse outcomes. This is the escalation example because coaching alone is not working."},
            {"employee_id": "EMP018", "employee_name": "Jordan Kim", "scenario": "Repeat no-improvement", "story": "Jordan is already escalated after repeated misses. This shows the product captures management history, not just today's snapshot."},
            {"employee_id": "EMP011", "employee_name": "Avery Stone", "scenario": "Recognition opportunity", "story": "Avery is a top performer with no recognition touchpoint logged. This proves the product also reinforces wins."},
            {"employee_id": "EMP026", "employee_name": "Cameron Price", "scenario": "Recognition opportunity", "story": "Cameron is another high performer, useful for showing recognition can become a development conversation, not just a pat on the back."},
            {"employee_id": "EMP005", "employee_name": "Sam Rivera", "scenario": "Resolved win", "story": "Sam started below target, improved after coaching, and was closed as a win. This gives you a before/after proof point in the demo."},
        ],
    }


def write_csv(rows: list[dict]) -> None:
    fieldnames = ["Date", "Department", "EmployeeID", "EmployeeName", "Shift", "UPH", "Units", "HoursWorked"]
    with (OUT_DIR / "demo_supervisor_history.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(name: str, payload: object) -> None:
    with (OUT_DIR / name).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    history_rows = build_history_rows()
    actions = build_actions()
    events = build_action_events()
    storytelling = build_storytelling()
    write_csv(history_rows)
    write_json("demo_actions_seed.json", actions)
    write_json("demo_action_events_seed.json", events)
    write_json("demo_storytelling.json", storytelling)
    print(f"Wrote {len(history_rows)} history rows, {len(actions)} actions, and {len(events)} action events to {OUT_DIR}")


if __name__ == "__main__":
    main()