# Coaching & Employee Tracking System

A comprehensive guide to the DPD coaching feature—your platform's most powerful asset for continuous improvement and performance management.

---

## 🎯 Overview

The Coaching & Employee Tracking system helps you:
- **Identify employees needing support** (below target UPH, downward trends)
- **Document coaching conversations** with timestamped notes
- **Track progress over time** with flagging and trend analysis
- **Prioritize interventions** based on risk levels and impact potential
- **Maintain accountability** with audit trails of all coaching activity

---

## 📍 Where Everything Lives

### Main Interface Locations

1. **Employees Page** - Primary coaching hub
   - **Path**: Left sidebar → "👥 Employees"
   - **File**: `pages/employees.py`
   - **Two tabs**: Performance Journal | Coaching Insights

2. **Supervisor View** - Daily oversight dashboard
   - **Path**: Left sidebar → "👔 Supervisor"  
   - **File**: `pages/supervisor.py`
   - **Sections**: Team health, top risks, trending down, cost impact

3. **Dashboard** - Historical trends and analysis
   - **Path**: Left sidebar → "📊 Dashboard"
   - **File**: `pages/dashboard.py`
   - **Focus**: Employee rankings, department trends

---

## 🔄 The Coaching Workflow

### Step 1: Identify (Supervisor View)

When you log in, the **Supervisor View** immediately shows:

```
┌─────────────────────────────────────────┐
│  📊 Team Health Snapshot                │
│  ─────────────────────────────────────  │
│  On Target: 12 employees                │
│  Below Target: 3 employees              │
│  Trending Down: 2 employees             │
│  High Risk: 1 employee                  │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  🔴 Top Risks — Action Required Today   │
│  ─────────────────────────────────────  │
│  1. John Smith (Picking) - 6.5 UPH     │
│     🔴 Below goal + Declining trend     │
│  2. Jane Doe (Packing) - 8.2 UPH       │
│     🟡 Below goal + Flat trend         │
└─────────────────────────────────────────┘
```

**Key Signals:**
- 🔴 Red = High priority (below goal + downward trend)
- 🟡 Yellow = Monitor (below goal or declining)
- 🟢 Green = On track
- ⭐ Star = Top performer (>150% of target)

### Step 2: Drill Into Details (Employees Page)

1. Click **"👥 Employees"** tab in sidebar
2. Select **"Performance Journal"** tab (left side)
3. **Employee roster appears** on the left with indicators:
   - **🚩 Flag icon** = Employee is flagged for follow-up
   - **📝N** = Employee has N coaching notes
   - **↑ ↓ →** = Trending up, down, or flat

4. **Click any employee row** → Their detail panel appears on the right

### Step 3: Review Employee Status

The **Employee Detail Panel** shows (right side):

```
┌─────────────────────────────────────────┐
│  John Smith (ID: E001)                  │
│  Department: Picking                    │
│  ─────────────────────────────────────  │
│  Current: 6.5 UPH (Calc'd from this    │
│  week's data)                           │
│  Target: 12.0 UPH                       │
│  Status: 🔴 Below Goal                  │
│  Trend: ↓ Declining 12% week-over-week  │
│                                         │
│  Last Coaching: 2 days ago              │
│  Coaching Impact: +0.8 UPH estimated   │
│         (what this person could gain)   │
└─────────────────────────────────────────┘
```

**Colors indicate status:**
- Black text = Neutral/on-target performance
- Red text = High alert (below goal + trend down)
- Blue text = Good news (trending up/top performer)

### Step 4: Take Action - Document Coaching

Below the status, you'll see **Coaching Actions**:

```
┌─────────────────────────────────────────┐
│  📋 Next Coaching Step                  │
│  ─────────────────────────────────────  │
│  Suggested: Check station setup,       │
│  help with process efficiency          │
│                                         │
│  🚩 Flag Status: [Not Flagged]          │
│     [→ Flag for follow-up]              │
│                                         │
│  📝 Add Context or Notes                │
│  ─────────────────────────────────────  │
│  [Text area for your notes]             │
│                                         │
│  Optional: Your Name                    │
│  [Enter your name if multi-user]        │
│                                         │
│  [💾 Save Note]                         │
│                                         │
│  📜 Coaching History (Previous notes)   │
│  ─────────────────────────────────────  │
│  ▼ Expand to see past conversations     │
└─────────────────────────────────────────┘
```

### Step 5: Navigate to Next Employee

After saving a note:
```
→ [Next Employee: Jane Doe]  ↩ [Back to List]
```

Clicking **"→ Next Employee"** takes you to the next highest-priority employee (usually the next person below goal or trending down).

---

## 📝 Add Notes/Context: What It Does

### What You're Doing

When you type notes and click "💾 Save Note", you're creating a **coaching record** that:

1. **Timestamps automatically** with the exact date/time you added it
2. **Stores your name** (if you enter it) to track who coached
3. **Links to that employee** so their history is easily accessible
4. **Becomes part of their record** - visible in Coaching History
5. **Feeds analytics** - helps identify which interventions are most effective

### Example Note

```
📝 Added by: Manager Alice | 2025-01-15 10:32 AM

"Discussed new picking technique with John. Showed him the 
optimized path through the warehouse that cuts 2 min per 
order. He seemed engaged. Follow up next Tuesday to see 
if he's adopting the technique."
```

**System captures:**
- Your message text
- Your name (optional, defaults to "Anonymous")
- Exact timestamp (in your configured timezone)
- Link to employee (John Smith, ID E001)

### Where Notes Appear

**Same notes visible across:**
1. **Employees page** → Coaching History expander (shows all past notes)
2. **Coaching Insights tab** → AI recommendations reference these notes
3. **Supervisor view** (upcoming feature) → Activity summary

---

## 🚩 Flagging: How It Works

### Why Flag?

Flagging marks an employee for **immediate attention** or **follow-up**:
- You want to check in again in X days
- They need specific resources (training, equipment, reassignment)
- They're a retention risk

### How to Flag

**Method 1: From Employee Detail Panel**
1. Select employee in roster
2. Look for **"🚩 Flag Status: [Not Flagged]"**
3. Click **"[→ Flag for follow-up]"** button
4. ✅ Status changes to **"🚩 Flagged"** (shown in red)
5. Employee's row in roster now shows **🚩** icon

**Method 2: From Employees List** (Bulk)
1. Switch to **Dashboard** tab
2. Look for bulk actions or filters
3. Select multiple employees + flag them together

### What Happens When Flagged

1. **Roster indicator updates** → 🚩 now visible next to their name
2. **Flagged date recorded** → System notes when they were flagged
3. **Shows in Supervisor view** → Flagged count appears in summary
4. **Coaching Insights filter** → "Show flagged employees only" option

### How to Unflag

1. Go back to employee detail panel
2. Look for **"🚩 Flagged"** status with unflag button
3. Click **"[Remove flag]"**
4. Status returns to "Not Flagged"
5. Coaching history is preserved (flags don't erase notes)

---

## 🧠 Coaching Insights Tab: AI-Powered Recommendations

Switch to the **"Coaching Insights"** tab (top of Employees page) to see:

```
┌─────────────────────────────────────────┐
│  Coaching Insights                      │
│  Filter: [All] [🔴 Urgent] [🟡 Monitor]│
│  ─────────────────────────────────────  │
│  🔴 HIGH PRIORITY                       │
│  ─────────────────────────────────────  │
│  John Smith (Picking) — 44% below goal  │
│  • Days below goal: 12 consecutive      │
│  • Recent trend: -15% week over week    │
│  • Specific action: Check workstation   │
│  • Why: Short cycle time suggests       │
│    speed but low efficiency             │
│                                         │
│  🟡 MEDIUM PRIORITY                     │
│  ─────────────────────────────────────  │
│  Jane Doe (Packing) — 31% below goal    │
│  • Days below goal: 5 of last 7         │
│  • Recent trend: Stable (flatting)      │
│  • Specific action: Pair with top       │
│    performer for 1 week                 │
│  • Why: Peer mentoring often effective  │
│                                         │
│  ⭐ TOP PERFORMERS                      │
│  ─────────────────────────────────────  │
│  Jamie Kim (Picking) — 203% of target   │
│  • Consistent high performance          │
│  • Could mentor 2-3 struggling peers    │
│  • Consider for lead or trainer role    │
└─────────────────────────────────────────┘
```

### How AI Recommendations Work

The system analyzes each employee's:
- **Current UPH vs. target** (% gap)
- **Trend direction** (up, down, flat)
- **Consistency** (number of days below goal)
- **Department context** (how they compare to peers)
- **Your coaching notes** (what's been tried)

→ **Result**: Prioritized, specific action suggestions

---

## 📊 Key Metrics Used in Coaching

### UPH (Units Per Hour)
- **What**: How many units the employee processes per hour
- **Why it matters**: Main productivity measure
- **Example**: John averages 6.5 UPH but target is 12.0

### Rolling Average
- **What**: Average UPH calculated from the last 7 or 14 days
- **Why it matters**: Smooths out bad days, shows real trend
- **Used in**: Deciding if trend is up/down
- **Access**: Productivity → 📉 Rolling Avg

### Target UPH
- **What**: Goal set for each department
- **Why it matters**: Benchmark for "on goal"
- **Set in**: Settings page (configurable per department)

### Trend Direction
- **↑ Up**: Improving week-over-week
- **↓ Down**: Declining week-over-week
- **→ Flat**: Stable, no significant change
- **Why it matters**: Distinguishes "off-day" from "declining performer"

---

## 🔍 Current Limitations & Improvement Opportunities

### What's Working Well
✅ Easy identification of at-risk employees  
✅ Simple note-taking and historical tracking  
✅ Automation of coaching suggestions  
✅ Flags for follow-up items  
✅ Trend visualization  

### Areas for Enhancement

#### 1. **Coaching Plan Templates**
Currently: Free-form text notes for everything
Opportunity: Pre-built coaching plans
- "Efficiency training" → includes: 3-day ramp-up, check-in schedule
- "Workstation setup" → walk-through steps, verification checklist
- "Quality focus" → common mistakes, quality audit rubric

#### 2. **Coaching History Timeline**
Currently: Just a list of notes
Opportunity: Visual timeline showing:
- Note date
- Coaching action taken
- UPH improvement (if any) in following week
- Was flag applied? When removed?
- Effectiveness indicator (↑ working, → no change, ↓ worsened)

#### 3. **Better Grouping/Organization**
Currently: All employees in one roster
Opportunity:
- **By Department** (see all Packing employees together)
- **By Risk Level** (Show high-risk only)
- **By Status** (Flagged only, Below Goal, Trending Down)
- **Bulk Actions** (Flag/unflag 5 people at once)

#### 4. **Coaching Flow - Smarter Navigation**
Currently: Linear "next employee" button
Opportunity:
- Start coaching session → auto-loads highest-risk  
- After each note, show related metrics: "Since last coaching, John's UPH: 6.5 → 7.1 (+8% improvement)"
- Coaching agenda/priority list to work through systematically

#### 5. **Coaching Effectiveness Tracking**
Currently: Notes exist, but no link to UPH improvement
Opportunity:
- After coaching, show employee's UPH for next 7 days
- Calculate "coaching ROI" (UPH gain / coaching time)
- Identify which coaching types work best for each department

#### 6. **Task/Reminder System**
Currently: Informal follow-ups ("next Tuesday")
Opportunity:
- "Schedule follow-up in 3 days" → system reminds you
- Create task board: "Follow-ups needed this week"
- Escalation rules: "No improvement in 7 days? → Manager alert"

#### 7. **Context Integration**
Currently: Isolated coaching page
Opportunity:
- Show recent shift data when coaching ("You said you'd show him the shortcut—here's his activity from yesterday")
- Link to employee's actual history records
- Show department benchmarks right there

---

## 💡 Best Practices

### What Makes Coaching Stick
1. **Same-shift feedback** - Coach them while memory is fresh
2. **Show the data** - Point to specific metrics that changed
3. **Clear action** - "Do X" vs. "try to improve"
4. **Follow-up** - Flag them and check progress in 7 days
5. **Celebrate wins** - Note when they improve (builds momentum)

### Using Notes Effectively
```
❌ Bad:   "John needs to work faster"
✅ Good:  "Showed John the optimized picking route from 
          the dispatch screen. Saves ~2min per order. 
          Following up tomorrow to see if adoption is working."

❌ Bad:   "Jane is struggling"
✅ Good:  "Jane will pair with Jamie (top performer) for 
          one week on same shift. Goal: learn Jamie's 
          efficiency tricks. Checking in Friday."
```

### When to Flag
- They need consistent follow-up
- You identified a specific gap to fix
- They're at risk of disengagement
- You want management awareness
- You scheduled a follow-up meeting

### When to Unflag
- The issue resolved (UPH improved for 2+ weeks)
- The action/intervention is complete
- They transferred departments
- Follow-up period is done and target hit

---

## 🛠️ Behind the Scenes: How It's Built

### Data Storage
- **Coaching Notes**: Stored in Supabase `coaching_notes` table with:
  - `emp_id` (employee ID)
  - `note_text` (what you wrote)
  - `created_by` (your name)
  - `created_at` (timestamp in your timezone)

- **Flags**: Stored in Supabase `employee_flags` table with:
  - `emp_id` (who's flagged)
  - `flagged_on` (when)
  - `flagged_by` (who flagged them)

- **Metrics**: Calculated from `uph_history` table (updates with each import)

### timezone Handling
All timestamps (notes, flags, audit logs) are stored in **your configured timezone** for consistency. Set in Settings → Admin → Timezone.

### Caching
Coaching notes and flags are cached for fast page loads but invalidated when you:
- Save a new note
- Apply/remove a flag
- Import new employee data

---

## 🎓 Quick Reference

| Task | Location | Steps |
|------|----------|-------|
| View all employees | Employees page, Performance Journal tab | Done! |
| See an employee's details | Click their name in the roster | Done! |
| Add a coaching note | Write in text area, click Save | 30 seconds |
| Flag an employee | Click "Flag for follow-up" button | 5 seconds |
| Unflag an employee | Click "Remove flag" button | 5 seconds |
| View coaching history | Expand "📜 Coaching History" section | Click + read |
| See all top risks | Supervisor page, top section | Sorted by risk |
| Get AI recommendations | Coaching Insights tab | Auto-generated |
| Export coaching records | (Coming soon) | — |

---

## 🚀 Next Steps for Your Team

1. **Customize coaching templates** (if feature is added) based on your top failure modes
2. **Set timezone** in Settings to ensure all timestamps are accurate
3. **Start a coaching session** with your highest-risk employee today
4. **Use the follow-up feature** - don't just note and move on, actually revisit
5. **Share wins** - when someone improves, update their note to celebrate it

---

## 📞 Support & Feedback

The coaching system is designed to be **your competitive advantage**—continuous, data-driven improvement of your team. 

**Want to improve the flow?** 
- AI-suggested coaching templates
- Automated follow-up reminders
- Coaching effectiveness dashboard
- Bulk actions for multiple employees

Let me know what would make coaching easier and more impactful for your team!
