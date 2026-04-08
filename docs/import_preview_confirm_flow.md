# Preview + Confirm Import Flow (Streamlit Example)

This example keeps the page thin by delegating parsing, mapping review, validation,
and DB writes to the import pipeline service.

```python
from datetime import date

import streamlit as st

from services.import_pipeline import confirm_import, preview_import


def render_import_preview_confirm_page() -> None:
    st.title("Import Data")

    sessions = st.session_state.get("uploaded_sessions", [])
    tenant_id = str(st.session_state.get("tenant_id", "") or "")

    if not sessions:
        st.info("Upload one or more files to begin.")
        return

    if "import_preview" not in st.session_state:
        st.session_state["import_preview"] = None

    if st.button("Validate & Preview", type="primary"):
        st.session_state["import_preview"] = preview_import(
            sessions,
            fallback_date=date.today(),
            tenant_id=tenant_id,
        )

    preview = st.session_state.get("import_preview")
    if not preview:
        return

    st.subheader("Preview Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Rows", preview.summary.total_rows)
    c2.metric("Valid Rows", preview.summary.valid_rows)
    c3.metric("Invalid Rows", preview.summary.invalid_rows)

    if preview.mapping_review.required_missing:
        st.error(
            "Missing required mappings: "
            + ", ".join(preview.mapping_review.required_missing)
        )

    if preview.mapping_review.optional_unmapped:
        st.info(
            "Optional unmapped columns: "
            + ", ".join(preview.mapping_review.optional_unmapped)
        )

    st.caption(preview.message)

    if preview.invalid_issues:
        with st.expander("Invalid Row Report", expanded=False):
            st.dataframe(
                [
                    {
                        "severity": issue.severity,
                        "code": issue.code,
                        "row": issue.row_index,
                        "field": issue.field,
                        "message": issue.message,
                        "value": issue.value,
                    }
                    for issue in preview.invalid_issues
                ],
                use_container_width=True,
            )

    with st.expander("Candidate Rows", expanded=False):
        st.dataframe(preview.candidate_rows[:200], use_container_width=True)

    disabled = not preview.can_import
    if st.button("Confirm Import", disabled=disabled):
        result = confirm_import(preview, tenant_id=tenant_id, upload_name="CSV Import")
        if result.success:
            st.success(result.message)
            st.caption(
                f"Inserted: {result.summary.inserted_rows} | "
                f"Skipped: {result.summary.skipped_rows} | "
                f"Duplicates in file: {result.summary.duplicate_rows_in_file}"
            )
            st.session_state["import_preview"] = None
        else:
            st.error(result.message)
            for issue in result.issues:
                st.caption(f"{issue.code}: {issue.message}")
```
