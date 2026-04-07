from types import ModuleType

from domain import risk as domain_risk
from domain.risk_scoring import _compute_priority_summary
from ranker import _get_cutoff_month, build_top_bottom_summary, calculate_employee_risk


class _SettingsStub:
    def __init__(self, chart_months=0, trend_weeks=4):
        self._chart_months = chart_months
        self._trend_weeks = trend_weeks

    def get(self, key, default=None):
        if key == "chart_months":
            return self._chart_months
        if key == "trend_weeks":
            return self._trend_weeks
        return default


class _ErrorLogStub:
    def log(self, *args, **kwargs):
        return None


def test_risk_scoring_high_threshold_path(monkeypatch):
    emp = {"EmployeeID": "E1", "trend": "down", "Target UPH": 100}
    history = [
        {"EmployeeID": "E1", "Date": "2026-01-01", "UPH": 20},
        {"EmployeeID": "E1", "Date": "2026-01-02", "UPH": 90},
        {"EmployeeID": "E1", "Date": "2026-01-03", "UPH": 30},
        {"EmployeeID": "E1", "Date": "2026-01-04", "UPH": 80},
        {"EmployeeID": "E1", "Date": "2026-01-05", "UPH": 40},
        {"EmployeeID": "E1", "Date": "2026-01-06", "UPH": 70},
        {"EmployeeID": "E1", "Date": "2026-01-07", "UPH": 50},
    ]

    level, score, details = domain_risk.calc_risk_level(emp, history)

    assert level == "🔴 High"
    assert score >= 7
    assert details["trend_score"] == 4
    assert details["streak_score"] == 5
    assert details["variance_score"] == 3


def test_risk_scoring_low_threshold_path(monkeypatch):
    emp = {"EmployeeID": "E2", "trend": "up", "Target UPH": 100}
    history = [
        {"EmployeeID": "E2", "Date": "2026-01-01", "UPH": 105},
        {"EmployeeID": "E2", "Date": "2026-01-02", "UPH": 110},
        {"EmployeeID": "E2", "Date": "2026-01-03", "UPH": 108},
    ]

    level, score, details = domain_risk.calc_risk_level(emp, history)

    assert level == "🟢 Low"
    assert score < 4
    assert details["under_goal_streak"] == 0


def test_priority_summary_counts_critical_and_quick_wins(monkeypatch):
    gs = [
        {
            "EmployeeID": "E1",
            "goal_status": "below_goal",
            "trend": "down",
            "Average UPH": 80,
            "Target UPH": 100,
        },
        {
            "EmployeeID": "E2",
            "goal_status": "below_goal",
            "trend": "flat",
            "Average UPH": 96,
            "Target UPH": 100,
        },
        {
            "EmployeeID": "E3",
            "goal_status": "on_goal",
            "trend": "up",
            "Average UPH": 110,
            "Target UPH": 100,
        },
    ]

    monkeypatch.setattr(
        "domain.risk_scoring._get_all_risk_levels",
        lambda _gs, _hist: {
            "E1": ("🔴 High", 9.0, {}),
            "E2": ("🟡 Medium", 4.5, {}),
        },
    )

    summary = _compute_priority_summary(gs, history=[])

    assert summary["below"] == 2
    assert summary["critical"] == 1
    assert summary["quick_wins"] == 1


def test_rankings_top_bottom_summary_has_no_overlap():
    rows = [
        {"EmployeeID": "E1", "Average UPH": 120},
        {"EmployeeID": "E2", "Average UPH": 110},
        {"EmployeeID": "E3", "Average UPH": 100},
        {"EmployeeID": "E4", "Average UPH": 90},
        {"EmployeeID": "E5", "Average UPH": 80},
    ]

    summary = build_top_bottom_summary(rows, n=2)

    top_ids = {r["EmployeeID"] for r in summary["top"]}
    bottom_ids = {r["EmployeeID"] for r in summary["bottom"]}
    assert top_ids == {"E1", "E2"}
    assert bottom_ids == {"E4", "E5"}
    assert top_ids.isdisjoint(bottom_ids)


def test_cutoff_month_threshold_logic():
    settings = _SettingsStub(chart_months=0)
    assert _get_cutoff_month(settings) == ""

    settings_recent = _SettingsStub(chart_months=1)
    cutoff = _get_cutoff_month(settings_recent)
    assert isinstance(cutoff, str)
    assert len(cutoff) == 7
    assert cutoff.count("-") == 1


def test_benchmark_risk_logic_from_targets_and_dept_averages(monkeypatch):
    fake_goals = ModuleType("goals")
    fake_goals.get_all_targets = lambda: {"Pack": 100}
    fake_goals.analyse_trends = lambda _h, _m, weeks=4: {
        "Alex": {"direction": "down"},
        "Blair": {"direction": "down"},
        "Casey": {"direction": "flat"},
    }
    monkeypatch.setitem(__import__("sys").modules, "goals", fake_goals)

    history = [
        {"EmployeeName": "Alex", "Department": "Pack", "Date": "2026-01-01", "UPH": 70},
        {"EmployeeName": "Alex", "Department": "Pack", "Date": "2026-01-02", "UPH": 75},
        {"EmployeeName": "Alex", "Department": "Pack", "Date": "2026-01-03", "UPH": 80},
        {"EmployeeName": "Blair", "Department": "Pack", "Date": "2026-01-01", "UPH": 90},
        {"EmployeeName": "Blair", "Department": "Pack", "Date": "2026-01-02", "UPH": 95},
        {"EmployeeName": "Blair", "Department": "Pack", "Date": "2026-01-03", "UPH": 100},
        {"EmployeeName": "Casey", "Department": "Pack", "Date": "2026-01-01", "UPH": 120},
        {"EmployeeName": "Casey", "Department": "Pack", "Date": "2026-01-02", "UPH": 118},
        {"EmployeeName": "Casey", "Department": "Pack", "Date": "2026-01-03", "UPH": 122},
    ]

    out = calculate_employee_risk(history, {}, _SettingsStub(trend_weeks=4), _ErrorLogStub())
    by_name = {row["Employee"]: row for row in out}

    assert by_name["Alex"]["Risk Level"] == "high"
    assert by_name["Blair"]["Risk Level"] == "medium"
    assert by_name["Casey"]["Risk Level"] == "low"
