from repositories import import_repo


def test_batch_store_uph_history_drops_non_schema_fields_from_upsert_payload(monkeypatch):
    captured = {}

    class _UpsertQuery:
        def execute(self):
            return type("Resp", (), {"data": []})()

    class _Table:
        def upsert(self, rows, on_conflict=None):
            captured["rows"] = rows
            captured["on_conflict"] = on_conflict
            return _UpsertQuery()

    class _Client:
        def table(self, name):
            assert name == "uph_history"
            return _Table()

    monkeypatch.setattr(import_repo, "get_client", lambda: _Client())
    monkeypatch.setattr(import_repo, "require_tenant", lambda: "tenant-a")
    monkeypatch.setattr(import_repo, "get_tenant_id", lambda: "tenant-a")

    import_repo.batch_store_uph_history(
        [
            {
                "tenant_id": "tenant-a",
                "emp_id": "1",
                "work_date": "2026-04-21",
                "department": "Pack",
                "uph": "41.0",
                "units": "123",
                "hours_worked": "3",
                "order_id": "ORD-1",
                "employee_name": "Alex",
                "source_file": "trace.csv",
                "row_index": 1,
            }
        ]
    )

    assert captured["on_conflict"] == "tenant_id,emp_id,work_date,department"
    assert len(captured["rows"]) == 1

    row = captured["rows"][0]
    assert row == {
        "tenant_id": "tenant-a",
        "emp_id": 1,
        "work_date": "2026-04-21",
        "department": "Pack",
        "uph": 41.0,
        "units": 123.0,
        "hours_worked": 3.0,
        "order_id": "ORD-1",
    }
    assert "employee_name" not in row
    assert "source_file" not in row
    assert "row_index" not in row
