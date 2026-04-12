# Product Rules

## Core Position

This product highlights and interprets operational data. It does not prescribe how supervisors should manage people.

## Rules

1. Highlight, do not dictate.
2. Every important insight must explain:
   - what happened
   - compared to what
   - why it is shown now
   - confidence level
   - supporting data
3. Progressive disclosure on major screens:
   - summary first
   - expand for context
   - drill down for evidence/source rows
4. Include context where available:
   - performance
   - time comparison
   - volume/workload
   - data completeness
5. Prefer strong signals over noisy signals.
6. Cards-first UI. Tables belong in drill-down/evidence views.
7. Trust over false precision.
8. Preserve current behavior unless trust/clarity/usability/scalability improves.

Reference: source-of-truth contract for confidence policy, attention priority policy,
signal maturity policy, minimum-data policy, and Today queue display policy:
docs/attention_priority_confidence_contract.md

## Decision Test for Changes

A change should only ship if it improves at least one of:
- trust transparency
- explanation quality
- drill-down traceability
- daily usability for supervisors
- maintainability/scalability of service logic
