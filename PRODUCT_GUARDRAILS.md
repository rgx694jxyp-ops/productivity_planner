# PRODUCT GUARDRAILS
> Last updated: 2026-04-09  
> Branch: stabilization-architecture-pass  
> Status: Authoritative. Supersedes informal notes. Review before shipping any new UI surface.

---

## 1. Target User

**Primary:** A warehouse supervisor or shift lead at a small-to-mid warehouse or 3PL.  
- Manages 5–80 employees directly.  
- Works shifts, not desk hours.  
- Has limited time on screen — minutes per session, not hours.  
- Already knows who is struggling. Does not need the app to tell them who is a "low performer."  
- Needs the app to help them follow through: remember what they said last time, log what they did, and see if it worked.  

**Secondary:** An operations manager reviewing team-level patterns (multi-dept, trend-over-time).  

**Not the user:** HR. Workforce planning. Corporate analytics. WMS operators.

---

## 2. Product Mission (One Sentence)

Help supervisors act consistently on the right people at the right time — and know if it worked.

---

## 3. What This Product Is

A **Supervisor Execution System.**

The primary job is not discovery — it is follow-through.

The three questions the product answers:  
1. What needs my attention right now?  
2. What should I do next?  
3. Did it work?

All features ship only if they serve one of these three questions.

---

## 4. Non-Goals (Explicit)

| Category | Example | Why excluded |
|---|---|---|
| WMS replacement | Shift plan with volume projection, departments, checkpoint math | Supervisors won't configure this daily |
| HR / PIP tool | Discipline tracking, formal write-ups, attendance calendars | Not the primary use case; introduces liability confusion |
| Generic analytics dashboard | Trend comparison charts with no follow-through path | Passive consumption; not action-oriented |
| Discovery product | "Here are your low performers" ranked tables, leaderboards | Supervisors already know this |
| Coaching prescriptor | "You should coach this employee on X technique" | App does not manage people |
| Reporting tool | Export-first features, custom report builder | Better served by the WMS or BI layer |
| Cost/ROI projector | Dollar value of UPH gap projected over a year | Interesting but not decision-critical on the floor |

---

## 5. The Highlight-Don't-Dictate Rule

The app surfaces facts. The supervisor decides what to do.

**Allowed:** "3 employees have been below goal for 5+ consecutive days."  
**Not allowed:** "You need to coach these 3 employees today."

**Allowed:** "Performance dropped 12% after shift change last Tuesday."  
**Not allowed:** "Consider reassigning these employees or reviewing the shift change policy."

Recommendations that do appear (action queue, adaptive rail) must be framed as:  
- *What is happening* (the signal)  
- *Why it surfaced now* (the trigger / context)  
- *What the data says* (evidence)  

They must **not** frame as directives, prescribe management technique, or imply fault.

---

## 6. First-Session Value

A new user must reach a useful state within one session — defined as:
> After uploading data, the supervisor sees something they did not know (or were not sure about) that is specific to their team.

First-session value checklist:
- [ ] Import completes with a diagnosis (what data was found, how confident the result is)
- [ ] At least one signal is surfaced immediately after import (who is below goal, any pattern)
- [ ] The signal explains *why* it is being shown (not just "below goal" — but trend direction + streak length)
- [ ] There is a clear next action (go to Today queue, or drill into an employee)
- [ ] The empty state is never silent — it always explains what is missing and how to fix it

---

## 7. Daily-Use Goal

A returning supervisor should be able to open the app, see what needs attention, act on it, and close the app in **under 3 minutes**.

Design for this flow:
1. Open app → **Today page** (action queue, not dashboard)
2. See who needs follow-up today (sorted by urgency)
3. Log an outcome or add a note
4. Done

Every additional page is a drill-down from this loop, not an alternative entry point.

---

## 8. Simplicity Constraints

### Navigation
- Maximum 5–6 primary navigation items visible at any time.
- The default landing page for a returning user is **Today**, not Dashboard or Supervisor.
- Complex configuration (shift plan setup, integration settings) lives in Settings — not as a primary nav item.

### Per-page complexity
- Every page has **one primary action** a user can take.
- Every page has a **meaningful empty state** (not "no data found").
- No page should require scrolling past 3 sections to find actionable information.
- Tables are for drill-down only — never the first thing shown on a page.

### Progressive disclosure (mandatory)
All important surfaces must follow this order:
1. **Summary** — what is happening, in plain language (≤2 sentences)
2. **Context** — compared to what, how confident, how many affected
3. **Evidence** — drill-down to source rows, individual history, raw data

Do not show evidence at summary level. Do not bury summaries below evidence.

### Signal quality
- Do not show a signal if the data is insufficient to support it.
- Minimum confidence requirements before surfacing a trend: ≥3 data points.
- Annotate low-confidence signals with a visible caveat — do not suppress them entirely.
- Prefer 1 strong signal over 5 weak ones on the same page.

---

## 9. Overbuild Risks (Active Audit Findings — April 2026)

These are areas in the current codebase that risk violating the product mission:

### 9a. Prescriptive action language
- `services/recommendation_service.py` uses language like `"Coach → Document Pattern"` and `"emphasis"` fields that tell supervisors what to do next in specific terms.
- `ui/coaching_components.py` renders a "Recommended Action" rail that pushes the supervisor toward a specific employee.
- **Risk:** Becomes a coaching prescriptor, not a visibility tool.
- **Guardrail:** Frame recommendations as "signal + trigger," not "you should do X." Replace imperative labels with observational ones.

### 9b. Dashboard-heavy navigation
- There are currently 8 pages in `pages/`: dashboard, employees, import, productivity (Context/Analysis), supervisor, today, shift_plan, cost_impact, coaching_intel, settings, email.
- Many of these overlap in purpose (supervisor vs. dashboard vs. productivity all show team health).
- **Risk:** Users don't know where to go. Discoverability drops. Complexity rises.
- **Guardrail:** Consolidate around Today (execution) + Employees (drill-down) + Import. All other pages are secondary/settings-tier or fold into these.

### 9c. Table-first rendering
- `pages/dashboard.py` and `pages/productivity.py` render ranked employee tables as the main content.
- `pages/cost_impact.py` is almost entirely a table with calculations.
- **Risk:** Feels like a spreadsheet viewer, not an operating tool.
- **Guardrail:** Tables appear only inside expanders or drill-down views. First visible content must be a summary card or metric strip.

### 9d. Shift Plan as a WMS feature
- `pages/shift_plan.py` has setup flows for shift hours, departments, volume expectations, task-minutes-per-unit, and checkpoint management.
- **Risk:** Scope creep toward lightweight WMS. High configuration burden for minimal daily value.
- **Guardrail:** Shift Plan should exist only as a contextual aid for the Today queue, not as its own primary page. If it requires per-session configuration, it is too heavy.

### 9e. Cost Impact as a "money feature"
- `pages/cost_impact.py` is titled and designed as a ROI projection tool ("the money feature").
- Calculates "$/week lost," "value if at target," "coaching gain $/wk" per employee.
- **Risk:** Misleads supervisors into optimizing for cost metrics they don't control. Also oversimplifies the labor cost relationship.
- **Guardrail:** Cost context is a supporting lens, not a primary screen. Move to a secondary/expandable section inside Productivity or Today. Remove annual projection language.

### 9f. Coaching Intel as a standalone page
- `pages/coaching_intel.py` ("🧠 Actions") provides a team-wide coaching trend dashboard with auto-tagging and "what's working" analysis.
- **Risk:** Turns coaching observation data into a passive analytics layer — the opposite of follow-through focus.
- **Guardrail:** Move this signal into the Today queue as supporting context (e.g., "3 recent notes tagged 'speed issue' in Picking"). Don't make it a separate primary page.

### 9g. Adaptive recommendation system complexity
- `recommendation_service.py` and `action_recommendation_service.py` contain multi-variable recommendation logic (department patterns, momentum tracking, coached-today counter, same-dept chaining).
- **Risk:** Complex enough to be wrong in subtle ways, and hard to explain to the user why a recommendation appeared.
- **Guardrail:** Every recommendation shown in UI must trace back to one visible signal the user can verify. If the logic requires more than 2 hops to explain, simplify it.

---

## 10. Decision Framework for New Features

Before adding any new feature, answer all of these:

1. **Which of the three core questions does this answer?**  
   (What needs my attention? / What should I do next? / Did it work?)  
   If none, do not build it.

2. **Does this help a supervisor act, or does it help them analyze?**  
   Action → probably fits. Analysis → might be a secondary/drill-down only feature.

3. **Can a first-time user understand this on session one?**  
   If it requires understanding 3+ other features first, build those first or simplify.

4. **Does this surface a signal the supervisor can act on within the same session?**  
   If the signal is informational only (no possible follow-through path), do not surface it at the primary level.

5. **What is the empty/loading/error state?**  
   If you haven't designed these, the feature is not ready.

---

## 11. Language Standards

Use this language in UI copy, page titles, and feature names:

| Use | Avoid |
|---|---|
| "Needs attention" | "Low performer" |
| "Below goal" | "Underperformer," "at risk of termination" |
| "Follow-up due" | "You should coach" |
| "Trend: dropping" | "Declining performance score" |
| "Outcome: no change after 2 check-ins" | "Failed to improve" |
| "3 employees flagged" | "3 problem employees" |
| "Unresolved since [date]" | "Ignored for X days" |

---

## 12. What Success Looks Like

A supervisor who uses this product daily:
- Spends less than 3 minutes per morning logging what they observed.
- Never forgets to close out a follow-up they said they'd do.
- Can answer "what have you done about this?" with a log entry, not from memory.
- Sees trends emerge over 2–3 weeks without having to manually track spreadsheets.

A supervisor who gets value on session one:
- Sees their real team data reflected accurately within 10 minutes of first login.
- Understands why at least one employee is flagged (trend + streak + gap, not just "below goal").
- Has a clear next step surfaced for them before they close the tab.
