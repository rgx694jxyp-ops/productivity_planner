from pages.today import _render_today_low_data_fallback
from services.today_view_model_service import TodayLowDataFallbackViewModel, build_today_low_data_fallback_view_model


def test_low_data_fallback_triggers_with_limited_history_and_low_rows():
    fallback = build_today_low_data_fallback_view_model(
        goal_status=[
            {"Employee": "Riley", "Average UPH": 62, "change_pct": None, "trend": "insufficient_data"},
            {"Employee": "Sam", "Average UPH": 41, "change_pct": None, "trend": "insufficient_data"},
        ],
        import_summary={"days": 2, "valid_rows": 8},
    )

    assert fallback is not None
    assert fallback.mode_label == "Early signal mode"
    assert fallback.bullets == [
        "Riley leading at 62 UPH",
        "Sam lowest at 41 UPH",
        "Wide gap between top and lowest performance",
    ]
    assert fallback.explanation_line == "Early signal only - limited recent data"


def test_low_data_fallback_triggers_when_no_reliable_trend_exists():
    fallback = build_today_low_data_fallback_view_model(
        goal_status=[
            {"Employee": "Riley", "Average UPH": 62, "trend": "insufficient_data", "confidence_label": "low"},
            {"Employee": "Sam", "Average UPH": 41, "trend": "", "confidence_label": "low"},
        ],
        import_summary={"days": 4, "valid_rows": 24},
    )

    assert fallback is not None
    assert fallback.mode_label == "Early signal mode"


def test_low_data_fallback_suppresses_gap_line_when_variance_is_small():
    fallback = build_today_low_data_fallback_view_model(
        goal_status=[
            {"Employee": "Riley", "Average UPH": 62, "trend": "insufficient_data", "confidence_label": "low"},
            {"Employee": "Sam", "Average UPH": 58, "trend": "", "confidence_label": "low"},
        ],
        import_summary={"days": 2, "valid_rows": 10},
    )

    assert fallback is not None
    assert fallback.bullets == [
        "Riley leading at 62 UPH",
        "Sam lowest at 58 UPH",
    ]


def test_low_data_fallback_returns_none_when_data_is_stable():
    fallback = build_today_low_data_fallback_view_model(
        goal_status=[
            {"Employee": "Riley", "Average UPH": 62, "change_pct": -8.0, "trend": "down", "confidence_label": "medium"},
            {"Employee": "Sam", "Average UPH": 41, "change_pct": 6.0, "trend": "up", "confidence_label": "medium"},
        ],
        import_summary={"days": 5, "valid_rows": 30},
    )

    assert fallback is None


def test_render_low_data_fallback_shows_clean_bullets_and_no_banned_text(monkeypatch):
    rendered: list[str] = []
    monkeypatch.setattr("pages.today.st.markdown", lambda text, **_kwargs: rendered.append(str(text)))

    _render_today_low_data_fallback(
        TodayLowDataFallbackViewModel(
            mode_label="Early signal mode",
            bullets=[
                "Riley leading at 62 UPH",
                "Sam lowest at 41 UPH",
                "Wide gap between top and lowest performance",
            ],
            explanation_line="Early signal only - limited recent data",
        )
    )

    payload = "\n".join(rendered).lower()
    assert "today (early signal mode)" in payload
    assert "riley leading at 62 uph" in payload
    assert "sam lowest at 41 uph" in payload
    assert "wide gap between top and lowest performance" in payload
    assert "not enough data" not in payload
    assert "insufficient data" not in payload
    assert "declining" not in payload
    assert "improving" not in payload
    assert "%" not in payload