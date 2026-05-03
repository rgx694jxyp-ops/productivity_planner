from pages.today import _render_attention_summary_strip, _render_manager_loop_strip
from services.today_view_model_service import TodayAttentionStripViewModel, TodayManagerLoopStripViewModel


class _Column:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_attention_strip_renders_same_day_metrics_when_present(monkeypatch):
    labels: list[tuple[str, int]] = []
    monkeypatch.setattr("pages.today.st.columns", lambda n: [_Column() for _ in range(n)])
    monkeypatch.setattr("pages.today.st.metric", lambda label, value: labels.append((str(label), int(value))))

    _render_attention_summary_strip(
        TodayAttentionStripViewModel(
            total_needing_attention=5,
            new_today=2,
            overdue_follow_ups=1,
            reviewed_today=3,
            touchpoints_logged_today=2,
            follow_ups_scheduled_today=1,
        )
    )

    assert labels == [
        ("Needing attention", 5),
        ("New today", 2),
        ("Overdue follow-ups", 1),
        ("Reviewed today", 3),
        ("Touchpoints logged", 2),
        ("Follow-ups set", 1),
    ]


def test_attention_strip_keeps_no_activity_state_compact(monkeypatch):
    labels: list[tuple[str, int]] = []
    monkeypatch.setattr("pages.today.st.columns", lambda n: [_Column() for _ in range(n)])
    monkeypatch.setattr("pages.today.st.metric", lambda label, value: labels.append((str(label), int(value))))

    _render_attention_summary_strip(
        TodayAttentionStripViewModel(
            total_needing_attention=5,
            new_today=2,
            overdue_follow_ups=1,
            reviewed_today=None,
            touchpoints_logged_today=None,
            follow_ups_scheduled_today=None,
        )
    )

    assert labels == [
        ("Needing attention", 5),
        ("New today", 2),
        ("Overdue follow-ups", 1),
    ]


def test_manager_loop_strip_renders_when_metrics_exist(monkeypatch):
    labels: list[str] = []
    values: list[str] = []

    monkeypatch.setattr("pages.today.st.columns", lambda n: [_Column() for _ in range(n)])
    monkeypatch.setattr("pages.today.st.container", lambda **kwargs: _Column())
    monkeypatch.setattr("pages.today.st.caption", lambda text, **kwargs: labels.append(str(text)))
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **kwargs: values.append(str(text)))

    _render_manager_loop_strip(
        TodayManagerLoopStripViewModel(
            open_loops=7,
            due_today=2,
            overdue=1,
            improved=3,
            no_action_yet=4,
        )
    )

    assert labels[-5:] == ["Open loops", "Due today", "Overdue", "Improved", "No action yet"]
    joined = "\n".join(values)
    assert "**7**" in joined
    assert "**2**" in joined
    assert "**1**" in joined
    assert "**3**" in joined
    assert "**4**" in joined


def test_manager_loop_strip_noops_when_metrics_missing(monkeypatch):
    calls = {"columns": 0, "caption": 0, "markdown": 0}

    def _columns(n):
        calls["columns"] += 1
        return [_Column() for _ in range(n)]

    monkeypatch.setattr("pages.today.st.columns", _columns)
    monkeypatch.setattr("pages.today.st.caption", lambda *args, **kwargs: calls.__setitem__("caption", calls["caption"] + 1))
    monkeypatch.setattr("pages.today.st.markdown", lambda *args, **kwargs: calls.__setitem__("markdown", calls["markdown"] + 1))

    _render_manager_loop_strip(None)

    assert calls["columns"] == 0
    assert calls["caption"] == 0
    assert calls["markdown"] == 0