# Insight Model

## Required Insight Fields

Important insights should consistently provide:
- what happened
- compared to what
- why shown now
- confidence
- supporting data/evidence path

## Service-Layer Shape

Most insights map to contract fields used by interpretation services:
- title / insight_kind
- what_happened
- compared_to_what
- why_flagged
- confidence (level + rationale)
- data_completeness (status + note)
- workload/time context
- drill-down target
- traceability metadata

## Consistency Rules

- Use plain language labels for trend/status states.
- Provide caveats explicitly when confidence or completeness is limited.
- Include enough metadata for drill-down and source references.
