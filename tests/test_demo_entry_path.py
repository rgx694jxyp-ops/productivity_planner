from pages import import_page
from services.daily_signals_service import _build_import_summary


def test_build_sample_demo_sessions_returns_demo_tagged_sessions():
    sessions = import_page._build_sample_demo_sessions(tenant_id="tenant-1")

    assert sessions
    assert all(str(session.get("source_mode") or "") == "demo" for session in sessions)
    assert all(int(session.get("row_count") or 0) > 0 for session in sessions)
    assert all(str(session.get("filename") or "").startswith("sample/") for session in sessions)


def test_build_import_summary_exposes_demo_source_mode(monkeypatch):
    def _fake_uploads(tenant_id: str, days: int = 30):
        return [
            {
                "is_active": True,
                "filename": "sample/demo_supervisor_history.csv",
                "header_mapping": {
                    "source_mode": "demo",
                    "stats": {
                        "candidate_rows": 120,
                        "accepted_rows": 108,
                        "warnings": 7,
                        "rejected_rows": 12,
                        "trust_status": "partial",
                        "confidence_score": 64,
                    },
                },
            }
        ]

    monkeypatch.setattr("services.import_service._list_recent_uploads", _fake_uploads)
    monkeypatch.setattr("services.import_service._decode_jsonish", lambda raw: raw if isinstance(raw, dict) else {})

    out = _build_import_summary(
        tenant_id="tenant-1",
        goal_status=[
            {"EmployeeID": "E1", "goal_status": "below_goal", "Record Count": 2},
            {"EmployeeID": "E2", "goal_status": "on_goal", "Record Count": 2},
        ],
    )

    assert out["source_mode"] == "demo"
    assert out["source_label"] == "sample/demo_supervisor_history.csv"
