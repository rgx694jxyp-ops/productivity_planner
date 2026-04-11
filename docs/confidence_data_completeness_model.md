# Confidence and Data Completeness Model

## Confidence

Confidence reflects reliability of the underlying comparison signal, not certainty of managerial action.

Typical labels:
- High
- Medium
- Low

Confidence is influenced by:
- number of comparable points
- baseline availability
- stability/volatility
- data quality issues and exclusions

## Data Completeness

Completeness communicates coverage and missingness explicitly.

Typical labels:
- complete / data mostly complete
- partial
- limited

Completeness note should state:
- included count
- excluded count
- lookback window and coverage ratio

## Trust Rules

- Low confidence and limited completeness should down-rank or suppress weak signals.
- Suppression is preferred over noisy false precision.
- If shown, low-confidence signals must include caveat text.
