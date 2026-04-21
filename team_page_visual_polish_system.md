# Team Page Visual Polish System

Date: 2026-04-20
Source: team_page_visual_polish_audit.md
Depends on: team_page_visual_hierarchy_system.md (hierarchy remains primary)
Page role: Understand

## Purpose
Define a presentation-only polish system that makes the Team page feel clean, calm, premium, readable, operational, and sellable without becoming flashy or dashboard-heavy. This system preserves the current hierarchy work and refines finish quality through spacing, containment, typography, and list rhythm.

## Scope Guardrails
- No logic changes
- No data flow or query changes
- No routing changes
- No Team -> Today bridge behavior changes
- No new controls
- No new data surfaces
- No performance-sensitive restructuring
- No feature or layout redesign

## 1. Visual Goals

### What premium but operational means for this page
- Premium means intentional visual decisions, consistent rhythm, restrained contrast, and clear hierarchy with low friction.
- Operational means information remains direct, quick to parse, and task-relevant, with no ornamental effects that compete with content.
- The page should feel productized rather than improvised: consistent containers, predictable spacing, disciplined text tiers.

### What should feel calmer than today
- Fewer abrupt transitions between sections.
- Less separator noise in long lists.
- Less caption/helper stacking around primary signals.
- More breathing room between blocks and less micro-jitter between adjacent text lines.
- Stronger difference between emphasized signal lines and muted metadata.

## 2. Container Rules

### Card-like vs open treatment
Use card-like treatment when:
- A section contains mixed content types (heading + summary + chart, or heading + dense list).
- A block must read as a cohesive analytical unit (summary, trend, long-history modules).
- The section spans more than one visual rhythm unit and benefits from containment.

Use open treatment when:
- Content is a short transitional element or lightweight synthesis line.
- A section contains only one concise statement and no dense internal structure.

### Boundaries: borders vs fills vs whitespace
- Primary boundary mechanism: whitespace separation.
- Secondary boundary mechanism: subtle border (low contrast, thin stroke).
- Optional tertiary mechanism: very light neutral background tint for major containers.
- Avoid combining strong border + strong fill + tight spacing in the same block.

### Boundary strength
- Major analytical sections: soft but visible boundaries.
- Minor synthesis sections (for example comparison): lighter, quieter boundary than major sections.
- Internal row boundaries: minimal; prefer spacing rhythm first, separators second.

## 3. Spacing Rules

### Base rhythm scale
- XS = 6px
- S = 8px
- M = 12px
- L = 16px
- XL = 24px

### Page-level spacing
- Top page title/caption area to filter row: L
- Filter row to two-column shell: L to XL depending on control density
- Bottom page buffer: L

### Section spacing (right detail column)
- Major section to major section: XL
- Heading to first content item: M
- Primary signal to support line: S to M
- Support line to tertiary metadata: S
- Divider usage should include breathing room: at least M above and M below

### Entry spacing inside timeline, notes, exceptions
- Row top/bottom padding: S to M
- Title to metadata/detail within row: XS to S
- Between rows: S (if separator exists) or M (if separator removed)
- Expanded content should introduce M top spacing to avoid collisions with row content

### Rhythm constraint
- Improve rhythm through consistency, not by increasing every gap.
- Preserve operational compactness: never let repeated sections look airy enough to reduce scan speed.
- If one spacing increase is applied, pair it with one de-emphasis action (for example softer separator) to keep density balanced.

## 4. Typography Rules

### Heading strength
- Maintain hierarchy ladder from the hierarchy system.
- Increase distinction between section headings and body copy using weight/size contrast, not decorative styling.
- Keep heading line-height compact and stable across sections.

### Sublabel treatment
- Section-intent sublabels remain optional supporting text.
- Render sublabels quieter than headings and avoid identical treatment across all sections.
- Suppress redundant sublabels where heading wording already conveys intent.

### Primary vs secondary vs tertiary balance
- Primary lines: highest contrast, strongest weight, shortest scan path.
- Secondary lines: standard body contrast, supportive but clear.
- Tertiary lines: visibly muted and smaller, never equal to secondary in contrast.

### Where to reduce visual harshness
- Reduce contrast intensity of repetitive metadata lines.
- Soften separator color and reduce hard edge frequency.
- Avoid multiple bold lines back-to-back in list rows.
- Keep uppercase/letterspacing restrained to prevent aggressive texture.

## 5. List and Readability Rules

### Long history sections
- Preserve current ordering/behavior.
- Add visual cadence for depth: grouping cues, breathing intervals, or light sub-anchors for recency blocks.
- Keep row pattern predictable across long scans.

### Separators
- Prefer subtle separators or alternating low-contrast row background, not both strongly.
- Separator presence should support readability, not dominate it.
- In dense lists, lighten separator treatment before increasing border quantity.

### Row treatment
- One dominant row line (event/type/entry lead).
- One support line (optional detail/preview).
- One tertiary metadata line (timestamp/context).
- Keep row internals consistent across timeline, notes, and exceptions while preserving semantic distinction.

### Scan rhythm
- Support fast vertical scanning with repeatable row geometry.
- Ensure each section has a recognizable visual signature so sections are distinguishable at a glance.
- Avoid abrupt pattern shifts between visible rows and expanded rows.

## 6. Tone Through Visuals Rules

### Trustworthy and refined through restraint
- Emphasize order and consistency over effects.
- Use subtle contrast layering instead of heavy containers.
- Let whitespace and typographic hierarchy carry clarity.

### Trust signals
- Stable spacing cadence across the entire page.
- Predictable boundaries and consistent row construction.
- Limited visual noise from helper/caption repetition.
- Muted metadata that stays available without competing.

### Avoiding dashboard heaviness
- Do not add ornamental badges, bright accents, or dense KPI framing.
- Keep charts and lists contextual, not theatrical.
- Avoid over-fragmenting the page into too many boxed regions.

## 7. Implementation Guardrails
- Presentation-only changes.
- No logic, data, query, routing, or bridge behavior changes.
- No new controls or interactions.
- No new data fields or derived metrics.
- No performance-sensitive structure changes (no additional heavy rendering passes).
- Maintain existing section order and hierarchy intent from team_page_visual_hierarchy_system.md.

## 8. Recommended Implementation Order
1. Spacing normalization pass (page-level and section-level rhythm).
2. Typography/contrast tuning pass (primary-secondary-tertiary balance).
3. Separator and row-treatment softening pass for timeline/notes/exceptions.
4. Helper/caption consolidation and sublabel restraint pass.
5. Container unification pass for summary/trend/long-history major blocks.
6. Long-list scan-anchor refinements for deep histories.
7. Comparison-section finishing treatment as final polish.

## Completion Checklist
- Page feels calmer without becoming sparse.
- Primary signals remain immediate in under 3 seconds.
- List-heavy sections are readable over long scroll depth.
- Boundaries are subtle and intentional, not harsh.
- The visual tone reads premium and operational, not flashy and not dashboard-heavy.
