"""Preview + confirm orchestration for reliable CSV imports."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date, timedelta

from repositories._common import get_client, tenant_query
from services.app_logging import log_error, log_info, log_warn
from services.import_pipeline.importer import build_upload_payload, persist_import_rows, record_upload_event
from services.import_pipeline.mapper import review_mapping
from services.import_pipeline.models import ImportCommitResult, ImportIssue, ImportPreviewResult, ImportSummary, MappingReview
from services.import_pipeline.parser import parse_sessions_to_rows
from services.import_pipeline.validator import validate_rows
from services.access_control_service import require_write
from services.perf_profile import profile_block
from services.import_trust_service import trust_summary_from_issues


_UPLOAD_FINGERPRINT_CACHE_TTL_SECONDS = 300
_UPLOAD_FINGERPRINT_CACHE: dict[tuple[str, str], tuple[float, dict | None]] = {}


def _build_import_fingerprint(rows: list[dict]) -> str:
    canon = []
    for row in rows or []:
        canon.append(
            [
                str(row.get("emp_id", "") or "").strip(),
                str(row.get("work_date", "") or "").strip()[:10],
                str(row.get("department", "") or "").strip().lower(),
                round(float(row.get("uph") or 0.0), 4),
                round(float(row.get("units") or 0.0), 4),
                round(float(row.get("hours_worked") or 0.0), 4),
            ]
        )
    canon.sort()
    raw = json.dumps(canon, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fingerprint_cache_key(*, tenant_id: str, fingerprint: str) -> tuple[str, str]:
    return (str(tenant_id or "").strip(), str(fingerprint or "").strip())


def _get_cached_upload_match(*, tenant_id: str, fingerprint: str) -> dict | None | type(Ellipsis):
    cache_key = _fingerprint_cache_key(tenant_id=tenant_id, fingerprint=fingerprint)
    cached = _UPLOAD_FINGERPRINT_CACHE.get(cache_key)
    if not cached:
        return Ellipsis
    expires_at, payload = cached
    if expires_at < time.time():
        _UPLOAD_FINGERPRINT_CACHE.pop(cache_key, None)
        return Ellipsis
    return dict(payload or {}) if isinstance(payload, dict) else None


def _set_cached_upload_match(*, tenant_id: str, fingerprint: str, payload: dict | None) -> None:
    clean_tenant_id = str(tenant_id or "").strip()
    clean_fingerprint = str(fingerprint or "").strip()
    if not clean_tenant_id or not clean_fingerprint:
        return
    _UPLOAD_FINGERPRINT_CACHE[_fingerprint_cache_key(tenant_id=clean_tenant_id, fingerprint=clean_fingerprint)] = (
        time.time() + _UPLOAD_FINGERPRINT_CACHE_TTL_SECONDS,
        dict(payload or {}) if isinstance(payload, dict) else None,
    )


def _find_matching_upload_by_fingerprint(tenant_id: str, fingerprint: str, days: int = 3650) -> dict | None:
    if not tenant_id or not fingerprint:
        return None
    cached = _get_cached_upload_match(tenant_id=tenant_id, fingerprint=fingerprint)
    if cached is not Ellipsis:
        return cached
    try:
        from services.settings_service import get_tenant_local_now

        since = (get_tenant_local_now(tenant_id) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        sb = get_client()
        result = tenant_query(
            sb.table("uploaded_files")
            .select("id, header_mapping, is_active, created_at")
            .eq("tenant_id", tenant_id)
            .gte("created_at", since)
            .order("created_at", desc=True)
        ).execute()
        for row in result.data or []:
            meta = row.get("header_mapping")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if not isinstance(meta, dict):
                continue
            if meta.get("undo_applied_at"):
                continue
            fp = str(meta.get("data_fingerprint") or meta.get("fingerprint") or "").strip()
            if fp and fp == fingerprint:
                _set_cached_upload_match(tenant_id=tenant_id, fingerprint=fingerprint, payload=row)
                return row
    except Exception:
        return None
    _set_cached_upload_match(tenant_id=tenant_id, fingerprint=fingerprint, payload=None)
    return None


def preview_import(sessions: list[dict], *, fallback_date: date, tenant_id: str = "", user_role: str = "") -> ImportPreviewResult:
    require_write(user_role)
    with profile_block(
        "import.preview",
        tenant_id=str(tenant_id or ""),
        context={"input_bundle_count": len(sessions or [])},
        execution_key=f"_perf_profile_import_preview_{str(tenant_id or '').strip()}",
    ) as profile:
        try:
            all_required_missing: set[str] = set()
            all_optional_unmapped: set[str] = set()
            merged_mapping: dict[str, str] = {}

            with profile.stage("mapping_review"):
                for session in sessions or []:
                    mapping = session.get("mapping") or {}
                    review = review_mapping(mapping)
                    merged_mapping.update({k: v for k, v in review.mapped.items() if str(v).strip()})
                    all_required_missing.update(review.required_missing)
                    all_optional_unmapped.update(review.optional_unmapped)

            with profile.stage("parse_input_rows"):
                parsed_rows = parse_sessions_to_rows(sessions, fallback_date)
            profile.set("parsed_rows", len(parsed_rows or []))

            with profile.stage("validate_rows"):
                candidate_rows, issues, duplicate_rows_in_file = validate_rows(parsed_rows)
            profile.set("candidate_rows", len(candidate_rows or []))
            profile.set("invalid_issue_count", len(issues or []))
            profile.set("duplicate_rows_in_file", int(duplicate_rows_in_file or 0))

            with profile.stage("merge_mapping_review"):
                merged_review = review_mapping(merged_mapping)

            fingerprint = _build_import_fingerprint(candidate_rows)
            exact_duplicate = False
            if fingerprint:
                with profile.stage("duplicate_check"):
                    exact_duplicate = bool(_find_matching_upload_by_fingerprint(tenant_id, fingerprint))
                profile.query(count=1)
            profile.set("exact_duplicate", bool(exact_duplicate))

            summary = ImportSummary(
                total_rows=len(parsed_rows),
                valid_rows=len(candidate_rows),
                invalid_rows=sum(1 for issue in issues if issue.severity == "error"),
                duplicate_rows_in_file=duplicate_rows_in_file,
                duplicate_rows_existing=(len(candidate_rows) if exact_duplicate else 0),
            )
            trust_summary = trust_summary_from_issues(
                total_rows=summary.total_rows,
                accepted_rows=summary.valid_rows,
                issues=issues,
                duplicates=summary.duplicate_rows_in_file + summary.duplicate_rows_existing,
                missing_required_fields=len(all_required_missing),
            )

            can_import = (not all_required_missing) and bool(candidate_rows) and (not exact_duplicate)
            if all_required_missing:
                message = "Required mappings are missing. Review column mapping before import."
                log_warn(
                    "import_preview_blocked",
                    "Import preview blocked due to missing required mappings.",
                    tenant_id=tenant_id,
                    context={"required_missing": sorted(all_required_missing)},
                )
            elif exact_duplicate:
                message = "This file appears identical to a previous import. No new rows would be inserted."
                log_warn(
                    "import_preview_duplicate",
                    "Import preview matched a previously imported file.",
                    tenant_id=tenant_id,
                    context={"fingerprint": fingerprint, "valid_rows": len(candidate_rows)},
                )
            elif not candidate_rows:
                message = "No valid rows found after validation."
                log_warn(
                    "import_preview_empty",
                    "Import preview produced no valid candidate rows.",
                    tenant_id=tenant_id,
                    context={"total_rows": len(parsed_rows), "invalid_rows": summary.invalid_rows},
                )
            else:
                message = "Preview is ready. Review summary and confirm import."
                log_info(
                    "import_preview_ready",
                    "Import preview completed successfully.",
                    tenant_id=tenant_id,
                    context={
                        "total_rows": summary.total_rows,
                        "valid_rows": summary.valid_rows,
                        "invalid_rows": summary.invalid_rows,
                        "duplicate_rows_in_file": duplicate_rows_in_file,
                    },
                )

            return ImportPreviewResult(
                success=True,
                can_import=can_import,
                summary=summary,
                mapping_review=merged_review,
                candidate_rows=candidate_rows,
                invalid_issues=issues,
                exact_duplicate_import=exact_duplicate,
                fingerprint=fingerprint,
                message=message,
                trust_summary=trust_summary,
            )
        except Exception as error:
            log_error(
                "import_preview_failed",
                "Import preview failed unexpectedly.",
                tenant_id=tenant_id,
                context={"session_count": len(sessions or [])},
                error=error,
            )
            return ImportPreviewResult(
                success=False,
                can_import=False,
                summary=ImportSummary(total_rows=len(sessions or [])),
                mapping_review=MappingReview(),
                candidate_rows=[],
                invalid_issues=[ImportIssue(code="preview_failed", message="Import preview failed. Please try again.")],
                exact_duplicate_import=False,
                fingerprint="",
                message="Import preview failed. Please try again. If it keeps failing, contact support.",
            )


def confirm_import(preview: ImportPreviewResult, *, tenant_id: str, upload_name: str = "Import", user_role: str = "") -> ImportCommitResult:
    require_write(user_role)
    if not preview.can_import:
        log_warn(
            "import_confirm_blocked",
            "Import confirmation was blocked because preview was not confirmable.",
            tenant_id=tenant_id,
            context={"message": preview.message, "valid_rows": preview.summary.valid_rows},
        )
        return ImportCommitResult(
            success=False,
            summary=preview.summary,
            issues=[ImportIssue(code="not_confirmable", message=preview.message, severity="error")],
            message="Import blocked. Resolve preview issues and try again.",
            trust_summary=preview.trust_summary,
        )

    with profile_block(
        "import.commit",
        tenant_id=str(tenant_id or ""),
        context={"candidate_rows": len(preview.candidate_rows or [])},
        execution_key=f"_perf_profile_import_commit_{str(tenant_id or '').strip()}",
    ) as profile:
        try:
            with profile.stage("persist_rows"):
                inserted_rows = persist_import_rows(preview.candidate_rows, tenant_id)
            profile.query(rows=int(inserted_rows or 0))
            summary = ImportSummary(
                total_rows=preview.summary.total_rows,
                valid_rows=preview.summary.valid_rows,
                invalid_rows=preview.summary.invalid_rows,
                duplicate_rows_in_file=preview.summary.duplicate_rows_in_file,
                duplicate_rows_existing=preview.summary.duplicate_rows_existing,
                inserted_rows=inserted_rows,
                skipped_rows=max(0, preview.summary.total_rows - inserted_rows),
            )

            with profile.stage("record_upload_event"):
                payload = build_upload_payload(
                    fingerprint=preview.fingerprint,
                    summary={
                        "candidate_rows": summary.valid_rows,
                        "invalid_rows": summary.invalid_rows,
                        "duplicate_rows_in_file": summary.duplicate_rows_in_file,
                        "duplicate_rows_existing": summary.duplicate_rows_existing,
                        "inserted_rows": summary.inserted_rows,
                    },
                    mapping=preview.mapping_review.mapped,
                    source_files=[],
                )
                upload_id = record_upload_event(
                    tenant_id=tenant_id,
                    filename=upload_name,
                    row_count=summary.valid_rows,
                    payload=payload,
                )
            profile.query(count=1)
            profile.set("inserted_rows", int(inserted_rows or 0))
            if preview.fingerprint:
                _set_cached_upload_match(
                    tenant_id=tenant_id,
                    fingerprint=preview.fingerprint,
                    payload={"id": upload_id, "header_mapping": payload},
                )

            log_info(
                "import_commit_succeeded",
                "Import commit completed successfully.",
                tenant_id=tenant_id,
                context={"upload_name": upload_name, "inserted_rows": inserted_rows, "upload_id": upload_id},
            )

            return ImportCommitResult(
                success=True,
                summary=summary,
                upload_id=upload_id,
                message=f"Import completed successfully: {inserted_rows} row(s) inserted.",
                trust_summary=preview.trust_summary,
            )
        except Exception as error:
            log_error(
                "import_commit_failed",
                "Import commit failed during persistence.",
                tenant_id=tenant_id,
                context={"upload_name": upload_name, "candidate_rows": len(preview.candidate_rows)},
                error=error,
            )
            return ImportCommitResult(
                success=False,
                summary=preview.summary,
                issues=[ImportIssue(code="import_failed", message="Import failed while saving data.", severity="error")],
                message="Import failed while saving data. Please try again. If it keeps failing, contact support.",
                trust_summary=preview.trust_summary,
            )
