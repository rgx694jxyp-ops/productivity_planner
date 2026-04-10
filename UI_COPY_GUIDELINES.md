# UI Copy Guidelines

Last updated: 2026-04-09
Status: Writing framework for all product surfaces
Aligned with: PRODUCT_GUARDRAILS.md, INSIGHT_CARD_CONTRACT.md, DRILLDOWN_RULES.md

## Purpose

Create a consistent voice that makes the interface feel clear, helpful, and confidence-building.

Tone standards:
- clear
- calm
- observational
- non-prescriptive

## Core Principles

1. State what is observed, not what the user should do.
2. Explain why a signal appears before exposing deep evidence.
3. Use plain words and short sentences.
4. Include confidence and data quality context whenever possible.
5. Keep labels predictable across screens.

## Voice And Tone

Use this style:
- Neutral and factual.
- Human and direct.
- Low-drama even for warnings.
- Respectful of user judgment.

Avoid this style:
- Commanding or instructional tone.
- Alarmist phrasing.
- Blame-oriented wording.
- Technical shorthand without explanation.

## Headings Rules

Heading purpose:
- Tell users exactly what this section is about in under 8 words.

Rules:
- One idea per heading.
- Prefer concrete nouns and signal language.
- Avoid abstract names like Intelligence, Insights Hub, Pipeline Monitor.
- Avoid emoji-first headings unless page already follows that pattern.

Good heading examples:
- Needs Attention Today
- Team Performance This Week
- Data Quality Summary
- Follow-Up Status

Avoid heading examples:
- Execute Performance Intervention
- Coaching Intelligence Optimizer
- Pipeline and Variance Dashboard

## Section Description Rules

Section description purpose:
- Add one short line that clarifies interpretation context.

Rules:
- 1-2 sentences max.
- Include what period/baseline is being used.
- Keep interpretation factual, no recommendation language.

Template:
- This view shows <what> for <scope> over <time window>, compared with <baseline>.

Good examples:
- This view shows open follow-ups for today, compared with their planned due dates.
- This chart shows department output this week, compared with the previous week.

Avoid examples:
- Use this list to coach underperformers now.
- Fix these issues immediately to avoid losses.

## Tooltip Rules

Tooltip purpose:
- Explain one term, metric, or rule quickly.

Rules:
- 1 sentence preferred, 2 max.
- Start with definition, then rule/context.
- Avoid nested conditions in tooltip copy.
- If explanation is long, move to inline expansion not tooltip.

Template:
- <Term> means <plain definition>. It is calculated from <source/basis>.

Good examples:
- Confidence is how reliable this signal appears based on sample size and data freshness.
- Repeated decline means output dropped in consecutive observations.

Avoid examples:
- This is a proprietary weighted model with multidimensional feature extraction.

## Confidence Language Rules

Confidence language purpose:
- Build trust without overstating certainty.

Rules:
- Always pair confidence with basis.
- Prefer High/Medium/Low labels and short evidence basis.
- Include caveat when sample size is small or data is stale.
- Do not imply certainty where evidence is partial.

Format:
- Confidence: <level> (<basis>)

Examples:
- Confidence: High (8 recent shifts, updated 20 minutes ago)
- Confidence: Medium (3 shifts observed; trend may change with more data)
- Confidence: Low (limited recent data)

Avoid examples:
- This is definitely correct.
- We know this will continue.

## Empty State Rules

Empty state purpose:
- Explain why the section is empty and preserve momentum.

Rules:
- State current condition clearly.
- Give context for why nothing is shown.
- Offer one optional next path, framed as navigation not instruction.
- Never use dead-end language like No data found without context.

Template:
- Nothing is currently shown here because <reason>. More results appear when <condition>.

Good examples:
- No follow-ups are due right now. This list updates as due times are reached.
- No trend is shown yet because fewer than 3 data points are available.

Avoid examples:
- Nothing to do.
- No data.

## Warning State Rules

Warning state purpose:
- Surface risk or uncertainty calmly and specifically.

Rules:
- Describe the exact issue.
- Describe impact scope.
- Describe confidence effect.
- Offer destination for details.
- Avoid panic words.

Template:
- Some data may be incomplete: <specific issue>. This may affect <affected outputs>.

Good examples:
- Some data may be incomplete: 12% of rows are missing hours. Trend confidence is reduced for this period.
- Data may be stale: last update was 9 hours ago. Recent changes may not be reflected yet.

Avoid examples:
- Critical failure.
- Data is broken.

## Button Label Rules

Button label purpose:
- Clarify destination or operation with minimal words.

Rules:
- Start with clear action verb: View, Open, Show, Log, Compare, Check.
- Prefer outcome-neutral verbs over directive verbs.
- Keep to 2-4 words.
- Labels should not prescribe management behavior.

Good examples:
- View Details
- Open Timeline
- Show Evidence
- Log Outcome
- Compare Periods
- Check Data Quality

Avoid examples:
- Coach Now
- Escalate Immediately
- Fix This
- Force Refresh

## Non-Prescriptive Language Guide

Preferred observational phrasing:
- Flagged because
- Observed pattern
- Compared with
- No measurable change
- Follow-up is overdue by
- Data may be incomplete

Avoid directive phrasing:
- You should
- Must
- Need to
- Do this now
- Recommended action is

## Jargon Replacement Guide

Use plain alternatives:
- pipeline -> import process
- anomaly -> data quality concern
- variance -> day-to-day spread
- rolling average -> recent average
- delta -> change
- risk score -> attention level
- intervention -> follow-up activity
- escalation path -> follow-up path

## Reusable Microcopy Patterns

Signal summary pattern:
- <Signal statement>. Compared with <baseline>. Flagged because <trigger>.

Confidence pattern:
- Confidence: <level> (<basis>). <optional caveat>

Completeness pattern:
- Data quality: <status>. <missing/excluded note>

Freshness pattern:
- Last updated <time>. <stale note if needed>

Empty state pattern:
- Nothing is currently shown because <reason>. Results appear when <condition>.

Warning pattern:
- Some data may be incomplete: <issue>. This may affect <scope>.

## Screen-Level Defaults

Today:
- Heading: Needs Attention Today
- Description: Open follow-ups and due items for this shift, sorted by urgency.

Employee Detail:
- Heading: Employee Detail
- Description: Performance and follow-up history for this person, with supporting evidence.

Team / Process:
- Heading: Team And Process Signals
- Description: Team-level patterns for this period, compared with normal range.

Import / Data Trust:
- Heading: Import And Data Trust
- Description: Import status, data quality, and confidence context for current signals.

## Review Checklist

Before shipping new copy, confirm:
1. Is the wording observational rather than directive?
2. Is any jargon replaced or explained?
3. Is confidence basis visible when a signal is shown?
4. Does empty/warning copy explain why and impact?
5. Are button labels destination-oriented and short?
6. Can a first-time user understand the message in one read?
