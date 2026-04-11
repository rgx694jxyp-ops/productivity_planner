from services.import_quality_service import (
    ISSUE_HANDLING_CHOICES,
    build_issue_groups,
    build_latest_import_summary,
    trust_level_from_summary,
)


def test_trust_level_from_summary_high_moderate_low():
    assert trust_level_from_summary({"status": "valid", "confidence_score": 90}) == "High"
    assert trust_level_from_summary({"status": "partial", "confidence_score": 65}) == "Moderate"
    assert trust_level_from_summary({"status": "invalid", "confidence_score": 20}) == "Low"


def test_build_latest_import_summary_clamps_negative_values():
    summary = build_latest_import_summary(
        rows_processed=-10,
        valid_rows=-1,
        warning_rows=3,
        rejected_rows=-2,
        ignored_or_excluded_rows=4,
    )

    assert summary.rows_processed == 0
    assert summary.valid_rows == 0
    assert summary.warning_rows == 3
    assert summary.rejected_rows == 0
    assert summary.ignored_or_excluded_rows == 4


def test_build_issue_groups_includes_expected_categories_and_defaults():
    trust = {
        "duplicates": 2,
        "missing_required_fields": 1,
        "inconsistent_names": 1,
        "suspicious_values": 1,
    }
    row_issues = [
        {"code": "missing_emp_id", "severity": "error", "field": "EmployeeID"},
        {"code": "invalid_uph", "severity": "warning", "field": "UPH"},
        {"code": "missing_date", "severity": "warning", "field": "Date"},
        {"code": "invalid_units", "severity": "error", "field": "Units"},
    ]
    preview_rows = [
        {"Department": "Packing"},
        {"Department": "packing "},
        {"Department": "Shipping"},
    ]
    excluded_rows = [{"Employee ID": "E1", "Reason": "Duplicate"}]

    groups = build_issue_groups(
        trust=trust,
        row_issues=row_issues,
        preview_rows=preview_rows,
        excluded_rows=excluded_rows,
    )

    keys = {group.key for group in groups}
    assert {"missing_fields", "duplicate_rows", "suspicious_values", "partial_records"}.issubset(keys)
    for group in groups:
        assert group.default_choice in ISSUE_HANDLING_CHOICES
