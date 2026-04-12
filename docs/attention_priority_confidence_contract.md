# Attention Priority and Confidence Contract

This document is the internal source of truth for Today signal meaning, ranking intent, and copy constraints.

## 1. Confidence policy

Confidence is evidence quality only.

Confidence does not represent urgency, impact, business cost, or how bad a condition is.

Confidence answers one question: how strong is the data support behind this signal.

Required interpretation:

- High confidence: Evidence is strong enough for stable interpretation.
- Medium confidence: Evidence is directionally useful but still incomplete.
- Low confidence: Evidence is limited and must be treated as provisional.

Forbidden interpretation:

- Never treat high confidence as automatically high attention priority.
- Never treat low confidence as automatically low attention priority when operational urgency exists.

## 2. Priority policy

Attention priority means how strongly an item deserves supervisor attention now.

Attention priority is not confidence.

Attention priority combines operational urgency and pattern strength signals (for example overdue follow-up, repeat pattern, sustained decline, open exception context) into a single ordering intent for Today.

Policy requirements:

- Confidence is one input to attention priority, not the definition of attention priority.
- Operational urgency can justify high attention priority even under low confidence.
- Attention priority language in product and code-facing docs must use the term attention priority, not severity.

## 3. Signal maturity policy

Signal maturity has exactly three product states:

- Full signal
- Early signal
- Low-data prompt

Definitions:

- Full signal: Comparison/trend interpretation is eligible and stable enough for standard queue review.
- Early signal: Directional interpretation is allowed, but confidence and data caveats are expected.
- Low-data prompt: Not enough history for trend claims; only lightweight current-state prompting is allowed.

## 4. Minimum data policy

Minimum usable-point policy is mandatory:

- 1 usable point: Current-state prompts only.
- 2 usable points: Early directional signals only.
- 3 or more usable points: Stable trend/comparison eligible.

Interpretation constraints:

- Fewer than 3 usable points must not be presented as stable trend evidence.
- One-point cases must not be framed as trend movement.
- Two-point cases may indicate direction, but must retain explicit provisional framing.

## 5. Today queue policy

Today queue policy is intentionally looser than strict full-display contexts.

Purpose:

- Today is an operational attention surface, not a strict analytics report.

Policy requirements:

- Today may include lower-confidence or early signals when they are useful for triage.
- Today must preserve transparency about evidence limitations.
- Today ordering and card inclusion must still follow attention-priority intent.

## 6. Copy policy for confidence and maturity combinations

Copy must explicitly communicate both confidence and maturity when confidence is medium or low.

Required copy behavior:

- Full + high confidence: Standard action-oriented signal copy allowed.
- Full + medium confidence: Include a brief caution that data support is partial.
- Full + low confidence: Allowed only where queue policy permits; must include explicit limitation text.
- Early signal + any confidence: Must include directional/provisional language.
- Low-data prompt: Must include explicit not-enough-history wording.

Mandatory low-confidence rule for Today:

- Any low-confidence Today item must include explicit limitation language in collapsed card content, not only in hidden details.

Disallowed copy patterns:

- No deterministic claims from low-data prompts.
- No urgency language that implies confidence equals impact.

## 7. Non-goals and guardrails

Non-goals:

- This contract does not redesign ranking formulas.
- This contract does not prescribe UI layout redesign.
- This contract does not introduce new signal categories.

Guardrails:

- Do not conflate confidence with attention priority.
- Do not present early or low-data items as stable trends.
- Do not suppress operationally urgent items solely because confidence is low.
- Do not remove limitation language from low-confidence Today cards.

## 8. QA implications

QA must validate policy behavior, not only rendering.

Required QA checks:

- Confidence semantics check: confidence copy reflects evidence quality only.
- Attention-priority separation check: low-confidence urgent items can still rank high.
- Maturity check: one-point and two-point items are not labeled as stable trends.
- Minimum-data check: 1/2/3+ usable-point behavior matches policy.
- Today transparency check: low-confidence items show explicit limitation language in collapsed state.
- Terminology check: product-facing text uses attention priority and avoids severity for product meaning.

## 9. Engineering implications

Engineering ownership and implementation constraints:

- Product meaning for confidence, maturity, and state messaging should be service-owned, not page-owned.
- UI modules should render precomputed view models and copy decisions.
- Changes to confidence interpretation and minimum-data thresholds require contract-level review.
- Ranking/scoring and copy behavior should be tested separately:
  - Scoring tests validate ordering mechanics.
  - Meaning/copy tests validate confidence and maturity policy compliance.

Change-control requirement:

- Any change that alters confidence meaning, maturity definitions, or minimum-data thresholds must update this contract and associated tests in the same change set.
