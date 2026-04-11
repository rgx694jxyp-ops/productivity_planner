# Highlight-Do-Not-Dictate Principle

## Intent

The app surfaces reliable operational signals and context. Supervisors choose the intervention.

## Allowed

- "3 employees are below expected pace in recent comparable windows."
- "This signal is low confidence due to incomplete hours data."
- "After the logged activity, average output improved in the next comparison window."

## Not Allowed

- "You should coach employee X today."
- "Reassign this team now."
- "Use this specific management method."

## Implementation Guidance

- Service-layer outputs should be descriptive, not imperative.
- UI action labels can navigate to evidence or workflow screens, but explanatory copy remains observational.
- Recommendation logic must preserve user agency and include clear evidence links.
