# Team Page Language Rewrite: Implementation Plan

## Goal
Implement a maintainable Team page wording system with centralized formatting, while keeping behavior and data semantics unchanged.

Scope for implementation phase:
- Presentation-only text rewrite
- No layout changes
- No query or data-flow changes
- No performance behavior changes
- No state-key or navigation-contract changes

## Recommended Architecture

### Recommendation
Use a dedicated formatter module and refactor existing Team text helpers to delegate to it.

Why this is the cleanest approach:
- Current Team wording is spread across many inline strings and local helpers in [pages/team.py](pages/team.py).
- Project already uses centralized wording/formatting services (for example [services/signal_formatting_service.py](services/signal_formatting_service.py), [services/plain_language_service.py](services/plain_language_service.py)).
- A dedicated Team formatter keeps copy decisions in one place and avoids growing [pages/team.py](pages/team.py) further.
- This allows incremental migration without changing data logic.

### Decision on options requested
- Add helper functions to existing Team service/module: partially
  - Keep existing data/normalization helpers in [pages/team.py](pages/team.py) for now.
  - Do not move business logic into existing process services.
- Create dedicated formatter module: yes (primary recommendation)
- Refactor existing formatting helpers: yes (delegate wording to new module)

## File Change Plan

### New files
1. [services/team_page_language_service.py](services/team_page_language_service.py)
- Central source of Team page display copy and formatting adapters.
- Contains section titles, labels, empty states, and text-formatting functions.

2. [tests/test_team_page_language_service.py](tests/test_team_page_language_service.py)
- Unit tests for copy formatting behavior and fallback wording.
- Ensures presentation-only rewrites remain stable.

### Existing files to update
1. [pages/team.py](pages/team.py)
- Replace inline literals with calls to language service functions.
- Keep all branching, filtering, state mutation, and data-query behavior identical.
- Keep existing helper signatures where practical; switch return text source only.

2. [team_page_language_system.md](team_page_language_system.md)
- Optional: add a short "implemented mapping" appendix after coding pass (documentation only).

## Proposed Helper Function Categories

Implement the following in [services/team_page_language_service.py](services/team_page_language_service.py):

### Section and labels
- `get_team_section_titles() -> dict[str, str]`
  - Keys like `page_title`, `roster`, `trend`, `timeline`, `notes`, `exceptions`, `comparison`.
- `get_team_filter_labels() -> dict[str, str]`
  - `employee_label`, `employee_placeholder`, `department_label`, `status_label`, `window_label`.

### Chips and status text
- `format_trend_label(status_bucket: str) -> str`
  - Maps internal buckets to plain display labels.
- `format_current_vs_target(avg_uph: float | None, target_uph: float | None) -> str`
- `format_window_trend(change_pct: float | None, days: int) -> str`
- `format_follow_up_chip(follow_up_context: dict[str, str] | None) -> str`
- `format_selected_summary(...) -> str`

### Timeline
- `format_timeline_event(event_type: str, status: str = "", action_id: str = "") -> str`
- `format_timeline_description_fallback(source: str) -> str`
- `format_timeline_when_fallback() -> str`

### Notes/history
- `format_note_entry_header(when_text: str, author: str = "") -> str`
- `format_note_expand_label(index: int, when_text: str = "") -> str`
- `format_notes_empty_state() -> str`

### Exceptions/context
- `format_exception_text(exception_type: str) -> str`
- `format_exception_context_line(exception_date: str, shift: str, process_name: str, category: str) -> str`
- `format_exception_expand_label(index: int, when_text: str = "") -> str`
- `format_exceptions_empty_state() -> str`

### Comparison
- `format_comparison_text(delta_pct: float, below_target_share: float | None = None) -> list[str]`
  - Returns one or two display lines, preserving existing semantics.

### Empty states (shared)
- `format_empty_state(kind: str, **kwargs) -> str`
  - Centralized literals for all Team empty-state messages.

## Existing Inline Strings to Replace (High Priority)

Replace direct literals in [pages/team.py](pages/team.py) with formatter calls for:
- Page title and hero caption
- Filter labels/placeholders
- Roster captions and counters
- Team-to-Today helper caption
- Chip labels and fallbacks
- Trend section helper and all trend interpretation strings
- Timeline heading labels and fallback event words
- Notes headings/expanders/empty states
- Exceptions headings/expanders/empty states
- Comparison section title and generated comparison sentences
- Generic unknown fallbacks (time/date/type)

## Mapping Strategy (No Behavior Changes)

1. Preserve decision logic, replace wording only.
- Keep all condition branches and thresholds as-is.
- Keep all return types and function signatures stable where feasible.

2. Keep data semantics unchanged.
- Internal buckets like `needs attention`, `stable`, `improved recently` can remain as internal values.
- Convert to new display labels at render boundary.

3. Keep state and navigation contracts unchanged.
- Do not change `st.session_state` keys.
- Do not change Team-to-Today bridge data writes.

4. Keep query and performance behavior unchanged.
- No new queries.
- No additional expensive computations.
- Formatter functions must be pure and lightweight.

5. Keep event payloads unchanged.
- Do not mutate raw timeline/note/exception source rows.
- Format display text only.

## Migration Steps

### Step 1: Add formatter service (no page changes yet)
- Create [services/team_page_language_service.py](services/team_page_language_service.py) with constants + pure functions.
- Add tests in [tests/test_team_page_language_service.py](tests/test_team_page_language_service.py).

### Step 2: Integrate section-level strings
- Replace page headers, section titles, and filter labels in [pages/team.py](pages/team.py).
- Validate no behavior deltas.

### Step 3: Integrate helper-return strings
- Update existing Team helper functions to call formatter service.
- Keep helper inputs/outputs structurally the same.

### Step 4: Integrate timeline/notes/exceptions/comparison wording
- Replace remaining inline strings and fallback text.
- Keep content ordering and render flow unchanged.

### Step 5: Validation
- Run Team page tests + bridge tests.
- Add targeted assertions for wording outputs only.

## Presentation-Only Safeguards

Use this checklist during implementation:
- No change to conditional thresholds or branch logic
- No change to data fetch functions or call counts
- No change to section order or UI structure
- No change to button actions or session-state keys
- No change to event normalization semantics
- No change to performance profile instrumentation

## Minimal Test Plan for the Rewrite Pass

1. Unit tests for new formatter module
- Trend labels and fallbacks
- Timeline event labels and fallbacks
- Notes/exception empty states and expander labels
- Comparison phrasing variants

2. Page-level regression tests
- Reuse [tests/test_team_page.py](tests/test_team_page.py)
- Update only wording assertions where present
- Keep existing behavioral assertions intact

3. Bridge safety tests
- Re-run [tests/test_team_today_bridge.py](tests/test_team_today_bridge.py)
- Confirm no Team->Today state handoff regressions

## Summary
The cleanest approach is:
- Introduce a dedicated Team language formatter service
- Refactor Team text helpers to delegate wording to that service
- Replace inline strings in [pages/team.py](pages/team.py) incrementally
- Keep all logic/data/state/query behavior unchanged

This delivers maintainability (single wording system) without architectural or behavioral risk.
