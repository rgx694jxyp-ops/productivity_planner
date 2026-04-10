# DAILY HABIT LOOP
> How managers open this app every day (not just in crisis)  
> Status: Design spec only. No feature changes yet.  
> Updated: 2026-04-09  
> Aligned with: PRODUCT_GUARDRAILS.md, FIRST_SESSION_FLOW.md

---

## Overview

The daily habit loop is the heartbeat of supervisor adoption. It answers:

1. **Why** open the app today?
2. **What** understanding is possible in 60 seconds?
3. **What** can be confirmed or logged quickly?
4. **How** is the app useful even when nothing is critically wrong?
5. **How** does incomplete data become intelligence, not confusion?

This document defines the *experience* of daily use, not the mechanics. Implementation follows design approval.

---

## The Daily User Journey (Ideal)

### 08:00 AM — Standing at the line, about to start shift

**Trigger:** Shift kickoff / standup / morning routine  
**Current behavior:** Maybe pulls up a spreadsheet or logs into WMS  
**Desired behavior:** "Let me check DPD for 60 seconds"

**Why they open:**
- They **know** someone needed coaching yesterday — did they follow up?
- They **want to know** who's struggling before taking floor visibility
- They **should log** what they observed during the shift yesterday (if not done live)
- They **want to confirm** their action worked or adjust approach

**The ask is not:** "Use this data to make a decision"  
**The ask is:** "Use this to stay on top of your follow-throughs"

---

## The 60-Second Understanding

### Landing Page → What a Supervisor Sees

**When they open the app (landing on Today page):**

```
┌──────────────────────────────────────────────────────────────┐
│ Who needs your attention today?                              │
│                                                              │
│ QUEUE SUMMARY (5 buttons, pick one)                          │
├──────────────────────────────────────────────────────────────┤
│  [ 0 Overdue ] [ 2 Due today ] [ 1 Repeat ] [ 3 Recognition ] 
│  [ 5 Total open ]                                            │
├──────────────────────────────────────────────────────────────┤
│ ACTION QUEUE (sortable, tappable)                            │
├──────────────────────────────────────────────────────────────┤
│ 1. John Smith (Picking) — OVERDUE follow-up from 3 days ago │
│    Coached: Performance was 5.2 UPH, target 7.5             │
│    Reason: Trending down + below goal × 4 days              │
│    What we're looking for: Get to 6.5+ and stay there      │
│    [ Log note ] [ Check in ]                                │
│                                                              │
│ 2. Sarah Lee (Packing) — DUE TODAY                          │
│    (Details, actions)                                        │
│                                                              │
│ SINCE YESTERDAY (collapsible strip)                         │
├──────────────────────────────────────────────────────────────┤
│  ✓ 1 Improved  •  — 2 No change  •  ✗ 0 Worse              │
│  ⏰ 3 Still overdue                                          │
└──────────────────────────────────────────────────────────────┘
```

**What they understand in 60 seconds (without scrolling):**
1. **Status at a glance** — 2 people due today, 0 overdue (good) or 2 overdue (needs attention)
2. **Who to see first** — Sorted by urgency (overdue floats to top)
3. **Why that person** — Simple 1-line reason (trending down, below goal × N days, repeat issue)
4. **Quick outcome** — Did yesterday's actions work? (1 improved, 2 no change = progress?)
5. **Next move** — Button options: Log note, Check in, Recognize, Escalate

**Critically: No scrolling required to see top 3 queue items**

---

## Quick Actions (< 2 minutes)

A manager should be able to do ONE of these in under 2 minutes without leaving the app:

### 1. **Log Outcome** (30 seconds)
*"Did the coaching you did yesterday work?"*

```
[ Did this improve? ]
  ○ Improved — performance went up or stabilized
  ○ No change — still struggling
  ○ Worse — got worse
  ○ Blocked — external issue (eq breakdown, short staffed)
  ○ N/A — something changed
  
[Optional note field]
```

**Why:** Closes the loop. Shows this follow-up is tracked. Informs next steps.

### 2. **Quick Note** (30 seconds)
*"What did you observe today that didn't fit yesterday?"*

```
Type: [Coaching update / General note / Issue flagged]
Employee: [Select]
Note: [Free text, 100 chars]
When did this happen? [Today / Yesterday / Earlier]
```

**Why:** Captures teachable moments before they're forgotten.

### 3. **Recognize** (20 seconds)
*"Someone crushed it today."*

```
Employee: [Select]
Quick note: [100 chars]
```

**Why:** Closes the "plus side" loop. Prevents good performance being invisible.

### 4. **Escalate** (30 seconds)
*"This isn't getting better with coaching."*

```
Employee: [Select]
Reason: [Repeat no-improvement / Unsafe / Other]
Detail: [Optional]
Alert: [Supervisor / Manager / HR]
```

**Why:** Marks when individual coaching isn't sufficient.

---

## Deep Dives (Available, Not Required)

These are 2–5 minute dives that may be valuable some days, but not every day:

### A. **Drill into an employee** (2–3 min)
- Last 7 days of performance (chart + raw numbers)
- All coaching notes on file for this person
- Trigger reason (why they're in the queue)
- Comparison to peer / department baseline

### B. **See department pattern** (2–3 min)
- 3+ people in Picking are below goal
- Common thread: all trending down
- Suggested pattern (shift change? Equipment? New batch?)

### C. **Review your coaching effectiveness** (3–5 min)
- How many you coached this week
- How many improved after coaching
- Repeat issues (same person twice, different issue)

---

## Usefulness When Quiet

**The big question:** *If all employees are on goal, why open the app?*

This is where daily habit breaks. Design must ensure value even when there are no crises.

### Scenario 1: All employees on target
**Current behavior:** Empty state → "nothing to do" → user stops opening

**Redesigned behavior:**
```
┌─────────────────────────────────────────────┐
│ ✓ Your team is on target today!             │
│                                             │
│ So far this week:                           │
│ • 2 coached to improvement                  │
│ • 5 recognized for performance              │
│ • 1 pattern caught (short staff in dock)    │
│                                             │
│ What's working:                             │
│ • Packing dept trending up (avg +6% UPH)    │
│ • Picking stable day-to-day variance low    │
│                                             │
│ Next check: New hire ramping (on track)     │
│ Recognition due: Top 3 performers          │
│                                             │
│ [ Log observation ] [ Recognize ] [ Drill ]│
└─────────────────────────────────────────────┘
```

**Key insight:** Show progress trackers, trending data, and recognition opportunities. Value isn't just "catch problems" — it's "track improvements and maintain momentum."

### Scenario 2: Data is stale (hours old)
**Current behavior:** User sees outdated queue, gets confused

**Redesigned behavior:**
```
⚠ Performance data was last updated 8 hours ago (8 AM).
  Live data may have changed. Next refresh: before 6 PM.
  
👉 If performance changed significantly, log a note:
  [ + Data observation ]
```

**Key insight:** Be honest about data freshness. Don't pretend real-time is possible. Make note-capture the "manual update" path.

### Scenario 3: New hire ramping
**Current behavior:** Just sees below-goal, might discourage coaching

**Redesigned behavior:**
```
Alex Chen — New employee (started 3 days ago)
Status: Below goal ← Expected for ramp (normal)
Baseline: N/A (first week)
Approach: Monitor daily, adjust targets after day 7
[ Log ramp observation ] [ Set targets after ramp ]
```

**Key insight:** Context matters. Same below-goal signal means different things for different people.

---

## Interpretation Under 60 Seconds

For a signal to be acted on, a manager must understand it in under 60 seconds. This means every piece of information needs:

### The "5 Ws" for each queue item:

**What happened?**
```
John's performance dropped 12% since the shift change Tuesday.
```

**Compared to what?**
```
His baseline is 7.5 UPH. He was at 8.1 last week before the change.
```

**Why is this being shown?**
```
He's been below goal × 4 consecutive days + trending down = higher risk.
```

**How confident are we?**
```
ℹ️ Based on 4 days of data. Still consistent enough to warrant check-in.
```

**What should they do?**
```
→ Check in about the shift change. Ask if it's a workflow or adjustment issue.
→ If it's adjustment, follow up again tomorrow.
→ If it's workflow, may need to escalate to ops.
```

**Example on card:**
```
┌────────────────────────────────────────┐
│ John Smith — OVERDUE follow-up        │
├────────────────────────────────────────┤
│ Performance: 5.2 UPH (was 8.1)        │
│ Status: Below goal × 4 days           │
│ Trend: Down 12% (since Tue 2/10)     │
├────────────────────────────────────────┤
│ Why shown:                            │
│ • Consistent below target             │
│ • Downward direction                  │
│ • No follow-up since coaching Wed     │
├────────────────────────────────────────┤
│ Next step:                            │
│ → Check what changed (shift? eq?)     │
│ → Log what you find                   │
│ → Schedule next check                 │
│                                       │
│ [ Log outcome ] [ Log note ] [ Skip ]│
└────────────────────────────────────────┘
```

**What a manager can understand in 60 seconds:**
- ✓ Who needs a follow-up (name, what they do)
- ✓ Why (one clear reason, not a laundry list)
- ✓ Data freshness (from when?)
- ✓ What action is helpful (not prescriptive, just a suggestion)
- ✓ How to log it

**What requires drilling down (not in 60 sec):**
- Historical performance (before the drop)
- Coaching notes history
- Peer comparison
- Department trends

---

## Confidence Cues

The app must communicate data confidence without jargon.

### Confidence levels on every queue item:

**High confidence:**
```
✓ Strong signal — 2+ weeks of data, consistent pattern
  Based on 10 days of performance
  Seen this pattern before [links to past issue if repeat]
```

**Medium confidence:**
```
● Moderate signal — early but clear
  Based on 4 days of performance
  Pattern is consistent but short-term, may adjust
```

**Low confidence (suppress or demote):**
```
⊙ Weak signal — too limited data
  Based on 1 day of data
  May just be normal variance. Wait for more data before acting.
  
  Next check: After 3 more days of data
```

### Freshness cues:

**Live / Today:**
```
📡 Updated before shift (6:00 AM)
```

**Recent:**
```
🕐 Updated 2 hours ago
```

**Stale:**
```
⏳ Last updated 12 hours ago (8:00 AM)
   Live data may have changed. Next update: 6:00 PM
```

**Missing:**
```
❌ No performance data since Monday
   Can't surface signals without recent data.
   [ Import today's data to refresh ]
```

---

## Follow-Through Visibility

The core product promise: "Did my action work?"

### The outcome loop:

```
1. IDENTIFY
   ↓
   Coaching note logged
   Follow-up scheduled: Feb 15
   
2. COACH
   ↓
   Manager checks in with employee
   Discusses shift change issues
   
3. LOG OUTCOME
   ↓
   Manager records: "Improved"
   New baseline established
   
4. FOLLOW UP
   ↓
   Tomorrow: John's at 6.8 UPH (up from 5.2)
   Still below target, but moving right direction
   
5. RECOGNIZE (or escalate if not improving)
   ↓
   If trend continues: positive recognition
   If trend stalls: escalate or change approach
```

### Visibility points:

**When logging outcome, show:**
```
You coached John on Feb 12 at 2:30 PM
His performance then: 5.2 UPH
His performance today: 6.8 UPH (+1.6, +31%)

Status: Improving
Next check: Tomorrow (Feb 16)
```

**When outcome stalls, surface it:**
```
⚠ Follow-up due: Feb 16
   Last checked: Feb 15 — Improved to 6.8 UPH
   Today's performance: 6.4 UPH
   Status: Slight decline, but within variance
   
   Decision: Continue observing or re-engage?
   [ Continue ] [ Coach again ] [ Escalate ]
```

**Weekly summary (optional, but supportive):**
```
This week you coached 3 people:
• John Smith — Improved (5.2 → 6.8)
• Maria Garcia — No change (6.1 → 6.3)
• Robert Chen — Worse (7.2 → 6.9)

Overall: 1 improved, 1 stable, 1 declined
Trend: Mostly stable week, one success
```

---

## Handling Incomplete/Stale Data

The app must remain useful (and trusted) even when data is incomplete.

### Scenario A: Employee has no baseline
**Don't say:**
```
"Insufficient data to evaluate"
```

**Instead say:**
```
Jake is new — no baseline yet (started 2 days ago)
Tracking: 5.2 UPH, 6.1 UPH (day-by-day)
Status: Monitor for 5 days to establish baseline

Still here to help you track coaching and log notes.
```

### Scenario B: One department has no data for today
**Don't hide it:**
```
Picking started late (8:30 instead of 8:00)
Only 2 hours of data so far
Expected update: After next break or shift end

Meanwhile: Packing and Dock data is live ↓
```

### Scenario C: Stale data (last update 12 hours old)
**Don't ignore it:**
```
⏳ Last update: 8:00 AM (12 hours ago)

Known: Picking had a breakdown around 11 AM
Visible impact: Unknown

You can help: Log what you're seeing now
[ Log observation ] [ Import latest data ]
```

### Scenario D: Data conflict (WMS says one thing, import says another)
**Be honest:**
```
⚠ Data mismatch detected
WMS shows 34 units for John today
Your import shows 28 units

Which is correct?
[ Use WMS data ] [ Use import data ] [ Don't know, need help ]
```

### Scenario E: Employee hasn't been coded into system yet (appears in WMS but not in app)
**Don't show them in queue, but note it:**
```
👤 New employee detected: Jessica Park (Picking)
   Status: Not yet in coaching system
   
   Options:
   [ Add to tracking ] [ Not starting yet ]
```

---

## Daily Habit Success Metrics

When the daily habit loop is working:

1. **Usage frequency:** Managers open app 4–5 days per week (not daily, but habitual)
2. **Session length:** Most sessions < 5 minutes (not a time sink)
3. **Quick actions:** 60–70% of sessions include at least one logged outcome/note
4. **Return rate:** Manager opens within 24 hours of logging something (closing loops)
5. **Queue reductions:** Open items close within 2–3 days of entry (actions are happening)
6. **Confidence:** Fewer "wait, is this outdated?" questions in support (data freshness clear)

---

## Design Principles for Daily UX

### 1. **Prioritize the past over the future**
Show "did yesterday work?" before "here's tomorrow's prediction."

### 2. **Outcomes > Rankings**
Show improvement from actions taken, not just a leaderboard.

### 3. **Confidence > Comprehensiveness**
Show fewer signals that are stronger, not more signals that are weaker.

### 4. **Actionable > Informational**
Every displayed signal should have a "what now?" path visible.

### 5. **Quick over complete**
Let managers log 20% now and 80% later, rather than nothing.

### 6. **Honest about data**
Show freshness, completeness, and limitations. Users adapt better than they trust false certainty.

### 7. **Recognition = Momentum**
Balance "who needs help" with "who's doing well." Both are motivational.

---

## What Daily Habit Loop Does NOT Do

- Does not tell managers how to manage people
- Does not rank employees (by performance metric)
- Does not prescribe coaching approach or frequency
- Does not punish or reward based on data
- Does not require daily data entry (just accepts it)
- Does not become another reporting tool

---

## Next Steps (Design → Implementation)

Before building, confirm:

1. **Is Today page the right landing?**
   - Or should Supervisor view be the default?
   - Decision needed: Single entry point vs. task-based routing?

2. **Can we compute queue status live?**
   - Overdue / Due today / Repeat / Recognition sorting
   - What data triggers each bucket?

3. **What's the "Since yesterday" calculation?**
   - How far back = "yesterday"?
   - Do outcomes stay visible or clear after a day?

4. **How do we handle empty queue gracefully?**
   - What value exists when no actions are due?
   - What encourages opening anyway?

5. **What's the minimum viable quick action?**
   - Log outcome only? Or note + outcome?
   - Should recognitions go the same path?

6. **How fresh should we claim data is?**
   - What's acceptable staleness? (6 hours? 24 hours?)
   - When do we suppress signals?

---

## Implementation Tracking

These are phase changes, not feature adds. Order matters:

- [ ] **Phase 1:** Clarify queue buckets (overdue, due today, repeat, recognition)
- [ ] **Phase 2:** Implement outcome logging loop (brief → saves → surfaced next session)
- [ ] **Phase 3:** Add "since yesterday" outcome summary
- [ ] **Phase 4:** Suppress low-confidence signals (don't surface < 3 days data)
- [ ] **Phase 5:** Add data freshness indicators to every signal
- [ ] **Phase 6:** Empty-state redesign (when no actions due, show progress instead)
- [ ] **Phase 7:** Quick notes path (type-action-log in < 30 sec)
- [ ] **Phase 8:** Recognition quick action
- [ ] **Phase 9:** Weekly summary (optional, but closes motivation loop)

---

## Alignment with Core Product

**Daily Habit Loop directly supports the 3 core questions:**

1. **What needs my attention right now?**  
   ✓ Queue sorted by urgency (overdue first)

2. **What should I do next?**  
   ✓ Actions are visible (Log outcome, Check in, Recognize)

3. **Did it work?**  
   ✓ Follow-through loop is visible (coached → did they improve → logged → next step)

**Respects non-goals:**
- ✓ Does not prescribe coaching approach
- ✓ Does not tell users how to manage people
- ✓ Does not replace performance review
- ✓ Does not become a dashboard

