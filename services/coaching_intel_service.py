"""
services/coaching_intel_service.py
-----------------------------------
Domain logic for Coaching Intelligence:
  - keyword taxonomy
  - note auto-tagging
  - tag aggregation
  - coaching effectiveness analysis

Nothing here imports Streamlit or touches session state.
"""

# ── Tag taxonomy ───────────────────────────────────────────────────────────────
ISSUE_TYPES = ["", "speed", "accuracy", "process", "attendance", "training"]
ACTION_TYPES = ["", "coaching", "retraining", "reassignment", "reminder"]
TONE_TYPES = ["", "warning", "neutral", "positive"]

ISSUE_KEYWORDS: dict[str, list[str]] = {
    "speed":      ["slow", "uph", "pace", "behind", "rate", "fast", "picking speed", "output"],
    "accuracy":   ["error", "mistake", "wrong", "incorrect", "accuracy", "mispick", "quality"],
    "process":    ["process", "workflow", "procedure", "steps", "method", "technique"],
    "attendance": ["absent", "late", "tardy", "no show", "attendance", "missed", "call-out"],
    "training":   ["new hire", "training", "on-board", "ramp", "learn", "orientation", "unfamiliar"],
}
ACTION_KEYWORDS: dict[str, list[str]] = {
    "coaching":     ["coach", "discussed", "talked", "one-on-one", "feedback", "guided"],
    "retraining":   ["retrain", "re-train", "walkthrough", "shadow", "showed", "demonstrated"],
    "reassignment": ["move", "moved", "reassign", "transfer", "changed station", "new lane"],
    "reminder":     ["remind", "reminded", "mentioned", "noted", "asked to"],
}
TONE_KEYWORDS: dict[str, list[str]] = {
    "warning":  ["warning", "final", "written up", "disciplinary", "urgent", "must improve", "last"],
    "positive": ["great", "excellent", "improved", "star", "well done", "good job", "above"],
}


def auto_tag_note(note_text: str) -> dict:
    """
    Return best-guess tags for a note based on keyword matching.

    Returns: {"issue_type": str, "action_taken": str, "tone": str}
    """
    text = note_text.lower()
    result: dict = {"issue_type": "", "action_taken": "", "tone": "neutral"}

    for issue, kws in ISSUE_KEYWORDS.items():
        if any(kw in text for kw in kws):
            result["issue_type"] = issue
            break
    for action, kws in ACTION_KEYWORDS.items():
        if any(kw in text for kw in kws):
            result["action_taken"] = action
            break
    for tone, kws in TONE_KEYWORDS.items():
        if any(kw in text for kw in kws):
            result["tone"] = tone
            break

    return result


def aggregate_note_tags(notes: list[dict]) -> dict:
    """
    Aggregate tag counts across all notes.

    Returns:
    {
      "issue_counts":       {issue: count},        sorted by count desc
      "action_counts":      {action: count},        sorted by count desc
      "tone_counts":        {tone: count},           sorted by count desc
      "employees_by_issue": {issue: {emp_id: count}},
    }
    """
    issue_c: dict = {}
    action_c: dict = {}
    tone_c: dict = {}
    emp_by_issue: dict = {}

    for n in notes:
        issue = n.get("issue_type") or ""
        action = n.get("action_taken") or ""
        tone = n.get("tone") or "neutral"
        emp_id = str(n.get("emp_id", ""))

        if issue:
            issue_c[issue] = issue_c.get(issue, 0) + 1
            emp_by_issue.setdefault(issue, {})
            emp_by_issue[issue][emp_id] = emp_by_issue[issue].get(emp_id, 0) + 1
        if action:
            action_c[action] = action_c.get(action, 0) + 1
        if tone:
            tone_c[tone] = tone_c.get(tone, 0) + 1

    return {
        "issue_counts":       dict(sorted(issue_c.items(),  key=lambda x: -x[1])),
        "action_counts":      dict(sorted(action_c.items(), key=lambda x: -x[1])),
        "tone_counts":        dict(sorted(tone_c.items(),   key=lambda x: -x[1])),
        "employees_by_issue": emp_by_issue,
    }


def coaching_effectiveness(notes: list[dict]) -> list[dict]:
    """
    For notes that have both uph_before and uph_after, calculate
    average improvement grouped by action_taken.

    Returns list of {"action", "count", "avg_improvement_pct"} sorted by improvement desc.
    """
    buckets: dict = {}
    for n in notes:
        act = n.get("action_taken") or "untagged"
        before = n.get("uph_before")
        after = n.get("uph_after")
        if before is None or after is None:
            continue
        try:
            b = float(before)
            a = float(after)
            if b <= 0:
                continue
            pct = round((a - b) / b * 100, 1)
            buckets.setdefault(act, []).append(pct)
        except (TypeError, ValueError):
            pass

    out = []
    for act, improvements in buckets.items():
        out.append({
            "action": act,
            "count": len(improvements),
            "avg_improvement_pct": round(sum(improvements) / len(improvements), 1),
        })
    return sorted(out, key=lambda x: -x["avg_improvement_pct"])
