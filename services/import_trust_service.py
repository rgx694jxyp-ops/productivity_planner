"""Build trust and data-quality summaries for import previews and commits."""

from __future__ import annotations

from services.import_pipeline.models import DataQualityStatus, ImportIssue, ImportTrustSummary


def _clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


def _issue_value(issue: ImportIssue | dict, field: str) -> object:
    if isinstance(issue, dict):
        return issue.get(field)
    return getattr(issue, field, None)


def build_import_warning_summary(
    *,
    issues: list[ImportIssue] | list[dict] | None = None,
    trust: ImportTrustSummary | dict | None = None,
) -> str:
    """Build one plain-language warning sentence for preview/result surfaces.

    Priority:
    1. Date fallback warnings, because they silently substitute the selected work date.
    2. Generic quality warning if the import contains other non-fatal issues.
    3. Empty string for clean imports.
    """
    issue_list = list(issues or [])
    fallback_date_count = sum(
        1
        for issue in issue_list
        if str(_issue_value(issue, "code") or "").strip().lower() == "date_parse_fallback"
    )
    if fallback_date_count > 0:
        if fallback_date_count == 1:
            return "Some row dates could not be parsed and used the selected work date instead."
        return "Some row dates could not be parsed and used the selected work date instead."

    trust_obj = trust or {}
    if isinstance(trust_obj, dict):
        warnings = int(trust_obj.get("warnings", 0) or 0)
        duplicates = int(trust_obj.get("duplicates", 0) or 0)
        rejected = int(trust_obj.get("rejected_rows", 0) or 0)
        missing = int(trust_obj.get("missing_required_fields", 0) or 0)
        inconsistent = int(trust_obj.get("inconsistent_names", 0) or 0)
        suspicious = int(trust_obj.get("suspicious_values", 0) or 0)
    else:
        warnings = int(getattr(trust_obj, "warnings", 0) or 0)
        duplicates = int(getattr(trust_obj, "duplicates", 0) or 0)
        rejected = int(getattr(trust_obj, "rejected_rows", 0) or 0)
        missing = int(getattr(trust_obj, "missing_required_fields", 0) or 0)
        inconsistent = int(getattr(trust_obj, "inconsistent_names", 0) or 0)
        suspicious = int(getattr(trust_obj, "suspicious_values", 0) or 0)

    if any(value > 0 for value in (warnings, duplicates, rejected, missing, inconsistent, suspicious)):
        return "Import completed with data quality warnings."
    return ""


def classify_data_quality_status(
    *,
    accepted_rows: int,
    rejected_rows: int,
    missing_required_fields: int,
    warnings: int,
    suspicious_values: int,
    inconsistent_names: int,
    duplicates: int,
) -> DataQualityStatus:
    if accepted_rows <= 0:
        return "invalid"

    if missing_required_fields > 0 and accepted_rows <= rejected_rows:
        return "invalid"

    total_rows = max(1, accepted_rows + rejected_rows)
    rejection_rate = rejected_rows / total_rows
    warning_rate = warnings / total_rows

    if rejection_rate >= 0.25:
        return "invalid"

    if suspicious_values > 0 or inconsistent_names > 0:
        return "low_confidence"

    if warning_rate >= 0.25 or duplicates > 0:
        return "partial"

    if rejected_rows > 0 or warnings > 0 or missing_required_fields > 0:
        return "partial"

    return "valid"


def build_import_trust_summary(
    *,
    total_rows: int,
    accepted_rows: int,
    duplicates: int = 0,
    missing_required_fields: int = 0,
    inconsistent_names: int = 0,
    suspicious_values: int = 0,
    warnings: int = 0,
    extra_rejected_rows: int = 0,
    warning_summary: str = "",
) -> ImportTrustSummary:
    accepted = max(0, int(accepted_rows))
    total = max(0, int(total_rows))
    duplicate_rows = max(0, int(duplicates))
    warning_count = max(0, int(warnings))
    missing_required = max(0, int(missing_required_fields))
    inconsistent = max(0, int(inconsistent_names))
    suspicious = max(0, int(suspicious_values))
    additional_rejected = max(0, int(extra_rejected_rows))

    base_rejected = max(0, total - accepted)
    rejected = max(base_rejected, duplicate_rows + additional_rejected)

    status = classify_data_quality_status(
        accepted_rows=accepted,
        rejected_rows=rejected,
        missing_required_fields=missing_required,
        warnings=warning_count,
        suspicious_values=suspicious,
        inconsistent_names=inconsistent,
        duplicates=duplicate_rows,
    )

    score = 100
    score -= min(70, rejected * 2)
    score -= min(20, warning_count)
    score -= min(20, duplicate_rows)
    score -= min(30, missing_required * 5)
    score -= min(20, suspicious * 2)
    score -= min(15, inconsistent)

    return ImportTrustSummary(
        status=status,
        accepted_rows=accepted,
        rejected_rows=rejected,
        warnings=warning_count,
        duplicates=duplicate_rows,
        missing_required_fields=missing_required,
        inconsistent_names=inconsistent,
        suspicious_values=suspicious,
        confidence_score=_clamp_score(score),
        warning_summary=str(warning_summary or ""),
    )


def trust_summary_from_issues(
    *,
    total_rows: int,
    accepted_rows: int,
    issues: list[ImportIssue],
    duplicates: int,
    missing_required_fields: int = 0,
    inconsistent_names: int = 0,
    suspicious_values: int = 0,
) -> ImportTrustSummary:
    warnings = sum(1 for issue in (issues or []) if issue.severity == "warning")
    errors = sum(1 for issue in (issues or []) if issue.severity == "error")
    missing_required_by_issue = sum(
        1
        for issue in (issues or [])
        if issue.code in {"missing_emp_id", "invalid_units", "invalid_hours", "missing_required"}
    )
    suspicious_by_issue = sum(
        1
        for issue in (issues or [])
        if issue.code in {"invalid_uph", "negative_units", "negative_hours"}
    )

    trust = build_import_trust_summary(
        total_rows=total_rows,
        accepted_rows=accepted_rows,
        duplicates=duplicates,
        missing_required_fields=missing_required_fields + missing_required_by_issue,
        inconsistent_names=inconsistent_names,
        suspicious_values=suspicious_values + suspicious_by_issue,
        warnings=warnings,
        extra_rejected_rows=errors,
        warning_summary=build_import_warning_summary(issues=issues),
    )
    if not trust.warning_summary:
        trust.warning_summary = build_import_warning_summary(issues=issues, trust=trust)
    return trust
