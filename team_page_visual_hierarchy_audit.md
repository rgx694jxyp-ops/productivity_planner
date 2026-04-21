# Team Page Visual Hierarchy Audit

Date: 2026-04-20
Scope: Visual hierarchy and scanability audit only (no behavior, data, routing, or performance changes).

## Audit Lens
- Section order
- Heading strength
- Spacing rhythm
- Caption/helper text density
- Metadata density
- Visual salience (what stands out vs blends in)
- 3-5 second supervisor comprehension

## 3-5 Second Read Assessment
Current first-impression scan is serviceable but not fast:
- The selected employee header is clear, but key signal hierarchy is diluted by many same-weight captions.
- Trend, timeline, notes, and exceptions use very similar visual treatment, so sections blend together.
- Metadata appears in multiple places (chips, status line, row subtitles, section captions), increasing cognitive load before the user reaches the most useful signal.

## Findings Table

| issue | where it appears | why it slows understanding | recommended UI fix (presentation-only) | implementation difficulty |
|---|---|---|---|---|
| Weak top-level focal point after employee selection | Right panel summary area (employee name -> subheader -> paragraph -> bridge helper -> chips) | The eye does not get one obvious "main signal" first; summary competes with bridge helper and four chips of equal visual weight | Create a compact "selected employee summary card" with stronger typographic hierarchy: main signal line as primary, supporting chips as secondary, bridge helper de-emphasized beneath | medium |
| Chip row is dense and visually flat | Four caption chips under divider (current vs target, trend, notes, follow-up) | All chips look equivalent despite different decision value, so users must read each fully | Introduce tiered chip emphasis: primary chip style for trend/current-vs-target, secondary style for notes/follow-up; add consistent chip spacing and subtle background containers | low |
| Repeated status metadata | Selected subheader, chip row, and separate status summary line | Similar metadata appears in multiple adjacent locations, causing re-read and reduced signal-to-noise | Collapse duplicated metadata into one compact status strip (icons/tags) and remove visual prominence from duplicates (keep data, reduce display weight) | low |
| Section transitions are too uniform | Trend, timeline, notes, exceptions, comparison all use similar heading/caption pattern | Equal styling implies equal urgency and makes scanning sequence unclear | Add section-level rhythm: stronger top margin before major blocks, lighter dividers between minor blocks, and distinct heading scales for primary vs secondary sections | low |
| Trend section lacks clear above-the-fold dominance | Trend appears below summary/chips with similar text weight to later sections | Trend is often the first analytical answer, but it does not stand out enough in initial scan | Elevate trend as first major analytical block with stronger heading weight and a dedicated container; keep interpretation caption visually attached to chart | low |
| Timeline rows have high visual repetition | Timeline uses repeated markdown row heading + caption per event | Timestamp and event label repeat with same contrast, causing long vertical scanning time | Convert rows into compact two-column visual grid: left timestamp (muted), right event title (strong) and optional detail (muted) | medium |
| Notes and exceptions blocks are visually similar despite different semantics | Both sections use repeated caption + text + optional expander pattern | Users cannot quickly distinguish "coaching context" from "operational variance" when scanning | Differentiate with section-specific visual markers (badge color, icon, or border accent) while keeping existing wording/data | low |
| Expander-heavy long lists hide recency structure | Older notes/exceptions only visible inside expanders; visible items still form long uninterrupted stacks | The user must interact to understand depth/history and can lose recency context | Add compact list meta above each section: total count, visible count, and latest timestamp; keep expander behavior unchanged | low |
| Roster (left) and detail (right) spacing rhythm is tight | Left radio list with multiline labels and compact gaps; right panel dense caption stacking | Tight rhythm makes dense text feel heavier and slows row-by-row scan | Increase vertical spacing in roster labels and add alternating subtle row background or separators; in right panel, use consistent 8/12/16 spacing scale | medium |
| Filter controls visually compete with analytical content | Filter row appears high-contrast and wide before details | Initial attention may stay on controls rather than selected-employee insight | De-emphasize filter chrome (lighter borders, less dominant labels), keep controls functional; emphasize result area through card/container contrast | low |
| Comparison section appears visually detached and easy to miss | Comparison shown at bottom as single caption under heading | Important context may be skipped because it appears as low-emphasis tail content | Render comparison as a compact callout card with a clear label and subtle contextual background to mark it as synthesis | low |
| Caption/helper density is high across whole page | Hero caption, roster helper, bridge helper, section intros, row captions | Frequent low-contrast text blocks reduce scanning speed and blur signal hierarchy | Apply a helper-text budget per section: one helper line max above each major block; move secondary helper content to tooltips or collapsible info affordances | medium |

## Focus-Area Notes

### Summary/Header
- Strength: Selected employee name anchors context well.
- Risk: Supporting elements (subheader, summary paragraph, bridge helper, chips, status line) are too similar in visual weight.

### Trend
- Strength: Chart plus interpretation exists and is concise.
- Risk: Its visual priority is not sufficiently stronger than timeline/notes/exceptions.

### Timeline
- Strength: Chronology is clear and recent-first.
- Risk: Repeated row formatting creates a wall of similarly weighted text.

### Notes
- Strength: Good preview + optional expansion pattern.
- Risk: Dense stacking and repeated headers/captions reduce skim efficiency.

### Exceptions
- Strength: Context line and detail separation is useful.
- Risk: Visual pattern is too close to notes, weakening semantic distinction.

### Comparison
- Strength: Lightweight and non-prescriptive.
- Risk: End-of-page placement and caption-level treatment makes it easy to overlook.

## Suggested Implementation Sequence (Presentation-Only)
1. Establish hierarchy tokens for section spacing and heading scale.
2. Rework selected employee top block into a stronger summary container.
3. Apply differentiated section treatments for trend, timeline, notes, exceptions, comparison.
4. Reduce helper/caption density and consolidate repeated metadata presentation.
5. Polish roster/detail rhythm for faster scan across both columns.

## Out of Scope (Intentionally Not Reviewed for Changes)
- Data flow
- Query behavior
- Performance optimizations
- Page routing
- Team -> Today bridge behavior
