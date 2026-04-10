# UI Audit: App Quality & Explainability

**Date:** Current session  
**Scope:** All Streamlit pages + shared UI components  
**Against:** 8 Core Product Rules (highlight/interpret, no prescriptions, signal clarity, drill-down, confidence, data support, freshness, jargon)

---

## Executive Summary

**Overall Assessment:** Mixed. Today page and recent import improvements feel like **real product**. Most other pages feel like **sophisticated spreadsheets**.

**Root Cause:** Inconsistent application of existing "app-like" components. Good diagnosis + coaching impact + confidence UX framework exists in `ui/components.py` and `coaching_components.py`, but Dashboard, Coaching Intel, and Cost Impact pages skip this context layer and render tables + analysis directly.

**Confidence:** High. Evidence from page inspection shows pattern: pages that use cards + context explanations (Today, Employees) feel product-like. Pages that start with tables feel analytical/passive.

---

## Strengths

### ✅ Today Page (Action Queue)
- **What it does right:**
  - Every action has `_why_this_is_here()` explanation (answers Rule 2: "why is it being shown?")
  - Clear sorting (overdue → due today → pending)
  - Status badges show action state visually
  - "View Context" button provides drill-down to Dashboard
  - Primary recommendation strip (coaching rail) surfaces signal + context
  - Soft action buttons offer alternatives (check-in vs. escalate vs. coach)

- **Evidence:**
  - `ui/today_queue.py` line 220+: `_why_this_is_here()` maps action state to explanation
  - `ui/coaching_components.py`: `_render_primary_action_rail()` shows name + context + reasoning

- **User Experience:** New user imports data → sees queue → understands immediately what to do + why

---

### ✅ Coaching Components (Action Rails)
- **What it does right:**
  - `_render_primary_action_rail()`: Shows recommended action with context + emphasis
  - `_render_soft_action_buttons()`: Offers low-risk alternatives ("Schedule Check-In", "Add Note" vs. coaching)
  - Visual hierarchy: Red for critical, orange for high, white for OK
  - Helps user understand confidence level without needing to ask

- **Evidence:**
  - `coaching_components.py` lines 45–90: Multiple action options based on risk level
  - Color gradient logic (critical = red, high = orange)

---

### ✅ Import Page (Recently Improved)
- **What it does right:**
  - Dynamic button copy ("View X people below goal" vs. generic "Start your day")
  - Context about data freshness
  - Help text explaining UPH = "Units Per Hour when operating at target"
  - Shows post-import summary with count + next action

- **User Experience:** New user sees "You uploaded 30 people. 8 are below goal today → View them now"

---

### ✅ Existing Component Library
- **What's available but underused:**
  - `show_diagnosis()` — Signal card explaining what + why + confidence
  - `show_coaching_impact()` — Shows impact of coaching with trend
  - `_render_confidence_ux()` — Confidence indicator component
  - `show_operation_status_header()` — Context summary header
  - `show_pattern_detection_panel()` — Pattern explanation with data support

- **Problem:** These exist but are **NOT used consistently** across all pages

---

## Weaknesses

### ❌ Dashboard (Ranked Employee Table)
- **Current state:**
  - Renders filtered list → shows risk color → displays 1-page table
  - Table columns: Name, Department, UPH, Status, Trend, Last Coaching, Actions
  - Sorting by risk level (red → yellow → green)
  - No explanation of why employee is shown
  - No confidence indicator
  - No data freshness indicator

- **Rule violations:**
  - **Rule 2 (5 Ws):** User sees row for "Jane, Warehouse, 45 UPH, Below Goal" but cannot answer:
    - What is "Below Goal"? (compared to what?)
    - Why is Jane shown (most important, highest risk, most improvable)?
    - How confident is this signal? (based on 1 day? 1 week?)
    - How fresh is this data? (updated 2 hours ago, or 1 week ago?)
  - **Rule 3 (drill-down):** Button says "View Details" but takes user to Employees page (generic context, not contextual to this signal)

- **Evidence:**
  - `pages/dashboard.py` line ~56: `st.metric("Employees meeting goals", len(on_goal))` — single metric, no context
  - Line ~177: `st.dataframe()` — raw table render, no card wrapper
  - No visible "why is this data here?" explanation

- **User Impact:** Dashboard feels like data export, not insight

---

### ❌ Coaching Intel (Trends + Analytics)
- **Current state:**
  - Tabs: "trends" (line chart), "working" (active coaching issues), "notes" (coaching summaries)
  - Issue ranking bar chart
  - Trend analysis cards
  - Mostly observational (passive analytics)

- **Rule violations:**
  - **Rule 1 (no prescriptions):** Issue ranking suggests priorities but doesn't explain why
  - **Rule 2 (5 Ws):** User sees "Equipment issues: 3 recent incidents" but cannot answer:
    - Why is this issue surfaced? (most common? most impactful? new spike?)
    - What does "recent" mean? (last 7 days? 30 days?)
    - Should I take action based on this? (highlighting, not prescribing, is unclear)
  - **Rule 5 (confidence):** No confidence band, no sample size, no "based on X employees" context

- **Evidence:**
  - `pages/coaching_intel.py` shows trends but no reasoning
  - Tab structure is good (organized) but analytics feel disconnected from action

- **User Impact:** "Coaching Intel is interesting but I don't know what to do about it"

---

### ❌ Cost Impact (ROI Table)
- **Current state:**
  - Cost opportunity table
  - Shows wage, hours, potential impact
  - Wage settings editor
  - Single view: all data exposed at once

- **Rule violations:**
  - **Rule 2 (5 Ws):** User sees "$2,400 weekly cost impact" but cannot answer:
    - How is this calculated? (which employees included? which time period?)
    - How confident is this? (based on 1 week? roling 4-week average?)
    - Is this reliable? (what if someone works 1 shift this week?)
  - **Rule 4 (no over-spec):** Wage settings editor suggests "You can tune this to see different scenarios" — invites analysis paralysis

- **Evidence:**
  - `pages/cost_impact.py` shows table without calculation context
  - Wage settings panel invites configuration without guiding decision

- **User Impact:** "I don't trust these numbers"; "Why should I change wage settings?"

---

### ❌ Productivity (Table-Heavy Analysis)
- **Current state:**
  - Multiple views (Priority List, Trends, Distribution, Export)
  - Mostly render filtered DataFrames
  - Tables show employee UPH, department stats, weekly trends
  - No summary cards

- **Rule violations:**
  - **Rule 2 (5 Ws):** Tables show data but don't explain interpretation
  - **Rule 3 (drill-down):** User can see "Jane, 42 UPH, below 45 goal" but cannot click through to understand **why** (equipment issue? new employee? scheduling changes?)

- **Evidence:**
  - `pages/productivity.py` uses `st.dataframe()` for all views
  - No card summary before table
  - No "what does this mean for action?" context

- **User Impact:** "Productivity shows trends but I need to interpret them myself"

---

### ⚠️ Employees (Drill-Down)
- **Current state:**
  - Radio tabs: Performance Journal, Employee History, Coaching Impact, Export
  - Performance Journal: Free-form coaching notes + issue tagging
  - Shows coaching history + trends
  - Good UI structure but separated from action

- **Rule violations:**
  - **Rule 2 (5 Ws):** User sees coaching notes but cannot see:
    - Why coaching was needed (what triggered the coaching event?)
    - Has coaching been effective? (trend before + after coaching)
    - What baseline are we comparing to? (this team's average? supervisor's past history?)

- **Evidence:**
  - `pages/employees.py` shows coaching history but not coached-to-outcome tracking
  - No "coaching impact" visualization (before/after UPH trend)

- **User Impact:** Drill-down is detailed but doesn't help user understand coaching effectiveness

---

### ⚠️ Supervisor (Team Overview)
- **Current state:**
  - Shows priority strip (below goal, critical, quick wins)
  - Shows primary action rail (recommended coaching candidate)
  - Shows operation status summary
  - Coaching activity summary

- **Potential issues:**
  - Shares design with Today page (good consistency)
  - But might be **redundant** with Today page (both show recommended action)
  - Positioning: Is this "home page" or "secondary view"?

- **Rule violations:**
  - **Rule 5 (confidence):** Priority numbers (below goal, critical) lack confidence bands or caveats
  - Example: "🔥 Critical Risk: 5" — but if total team is 6, that's 83% (very high), vs. 5 of 50 (10%, lower urgency). No context.

---

## Top 5 UX Issues to Fix (Priority Order)

### 🔴 Issue 1: Signals Lack "Why This?" Context (All Pages)

**Problem:** User sees a signal (employee below goal, cost impact, coaching trend) but cannot answer "Why am I seeing this?" or "Should I act?"

**Locations:** Dashboard, Coaching Intel, Cost Impact, Productivity  
**Severity:** HIGH — Violates Rule 2 (5 Ws)  
**Frequency:** Every page except Today + Employees

**Current State:**
- Today page: ✅ Has explanations ("This follow-up date passed", "This employee has repeated pattern")
- Dashboard: ❌ No explanation for why employee is ranked
- Coaching Intel: ❌ No explanation for why issue is surfaced
- Cost Impact: ❌ No explanation for calculation

**Fix Approach:**
1. Add card summary above tables (move context up, not behind drill-down)
2. Every row/signal includes inline help (hover tooltip or info icon)
3. Context explains: What + Compared To + Why Shown + Confidence + Data Source
4. Example:
   ```
   Jane Smith | Warehouse
   45 UPH today (goal: 50) | ⚠️ Yellow Risk
   
   Why shown: Jane's UPH has been declining 
   for 3 days (was 52 → 50 → 48 → 45).
   
   Confidence: Based on 5 shifts this week.
   Last updated: 2 hours ago.
   
   [Drill into Jane's shifts] [Add note]
   ```

**Impact:** Users stay engaged ("I understand what this means"); confidence in signals increases

---

### 🔴 Issue 2: Tables as Primary Content (Dashboard, Productivity, Cost Impact)

**Problem:** Pages show tables first, analysis second. Feels like spreadsheet export, not product insight.

**Locations:** Dashboard, Productivity, Cost Impact  
**Severity:** HIGH — Violates Rule 1 (highlight, don't report)  
**Frequency:** 3 pages, high traffic

**Current State:**
- Rendering: `st.dataframe()` directly with no summary
- Structure: Table > Optional drill-down
- User journey: Scan rows, click one, interpret

**Fix Approach:**
1. Invert structure: Summary card first, table in expander (if needed)
2. Summary card shows: Top 3 insights + visual (bars, colors, trends)
3. Table becomes "see details" not "primary view"
4. Example:
   ```
   📊 Team Performance Summary (Today)
   
   On Goal: 23/30 (77%) ↑ up from 72% yesterday
   Below Goal: 7/30 | 3 trending down | 4 at risk
   
   [Expand to see list] | [Focus on at-risk]
   ```

**Impact:** Pages feel like insights first, data second (product, not report)

---

### 🔴 Issue 3: Missing Confidence & Freshness Indicators (All Pages)

**Problem:** User doesn't know if signal is based on 1 shift or 1 week, if data is 1 hour old or 1 day old, or if pattern is reliable or noise.

**Locations:** Dashboard, Coaching Intel, Productivity, Cost Impact  
**Severity:** HIGH — Violates Rule 5  
**Frequency:** All pages except Today

**Current State:**
- No visible confidence bands
- No sample size indicators
- No data freshness timestamps
- No margin-of-error callouts

**Fix Approach:**
1. Add confidence indicator component (exists: `_render_confidence_ux()`, but unused)
2. Every summary metric includes confidence badge:
   ```
   45 UPH ⚠️ [Based on 5 shifts] [Updated 2h ago]
   ```
3. Thresholds:
   - Green: 7+ days data, confidence > 90%
   - Yellow: 3–7 days data, confidence 70–90%
   - Red: <3 days data, confidence <70%
4. Example for Cost Impact:
   ```
   $2,400 weekly cost impact 🟡
   [Based on 4-week average] [Excludes unscheduled shifts]
   ```

**Impact:** Users trust signals; false alarms decrease

---

### 🔴 Issue 4: Drill-Down Paths Not Contextual (Dashboard → Employees)

**Problem:** User sees signal on Dashboard → clicks "Details" → lands on generic Employees page without context from the signal.

**Locations:** Dashboard (→ Employees), Coaching Intel (→ Employees?)  
**Severity:** MEDIUM — Violates Rule 3 (drill-down tells story)  
**Frequency:** Dashboard accesses are high traffic

**Current State:**
- Dashboard table row → "View Details" button
- User lands on Employees page (generic view)
- No context passed: "Why was I shown this employee?"

**Fix Approach:**
1. Pass context in `session_state`: `cn_selected_emp` + reason tag (e.g., "trending_down", "repeat_issue")
2. Employees page pre-selects context:
   - If reason = "trending_down": Show trend chart first, then notes
   - If reason = "repeat_issue": Highlight repeated patterns, show coaching history
3. Breadcrumb shows: Dashboard → Jane (Trending Down)
4. Context card at top:
   ```
   📍 You came from: Dashboard (Employee Risk View)
   Jane's UPH has been declining 3 days. 
   [See her shift history] [See coaching notes]
   ```

**Impact:** Drill-down tells coherent story; user understands navigation

---

### 🟡 Issue 5: Supervisor Page May Duplicate Today (Navigation Confusion)

**Problem:** Both Supervisor and Today pages show recommended action + priority strip. Unclear which is home, which is secondary.

**Locations:** Supervisor, Today  
**Severity:** MEDIUM — Violates Rule 1 (progressive disclosure)  
**Frequency:** New user confusion first 10 minutes

**Current State:**
- Both pages include coaching rail + priority metrics
- Inconsistent mental model: Is "Today" for actions, "Supervisor" for overview, or vice versa?

**Fix Approach (Recommend One):**
- **Option A:** Make Today the home (action queue → single decision), Supervisor secondary (team overview → trends)
- **Option B:** Make Supervisor the home (team health / coaching opportunities → what to do today), Today secondary (detailed action queue)
- **Option C:** Retire Supervisor, enhance Today to show both action + team context in one flow

**Evidence for recommendation:**
- First-session flow showed: new users want action queue first (Today page works)
- Daily habit loop design specified: "why a user opens the app today" = action queue
- Current nav shows both equally (confusing)

**Recommendation:** Make Today the home (action-centered). Make Supervisor a "Team Health" drill-down (optional, for weekly reviews).

**Impact:** New user has clear entry point; fewer clicks to first action

---

## Missing Design Patterns

### 1. Signal + Reason Card
**Not implemented consistently.** Exists in Today page + coaching components, but missing from Dashboard, Productivity, Cost Impact.

**Pattern:**
```
[SIGNAL CARD]
├─ Metric (large)
├─ Status (color badge)
├─ Reason (plain text, "Why shown")
├─ Confidence (small badge)
└─ Data source (tiny caption)

[DRILL-DOWN]
├─ Show details button
└─ Context preserved in session
```

**When to use:** Every page where a user sees data < 10s after landing

---

### 2. Freshness Indicator
**Not implemented.** Cost Impact is 1-week rolling (but not flagged). Productivity shows daily (but user doesn't know). Dashboard shows real-time? (unclear).

**Pattern:**
```
[DATA FRESHNESS]
├─ Green circle: Updated < 2 hours
├─ Yellow circle: Updated 2–12 hours ago
├─ Red circle: Updated > 12 hours ago
└─ Tooltip: "Last updated at 2:45 PM" + "Refreshes every 4 hours"
```

**When to use:** Any metric, any page

---

### 3. Confidence Band
**Component exists (`_render_confidence_ux()`) but unused.**

**Pattern:**
```
[CONFIDENCE BAND]
├─ "Based on 7 days of data" (green = reliable)
├─ "Based on 2 shifts" (yellow = early signal)
└─ Sample size (N=5 shifts) + margin of error (±3 UPH)
```

**When to use:** Any chart, trend, or ranking

---

### 4. Contextual Drill-Down
**Currently not preserved.** Dashboard → Employees loses "why were they shown?"

**Pattern:**
```
Session state:
- cn_selected_emp = "emp_123"
- cn_reason = "trending_down" | "repeat_issue" | "at_risk" | etc.
- cn_source_page = "dashboard" | "coaching_intel" | etc.

Employees page:
- Reads cn_reason
- Highlights relevant tab (Coaching Impact, not notes)
- Shows tip: "You came from Dashboard Looking At: [reason]"
```

**When to use:** Any drill-down button

---

## Recommendations by Page

| Page | Current Feel | Primary Issue | Quick Fix | Effort |
|------|--------------|---------------|-----------|--------|
| **Today** | ✅ Product | None | Maintain | — |
| **Supervisor** | ⚠️ Mixed | Duplicate with Today | Clarify positioning OR retire | 1–2 hours |
| **Dashboard** | ❌ Spreadsheet | Table-first, no context | Add summary card, move table to expander | 2–3 hours |
| **Productivity** | ❌ Spreadsheet | Table-first, no drill-down context | Add summary card, contextual drill-down | 2–3 hours |
| **Coaching Intel** | ⚠️ Analytics | Passive, no explainability | Add "why this signal?" cards | 2 hours |
| **Cost Impact** | ❌ Spreadsheet | No context on calculations | Add calculation card above table | 1–2 hours |
| **Employees** | ⚠️ Detailed | Lacks coaching effectiveness tracking | Add before/after coaching trend | 1–2 hours |
| **Shift Plan** | ⚠️ WMS-lite | Low daily value (MEDIUM risk per guardrails) | Audit separately (low priority) | TBD |

---

## Recommended Implementation Order

### Phase 1 (Highest impact + Lowest effort): **Freshness + Confidence (All Pages)**
- **Estimated effort:** 4 hours
- **Highest value pages:** Dashboard, Productivity, Cost Impact
- **Reason:** Fixes Rule 5 (confidence) quickly, increases trust immediately
- **Outcome:** Users see data freshness everywhere + confidence badges on metrics

### Phase 2 (High impact): **Context Cards + Summary-First (Dashboard → Productivity → Cost Impact)**
- **Estimated effort:** 6–8 hours
- **Phases:**
  1. Dashboard: Add summary card, move table to expander
  2. Productivity: Add summary card, add contextual drill-down
  3. Cost Impact: Add calculation explanation card
- **Reason:** Fixes Rule 2 (5 Ws) and Rule 1 (highlight vs. report)
- **Outcome:** Pages feel like insights first, data second

### Phase 3 (Medium impact): **Fix Navigation (Supervisor vs. Today)**
- **Estimated effort:** 2–3 hours or 1 hour (depending on option chosen)
- **Decision required:** Keep both (clarify) or retire one?
- **Reason:** Reduces new user confusion on first visit
- **Outcome:** Clear entry point, fewer lost users in first 10 minutes

### Phase 4 (Finesse): **Coaching Lifecycle + Effectiveness (Employees Page)**
- **Estimated effort:** 3–4 hours
- **Reason:** Validates if coaching is working (impact measurement)
- **Outcome:** Managers see coaching effectiveness, trust recommendations

---

## Success Metrics (Post-Audit)

After implementing fixes, validate against:

1. **Rule 2 Compliance:** "Can a new user answer 5 Ws for any metric in < 30 seconds?"
   - Test: Show user a metric, ask "Why are you showing me this?" Record time to answer
   - Target: <30 seconds, confidence answer > 80%

2. **App vs. Spreadsheet Feeling:** "Does this feel like a tool made for me or a data export?"
   - Test: Show user a page, ask "Would you use this daily?"
   - Target: 80% of pages score "product", not "report"

3. **Drill-Down Coherence:** "Do I understand why I ended up here?"
   - Test: Drill-down from Dashboard → Employees, ask "Why was this person shown?"
   - Target: 90% of drill-downs include context in breadcrumb or summary

4. **Signal Confidence:** "How confident are you in what this page tells you?"
   - Test: Show metrics with/without confidence badges, ask "Do you trust this?"
   - Target: Confidence badges increase trust score by 20%+

---

## Appendix: Component Inventory

### Existing App-Like Components (In `ui/components.py`)
- ✅ `show_diagnosis()` — Signal explanation card
- ✅ `show_coaching_impact()` — Before/after coaching card
- ✅ `_render_confidence_ux()` — Confidence badge component
- ✅ `show_operation_status_header()` — Context summary header
- ✅ `show_pattern_detection_panel()` — Pattern explanation
- ✅ `show_start_shift_card()` — Action card (shift context)
- ✅ `show_shift_complete_state()` — Completion card

### Existing Coaching Components (In `ui/coaching_components.py`)
- ✅ `_render_primary_action_rail()` — Recommended action (Today + Supervisor)
- ✅ `_render_priority_strip()` — Priority metrics (Below Goal, Critical, Quick Wins)
- ✅ `_render_soft_action_buttons()` — Alternative actions (Check-In, Note, Escalate)

### Components to Create/Enhance
- ⏳ **Freshness Indicator** — Timestamp + circle badge (green/yellow/red)
- ⏳ **Signal Context Card** — Metric + Reason + Confidence + Freshness (wrapper)
- ⏳ **Contextual Drill-Down Helper** — Session state preservation + breadcrumb
- ⏳ **Summary/Expander Pattern** — Card-first, table-in-expander layout

---

## Conclusion

Your app is **not a spreadsheet**. But 3–4 pages feel like one because they skip the "app-like" middle layer (context cards, confidence, freshness). The framework exists (`ui/components.py`, `coaching_components.py`). The patterns work (Today page + recent import improvements prove it).

**Next step:** Apply these patterns consistently across all pages. Start with freshness + confidence (4 hours), then tackle summary cards (6–8 hours).

**Question for user:** Which of the three rules violation categories is most important to fix first?
1. **Context/Explainability** (Rule 2: "Why is it showing me this?") — Fixes dashboard, productivity
2. **Confidence** (Rule 5: "How confident is this?") — Fixes all pages
3. **Drill-Down** (Rule 3: "Does the story flow make sense?") — Fixes dashboard → employees
