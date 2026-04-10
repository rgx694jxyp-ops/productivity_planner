from services.import_trust_service import build_import_trust_summary


def test_build_import_trust_summary_valid():
    summary = build_import_trust_summary(
        total_rows=120,
        accepted_rows=120,
        duplicates=0,
        warnings=0,
        missing_required_fields=0,
        inconsistent_names=0,
        suspicious_values=0,
    )

    assert summary.status == "valid"
    assert summary.accepted_rows == 120
    assert summary.rejected_rows == 0
    assert summary.confidence_score >= 90


def test_build_import_trust_summary_low_confidence_with_suspicious_values():
    summary = build_import_trust_summary(
        total_rows=50,
        accepted_rows=45,
        duplicates=2,
        warnings=4,
        missing_required_fields=0,
        inconsistent_names=3,
        suspicious_values=4,
    )

    assert summary.status == "low_confidence"
    assert summary.rejected_rows >= 5
    assert summary.suspicious_values == 4


def test_build_import_trust_summary_invalid_when_nothing_accepted():
    summary = build_import_trust_summary(
        total_rows=20,
        accepted_rows=0,
        duplicates=10,
        warnings=5,
        missing_required_fields=2,
        inconsistent_names=0,
        suspicious_values=2,
    )

    assert summary.status == "invalid"
    assert summary.accepted_rows == 0
    assert summary.rejected_rows >= 10
