"""Business logic for import data confidence and issue grouping.

TODO: Persist per-issue handling choices to a tenant-scoped store so user decisions
can be reused across repeated imports.
"""

from __future__ import annotations

from models.import_quality_models import IssueGroup, LatestImportSummary

ISSUE_HANDLING_CHOICES = [
    "review_details",
    "ignore_rows",
    "include_low_confidence",
    "map_or_correct",
]

ISSUE_HANDLING_LABELS = {
    "review_details": "Review details",
    "ignore_rows": "Ignore these rows",
    "include_low_confidence": "Include with low confidence",
    "map_or_correct": "Map/correct value",
}


def trust_level_from_summary(trust: dict) -> str:
    score = int(trust.get("confidence_score", 0) or 0)
    status = str(trust.get("status", "invalid") or "invalid")
    if status == "valid" and score >= 80:
        return "High"
    if status in {"partial", "low_confidence"} or score >= 50:
        return "Moderate"
    return "Low"


def build_latest_import_summary(
    *,
    rows_processed: int,
    valid_rows: int,
    warning_rows: int,
    rejected_rows: int,
    ignored_or_excluded_rows: int,
) -> LatestImportSummary:
    return LatestImportSummary(
        rows_processed=max(0, int(rows_processed)),
        valid_rows=max(0, int(valid_rows)),
        warning_rows=max(0, int(warning_rows)),
        rejected_rows=max(0, int(rejected_rows)),
        ignored_or_excluded_rows=max(0, int(ignored_or_excluded_rows)),
    )


def _issue_count_by_codes(row_issues: list[dict], *codes: str) -> int:
    wanted = {str(code).strip().lower() for code in codes}
    return sum(1 for issue in row_issues if str(issue.get("code", "")).strip().lower() in wanted)


def _build_process_variants(preview_rows: list[dict]) -> dict[str, set[str]]:
    process_variants: dict[str, set[str]] = {}
    for row in preview_rows or []:
        label = str(row.get("Department", "") or "").strip()
        if not label:
            continue
        normalized = " ".join(label.lower().split())
        process_variants.setdefault(normalized, set()).add(label)
    return process_variants


def build_issue_groups(
    *,
    trust: dict,
    row_issues: list[dict],
    preview_rows: list[dict],
    excluded_rows: list[dict],
) -> list[IssueGroup]:
    issues = row_issues or []
    process_variants = _build_process_variants(preview_rows)
    inconsistent_process_count = sum(max(0, len(raw_values) - 1) for raw_values in process_variants.values())
    warning_rows = sum(1 for issue in issues if str(issue.get("severity", "error")) == "warning")

    groups = [
        IssueGroup(
            key="missing_fields",
            label="Missing fields",
            count=int(trust.get("missing_required_fields", 0) or 0)
            + _issue_count_by_codes(issues, "missing_emp_id", "invalid_units", "invalid_hours"),
            effect="These rows can reduce confidence in today's comparisons because required fields are missing.",
            default_choice="ignore_rows",
            rows=[issue for issue in issues if str(issue.get("code", "")).lower() in {"missing_emp_id", "invalid_units", "invalid_hours"}],
        ),
        IssueGroup(
            key="duplicate_rows",
            label="Duplicate rows",
            count=int(trust.get("duplicates", 0) or 0),
            effect="Duplicate rows are ignored to avoid overstating performance trends.",
            default_choice="ignore_rows",
            rows=excluded_rows or [],
        ),
        IssueGroup(
            key="inconsistent_employee_names",
            label="Inconsistent employee names",
            count=int(trust.get("inconsistent_names", 0) or 0),
            effect="Name inconsistency can split one person across multiple records and weaken interpretation.",
            default_choice="map_or_correct",
            rows=[issue for issue in issues if "name" in str(issue.get("field", "")).lower()],
        ),
        IssueGroup(
            key="inconsistent_process_labels",
            label="Inconsistent process labels",
            count=inconsistent_process_count,
            effect="Process label variation can fragment team/process trends.",
            default_choice="map_or_correct",
            rows=[{"normalized": key, "variants": ", ".join(sorted(values))} for key, values in process_variants.items() if len(values) > 1],
        ),
        IssueGroup(
            key="suspicious_values",
            label="Suspicious values",
            count=int(trust.get("suspicious_values", 0) or 0)
            + _issue_count_by_codes(issues, "invalid_uph", "negative_units", "negative_hours"),
            effect="Suspicious values can create misleading spikes or drops, so confidence is reduced.",
            default_choice="include_low_confidence",
            rows=[issue for issue in issues if str(issue.get("code", "")).lower() in {"invalid_uph", "negative_units", "negative_hours"}],
        ),
        IssueGroup(
            key="partial_records",
            label="Partial/incomplete records",
            count=warning_rows + _issue_count_by_codes(issues, "missing_date"),
            effect="Partial records can be used, but they reduce certainty in time-based comparisons.",
            default_choice="include_low_confidence",
            rows=[issue for issue in issues if str(issue.get("severity", "error")).lower() == "warning"],
        ),
    ]
    return [group for group in groups if int(group.count or 0) > 0]
