# Team Page Visual Polish Audit

Date: 2026-04-20
Scope: Presentation polish audit only (no logic, data flow, query, performance, routing, or Team -> Today bridge behavior changes).

## Overall Assessment
The Team page is now structurally clearer than before, but the finish still reads somewhat utilitarian rather than premium. Main causes are tight spacing cadence, repeated thin borders across long lists, and limited container differentiation between major sections. Typography hierarchy is mostly correct, but several text styles sit too close together, so the page still feels busy under long-history conditions.

## Findings Table

| issue | where it appears | why it hurts perceived quality | recommended visual fix (presentation-only) | implementation difficulty |
|---|---|---|---|---|
| Vertical rhythm is slightly compressed in the right panel | Gap sequence around summary, divider, section headings, and first list rows in Team detail column | Compressed rhythm makes sections feel dense and transactional, reducing premium feel | Standardize a stricter spacing scale (for example 8/12/16/24) and apply larger section-to-section spacing than row-to-row spacing | low |
| Major sections rely on similar visual weight | Trend, Timeline, Notes, Exceptions, and Comparison headings are close in visual treatment | Section transitions can feel flat, making long pages harder to scan | Increase section separation with stronger top margins and subtle section containers for major blocks | low |
| Overuse of repeated row separators | Timeline, Notes, and Exceptions each use bottom borders on nearly every row | Repeating hard separators can create a ledger-like, utilitarian appearance | Replace every-row borders with softer alternating row backgrounds or keep separators but lighten color/opacities and rely more on spacing | low |
| Card/container treatment is inconsistent | Summary area, trend chart, and list sections mix plain flow and row wrappers | Inconsistent containment lowers perceived intentionality and polish | Introduce a unified lightweight card shell style for key blocks (summary, trend, long-history sections) with consistent corner radius, padding, and border tone | medium |
| Muted vs emphasized text balance is still tight | Summary secondary text, metadata chips, section intent labels, timestamps | Too many near-muted lines in sequence makes important lines work harder for attention | Increase contrast gap between primary and tertiary text; make metadata one step quieter and primary lines one step stronger | low |
| Typography scale is close between key labels and body | Timeline event title vs detail, note body vs metadata, exception primary vs support | Similar sizes reduce hierarchy clarity and premium readability | Normalize type ramp so each block has one dominant line, one support line, and one tertiary line with clear size/weight deltas | low |
| Section intent labels are useful but visually repetitive | The repeated small intent subtitle under multiple section headers | Repetition can feel mechanical and reduce perceived craft | Keep intent labels but vary placement/opacity by section importance, or suppress where heading already communicates intent clearly | low |
| Divider treatment is binary and abrupt | Single hard divider after summary/bridge block | A single hard divider can feel abrupt versus refined transitions | Use a softer divider style and pair it with intentional top/bottom spacing to smooth section transition | low |
| Long-list readability degrades over depth | Timeline can render many events; Notes/Exceptions stacks before older-content expander | Continuous stacked rows increase eye fatigue and scanning errors | Add periodic visual anchors in long lists (subtle date grouping, breathing gaps, or sticky mini-headers) while preserving data and ordering | medium |
| Left roster and right detail columns are close in perceived density | Left radio labels are multiline; right column has many stacked elements | When both columns are dense, the overall screen feels crowded and less premium | Slightly increase roster row breathing room and reduce non-essential helper prominence in both columns | medium |
| Helper/caption surfaces are still numerous | Hero caption, roster helper, selected-support caption, bridge helper, section captions | Excess helper lines create text noise and diminish headline impact | Apply a helper-text budget per section and consolidate adjacent helper lines into one concise support line | medium |
| Comparison block can be visually understated at page end | Bottom comparison heading with concise text treatment | Important synthesis can look like a footnote instead of a designed finish | Wrap comparison content in a distinct but subtle synthesis callout style | low |

## Top 5 Highest-Value Polish Improvements
1. Establish a consistent spacing and section-separation rhythm across the right panel.
2. Introduce unified lightweight card/container styling for summary, trend, and long-history blocks.
3. Rebalance typography and contrast tiers (stronger primary, quieter metadata).
4. Reduce row-separator harshness in long lists and rely more on spacing/grouping.
5. Consolidate helper/caption density using a stricter helper-text budget.

## Recommended Implementation Order (Safest/Highest-Value -> Lowest Priority)
1. Spacing rhythm normalization and section-separation tuning (safe, high visual payoff, low regression risk).
2. Typography and contrast tier tuning for primary/secondary/tertiary text (safe, high readability gain).
3. Row separator softening for Timeline/Notes/Exceptions (safe, improves premium feel quickly).
4. Helper/caption consolidation pass (moderate effort, strong declutter effect).
5. Unified card/container shell pass for major blocks (larger styling pass, medium complexity).
6. Long-list visual anchors for deep history readability (useful but secondary to global hierarchy/polish gains).
7. Comparison-section callout refinement and section-intent subtitle micro-tuning (nice finish, lower priority).

## Constraints Confirmed
- Audit-only step completed.
- No production code changes made.
- No behavior, logic, data, query, performance, routing, or Team -> Today bridge changes performed.
