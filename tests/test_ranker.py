from ranker import build_department_report, rank_employees


class _SettingsStub:
    def __init__(self, chart_months=0, top_pct=10, bot_pct=10, targets=None):
        self._chart_months = chart_months
        self._top_pct = top_pct
        self._bot_pct = bot_pct
        self._targets = targets or {}

    def get(self, key, default=None):
        if key == "chart_months":
            return self._chart_months
        if key == "top_pct":
            return self._top_pct
        if key == "bot_pct":
            return self._bot_pct
        return default

    def get_dept_target_uph(self, dept_name):
        return float(self._targets.get(dept_name, 0))


class _ErrorLogStub:
    def __init__(self):
        self.entries = []

    def log(self, *args):
        self.entries.append(args)


def test_rank_employees_aggregates_and_sorts_desc():
    history = [
        {"Month": "2026-01", "EmployeeID": "E1", "EmployeeName": "Alex", "Department": "Pack", "Shift": "A", "UPH": 100},
        {"Month": "2026-02", "EmployeeID": "E1", "EmployeeName": "Alex", "Department": "Pack", "Shift": "A", "UPH": 120},
        {"Month": "2026-01", "EmployeeID": "E2", "EmployeeName": "Blair", "Department": "Pack", "Shift": "B", "UPH": 90},
    ]
    settings = _SettingsStub(chart_months=0)
    errors = _ErrorLogStub()

    ranked = rank_employees(history, {}, settings, errors)

    assert [r["EmployeeID"] for r in ranked] == ["E1", "E2"]
    assert ranked[0]["Average UPH"] == 110.0
    assert ranked[0]["Record Count"] == 2


def test_build_department_report_assigns_highlights():
    rows = [
        {"Department": "Pack", "Shift": "A", "EmployeeID": "E1", "Employee Name": "Alex", "Average UPH": 130},
        {"Department": "Pack", "Shift": "A", "EmployeeID": "E2", "Employee Name": "Blair", "Average UPH": 60},
        {"Department": "Pack", "Shift": "B", "EmployeeID": "E3", "Employee Name": "Casey", "Average UPH": 95},
    ]
    settings = _SettingsStub(top_pct=34, bot_pct=34, targets={"Pack": 100})
    errors = _ErrorLogStub()

    report = build_department_report(rows, settings, errors)

    assert "Pack" in report
    highlights = {r["EmployeeID"]: r["_highlight"] for r in report["Pack"]}
    assert highlights["E2"] == "target"
    assert highlights["E1"] == "top"
