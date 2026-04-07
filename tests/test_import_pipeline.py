from datetime import date

from services import import_service


def test_sanitize_employee_name_flags_suspicious_input():
    name, suspicious = import_service._sanitize_employee_name("<script>alert(1)</script>", "E88")

    assert suspicious is True
    assert name == "Employee E88"


def test_build_candidate_uph_rows_aggregates_units_and_hours():
    sessions = [
        {
            "filename": "jan.csv",
            "mapping": {
                "EmployeeID": "EmployeeID",
                "Department": "Department",
                "Date": "Date",
                "Units": "Units",
                "HoursWorked": "HoursWorked",
                "UPH": "UPH",
            },
            "rows": [
                {"EmployeeID": "E1", "Department": "Pick", "Date": "2026-01-10", "Units": 120, "HoursWorked": 2, "UPH": ""},
                {"EmployeeID": "E1", "Department": "Pick", "Date": "2026-01-10", "Units": 80, "HoursWorked": 2, "UPH": ""},
            ],
        }
    ]

    out = import_service._build_candidate_uph_rows(sessions, fallback_date=date(2026, 1, 1))

    assert len(out) == 1
    row = out[0]
    assert row["emp_id"] == "E1"
    assert row["uph"] == 50.0
    assert row["units"] == 200
    assert row["hours_worked"] == 4.0


def test_import_fingerprint_stable_with_row_order_changes():
    rows_a = [
        {"emp_id": "E1", "work_date": "2026-01-01", "department": "Pick", "uph": 20, "units": 100, "hours_worked": 5},
        {"emp_id": "E2", "work_date": "2026-01-01", "department": "Pack", "uph": 30, "units": 120, "hours_worked": 4},
    ]
    rows_b = list(reversed(rows_a))

    fp_a = import_service._build_import_fingerprint(rows_a)
    fp_b = import_service._build_import_fingerprint(rows_b)

    assert fp_a
    assert fp_a == fp_b
