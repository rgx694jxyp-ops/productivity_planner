"""Column mapping review utilities for import pipeline."""

from __future__ import annotations

from services.import_pipeline.models import MappingReview

REQUIRED_FIELDS = ["EmployeeID", "Units", "HoursWorked"]
OPTIONAL_FIELDS = ["EmployeeName", "Department", "Date", "UPH"]


def review_mapping(mapping: dict | None) -> MappingReview:
    mapped = dict(mapping or {})
    required_missing = [field for field in REQUIRED_FIELDS if not str(mapped.get(field, "")).strip()]
    optional_unmapped = [field for field in OPTIONAL_FIELDS if not str(mapped.get(field, "")).strip()]
    return MappingReview(
        required_missing=required_missing,
        optional_unmapped=optional_unmapped,
        mapped=mapped,
    )
