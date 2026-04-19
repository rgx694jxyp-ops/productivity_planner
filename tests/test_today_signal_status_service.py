from services.today_signal_status_service import (
    SIGNAL_STATUS_LOOKED_AT,
    SIGNAL_STATUS_NEEDS_FOLLOW_UP,
    list_latest_signal_statuses,
    set_signal_status,
)


def test_set_signal_status_persists_in_action_events(monkeypatch):
    captured = {}

    def _log_action_event(**kwargs):
        captured.update(kwargs)
        return {"id": 9}

    monkeypatch.setattr("services.today_signal_status_service.action_events_repo.log_action_event", _log_action_event)

    out = set_signal_status(
        signal_key="today-signal:e1:packing:below_expected:stable_trend:2026-04-12",
        employee_id="E1",
        signal_status=SIGNAL_STATUS_LOOKED_AT,
        owner="lead@example.com",
        tenant_id="tenant-a",
    )

    assert out == {"id": 9}
    assert captured["event_type"] == "today_signal_status_set"
    assert captured["employee_id"] == "E1"
    assert captured["status"] == "done"
    assert '"signal_status":"looked_at"' in str(captured.get("details") or "")


def test_list_latest_signal_statuses_returns_latest_per_signal(monkeypatch):
    signal_key = "today-signal:e2:pick:lower_than_recent:stable_trend:2026-04-12"
    rows = [
        {
            "event_type": "today_signal_status_set",
            "details": '{"scope":"today_queue_signal_status","signal_key":"%s","signal_status":"needs_follow_up"}' % signal_key,
            "owner": "lead@example.com",
            "event_at": "2026-04-12T10:00:00Z",
        },
        {
            "event_type": "today_signal_status_set",
            "details": '{"scope":"today_queue_signal_status","signal_key":"%s","signal_status":"looked_at"}' % signal_key,
            "owner": "lead@example.com",
            "event_at": "2026-04-12T09:00:00Z",
        },
        {
            "event_type": "follow_up_logged",
            "details": "",
            "owner": "lead@example.com",
            "event_at": "2026-04-12T08:00:00Z",
        },
    ]

    class _FakeTable:
        def __init__(self, _rows):
            self._rows = _rows
            self._offset = 0
            self._upper = len(_rows) - 1

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def range(self, offset, upper):
            self._offset = int(offset)
            self._upper = int(upper)
            return self

        def execute(self):
            class _Resp:
                data = self._rows[self._offset : self._upper + 1]

            return _Resp()

    class _FakeClient:
        def table(self, name):
            assert name == "action_events"
            return _FakeTable(rows)

    monkeypatch.setattr("services.today_signal_status_service.get_client", lambda: _FakeClient())

    status_map = list_latest_signal_statuses(signal_keys={signal_key}, tenant_id="tenant-a")

    assert status_map[signal_key]["status"] == SIGNAL_STATUS_NEEDS_FOLLOW_UP
    assert status_map[signal_key]["owner"] == "lead@example.com"


def test_list_latest_signal_statuses_scans_multiple_pages(monkeypatch):
    signal_key = "today-signal:e9:pack:below_expected:stable_trend:2026-04-12"
    first_page = [
        {
            "event_type": "today_signal_status_set",
            "details": '{"scope":"today_queue_signal_status","signal_key":"other-%d","signal_status":"looked_at"}' % idx,
            "owner": "lead@example.com",
            "event_at": "2026-04-12T10:00:00Z",
        }
        for idx in range(200)
    ]
    second_page = [
        {
            "event_type": "today_signal_status_set",
            "details": '{"scope":"today_queue_signal_status","signal_key":"%s","signal_status":"looked_at"}' % signal_key,
            "owner": "lead@example.com",
            "event_at": "2026-04-11T10:00:00Z",
        }
    ]

    class _PagedTable:
        def __init__(self):
            self._offset = 0
            self._upper = 0

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def range(self, offset, upper):
            self._offset = int(offset)
            self._upper = int(upper)
            return self

        def execute(self):
            class _Resp:
                data = first_page if self._offset == 0 else second_page

            return _Resp()

    class _FakeClient:
        def table(self, name):
            assert name == "action_events"
            return _PagedTable()

    monkeypatch.setattr("services.today_signal_status_service.get_client", lambda: _FakeClient())

    status_map = list_latest_signal_statuses(signal_keys={signal_key}, tenant_id="tenant-a")

    assert status_map[signal_key]["status"] == SIGNAL_STATUS_LOOKED_AT


def test_list_latest_signal_statuses_scans_beyond_previous_max_scan_rows(monkeypatch):
    signal_key = "today-signal:e77:pack:below_expected:stable_trend:2026-04-12"
    row_count = 21000

    class _DeepHistoryTable:
        def __init__(self):
            self._offset = 0
            self._upper = 0

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def range(self, offset, upper):
            self._offset = int(offset)
            self._upper = int(upper)
            return self

        def execute(self):
            start = self._offset
            stop = min(self._upper + 1, row_count)
            rows = []
            for idx in range(start, stop):
                is_target = idx == (row_count - 1)
                key = signal_key if is_target else f"other-{idx}"
                rows.append(
                    {
                        "event_type": "today_signal_status_set",
                        "details": '{"scope":"today_queue_signal_status","signal_key":"%s","signal_status":"looked_at"}' % key,
                        "owner": "lead@example.com",
                        "event_at": "2026-04-12T10:00:00Z",
                    }
                )

            class _Resp:
                data = rows

            return _Resp()

    class _FakeClient:
        def table(self, name):
            assert name == "action_events"
            return _DeepHistoryTable()

    monkeypatch.setattr("services.today_signal_status_service.get_client", lambda: _FakeClient())

    status_map = list_latest_signal_statuses(signal_keys={signal_key}, tenant_id="tenant-a")

    assert status_map[signal_key]["status"] == SIGNAL_STATUS_LOOKED_AT


def test_list_latest_signal_statuses_reuses_cached_results(monkeypatch):
    signal_key = "today-signal:e10:pack:below_expected:stable_trend:2026-04-12"
    call_count = {"execute": 0}

    class _FakeTable:
        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def range(self, *_args, **_kwargs):
            return self

        def execute(self):
            call_count["execute"] += 1

            class _Resp:
                data = [
                    {
                        "event_type": "today_signal_status_set",
                        "details": '{"scope":"today_queue_signal_status","signal_key":"%s","signal_status":"looked_at"}' % signal_key,
                        "owner": "lead@example.com",
                        "event_at": "2026-04-12T10:00:00Z",
                    }
                ]

            return _Resp()

    class _FakeClient:
        def table(self, name):
            assert name == "action_events"
            return _FakeTable()

    monkeypatch.setattr("services.today_signal_status_service.get_client", lambda: _FakeClient())
    monkeypatch.setattr("services.today_signal_status_service._LATEST_SIGNAL_STATUS_CACHE", {})

    first = list_latest_signal_statuses(signal_keys={signal_key}, tenant_id="tenant-a")
    second = list_latest_signal_statuses(signal_keys={signal_key}, tenant_id="tenant-a")

    assert first[signal_key]["status"] == SIGNAL_STATUS_LOOKED_AT
    assert second[signal_key]["status"] == SIGNAL_STATUS_LOOKED_AT
    assert call_count["execute"] == 1
