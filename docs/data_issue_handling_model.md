# Data Issue Handling Model

## Goal

Expose import/data quality issues transparently and let users choose handling paths without silently mutating meaning.

## Issue Grouping

Service-layer issue grouping includes categories such as:
- missing fields
- duplicate rows
- inconsistent names/labels
- suspicious values
- partial records

## Handling Choices

Current handling choices:
- review_details
- ignore_rows
- include_low_confidence
- map_or_correct

## Logging/Audit Expectations

When import post-processing runs:
- issue-handling choice decisions are logged
- excluded/ignored data decisions are logged
- import lifecycle start/completion/failure is logged

## Product Rule Alignment

- No hidden “smart fix” should change records silently.
- Confidence and completeness must reflect unresolved issue impact.
