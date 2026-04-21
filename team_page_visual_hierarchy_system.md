# Team Page Visual Hierarchy System

Date: 2026-04-20
Source: team_page_visual_hierarchy_audit.md
Page role: Understand (not act)

## Purpose
Define a presentation-only hierarchy system that improves scanability and comprehension speed on the Team page without changing behavior, data flow, queries, routing, bridge behavior, or feature scope.

## Scope Guardrails
- No layout redesign
- No new features
- No wording rewrite as part of this system doc
- No logic changes
- No performance/query changes
- No Team -> Today bridge behavior changes

## 1. Information Tiers

### Tier 1: Primary (must see instantly)
Use for the first-answer signals a supervisor needs in under 3 seconds.
- Selected employee identity anchor (name)
- Current state summary signal (single primary summary line)
- Trend direction in selected window
- Current vs target snapshot

Visual treatment rules:
- Highest contrast text in the right panel
- Largest type used within content area (below page title)
- Strongest vertical position (top of right panel content)
- Minimal adjacent noise (no competing helper lines beside it)

### Tier 2: Secondary (context)
Use for explanatory context that supports Tier 1 interpretation.
- Trend chart interpretation line
- Timeline event labels
- Notes and exceptions item headings
- Department comparison headline statement

Visual treatment rules:
- Standard body contrast and medium weight
- Clearly grouped under related Tier 1 signals
- Visible but not dominant

### Tier 3: Tertiary (metadata)
Use for supportive details needed occasionally, not during initial scan.
- Timestamps
- Counts
- Sub-status/meta lines (confidence/coverage/follow-up timing)
- Helper/caption text
- Optional detail previews and expander labels

Visual treatment rules:
- Muted contrast
- Smaller text size than Tier 2
- Kept near parent content; never visually louder than Tier 1/2

## 2. Heading Hierarchy Rules
Use a strict and repeatable heading ladder.

- H1 (page): Team
- H2 (selected context anchor): selected employee block heading
- H3 (major analytical sections): Trend, Timeline, Notes, Exceptions
- H4-equivalent visual label (minor synthesis): Comparison

Rules:
- Only one H2-level focal block in the right panel at a time
- Major sections (H3) must have stronger visual separation than minor synthesis labels
- Heading strength must reflect scan order priority, not implementation order
- Do not promote metadata lines into heading styling

## 3. Text Emphasis Rules

### Visually strong
Reserve strong emphasis for:
- Primary summary signal
- Employee name anchor
- Trend direction statement
- Event/note/exception row titles (not timestamps)

Strong style guidance:
- Higher weight and contrast
- Short line length where possible
- One primary strong line per block

### Visually quiet
Keep visually quiet:
- Helper captions
- Repeated status metadata
- Timestamps and provenance/context strings
- Expand/collapse affordance labels

Quiet style guidance:
- Lower contrast and smaller size
- Avoid stacking multiple quiet lines before primary signal
- If repeated, render once per section, not per sub-row when avoidable

## 4. Section Structure Rules
Maintain current section set and order while enforcing hierarchy within each section.

### Summary
Required internal order:
1. Employee name anchor (Tier 1)
2. Single primary summary signal (Tier 1)
3. Compact secondary support row (Tier 2)
4. Metadata strip/chips (Tier 3)
5. Bridge helper (Tier 3, visually quiet)

Rules:
- One dominant focal point only
- Remove adjacent duplicate metadata emphasis
- Chip row must be tiered (not all equal visual weight)

### Trend
Required internal order:
1. Trend heading (H3)
2. Chart (Tier 1 visual object)
3. Interpretation sentence (Tier 2)
4. Any trend helper/meta (Tier 3)

Rules:
- Trend is the first major analytical block
- Keep interpretation attached to the chart, not floating far below
- Empty-state text stays tertiary and concise

### Timeline
Required internal order:
1. Timeline heading (H3)
2. Repeating event rows with clear sub-hierarchy:
   - Event title/label (Tier 2)
   - Timestamp and optional detail (Tier 3)

Rules:
- Timestamp should not compete with event label
- Limit same-weight repetition across rows
- Keep row rhythm consistent for fast vertical scan

### Notes
Required internal order:
1. Notes heading (H3)
2. Section-level list meta (Tier 3)
3. Note rows:
   - Note header/title (Tier 2)
   - Preview/detail (Tier 3)

Rules:
- Distinguish note headers from previews
- Avoid repeated helper text between every row
- Expanded content should preserve hierarchy, not reset it

### Exceptions
Required internal order:
1. Exceptions heading (H3)
2. Section-level list meta (Tier 3)
3. Exception rows:
   - Exception type/title (Tier 2)
   - Context/timestamp/detail (Tier 3)

Rules:
- Must be visually distinct from Notes section treatment
- Context lines remain quiet and supportive

### Comparison
Required internal order:
1. Comparison label (minor section heading)
2. Primary comparison statement (Tier 2)
3. Supporting comparison context (Tier 3, optional)

Rules:
- Comparison should read as synthesis context, not a new primary workload
- Must be discoverable without competing with Trend

## 5. Caption and Helper Text Rules

### Group vs separate
Group helper/caption text when:
- Multiple lines explain the same concept for one section
- Metadata can be summarized once at section level

Separate helper/caption text when:
- It applies to a specific item row and cannot be inferred globally
- The line changes meaning per row (for example, row-specific context)

### Repetition control rules
- Helper budget: max one helper line per major section entry point
- Do not repeat equivalent metadata in adjacent UI elements
- If data appears in chip + status line + caption, keep one prominent instance and downgrade/remove duplicates visually
- Prefer section-level meta summaries over per-row repeated captions where semantics allow

## 6. Spacing Rules
Use a consistent rhythm scale to reduce visual crowding and improve grouping.

Recommended spacing tokens:
- S = 8px
- M = 12px
- L = 16px
- XL = 24px

### Between sections
- Major section to major section: XL
- Summary block to first analytical section: XL (or stronger divider + L)
- Minor synthesis (comparison) after major section: L

### Within sections
- Heading to first content element: M
- Between primary and secondary elements: M
- Between secondary and tertiary elements: S
- Between repeated rows: M
- Between row title and metadata/detail: S

Rules:
- Keep same section type on the same rhythm
- Avoid stacked micro-gaps that create visual jitter
- Increase left-panel roster row spacing enough to parse multiline labels at a glance

## 7. Scan Goal (3 Seconds)
In 3 seconds, a supervisor should reliably understand:
1. Who is selected.
2. Whether recent direction is improving, steady, or slipping.
3. Whether current performance is near/above/below target.
4. Whether there is notable recent history to review (timeline/notes/exceptions) without opening details.

If any of these answers require reading more than one dense caption block, hierarchy is not meeting goal.

## Practical Application Checklist
Use this checklist before visual updates are considered complete.
- Tier 1 signals are visible without reading helper text.
- Trend section reads as first analytical destination.
- Timeline, Notes, and Exceptions are distinguishable at a glance.
- Repeated metadata has one clear home; duplicates are visually downgraded.
- Caption/helper text is present but does not dominate.
- Spacing rhythm is consistent across major sections.
- Comparison is noticeable but clearly secondary.

## Implementation Boundary Reminder
This system defines presentation behavior only. It must be implemented without changing:
- data flow
- query behavior
- performance optimizations
- page routing
- Team -> Today bridge behavior
