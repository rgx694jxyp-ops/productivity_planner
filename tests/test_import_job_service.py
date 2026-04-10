from services.import_pipeline.job_service import (
    complete_job,
    create_import_job,
    mark_stage_completed,
    mark_stage_in_progress,
    serialize_job,
)
from services.import_pipeline.mapping_profiles import build_mapping_profile_payload


def test_import_job_lifecycle_tracks_pipeline_stages():
    job = create_import_job(tenant_id="t1", upload_name="batch.csv", total_rows=42)

    mark_stage_in_progress(job, "validate")
    mark_stage_completed(job, "validate", meta={"row_errors": 3})
    mark_stage_in_progress(job, "persist")
    mark_stage_completed(job, "persist", meta={"inserted_rows": 39})
    complete_job(job, success=True)

    payload = serialize_job(job)
    assert payload["job_id"].startswith("import-")
    assert payload["stage_status"]["upload"] == "completed"
    assert payload["stage_status"]["validate"] == "completed"
    assert payload["stage_meta"]["validate"]["row_errors"] == 3
    assert payload["stage_meta"]["persist"]["inserted_rows"] == 39
    assert payload["success"] is True


def test_build_mapping_profile_payload_keeps_non_empty_fields():
    profile = build_mapping_profile_payload(
        headers=["EmployeeID", "EmployeeName", "UPH", "Department"],
        mapping={
            "EmployeeID": "EmployeeID",
            "EmployeeName": "EmployeeName",
            "UPH": "UPH",
            "Date": "",
        },
    )

    assert profile["headers_fingerprint"]
    assert profile["mapping"]["EmployeeID"] == "EmployeeID"
    assert "Date" not in profile["mapping"]
