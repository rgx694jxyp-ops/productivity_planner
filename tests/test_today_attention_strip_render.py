from pages.today import _render_attention_summary_strip
from services.today_view_model_service import TodayAttentionStripViewModel


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