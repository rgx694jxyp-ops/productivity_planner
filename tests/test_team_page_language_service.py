from services.team_page_language_service import (
    format_chip_current_vs_target,
    format_chip_follow_up,
    format_chip_notes,
    format_chip_trend,
    format_comparison_text,
    clean_note_text_for_display,
    format_empty_state,
    format_note_entry,
    format_note_expand_label,
    format_note_preview_text,
    format_status_filter_option,
    format_timeline_description,
    format_timeline_entry,
    format_timeline_event,
    format_timeline_event_display,
    format_timeline_row_heading,
    format_trend_interpretation_limited_days,
    format_trend_interpretation_no_days,
    format_window_trend,
    get_team_filter_labels,
    get_team_section_titles,
)


def test_team_section_titles_and_filter_labels_are_available():
    titles = get_team_section_titles()
    labels = get_team_filter_labels()

    assert titles["page_title"] == "Team"
    assert titles["timeline"] == "Timeline"
    assert titles["trend"] == "Trend"
    assert titles["notes"] == "Notes"
    assert titles["comparison"] == "Department comparison"
    assert labels["window_label"] == "Time range (days)"
    assert labels["employee_placeholder"]


def test_status_filter_option_maps_internal_values_to_friendly_labels():
    assert format_status_filter_option("all") == "All statuses"
    assert format_status_filter_option("needs attention") == "Needs review"
    assert format_status_filter_option("stable") == "Holding steady"
    assert format_status_filter_option("improved recently") == "Improving"


def test_window_trend_fallback_and_directional_wording():
    assert "Not enough data" in format_window_trend(None, 14)
    assert "Holding steady" in format_window_trend(0.2, 14)
    assert "Improving over the last 14 days" in format_window_trend(3.2, 14)
    assert "(+3.2%)" in format_window_trend(3.2, 14)
    assert "Slipping over the last 14 days" in format_window_trend(-2.0, 14)
    assert "(-4.0%)" in format_window_trend(-4.0, 14)


def test_timeline_event_wording_avoids_raw_event_log_labels():
    assert format_timeline_event("follow_up_logged") == "Follow-up scheduled"
    assert format_timeline_event("coached") == "Added note"
    assert format_timeline_event("today_signal_status_set") == "Status updated"
    assert format_timeline_event("some_internal_code") == "Update added"
    assert format_timeline_event("", status="") == "Update added"


def test_timeline_entry_hides_internal_event_codes_and_reduces_noise():
    unknown = format_timeline_entry(
        source="action_event",
        event_type="today_signal_status_set_internal",
        raw_description="today signal status set internal",
    )
    assert unknown["label"] == "Update added"
    assert unknown["description"] == ""

    completion = format_timeline_entry(
        source="action_event",
        event_type="resolved",
        status="completed",
        action_id="a-1",
        raw_description="completed",
    )
    assert completion["label"] == "Issue marked as handled"
    assert completion["description"] == ""


def test_timeline_description_drops_duplicate_or_log_style_text():
    assert (
        format_timeline_description(
            source="action_event",
            event_label="Status updated",
            raw_description="status updated",
            event_type="today_signal_status_set",
        )
        == ""
    )
    assert (
        format_timeline_description(
            source="action_event",
            event_label="Update added",
            raw_description="activity logged",
            event_type="created",
        )
        == ""
    )


def test_comparison_text_preserves_meaning_with_plain_language():
    below = format_comparison_text(delta_pct=-10.0, share_below_target=0.6)
    above = format_comparison_text(delta_pct=10.0, share_below_target=0.1)
    aligned = format_comparison_text(delta_pct=1.0, share_below_target=None)

    assert "below department average" in below[0]
    assert "similar pattern across team" in below[0]
    assert "above department average" in above[0]
    assert "most of team at or above target" in above[0]
    assert "In line with department average" in aligned[0]


def test_empty_state_copy_is_human_and_specific():
    assert format_empty_state("no_team_records") == "No team records are available for this period yet."
    assert "Showing the full team list" in format_empty_state("no_filter_match")
    assert format_empty_state("no_notes") == "No notes for this employee yet."
    assert format_empty_state("no_timeline") == "No recent timeline updates for this employee."
    assert format_empty_state("unknown_time") == "Time not available"
    assert format_empty_state("some_unknown_key") == "Nothing to show here yet."


def test_note_wording_is_clean_and_factual():
    assert format_note_entry("2026-04-20 10:30", author="Alex") == "2026-04-20 10:30 - Alex"
    assert format_note_entry("2026-04-20 10:30") == "2026-04-20 10:30"
    assert format_note_preview_text("  Shift started late due to dock delay.  ") == "Shift started late due to dock delay."
    assert format_note_expand_label(2, when_text="2026-04-20 10:30") == "Show full note from 2026-04-20"


def test_clean_note_text_for_display_drops_system_debug_strings():
    assert clean_note_text_for_display("reason=Today queue completion follow_up_required=yes") == ""
    assert clean_note_text_for_display("signal_key=uph_below_target scope=team") == ""
    assert clean_note_text_for_display("tenant_id=abc123") == ""


def test_clean_note_text_for_display_removes_metadata_and_keeps_user_text():
    text = "Equipment issue during shift. Contact me at coach@example.com employee_id: EMP-2241"
    cleaned = clean_note_text_for_display(text)
    assert cleaned == "Equipment issue during shift"


def test_limited_data_wording_is_cautious_not_overconfident():
    assert "No daily performance records" in format_trend_interpretation_no_days()
    limited = format_trend_interpretation_limited_days(2)
    limited_lower = limited.lower()
    assert "only 2 day(s)" in limited_lower
    assert "direction may change" in limited_lower


def test_section_chips_and_heading_wording_stays_consistent():
    assert format_chip_current_vs_target("98.0 vs 100.0 UPH").startswith("Performance vs target:")
    assert format_chip_trend("Improving over the last 14 days").startswith("Recent direction:")
    assert format_chip_notes(0) == "Notes: none"
    assert format_chip_follow_up("Follow-up pending") == "Follow-up: Follow-up pending"
    heading = format_timeline_row_heading("2026-04-20 11:00", "Follow-up completed")
    assert "2026-04-20 11:00" in heading
    assert "Follow-up completed" in heading


def test_format_timeline_event_display_completed_returns_handled_sentence():
    result = format_timeline_event_display({"event_type": "resolved", "status": "", "action_id": "a-1"})
    assert result["title"] == "Issue marked as handled"
    assert result["description"] == ""

    result2 = format_timeline_event_display({"event_type": "follow_up_logged", "status": "completed", "action_id": ""})
    assert result2["title"] == "Issue marked as handled"
    assert result2["description"] == ""


def test_format_timeline_event_display_exception_opened_uses_fixed_sentence():
    result = format_timeline_event_display({"event_type": "exception_opened", "status": "open", "notes": "bad"})
    assert result["title"] == "Issue logged for tracking"
    assert result["description"] == "bad"


def test_format_timeline_event_display_follow_up_formats_due_date():
    result = format_timeline_event_display({
        "event_type": "follow_up_logged",
        "status": "",
        "next_follow_up_at": "2026-05-04T09:00",
    })
    assert result["title"] == "Follow-up scheduled for May 4 at 9:00 AM"
    assert result["description"] == ""


def test_format_timeline_event_display_follow_up_no_due_date_returns_empty():
    result = format_timeline_event_display({"event_type": "follow_up_logged", "status": "", "next_follow_up_at": ""})
    assert result["title"] == "Follow-up scheduled"
    assert result["description"] == ""


def test_format_timeline_event_display_coached_shows_note_text_only():
    result = format_timeline_event_display({
        "event_type": "coached",
        "notes": "Training",
    })
    assert result["title"] == "Added note: 'Training'"
    assert result["description"] == ""


def test_format_timeline_event_display_coached_strips_json_blob():
    result = format_timeline_event_display({
        "event_type": "coached",
        "notes": '{"signal_key": "uph_below_target", "scope": "team"}',
    })
    assert result["description"] == ""


def test_format_timeline_event_display_strips_reason_prefix_debug_text():
    result = format_timeline_event_display({
        "event_type": "created",
        "notes": "reason=Today queue completion follow_up_required=yes",
    })
    assert result["description"] == ""


def test_format_timeline_event_display_strips_signal_key_debug_text():
    result = format_timeline_event_display({
        "event_type": "today_signal_status_set",
        "notes": "signal_key=uph_below_target scope=team signal_status=flagged",
    })
    assert result["description"] == ""


def test_format_timeline_event_display_unknown_event_uses_clean_outcome():
    result = format_timeline_event_display({
        "event_type": "escalated",
        "outcome": "Escalation reviewed by shift lead.",
    })
    assert result["title"] == "Escalation logged"
    assert "Escalation reviewed by shift lead." in result["description"]


def test_format_timeline_event_display_skips_raw_status_words_as_outcome():
    result = format_timeline_event_display({
        "event_type": "created",
        "outcome": "logged",
    })
    assert result["description"] == ""


def test_format_timeline_event_display_follow_up_date_only():
    result = format_timeline_event_display({
        "event_type": "follow_up_logged",
        "next_follow_up_at": "2026-05-04",
    })
    assert result["title"] == "Follow-up scheduled for May 4"
    assert result["description"] == ""
