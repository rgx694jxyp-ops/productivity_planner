# UI Screen Map

Last updated: 2026-04-09
Status: Design only, no implementation in this document
Aligned with: PRODUCT_GUARDRAILS.md, FIRST_SESSION_FLOW.md, DAILY_HABIT_LOOP.md

## Purpose

Define a simple, beginner-friendly core app architecture using 4 screens:

1. Today
2. Employee Detail
3. Team / Process
4. Import / Data Trust

Design principle for all screens:
Summary first, then context, then evidence.

## Global Structure

- Primary nav should expose only these four screens.
- Default landing for returning users: Today.
- Default landing immediately after first successful import: Team / Process.
- Every screen has one primary action and one clear way back.
- Tables are never the first visible element.

---

## 1) Today

Main question it answers:
What needs my attention right now, and what follow-through is due this shift?

What must be visible immediately:
- Queue summary chips: Overdue, Due Today, Repeat, Recognition, Total Open.
- Top 1-3 queue cards (no scroll to first action).
- For each card: who, issue in plain language, why surfaced now, confidence/freshness.
- One primary action per card: Log outcome.
- Secondary quick actions: Add note, Recognize, Escalate (non-prescriptive labels).

What should be hidden until expanded:
- Full historical timeline.
- Raw shift rows / per-day evidence table.
- Full recommendation rationale details.
- Cost/ROI impact details.

What drill-downs should exist:
- Card tap or View details -> Employee Detail (pre-filtered to selected employee and source reason).
- Queue summary chip tap -> filtered Today list (example: Overdue only).
- Since yesterday strip -> Team / Process (for pattern review).

How the user gets back:
- Back from Employee Detail returns to Today with prior queue filter and scroll anchor retained.
- Header breadcrumb:
Today -> Employee Detail
- One tap nav always available to Today in sidebar/top nav.

---

## 2) Employee Detail

Main question it answers:
What is happening with this person, why did they get flagged, and is follow-through working?

What must be visible immediately:
- Employee identity block: name, department, current status.
- Source context banner: why user arrived (example: trending down 3 days from Today queue).
- Signal summary card in plain language:
  - what happened
  - compared to what baseline/goal
  - why shown now
  - confidence and data freshness
- Most recent coaching/follow-up outcome status.
- Primary action: Log today outcome.

What should be hidden until expanded:
- Full note history and all historical notes.
- Full shift-by-shift raw data table.
- Archived actions and legacy exports.
- Advanced analytics for this employee.

What drill-downs should exist:
- Trend mini-chart -> expanded 7/14/30 day chart panel.
- Latest note preview -> full notes timeline.
- Confidence badge -> data quality explanation (sample size, missing rows).
- Related pattern link -> Team / Process pattern section for same issue type.

How the user gets back:
- Explicit Back to Today button when source was Today.
- Explicit Back to Team / Process button when source was Team / Process.
- Breadcrumb format:
Today -> Employee Detail: Name
or
Team / Process -> Employee Detail: Name
- Preserve source context in session state so back returns to same list state.

---

## 3) Team / Process

Main question it answers:
What team-level patterns should I understand before I act, and where should I drill next?

What must be visible immediately:
- Team health summary cards:
  - On goal vs below goal
  - Trend direction vs prior period
  - Data confidence and freshness
- Top 2-3 process signals in plain language (not prescriptions).
- Affected groups count (department/shift/process area).
- Primary action: Review affected people.

What should be hidden until expanded:
- Full ranked lists and raw tables.
- Deep trend analytics by every dimension.
- Cost impact calculator details.
- Secondary diagnostics not tied to current top signals.

What drill-downs should exist:
- Signal card -> filtered employee list (same screen section) and then Employee Detail.
- Department/process tag -> focused trend panel for that segment.
- Data trust indicator -> Import / Data Trust diagnostic section.
- Optional deep analytics expander for advanced users only.

How the user gets back:
- From Employee Detail, back returns to Team / Process with same signal filter.
- Breadcrumb format:
Team / Process -> Employee Detail
- One tap to Today always visible for quick return to action loop.

---

## 4) Import / Data Trust

Main question it answers:
Can I trust today’s signals, and what data setup step is needed next?

What must be visible immediately:
- Trust status banner:
  - last successful import time
  - coverage window (example: last 14 days)
  - completeness confidence
- Data quality summary in plain language:
  - rows loaded
  - employees recognized
  - missing/invalid fields count
- First insight preview after successful import.
- Primary action: Import latest file.

What should be hidden until expanded:
- Full column mapping details after initial setup.
- Duplicate row diagnostics and full validation logs.
- Historical import runs and rollback tooling.
- Advanced configuration/settings.

What drill-downs should exist:
- Trust banner -> detailed data quality panel.
- First insight preview -> Team / Process or Employee Detail depending on signal type.
- Import history item -> specific run diagnostics.

How the user gets back:
- Post-import CTA options:
  - View team summary -> Team / Process
  - Go to today queue -> Today
- Breadcrumb format:
Import / Data Trust -> Team / Process
or
Import / Data Trust -> Today
- Keep import progress state isolated so user can leave and return without losing setup.

---

## Cross-Screen Rules

- Every important signal must answer five items before evidence is shown:
  - what happened
  - compared to what
  - why shown now
  - confidence
  - supporting data
- Confidence/freshness appears on Today, Employee Detail, and Team / Process.
- Import / Data Trust is the canonical source for trust diagnostics.
- Do not place standalone Dashboard/Cost/Intel pages in primary navigation.
  - Their value becomes sections/drill-downs within Team / Process or Employee Detail.

## Core User Loops

Daily loop:
Today -> Employee Detail -> Today

Understanding loop:
Today -> Team / Process -> Employee Detail -> Today

Data trust loop:
Today -> Import / Data Trust -> Team / Process -> Today

First session loop:
Import / Data Trust -> Team / Process -> Employee Detail -> Today
