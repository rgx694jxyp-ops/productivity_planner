# Explanation Block Model

## Purpose

Every major signal surface should render explanation blocks in a stable order so users can quickly verify why the signal exists.

## Block Order

1. Summary block
   - current state
   - compared-to context
   - confidence
   - data completeness
2. Why-this-is-showing block
   - trigger
   - comparison used
   - why now
3. What-this-is-based-on block
   - timeframe
   - baseline/target source
   - workload context
   - missing/excluded data note
4. Drill-down evidence block
   - trend points
   - included/excluded supporting rows
   - source import/upload references

## UI Behavior

- Summary is visible by default.
- Context and evidence are progressively disclosed via expanders/sections.
- Raw tables appear only in drill-down/evidence regions.
