# Team Page Language Audit

## Scope and Constraints
- Scope: language-only inventory for Team page rendering.
- No production code changes were made.
- No data flow, layout, query pattern, or performance behavior changes were made.
- Entry point audited: [pages/team.py](pages/team.py#L589), function `page_team()`.
- Imported text helper audited: [services/exception_tracking_service.py](services/exception_tracking_service.py#L120), function `build_exception_context_line()`.

## Render Entry Point and Text Producers
- Page entry point: `page_team()` in [pages/team.py](pages/team.py#L589).
- Primary text-producing helpers in [pages/team.py](pages/team.py):
  - `_roster_reason_text`
  - `_snapshot_follow_up_context`
  - `_roster_meta_text`
  - `_roster_row_label`
  - `_current_vs_target_text`
  - `_selected_window_trend_text`
  - `_open_follow_up_state_text`
  - `_selected_employee_summary_sentence`
  - `_trend_interpretation_sentence`
  - `_event_label_from_action_event`
  - `_timeline_when_text`
  - `_normalize_recent_activity_timeline`
  - `_normalize_notes_history`
  - `_exception_type_text`
  - `_normalize_exception_history`
  - `_department_comparison_context`
- External helper with visible output on Team page:
  - `build_exception_context_line` in [services/exception_tracking_service.py](services/exception_tracking_service.py#L120).

## Language Surface Table

| file | function | current text | where it appears on screen | type of text | why it is unclear / too technical / too system-driven |
|---|---|---|---|---|---|
| pages/team.py | page_team | Team | Top page heading | page title | Very short and generic; does not explain purpose of this page versus Today. |
| pages/team.py | page_team | Person-level context for recent performance, history, and prior notes. Operational actions remain on Today. | Hero caption under title | hero helper text | Uses internal framing ("person-level", "operational actions") and assumes user knows Today contract. |
| pages/team.py | page_team | No team records are available yet. | Early return when roster empty | empty state | Vague root cause; no cue whether data import, filters, or date window is the reason. |
| pages/team.py | page_team | Employee | Filter row input label | field label | Clear but minimal; may be too terse relative to behavior (name plus ID matching). |
| pages/team.py | page_team | Search employee | Employee search placeholder | field placeholder | Slightly generic; does not hint accepted terms (name, ID). |
| pages/team.py | page_team | Department | Filter select label | field label | Clear. |
| pages/team.py | page_team | Status | Filter select label | field label | Ambiguous because status is derived trend bucket, not operational status. |
| pages/team.py | page_team | Window | Time-window radio label | field label | Ambiguous unit context; user must infer this means days. |
| pages/team.py | page_team | No team members match the current filters. Showing the full roster instead. | Above roster when filter result empty | empty-state helper | System-driven fallback behavior is stated, but can surprise users (auto fallback) and is verbose. |
| pages/team.py | page_team | No selectable team members are available in the current roster. | When no rows have employee ID | empty state | Technical phrasing ("selectable") and "current roster" may feel system-centric. |
| pages/team.py | page_team | Roster | Left panel section title | section header | Clear, but generic. |
| pages/team.py | page_team | Filtered view | Under roster title | helper text | Generic; does not indicate which filters are active. |
| pages/team.py | page_team | {n} in view | Under roster radio list | counter/helper text | "in view" is vague (view vs total roster). |
| pages/team.py | page_team | {Department} | {Status} | Selected employee caption under name | subheader metadata | Pipe-separated metadata is compact but can feel dense; status label meaning is implicit. |
| pages/team.py | page_team | -> Today (button currently rendered as arrow glyph + Today) | Bridge control in selected employee card | button label | Symbol-only intent can be unclear for assistive tech and for first-time users. |
| pages/team.py | page_team | Use Today to act on this employee | Bridge helper caption | helper text | Imperative/system-driven wording; references product architecture instead of user outcome. |
| pages/team.py | page_team | Current vs target: {value} | Chip row | chip/badge | Comparison shorthand can be opaque without metric unit or source date. |
| pages/team.py | page_team | Window trend: {value} | Chip row | chip/badge | "Window" is technical shorthand; direction math may be hard to parse quickly. |
| pages/team.py | page_team | Notes in view: {count} | Chip row | chip/badge | "in view" is UI-centric, not user-centric. |
| pages/team.py | page_team | Notes in view: none shown | Chip row | chip/badge empty | "none shown" is system phrasing; unclear if none exist or filtered out. |
| pages/team.py | page_team | {follow_up_state_text} | Chip row | chip/badge | Inherits technical language from follow-up helper; may read as system status. |
| pages/team.py | page_team | Recent signal: {trend_state} | Goal state: {goal_state} | Below chip row | status summary | "signal" and "goal state" are model/system terms; low plain-language clarity. |
| pages/team.py | page_team | Trend | Main right column section | section header | Clear. |
| pages/team.py | page_team | Last {days} days of observed history. | Trend section intro | helper text | "observed history" is analytical/system framing rather than plain language. |
| pages/team.py | page_team | No observed daily points are available in this view. | Trend chart empty | empty state | Technical phrase ("daily points"); "in this view" appears repeatedly and can feel UI-jargon-heavy. |
| pages/team.py | page_team | No historical points are available in this view. | Trend section empty | empty state | Similar technical phrasing and repeated "in this view" language. |
| pages/team.py | page_team | Timeline | Timeline section title | section header | Clear. |
| pages/team.py | page_team | No recent history is available in this view. | Timeline empty | empty state | Generic and repetitive; "history" type is unclear (notes/actions/exceptions). |
| pages/team.py | page_team | **{when_text}** | {event_type} | Timeline row heading | timeline row | Dense delimiter format; mixed timestamp and event can be hard to scan. |
| pages/team.py | page_team | {description} | Timeline row caption | timeline detail | Freeform; quality depends on upstream content, not always plain-language normalized. |
| pages/team.py | page_team | Notes | Notes section title | section header | Clear. |
| pages/team.py | page_team | No prior notes are available in this view. | Notes empty | empty state | Repeats "in this view" UI-centric phrasing; no cause/context. |
| pages/team.py | page_team | **{when_text} | {author}** | Notes row heading | note metadata | Pipe delimiter is compact but less readable for quick scan; no label words (date/author). |
| pages/team.py | page_team | Open full note #{index} | Notes expander label | expander/action label | System-style indexing (#) rather than semantic label (example: date). |
| pages/team.py | page_team | Show older notes ({remaining}) | Notes expander label | expander/action label | Clear enough, but list-centric language over user intent. |
| pages/team.py | page_team | Exceptions | Exceptions section title | section header | Clear. |
| pages/team.py | page_team | No recent exceptions are available in this view. | Exceptions empty | empty state | Repeats "in this view" pattern; could be more explicit on timeframe/source. |
| pages/team.py | page_team | {context_text} | Exceptions row caption | exception metadata | Often pipe-delimited machine-like context string from helper; may feel too technical. |
| pages/team.py | page_team | {exception_type} | Exceptions row title | exception label | Category title can be system taxonomy text, not always user language. |
| pages/team.py | page_team | Open exception detail #{index} | Exceptions expander label | expander/action label | Indexed label is system-oriented and less meaningful than date/category reference. |
| pages/team.py | page_team | Show older exceptions ({remaining}) | Exceptions expander label | expander/action label | Clear enough, but still list/system-centric phrasing. |
| pages/team.py | page_team | Comparison Context | Final section title | section header | Abstract and technical; "context" lacks explicit meaning. |
| pages/team.py | _team_status_bucket | improved recently | Status filter option and roster trend label | status bucket/chip text | Relative phrase without baseline definition; can be interpreted inconsistently. |
| pages/team.py | _team_status_bucket | needs attention | Status filter option and status label | status bucket/chip text | Directive undertone and managerial framing; may conflict with descriptive posture. |
| pages/team.py | _team_status_bucket | stable | Status filter option and status label | status bucket/chip text | Can mask weak/noisy data; lacks confidence cue. |
| pages/team.py | _roster_reason_text | down {x}% vs recent baseline | Roster row subtitle fallback | trend helper text | Analytical shorthand with undefined baseline window. |
| pages/team.py | _roster_reason_text | recent improvement ({x}% vs baseline) | Roster row subtitle fallback | trend helper text | "baseline" is undefined; percent context may be unclear. |
| pages/team.py | _roster_reason_text | variable trend | Roster row subtitle fallback | trend helper text | Vague without reason or confidence qualifier. |
| pages/team.py | _roster_reason_text | recent improvement | Roster row subtitle fallback | trend helper text | Improvement claim lacks comparator and timeframe details. |
| pages/team.py | _roster_reason_text | performance is below recent baseline | Roster row subtitle fallback | trend helper text | "baseline" not user-facing defined; can feel model-driven. |
| pages/team.py | _roster_reason_text | stable vs recent baseline | Roster row subtitle fallback | trend helper text | Same undefined-baseline issue; terse analytic phrase. |
| pages/team.py | _snapshot_follow_up_context | follow-up context: timing appears overdue (due {date}) | Selected employee chip/text and summary sentence | follow-up status/helper | Prefix "follow-up context" reads like system metadata rather than direct user language. |
| pages/team.py | _snapshot_follow_up_context | follow-up context: timing is pending (due {date}) | Selected employee chip/text and summary sentence | follow-up status/helper | Same system-framed prefix; "pending" lacks actor/next-step context. |
| pages/team.py | _snapshot_follow_up_context | follow-up context: timing is marked as pending | Selected employee chip/text and summary sentence | follow-up status/helper | Passive/system wording ("is marked") rather than plain statement. |
| pages/team.py | _snapshot_follow_up_context | follow-up context: recent note/follow-up activity ({date}) | Selected employee chip/text and summary sentence | follow-up status/helper | Compound noun phrase is dense and system-like. |
| pages/team.py | _snapshot_follow_up_context | follow-up overdue ({date}) | Roster metadata and chips | badge/chip text | Clearer than summary variants, but still data-centric without source recency cue. |
| pages/team.py | _snapshot_follow_up_context | follow-up pending ({date}) | Roster metadata and chips | badge/chip text | Clear but might imply action expectation. |
| pages/team.py | _snapshot_follow_up_context | follow-up pending | Roster metadata and chips | badge/chip text | No date or confidence context. |
| pages/team.py | _snapshot_follow_up_context | recent follow-up context ({date}) | Roster metadata and chips | badge/chip text | "context" is abstract jargon. |
| pages/team.py | _roster_meta_text | confidence {label} | Roster metadata fallback | badge/chip text | Confidence value source/model not explained here. |
| pages/team.py | _roster_meta_text | data {status} | Roster metadata fallback | badge/chip text | Highly system-driven shorthand. |
| pages/team.py | _roster_row_label | {name}\n{department} · {trend_label} · {meta/reason} | Each roster radio option label | roster row label | Dense multi-field formatting; no explicit labels, relies on user inference. |
| pages/team.py | _current_vs_target_text | no current vs target shown | Current-vs-target chip value | chip fallback | System phrasing; sounds like rendering failure rather than data condition. |
| pages/team.py | _current_vs_target_text | target {x} | Current-vs-target chip value | chip value | Missing unit and context date. |
| pages/team.py | _current_vs_target_text | current {x} | Current-vs-target chip value | chip value | Missing unit and context date. |
| pages/team.py | _current_vs_target_text | {current} vs {target} | Current-vs-target chip value | chip value | Compact but ambiguous without units. |
| pages/team.py | _selected_window_trend_text | {days}-day trend not shown | Window trend chip value | chip fallback | UI/system wording ("not shown") instead of data explanation. |
| pages/team.py | _selected_window_trend_text | {days}-day up/down/flat ({pct}) | Window trend chip value | trend chip | Analytical shorthand; may require interpretation literacy. |
| pages/team.py | _open_follow_up_state_text | follow-up context is not shown in this snapshot | Follow-up chip and summary sentence | follow-up empty/fallback | System/rendering-centric wording ("not shown", "snapshot"). |
| pages/team.py | _selected_employee_summary_sentence | Stable in recent data. | Main selected-employee summary paragraph | summary sentence | Generic and low-information for decision support. |
| pages/team.py | _selected_employee_summary_sentence | Below target in recent data. | Main summary paragraph | summary sentence | May feel evaluative without confidence qualifiers. |
| pages/team.py | _selected_employee_summary_sentence | Recent performance needs attention. | Main summary paragraph | summary sentence | Directive/managerial tone ("needs attention"). |
| pages/team.py | _selected_employee_summary_sentence | Recent improvement is visible in the selected window. | Main summary paragraph | summary sentence | "selected window" is UI jargon; lacks explicit comparison anchor. |
| pages/team.py | _selected_employee_summary_sentence | {n} prior note(s) in this view | Main summary paragraph | note count helper | Repeated "in this view" system phrasing. |
| pages/team.py | _trend_interpretation_sentence | No observed days are available in the selected window yet. | Trend interpretation caption | trend interpretation empty | Technical terms ("observed days", "selected window"). |
| pages/team.py | _trend_interpretation_sentence | {n} observed day(s)... trend confidence is still limited. | Trend interpretation caption | trend interpretation | Confidence phrase is useful but still model/analytics jargon-heavy. |
| pages/team.py | _trend_interpretation_sentence | Trend is improving, but remains below target on {x} of the last {n} observed days. | Trend interpretation caption | trend interpretation | Dense metric sentence; "observed days" repeated. |
| pages/team.py | _trend_interpretation_sentence | Recent dip appears limited to the last 2 observed days. | Trend interpretation caption | trend interpretation | "appears" plus hard-coded 2-day analytic heuristic can sound model-driven. |
| pages/team.py | _trend_interpretation_sentence | Performance has been below target on {x} of the last {n} observed days. | Trend interpretation caption | trend interpretation | Accurate but heavy analytic phrasing. |
| pages/team.py | _trend_interpretation_sentence | Performance is above target and improving across the selected window. | Trend interpretation caption | trend interpretation | "selected window" jargon. |
| pages/team.py | _trend_interpretation_sentence | Performance remains above target, but has softened recently. | Trend interpretation caption | trend interpretation | "softened" is interpretive and may be ambiguous. |
| pages/team.py | _trend_interpretation_sentence | Performance has stayed near or above target in the selected window. | Trend interpretation caption | trend interpretation | "selected window" jargon. |
| pages/team.py | _trend_interpretation_sentence | Performance trend is improving across the selected window. | Trend interpretation caption | trend interpretation | Repetitive analytic framing. |
| pages/team.py | _trend_interpretation_sentence | Performance trend is declining across the selected window. | Trend interpretation caption | trend interpretation | Repetitive analytic framing. |
| pages/team.py | _trend_interpretation_sentence | Performance appears relatively stable in the selected window. | Trend interpretation caption | trend interpretation | Hedged and generic; low specificity. |
| pages/team.py | _event_label_from_action_event | Follow-up set | Timeline event type | timeline event label | "set" can be ambiguous (scheduled vs completed). |
| pages/team.py | _event_label_from_action_event | Coached / Recognized / Escalated / Deprioritized / Reopened | Timeline event type | timeline event label | Some terms are process/system terms and may not match supervisor vocabulary. |
| pages/team.py | _event_label_from_action_event | Action completed | Timeline event type | timeline event label | "Action" is generic and system-like. |
| pages/team.py | _event_label_from_action_event | Follow-up completed | Timeline event type | timeline event label | Clearer but still process-centric. |
| pages/team.py | _event_label_from_action_event | Activity logged | Timeline event type fallback | timeline event label | System-generated tone; low user meaning. |
| pages/team.py | _timeline_when_text | Unknown time | Timeline row when fallback | timeline fallback | Generic fallback with no confidence/source hint. |
| pages/team.py | _normalize_recent_activity_timeline | Note added | Timeline row event type for notes | timeline event label | Clear. |
| pages/team.py | _normalize_recent_activity_timeline | Activity recorded | Timeline action description fallback | timeline description fallback | System-generated wording, low specificity. |
| pages/team.py | _normalize_recent_activity_timeline | Exception resolved | Timeline event type | timeline event label | Clear but depends on status heuristics not shown to user. |
| pages/team.py | _normalize_recent_activity_timeline | Exception logged | Timeline event type | timeline event label | Clear but system/process framing. |
| pages/team.py | _normalize_recent_activity_timeline | Exception recorded | Timeline exception description fallback | timeline description fallback | System fallback wording, low clarity. |
| pages/team.py | _normalize_notes_history | Unknown date | Note row date fallback | note metadata fallback | Generic fallback; no indication why date missing. |
| pages/team.py | _exception_type_text | Operational exception | Exceptions row type fallback | exception type fallback | Broad/system category, low detail. |
| pages/team.py | _normalize_exception_history | Unknown date | Exception row date fallback | exception metadata fallback | Generic fallback with no source cue. |
| pages/team.py | _department_comparison_context | Current average is {x}% below the department median in the latest snapshot. | Comparison Context caption | comparison text | Heavy statistical phrasing; "latest snapshot" is system terminology. |
| pages/team.py | _department_comparison_context | Current average is {x}% above the department median in the latest snapshot. | Comparison Context caption | comparison text | Same statistical/system framing. |
| pages/team.py | _department_comparison_context | Current average is broadly aligned with the department median in the latest snapshot. | Comparison Context caption | comparison text | Ambiguous qualifier ("broadly aligned"). |
| pages/team.py | _department_comparison_context | More than half of comparable employees in this department are also below target. | Comparison Context caption | comparison text | "comparable employees" criteria not visible; sounds model-selected. |
| pages/team.py | _department_comparison_context | Most comparable employees in this department are currently at or above target. | Comparison Context caption | comparison text | Same comparability transparency issue. |
| services/exception_tracking_service.py | build_exception_context_line | {exception_date} | {shift} | {process_name} | {category} | Exception row context caption | exception context line | Pipe-joined raw fields read like backend metadata, not polished user language. |

## Coverage Notes
- The table includes all explicit user-facing literals and key dynamic patterns rendered on Team.
- User-generated content shown on Team is also surfaced (notes text, timeline descriptions, exception summaries), but those are content payloads rather than authored UI copy.
- Style-only content in `_render_team_page_styles()` was intentionally excluded because it is not wording.

## High-Level Language Pattern Findings
- Repeated system/UI-centric phrasing: "in this view", "selected window", "latest snapshot", "observed days", "not shown".
- Analytical shorthand without plain-language framing in chips and trend/comparison lines.
- Several labels are generic (for example: "Status", "Window", "Comparison Context") and may require product familiarity.
- Timeline and exception lines use delimiter-heavy formats (`|`) that prioritize compactness over readability.
- Some status language is managerial/evaluative (for example: "needs attention") rather than descriptive.
