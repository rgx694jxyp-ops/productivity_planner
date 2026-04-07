"""Compatibility facade for split UI/Domain/Service modules.

This module preserves existing imports while implementations live in focused modules.
"""

from utils.numeric import (
    safe_float,
)
from ui.floor_language import (
    human_confidence_message,
    risk_to_human_language,
    translate_to_floor_language,
)
from services.coaching_service import (
    _enhance_coaching_feedback,
    _get_primary_recommendation,
    find_coaching_impact,
    summarize_coaching_activity,
)
from services.recommendation_service import _render_adaptive_action_suggestion
from domain.risk_scoring import _compute_priority_summary
from ui.components import (
    _apply_mode_styling,
    _render_breadcrumb,
    _render_confidence_ux,
    _render_session_context_bar,
    _render_session_progress,
    build_operation_status,
    detect_department_patterns,
    diagnose_upload,
    is_simple_mode,
    show_coaching_activity_summary,
    show_coaching_impact,
    show_diagnosis,
    show_manual_entry_form,
    show_operation_status_header,
    show_pattern_detection_panel,
    show_resume_session_card,
    show_shift_complete_state,
    show_start_shift_card,
    simplified_supervisor_view,
    toggle_simple_mode,
)
from ui.coaching_components import (
    _render_primary_action_rail,
    _render_priority_strip,
    _render_soft_action_buttons,
)

__all__ = [
    "safe_float",
    "human_confidence_message",
    "risk_to_human_language",
    "translate_to_floor_language",
    "_enhance_coaching_feedback",
    "_get_primary_recommendation",
    "find_coaching_impact",
    "summarize_coaching_activity",
    "_render_adaptive_action_suggestion",
    "_compute_priority_summary",
    "_apply_mode_styling",
    "_render_breadcrumb",
    "_render_confidence_ux",
    "_render_primary_action_rail",
    "_render_priority_strip",
    "_render_session_context_bar",
    "_render_session_progress",
    "_render_soft_action_buttons",
    "build_operation_status",
    "detect_department_patterns",
    "diagnose_upload",
    "is_simple_mode",
    "show_coaching_activity_summary",
    "show_coaching_impact",
    "show_diagnosis",
    "show_manual_entry_form",
    "show_operation_status_header",
    "show_pattern_detection_panel",
    "show_resume_session_card",
    "show_shift_complete_state",
    "show_start_shift_card",
    "simplified_supervisor_view",
    "toggle_simple_mode",
]
