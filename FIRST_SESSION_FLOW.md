# FIRST SESSION FLOW
> Design for first-time user onboarding  
> Target: Get useful value in 10 minutes  
> Status: Prescriptive. Use as checklist before shipping onboarding changes.

---

## Goal

A new user should:
1. **Sign up or log in** (~1 minute)
2. **Upload their data** (~3–4 minutes)
3. **See their first insight** (~2 minutes)
4. **Drill into one employee** (~2 minutes)
5. **Understand their next step** (~1 minute)

Total: 9–11 minutes to real value.

---

## Current User Journey

### Step 1: Login → Today Page (Empty)
**Current behavior:**
- User logs in → lands on "Today" page
- Page shows "Who needs your attention today?" hero
- If new tenant: empty queue, shows generic message "Import fresh data to refill the queue"
- No context about what the app does or where to start

**UX issue:**
- Non-obvious what "queue" means
- No scaffolding to help new users understand the product
- Lost opportunity to explain the three core product questions

### Step 2: Navigate to Import
**Current behavior:**
- User clicks "📁 Import" in sidebar
- Lands on Import Step 1: "Bring in whatever you have"
- Offered two modes: Upload file or Manual entry

**Good:**
- Clear heading and caption
- Friendly tone ("whatever you have", "still learning")
- Recent uploads shown in expander

**Gaps:**
- No explanation of what data format is expected (CSV? Excel? Columns?)
- No example or template download
- "This week's uploads" expander might confuse first-time users

### Step 3a: File Upload + Auto-Diagnosis
**Current behavior:**
- User uploads CSV/Excel file
- Auto-detected columns parsed
- System runs `diagnose_upload()` to check:
  - Row count + employee count
  - Date range
  - Days of data
  - Departments
  - Completeness warnings
- Shows success message for each file + diagnosis summary
- "Continue →" button goes to Step 2 (mapping)

**Good:**
- Diagnosis is immediately visible (no hidden processing)
- Warnings are specific: "Missing hours for X rows", "Only 1 day of data"
- Success checkmarks show what was recognized

**Gaps:**
- If **only 1 day of data** or **< 3 employees**, user may doubt if system is working
- Diagnosis message could be more encouraging
- No "next steps" guidance (e.g., "Ready to map your columns" vs. "Need to add more data first?")

### Step 3b: Column Mapping (Step 2)
**Current behavior:**
- System shows each uploaded file with auto-detected columns
- User confirms or adjusts mappings:
  - Employee ID (required)
  - Employee Name (required)
  - Department (optional)
  - UPH source: either direct column or **calculate from Units ÷ Hours**
  - Date (optional — defaults to manual date picker)
- Validation prevents confirmation until required fields mapped
- Auto-confirmation if all fields detected with high confidence

**Good:**
- Radio button for UPH source is clear
- Required vs. optional fields marked
- Validation is immediate
- Can't proceed without required fields

**Gaps:**
- "Units ÷ Hours" terminology may not be obvious to first-time users
- No example of what each column should contain
- Mapping persists across multiple files but no summary shown until confirmation

### Step 4: Pipeline Setup (Step 3)
**Current behavior:**
- System shows summary of files ready to process
- User selects work date (only if no Date column in data)
- System checks for duplicates vs. existing history
- Shows preview count of duplicate vs. new rows
- If date column exists, shows confidence message about data coverage
- "Run the pipeline" button at bottom

**Good:**
- Work date input is clear when needed
- Shows file-by-file summary
- Duplicate detection prevents accidental re-imports

**Gaps:**
- "Pipeline" is technical jargon — should be "Import" or "Load data"
- Duplicate check explanation is buried
- No visual feedback while pipeline runs (if async, should show spinner)

### Step 5: Post-Import Summary (Critical!)
**Current behavior:**
- After pipeline completes, shows **import summary card**:
  - ✔ X employees loaded · Y ranked
  - ✔ Z days of data
  - ⚠ OR ✔ N employees below goal · M high-priority risks
- Two buttons: **"→ Start your day"** and **"↺ Import more data"**
- Optional third button: **"↩ Undo last import"**

**Good:**
- Card design is visually distinct
- Below-goal count is highlighted (signals if there's work)
- "Start your day" is clear call-to-action

**Gaps:**
- "Start your day" doesn't explain what page they'll land on
- Summary doesn't show any actual employee names or insights
- No drill-down path visible ("tap here to see who and why")
- If no employees below goal, message feels anticlimactic ("All on target" → nothing to do?)

### Step 6: "Start your day" → Today Page
**Current behavior:**
- Button redirects to `st.session_state["goto_page"] = "supervisor"` → routes to page_today
- User lands on Today page
- If new import: queue is empty (no actions logged yet)
- Shows empty state: "No urgent actions right now"

**UX issue:**
- **Major friction:** User just imported data and expects to see their team. Instead sees "nothing to do."
- Page title/heading doesn't match expectation ("Who needs your attention today?" vs. "Here's your team")
- Empty state message is generic, doesn't help first-time users
- No link to next page (e.g., "View your team →") in empty state

---

## Ideal First-Session Flow (Spec)

### After Import → Before "Start your day"

**Show this page instead** (or alongside) the import summary:

```
┌─────────────────────────────────────────────┐
│ ✔ Your data is ready                        │
│                                             │
│ 25 employees loaded • 14 days of history    │
│                                             │
│ ⚠ 5 employees below target                  │
│  • Below goal for 3+ days                   │
│  • Performance is trending down             │
│                                             │
│ ✔ 8 recent coaching notes on file           │
│  • Ready to track outcomes                  │
│                                             │
├─────────────────────────────────────────────┤
│ Next steps:                                 │
│ 1. View your team summary  [→ Go]           │
│ 2. Pick an employee to drill into [→ Go]    │
│ 3. Log your first coaching note [→ Go]      │
│                                             │
│ Questions? See the guide [→ Help]           │
└─────────────────────────────────────────────┘
```

**Spec:**
- Show **what was imported** (count, date range, basic stats)
- Surface **immediate insight** (who is below goal, top risk count)
- Explain **why** (e.g., "trending down for 5 days")
- Provide **3 clear next steps** as buttons:
  1. **Team Summary** → Go to Supervisor (or new landing page)
  2. **Drill into Employee** → Go to Employees page with filter
  3. **Log Coaching Note** → Go to Employees, find someone below-goal, open note modal
- Optional: **Short guide link** → Explain what the app does and how to use it

### Ideal Next Page: "Team Summary" or Supervisor Landing

**Instead of Today queue (empty), show Supervisor page first-time:**

- ✔ **Team Health Snapshot**: How many on-target vs. below-goal
- ⚠ **Top Risks**: Name, dept, reason (trend + gap + last update)
- 📈 **Trends**: Any department-level patterns
- 👥 **Quick List**: Sortable table of all employees with status + trend

**User can:**
- Tap an employee → coach them
- Tap a trend → drill into pattern
- Go to Today queue → when ready for daily follow-up

---

## Friction Points (Current)

| Friction | Page | Severity | Impact |
|---|---|---|---|
| **1. No first-time indicator** | Today + all | High | User unsure if they're seeing empty state bc new or bc nothing happened |
| **2. Empty queue after import** | Today | High | User just imported data, expects to see it, sees nothing |
| **3. Generic empty state copy** | Today | Medium | "Import fresh data" doesn't help first-timer who just did |
| **4. No immediate insight shown post-import** | Import summary | High | User doesn't know if import worked or what to do next |
| **5. "Start your day" button is vague** | Import summary | Medium | User doesn't know what page they'll land on or what to expect |
| **6. Today page title confusing on first load** | Today | Medium | "Who needs your attention today?" implies action queue, not data view |
| **7. Supervisor page exists but not routed** | Navigation | Medium | Better first page hidden in codebase |
| **8. No scaffolding / guidance** | All | Medium | No hints about what each page does or where to go next |
| **9. No template or example data** | Import Step 1 | Low | User might wonder what columns are required |
| **10. Jargon: "pipeline", "UPH source"** | Import | Low | Technical terms might confuse warehouse supervisors |

---

## Blockers to Releasing First-Session Experience

### Must-fix before shipping

- [ ] **Empty state after import is addressable** — Need to ensure `_import_complete_summary` is properly set and accessible after pipeline
- [ ] **Supervisor page is routed or replaced** — Decision: use Supervisor page as first landing, or create new dedicated onboarding/dashboard?
- [ ] **Post-import redirect is clear** — Need to decide: Today → Supervisor → or custom first-page?
- [ ] **First-time indicator available** — Need session state flag or DB marker to detect first-time users

### Should-fix

- [ ] Add "New session" badge or onboarding tour
- [ ] Write first-time-specific empty state copy
- [ ] Add optional help guide / quick-start modal
- [ ] Improve post-import summary to show immediate insight (not just counts)
- [ ] Create or surface employee list/team summary page as first-time landing page

### Nice-to-have

- [ ] Download CSV template from import page
- [ ] Example data inline in import instructions
- [ ] Skip column mapping with 100% auto-confidence
- [ ] Progress bar through import steps

---

## Recommended Small Safe Changes (No Major Logic)

These are UX/copy/navigation improvements that support first-session flow without rewriting core systems:

### 1. Improve Import Summary Copy (pages/import_page.py)
**Change:** Add a "next step" line to the import complete summary

**Current:**
```
st.markdown(f'<div>✔ Import complete — you\'re ready</div>')
```

**Proposed:**
```
st.markdown(
    f'<div>✔ Import complete — ready to explore</div><br>'
    f'<div style="font-size:14px;color:#5d7693;">Loaded {_ic_emp} employees from {_ic_days} day(s). '
    f'{_ic_below} below goal{" — tap below to coach" if _ic_below > 0 else " — great shape!"}</div>'
)
```

**Impact:** User understands immediately what was loaded and if action is needed.

### 2. Enhance "Start your day" Button (pages/import_page.py)
**Change:** Add context to button label + show where they're going

**Current:**
```
st.button("→ Start your day", type="primary")
```

**Proposed:**
```python
if _ic_below > 0:
    label = f"→ See your team ({_ic_below} need attention)"
else:
    label = "→ View your team"
st.button(label, type="primary")
```

**Impact:** User knows what to expect before clicking.

### 3. Add First-Time Empty State (pages/today.py)
**Change:** Detect first-time users and show guided empty state

**Proposed:**
```python
def _render_first_time_empty_state() -> None:
    with st.container(border=True):
        st.markdown("### Welcome! 🎉")
        st.write("You've just imported your team data. The action queue starts filling up once you begin logging coaching conversations and follow-ups.")
        st.info("👉 **Next step:** Go to **👥 Team** to see your employees, pick someone, and log your first coaching note.")
        if st.button("View team →", type="primary", use_container_width=True):
            st.session_state["goto_page"] = "team"
            st.rerun()
```

**In page_today()**, check if first-time:
```python
is_first_time = not (len(queue_items) > 0) and st.session_state.get("_first_import_just_completed")
if is_first_time:
    _render_first_time_empty_state()
    return
```

**Impact:** First-time users get guided path to their team instead of generic message.

### 4. Add Session Badge to sidebar (core/navigation.py)
**Change:** Show "ℹ️ First session" badge next to logo if first-time

**Proposed:**
```python
if st.session_state.get("_first_import_just_completed"):
    st.markdown(
        '<div style="font-size:11px;background:#E8F0F9;color:#0F2D52;'
        'padding:4px 8px;border-radius:4px;display:inline-block;'
        'margin-bottom:8px;">ℹ️ First session — here\'s where to start</div>',
        unsafe_allow_html=True,
    )
    if st.button("Get started →", key="first_session_guide"):
        st.session_state["_show_getting_started"] = True
        st.rerun()
```

**Impact:** User knows they're new and has quick access to guidance.

### 5. Link Import Summary to Team Page (pages/import_page.py)
**Change:** Make the import summary counts clickable

**Current:**
```
st.markdown(f'Strong {_ic_emp} employees loaded')
```

**Proposed:**
```python
if st.button(f"👥 View {_ic_emp} employees", key="ic_view_team"):
    st.session_state["goto_page"] = "team"
    st.rerun()
```

**Impact:** User can immediately jump to team view instead of only the "Start your day" button.

### 6. Clarify Column Mapping Labels (pages/import_page.py)
**Change:** Add inline help text for confusing fields

**Current:**
```
st.radio("UPH source", ["Calculate: Units ÷ Hours", "Already have UPH column"])
```

**Proposed:**
```python
st.markdown("**UPH source** — How to calculate units per hour")
st.caption("Most warehouses track Units and Hours Worked. DPD will divide them.")
st.radio("", ["Calculate: Units ÷ Hours", "Already have UPH column"], ...)
```

**Impact:** First-time users understand what UPH means.

---

## Decision Points for Product (Choose One Path)

### Path A: Enhance Current Flow (Minimal Changes)
- Keep Today page as action queue
- Add first-time empty state + guidance in Today
- Add post-import summary improvements
- Redirect new users to Team page instead of Today
- **Timeline:** 1–2 hours
- **Risk:** Low

### Path B: Create Dedicated Onboarding Page
- Create new "Getting Started" page that appears only on first session
- Show full team summary + quick tour
- Then redirect to Today for daily use
- Requires new page + routing
- **Timeline:** 3–4 hours
- **Risk:** Medium

### Path C: Route Existing Supervisor Page (Approved Approach)
- Enable existing `page_supervisor()` in router
- Use as first-time landing page instead of Today
- Show team health + top risks + drill-down paths
- Then user can navigate to Today queue once familiar
- **Timeline:** 30 minutes
- **Risk:** Low (Supervisor page already exists)
- **Recommended:** This aligns with PRODUCT_GUARDRAILS.md guidance

---

## Success Metrics (First Session)

After making changes, measure:
- **Time to first insight:** How long from login to user sees "below goal" insight? (Target: < 5 min)
- **Time to drill-down:** How long from import to user views an individual employee? (Target: < 8 min)
- **Retention:** Do first-time users come back? (Track via session count)
- **Support tickets:** Do fewer support requests about "what should I do now?" appear?

---

## Implementation Checklist

- [ ] Decide routing: Today vs. Supervisor vs. New page?
- [ ] Set `_first_import_just_completed` flag in import pipeline
- [ ] Add first-time empty state messaging
- [ ] Improve post-import summary copy
- [ ] Update "Start your day" button text
- [ ] Test with sample data (1 day, 5 employees → should show something useful)
- [ ] Test with large import (50+ employees, 14+ days → should show insights)
- [ ] Test with no below-goal employees (should still feel successful)
- [ ] Update [PRODUCT_GUARDRAILS.md](PRODUCT_GUARDRAILS.md) if routing changes
