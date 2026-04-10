# Navigation Model

Last updated: 2026-04-09
Status: Design only, no implementation in this document

## Objective

Provide a simple, intuitive, beginner-friendly navigation system for the four core screens:

- Today
- Employee Detail
- Team / Process
- Import / Data Trust

## Primary Navigation

Visible primary items (max 4):
1. Today
2. Team / Process
3. Import / Data Trust
4. Settings (existing utility area, non-core but required)

Notes:
- Employee Detail is not a primary nav item. It is always a drill-down destination.
- Any legacy destinations (dashboard, productivity, coaching intel, cost impact) should route to Today or Team / Process sections.

## Landing Rules

- Returning user landing: Today.
- First successful import in a new tenant: Team / Process.
- If data is stale or incomplete at open: show warning strip with one-click path to Import / Data Trust.

## Screen Entry Model

Today entry conditions:
- Default app open.
- Return from Employee Detail after logging outcome.
- Return from Team / Process when user switches to action mode.

Employee Detail entry conditions:
- From Today queue card.
- From Team / Process signal card or filtered employee list.
- Optional direct deep link (with source metadata when available).

Team / Process entry conditions:
- From primary nav.
- From Today when user taps See pattern context.
- From Import / Data Trust after import completion.

Import / Data Trust entry conditions:
- From primary nav.
- From stale-data warning on Today or Team / Process.
- From setup/onboarding entry.

## Back Navigation Model

Rules:
- Back should return users to the immediate source and preserve context.
- Context includes filter, selected chip, search query, sort state, and scroll position where possible.
- If source context is missing, fallback goes to Today.

Source context payload (session-state concept):
- source_screen
- source_filter
- source_sort
- source_anchor
- source_reason

Behavior:
- Employee Detail back target = source_screen (Today or Team / Process).
- Team / Process back target:
  - if entered from Today via context link, back to Today with same queue filter.
  - if entered via primary nav, no forced back CTA (user uses nav).
- Import / Data Trust back target:
  - if entered from stale-data strip, back to originating screen.
  - if entered from nav, no forced back CTA.

## Breadcrumb Standard

Use breadcrumbs only for drill-down depth, not for top-level pages.

Patterns:
- Today -> Employee Detail: Name
- Team / Process -> Employee Detail: Name
- Import / Data Trust -> Team / Process

Guidelines:
- Breadcrumb first segment always reflects source screen.
- Breadcrumb appears above the first summary card.
- Breadcrumb click should preserve prior state where possible.

## Drill-Down Contract

Every drill-down action must provide:
- destination screen
- reason for drill (human-readable)
- carryover filter context

Examples:
- Today queue card "View details" sends:
  - destination: Employee Detail
  - reason: below goal 3 consecutive days, trending down
  - source_screen: Today
  - source_filter: overdue
- Team / Process signal "Review affected people" sends:
  - destination: Team / Process employee subset panel, then Employee Detail
  - reason: process slowdown in Picking
  - source_screen: Team / Process

## Progressive Disclosure in Navigation

Level 1: Summary pages
- Today
- Team / Process
- Import / Data Trust trust summary

Level 2: Context overlays/expanders
- why shown
- confidence
- freshness
- impacted scope

Level 3: Evidence
- Employee Detail timeline
- raw data rows
- import diagnostics

Rule:
Never route users directly into Level 3 from primary nav.

## Empty, Stale, and Error Paths

Empty queue (Today):
- Show meaningful state with next actions:
  - View team context
  - Log observation
  - Check data trust

No trusted data (Import needed):
- Any screen shows trust warning and one primary CTA to Import / Data Trust.

Low confidence signals:
- Show signal with caveat and quick path to evidence.
- Do not elevate low-confidence signals to top of Today queue.

Screen failure:
- Keep top nav available.
- Fallback route target: Today.
- Provide lightweight technical details only in expandable panel.

## Beginner-Friendly Defaults

- Keep visible actions per screen to one primary and up to two secondary.
- Use plain labels:
  - Needs attention
  - Why shown
  - Log outcome
  - Data last updated
- Avoid jargon in nav labels:
  - Replace pipeline with import
  - replace intel with team patterns

## Mapping from Current App Structure

Recommended mapping in current routing terms:
- today -> Today
- team (currently employees page) -> Team / Process entry + links to Employee Detail
- import -> Import / Data Trust
- settings -> Settings

Internal consolidation targets (design intent only):
- dashboard, productivity, cost_impact, coaching_intel become Team / Process sections or expanders.
- employees remains Employee Detail destination and related workflows.

## Acceptance Criteria

Navigation is successful when:
1. New user can reach first useful insight in one session after import.
2. Returning user can complete one follow-through action in under 3 minutes.
3. User always knows where they are, why they are there, and how to get back.
4. No primary page starts with a raw table.
5. Every primary signal has a clear drill-down to evidence.
