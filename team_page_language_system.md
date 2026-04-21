# Team Page Language System

## Purpose
This document defines the target wording system for the Team page.

Role split:
- Team page role: understand
- Today page role: act

This is a planning document only. It does not change layout, data flow, query patterns, performance behavior, or page structure.

## Product Philosophy Anchors
- Highlight, do not dictate
- Trust is more important than perfect precision
- Meaning is more important than raw metrics
- Fast scan for supervisors
- Decision tool, not a report

## 1. Page-Level Tone Rules
1. Use plain operational language, not product-internal language.
2. Keep most lines to one short sentence.
3. Lead with what changed or what stands out.
4. Add context only when it helps a decision.
5. Use descriptive wording, not prescriptive wording.
6. Avoid managerial commands and coaching directives.
7. Avoid system framing words such as view, snapshot, observed points, model terms.
8. Prefer specific nouns over abstract nouns.

Allowed style examples:
- Recent pattern is below target.
- Follow-up is overdue since 2026-04-18.
- No recent notes for this employee.

Avoid style examples:
- No historical points are available in this view.
- Performance appears relatively stable in the selected window.
- Use Today to act on this employee.

## 2. Writing Rules for Labels and Chips
1. Labels must be explicit about meaning, not UI mechanics.
2. Chips should be scan-first: short, concrete, and comparable.
3. Include unit or frame when needed for interpretation.
4. Avoid shorthand that depends on hidden assumptions.
5. Avoid terms such as in view, selected window, not shown.

Label rules:
- Employee field should indicate acceptable input in placeholder.
- Status label should map to plain meaning, not internal buckets.
- Window label should include day unit.

Chip rules:
- Pattern: Signal name: plain value
- Keep to 2 to 6 words after the colon when possible.
- If data is missing, state why in plain words.

Examples:
- Output vs target: 82 vs 100 UPH
- 14-day trend: down 8%
- Notes: 3 recent
- Follow-up: overdue since 2026-04-18

## 3. Writing Rules for Trends
1. Start with direction and impact, then evidence count.
2. Use stable comparison anchors and name them plainly.
3. Keep confidence cues short and explicit.
4. Do not over-interpret limited data.
5. Avoid technical analytics language unless translated.

Trend sentence pattern:
- Main line: Direction + target relation
- Optional second line: Evidence count or confidence note

Examples:
- Trend is improving but still below target.
- Trend is near target with low day-to-day change.
- Direction is unclear with only 2 days of data.

Disallowed patterns:
- observed day(s)
- selected window
- broadly aligned
- softened recently without evidence framing

## 4. Writing Rules for Timeline Events
1. Event names should describe what happened in operational terms.
2. Timestamp and event text should be easy to scan.
3. Remove event-log tone such as logged or recorded unless no better source exists.
4. Use consistent past-tense event labels.
5. Keep fallback labels human-readable and meaningful.

Event label system:
- Follow-up created
- Follow-up completed
- Coaching note added
- Recognition recorded
- Escalation opened
- Escalation reopened
- Exception opened
- Exception resolved
- Update added

Timeline row format:
- Time line: date and time
- Event line: short event label
- Detail line: one short supporting sentence

## 5. Writing Rules for Notes and History
1. Notes copy should emphasize continuity and context.
2. Avoid UI-centric phrasing such as open full note number 3.
3. Expanders should reference meaning or date, not index only.
4. Empty states should explain absence without blame.

Preferred patterns:
- Notes history
- No recent notes for this employee.
- Show full note from 2026-04-18
- Show older notes

Avoid patterns:
- No prior notes are available in this view.
- Open full note #3

## 6. Writing Rules for Exceptions and Context
1. Exception text should state event type, operational context, and status clearly.
2. Replace pipe-joined metadata style with natural phrase order.
3. Category names should be user-facing where possible.
4. If details are missing, use plain fallback language.

Context format target:
- Date, shift, process, exception type
- Example: 2026-04-18, Shift B, Packing, Scanner issue

Exception copy targets:
- Exception type as plain label
- One-line context summary
- One-line detail summary

Avoid:
- raw category keys
- dense symbol-delimited metadata strings

## 7. Writing Rules for Comparison Text
1. Keep comparison language practical and specific.
2. Always state comparison group in plain terms.
3. Avoid abstract statistical wording.
4. Avoid hidden methodology terms such as comparable employees unless defined.
5. Add short qualifier when confidence or sample is limited.

Comparison sentence pattern:
- Current level versus department midpoint
- Optional second sentence about how common this pattern is

Examples:
- Current output is 8% below the department midpoint.
- This pattern is common in the department this week.
- Current output is close to the department midpoint.

Avoid:
- broadly aligned
- latest snapshot without user meaning
- comparable employees without criteria

## 8. Writing Rules for Empty States
1. State what is missing in plain language.
2. Give the most likely non-technical reason.
3. Avoid implying a UI rendering problem.
4. Keep empty-state text to one sentence when possible.
5. Do not issue commands.

Empty-state templates:
- No team data yet for this period.
- No employees match these filters.
- No trend data for the selected time range.
- No recent timeline activity for this employee.
- No recent exceptions for this employee.

Avoid:
- no points are available in this view
- not shown in this snapshot
- selectable records are unavailable

## 9. Before and After Examples for Unclear Wording

| Surface | Before | After | Why this improves clarity |
|---|---|---|---|
| Hero caption | Person-level context for recent performance, history, and prior notes. Operational actions remain on Today. | Understand recent performance and history for each employee. Use Today for follow-through actions. | Keeps role split but removes internal/system phrasing. |
| Filter label | Window | Time range (days) | Makes unit explicit and scan-friendly. |
| Filter empty state | No team members match the current filters. Showing the full roster instead. | No employees match these filters. Showing all employees instead. | Plain language, less system tone. |
| Bridge helper | Use Today to act on this employee | Open Today to continue follow-through for this employee | Less directive and more operationally specific. |
| Chip fallback | no current vs target shown | Output and target are not available yet | Explains data condition, not render condition. |
| Trend chip | 14-day trend not shown | No trend data for the last 14 days | Plain meaning, no UI phrasing. |
| Follow-up helper | follow-up context is not shown in this snapshot | Follow-up timing is not available in current data | Removes snapshot/render jargon. |
| Trend interpretation | No observed days are available in the selected window yet. | No daily trend data in this time range yet. | Shorter and less technical. |
| Trend interpretation | Trend is improving, but remains below target on 5 of the last 7 observed days. | Trend is improving, but output is still below target on 5 of the last 7 days. | Keeps evidence, removes analytics jargon. |
| Timeline fallback | Activity logged | Update added | Less event-log wording and easier to read. |
| Timeline fallback | Unknown time | Time not available | Clearer reason framing. |
| Notes empty state | No prior notes are available in this view. | No recent notes for this employee. | Removes UI-centric phrasing and sharpens scope. |
| Notes expander | Open full note #3 | Show full note from 2026-04-18 | Meaningful reference replaces index-only wording. |
| Exceptions empty state | No recent exceptions are available in this view. | No recent exceptions for this employee. | Simpler and scope-specific. |
| Comparison header | Comparison Context | Team comparison | More concrete, easier to scan. |
| Comparison sentence | Current average is broadly aligned with the department median in the latest snapshot. | Current output is close to the department midpoint. | Removes abstract and system terminology. |

## Rewrite Plan by Surface Area

Phase 1: Foundation copy updates
- Page title and hero text
- Filter labels and placeholders
- Core section headers

Phase 2: High-impact scan surfaces
- Chips and status summaries
- Trend section intro and interpretation lines
- Timeline event labels and fallback labels

Phase 3: Context and long-tail surfaces
- Notes and exceptions empty states
- Expander labels
- Comparison header and comparison sentences
- Exception context formatting language

Phase 4: Consistency pass
- Remove remaining system/internal phrasing patterns
- Verify non-prescriptive tone across all text paths
- Ensure wording remains short and scanable in all states

## Guardrails for Implementation Later
- Keep existing logic and query behavior unchanged.
- Change wording only, not computation.
- Preserve state keys and event types unless a display map is added.
- Prefer display-mapping layers over changing source event payloads.
- Validate copy in empty, partial, and full-data states.
