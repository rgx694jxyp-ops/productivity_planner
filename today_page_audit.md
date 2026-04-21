# Today Page Visual & UX Audit

**Date:** April 20, 2026  
**Scope:** Presentation, visual hierarchy, scanability, performance perception, action clarity  
**Constraint:** No production code changes in this audit. Logic, data flow, and routing untouched.

---

## What the first 3 seconds currently communicate

> "There are N people to review. Here are three forms to fill out."

Specifically, a supervisor arriving at the page sees:

1. A naked `##` heading: **"Today: N people need review now"**
2. A dim timestamp line: "Updated just now"
3. A small-caps section label: **"Prioritize these first"** (directive)
4. Three queue cards — each immediately showing a note text area, a follow-up selectbox, and a disabled submit button

There is no scope, no orientation, no confidence signal. The user is dropped into action mode before understanding what is in the queue, why those items surfaced, or how significant they are.

---

## What it SHOULD communicate in the first 3 seconds

> "Here is what today's data produced. Here are the strongest signals. You decide what to do next."

1. **Scope statement:** how many records were checked, how many surfaced
2. **Signal mix:** e.g., "2 declining trends, 1 repeat issue, 15 total in queue"
3. **Top signals:** readable at a glance without action controls in the way
4. **Confidence framing:** clear that these are observations, not instructions

---

## Top 5 Problems

### 1. All orientation context is collapsed and invisible on load

Every piece of context that would help a supervisor understand the queue — the attention strip metrics (N needing attention, N overdue), the orientation block (signal type mix), the return trigger (what changed since yesterday), the weekly summary, the value strip — is collapsed inside `st.expander("Supporting context", expanded=False)`.

The page opens with a heading and raw action cards. There is no visible framing before the user encounters the first form.

**Impact:** Supervisors act on cards before understanding the queue scope. Low-confidence or low-priority cards may get attention first.

---

### 2. Phase 1 → Phase 2 rerun causes a full visible page wipe

The two-phase cold-load pattern works as follows:
- Phase 1 renders the top 3 cards and immediately calls `st.rerun()`
- Streamlit clears the entire DOM on rerun
- Phase 2 re-renders everything from scratch

This produces a visible sequence: loading shell → top 3 cards → **page goes blank** → full render. The user sees the previous screen cleared, then the top 3 appear, then everything disappears again before the full page stabilizes. This is the most visible performance perception problem on the page.

**Impact:** The transition pattern actively undermines trust in the page. It looks like a crash or a broken refresh rather than a loading state.

---

### 3. Action controls are always open on every card

`_render_guided_completion_controls` is called unconditionally inside `_render_attention_card`. Every card in the queue immediately shows:
- A "Note (required)" text area (90px height)
- A "Follow-up needed?" selectbox
- A "More actions" toggle button
- A disabled "Mark as complete" button

A supervisor scanning 3 cards has to visually parse 12+ interactive widgets before they can read the signal content. The card content (who, what, why it surfaced) competes visually with the action UI.

**Impact:** Dense visual noise on every card destroys scanability. The cognitive load to read the queue is 3–4× what it should be.

---

### 4. No styled page shell or visual grounding for the heading

The page heading (`## Today: N people need review now`) is a raw Markdown heading dropped at the top of the column with no container, background, or visual anchor. The Team page uses section containers with background tints, borders, and radius geometry to give each panel a defined presence. Today has nothing equivalent at the page level.

Compare:
- **Team page:** roster container has `#F8FAFD` background, border, `0.62rem` radius, scoped headings
- **Today page:** `st.markdown("## Today: N people need review now")` — no container, no visual shell

**Impact:** The page looks unfinished compared to Team. The heading floats without grounding. The queue cards appear immediately below with no visual separation from the page title.

---

### 5. Prescriptive and ambiguous section label copy

"Prioritize these first" appears in two places (Phase 1 and Phase 2 render paths). This is a directive instruction, not a data description. It also conflicts with the product posture: the app surfaces signals; supervisors decide what to prioritize.

The heading "N people need review now" similarly implies urgency and instruction. "Need review now" is not a data statement — it is an operational directive. The number N is also a count of signals, not a count of people who actually have problems.

**Impact:** Product posture violation. Copy should describe what the data shows, not tell the user what to do.

---

## Full Issue Table

| # | Issue | Where it appears | Why it hurts usability | Recommended fix | Priority |
|---|-------|-----------------|----------------------|-----------------|----------|
| 1 | All contextual framing buried in collapsed expander | `st.expander("Supporting context")` containing attention strip, orientation block, return trigger, value strip | Supervisor arrives with no scope. Cards feel arbitrary without framing | Surface attention strip (N needing attention, N overdue) and orientation chips above the queue, visible on load | **High** |
| 2 | Phase 1 → Phase 2 full-page rerun wipe | `_page_today_impl` two-phase pattern; `st.rerun()` after Phase 1 | User sees page blank/clear between Phase 1 and Phase 2. Looks broken | Replace blank-then-rerender with a placeholder container that updates in place rather than clearing (performance, not presentation) | **High** |
| 3 | Action controls always open on every card | `_render_attention_card` → `_render_guided_completion_controls` unconditional call | Every card shows note field + selectbox + buttons before signal content. Scanning is exhausting | Collapse action controls behind an expand or inline toggle per card; show signal content first | **High** |
| 4 | No styled page-level shell or header container | `st.markdown(f"## Today: {N} people need review now")` — no container | Page looks unfinished vs Team. Heading floats without grounding. No visual separation from queue | Add a styled page header container (tinted background, border-bottom or shadow) enclosing the heading and key metrics | **High** |
| 5 | Prescriptive section label "Prioritize these first" | `_render_today_phase1_top_cards` and `_render_unified_attention_queue` | Directive copy contradicts product posture (highlight, don't dictate) | Replace with descriptive label, e.g., "Surfaced now" or "Current signals" | **High** |
| 6 | Heading copy "need review now" is a directive, not a data statement | `st.markdown(f"## Today: {N} people need review now")` | Implies urgency the system cannot justify; N is a signal count, not a severity judgment | Replace with data-descriptive copy: "Today · N signals surfaced" or "N employees with active signals" | **High** |
| 7 | `today-hero` CSS class defined but never rendered | `_apply_today_styles` defines `.today-hero`, `.today-hero-title`, etc.; nothing calls it | Dead CSS implies a hero header was planned but never implemented. Page lacks the designed entrypoint | Either remove the dead hero CSS or implement a stripped-down header shell using existing `.today-hero` styles | **Medium** |
| 8 | Attention strip metrics (N needing attention, N overdue) hidden on load | `_render_attention_summary_strip` inside collapsed expander | Core operational numbers — what is in the queue — are invisible until the user expands | Move at least `total_needing_attention` and `overdue_follow_ups` above the queue fold | **Medium** |
| 9 | Return trigger (what changed since yesterday) hidden | `_render_return_trigger` inside collapsed expander | Return context is the most useful orientation for recurring supervisors. They have to find it manually | Surface return trigger chips (if present) above the queue, visible on load | **Medium** |
| 10 | Queue orientation block hidden | `_render_queue_orientation_block` inside collapsed expander | "3 declining trends, 2 repeat issues" is essential queue framing. Currently invisible | Move orientation chips to a thin visible strip above the first card | **Medium** |
| 11 | Overflow cards in plain expander "Other items" with no visual styling | `_render_unified_attention_queue` overflow section | Overflow expander has no visual distinction from card content. Hard to know how many items are below | Add count label to overflow expander: "Other items (N)" and subtle left border or tint | **Medium** |
| 12 | No styled container shell around the queue section | Queue renders directly into the page column | Team page wraps sections in anchor containers with tint/border. Today has no equivalent panel shell | Add a `.today-queue-anchor` container around the queue section for visual grounding | **Medium** |
| 13 | Typography weight 800 applied uniformly to all card titles | `.today-insight-title { font-weight: 800 }`, `.today-home-title { font-weight: 800 }` | Every element at the same weight removes hierarchy. Team page reserves 800/700/600/500 tiers | Reserve weight 800 for primary heading only; reduce card title to 700, meta to 500 | **Medium** |
| 14 | Confidence and freshness combined inline as a single `·`-joined string | `_render_attention_card` metadata row construction | Confidence level and freshness date serve different purposes; merging makes both harder to scan | Separate confidence chip (styled badge) from freshness line (muted text below) | **Medium** |
| 15 | "Supporting context" expander label is generic and uninviting | `st.expander("Supporting context", expanded=False)` | Name does not tell the user what they will find. Most users will not expand | Rename to "Queue context" or "Signal summary" and add a brief caption with the top-line metric visible outside the expander | **Low** |
| 16 | Weekly summary block renders with only `st.caption` text | `_render_weekly_summary_block` uses `st.container(border=True)` + `st.caption` | Weekly summary items have no visual weight or hierarchy to signal that they are summaries, not detail rows | Add label sizing and value display to weekly summary items (headline + value, not just caption) | **Low** |
| 17 | Completion flash ("Completed.") rendered as `st.caption` with no styling | `_render_unified_attention_queue` pops `_TODAY_LAST_COMPLETED_LABEL_KEY` and calls `st.caption` | Completion confirmation has less visual weight than a normal line of text. Easily missed. | Render as a styled flash chip or use the existing `today-completed-state` CSS class | **Low** |
| 18 | `_render_today_interpretation_strip` exists but is never called in Phase 2 | Defined function, not in `_page_today_impl` render path | Dead render function creates confusion about what the page is intended to show | Remove or integrate — the content ("why you see this queue") belongs above the fold | **Low** |
| 19 | `_render_summary_strip`, `_render_since_yesterday`, `_render_bottom_charts`, `_render_open_exceptions` defined but not called | All defined in the file, none called from `_page_today_impl` | Dead code inflates file size and creates ambiguity about intended page structure | Document as removed scope or schedule for removal; clarify intent in a comment | **Low** |
| 20 | Loading shell is identical to an error state | `_render_today_loading_shell` renders `## Today` + `st.caption(reason)` | No visual difference between "loading" and "broken." User cannot tell if the page is computing or failed | Add a spinner or pulse indicator to the loading shell to distinguish loading from empty | **Low** |

---

## Section-level summary

### Visual hierarchy
The page has one primary element (the heading) and immediately drops into a queue with full action controls. There is no secondary tier of context between heading and cards. Everything that should be in tier-2 (orientation, metrics, return trigger) is in a collapsed expander.

### Scanability
A supervisor cannot understand the queue scope in 3–5 seconds. The metrics that define scope (N overdue, N new) are hidden. The signal type mix (declining, repeat) is hidden. The first visible content after the heading is a form.

### Visual polish
- No page header shell (Team page has section containers; Today has none)
- Dead `.today-hero` CSS never used
- Typography weight not tiered (weight 800 everywhere, no 700/600/500 differentiation)
- No section separators or background panels
- Overflow expander has no count or visual styling

### Performance perception
- Phase 1 → Phase 2 rerun creates the most visible rough edge: page appears to crash and reload
- Multiple `with st.spinner()` calls can produce stacked spinners on cold start
- Loading shell is visually identical to an error state

### Clarity of action
- Action controls are always open, competing visually with signal content
- The "top 3" are dominant in quantity of interactive widgets, not in visual presence of signal information
- Completion confirmation is a single `st.caption("Completed.")` — easily missed

---

## Recommended implementation sequence (for a future implementation pass)

1. **Prescriptive copy** — rename "Prioritize these first" and revise heading copy (pure text/CSS, no logic)
2. **Styled page header shell** — add a container with tint/border around the heading and a one-line orientation summary
3. **Surface orientation chips above the fold** — move the orientation block (signal type mix) out of the expander into a thin always-visible strip
4. **Surface attention strip above the fold** — move N-needing-attention and N-overdue metrics above the queue
5. **Collapse action controls per card** — add a per-card expand gate before the note/follow-up/submit section
6. **Typography weight tiering** — align card title/meta weights to the Team page scale
7. **Phase 1 → Phase 2 transition** — architecture change; defer to a performance pass

> All items 1–6 are presentation-only. Item 7 requires changes to the two-phase render orchestration and should be a separate pass.
