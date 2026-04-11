"""
goals.py
--------
Department UPH goals, trend analysis, and employee flagging.

Storage: Supabase tenant_goals table only.
"""

from datetime import datetime, date
from collections import defaultdict

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


def _get_user_timezone_now(tenant_id: str = "") -> datetime:
    """Get current datetime in user's configured timezone.
    
    If timezone is configured in settings, returns timezone-aware datetime.
    Otherwise, returns server local time (naive datetime).
    """
    try:
        from services.settings_service import get_tenant_local_now

        return get_tenant_local_now(tenant_id)
    except Exception:
        return datetime.now()


def _log_target_change(event_type: str, *, tenant_id: str = "", context: dict | None = None) -> None:
    try:
        from services.observability import log_operational_event

        log_operational_event(
            event_type,
            status="completed",
            tenant_id=tenant_id,
            context=context or {},
        )
    except Exception:
        pass


def _empty_goals() -> dict:
    return {
        "default_target_uph": 0.0,
        "dept_targets": {},
        "process_targets": {},
        "employee_target_overrides": {},
        "configured_processes": [],
        "flagged_employees": {},
    }


def _normalize_goals_payload(data: dict | None) -> dict:
    data = data or {}
    default_target_uph = data.get("default_target_uph") or 0
    dept_targets = data.get("dept_targets") or {}
    process_targets = data.get("process_targets") or {}
    employee_target_overrides = data.get("employee_target_overrides") or {}
    configured_processes = data.get("configured_processes") or []
    flagged_employees = data.get("flagged_employees") or {}
    if not isinstance(dept_targets, dict):
        dept_targets = {}
    if not isinstance(process_targets, dict):
        process_targets = {}
    if not isinstance(employee_target_overrides, dict):
        employee_target_overrides = {}
    if not isinstance(configured_processes, list):
        configured_processes = []
    if not isinstance(flagged_employees, dict):
        flagged_employees = {}

    try:
        default_target_uph = float(default_target_uph or 0)
    except (TypeError, ValueError):
        default_target_uph = 0.0

    normalized_process_targets: dict[str, float] = {}
    try:
        from services.target_service import normalize_process_name

        for key, value in {**dept_targets, **process_targets}.items():
            canonical_name = normalize_process_name(key, {"configured_processes": configured_processes}) or str(key or "").strip()
            if not canonical_name:
                continue
            try:
                normalized_process_targets[canonical_name] = float(value or 0)
            except (TypeError, ValueError):
                normalized_process_targets[canonical_name] = 0.0
    except Exception:
        normalized_process_targets = {str(key): float(value or 0) for key, value in process_targets.items() if str(key).strip()}

    normalized_overrides: dict[str, dict] = {}
    for emp_id, raw_value in employee_target_overrides.items():
        if isinstance(raw_value, dict):
            target_value = raw_value.get("target_uph")
            process_name = raw_value.get("process_name") or ""
        else:
            target_value = raw_value
            process_name = ""
        try:
            target_value = float(target_value or 0)
        except (TypeError, ValueError):
            target_value = 0.0
        normalized_overrides[str(emp_id)] = {
            "target_uph": target_value,
            "process_name": str(process_name or "").strip(),
        }

    return {
        "default_target_uph": default_target_uph,
        "dept_targets": dict(dept_targets),
        "process_targets": normalized_process_targets,
        "employee_target_overrides": normalized_overrides,
        "configured_processes": [entry for entry in configured_processes if isinstance(entry, dict)],
        "flagged_employees": dict(flagged_employees),
    }


# ── Goal store (DB only) ─────────────────────────────────────────────────────

def load_goals(tenant_id: str = "") -> dict:
    """Load goals from tenant_goals only."""
    try:
        from database import load_goals_db
        return _normalize_goals_payload(load_goals_db(tenant_id))
    except Exception:
        return _empty_goals()


def save_goals(data: dict, tenant_id: str = ""):
    """Save goals to tenant_goals only."""
    payload = _normalize_goals_payload(data)
    try:
        from database import save_goals_db
        save_goals_db(payload, tenant_id)
    except Exception:
        pass
    try:
        from cache import bust_cache as _bust_cache
        _bust_cache()
    except Exception:
        pass


def set_dept_target(dept: str, target_uph: float, tenant_id: str = ""):
    data = load_goals(tenant_id)
    data["dept_targets"][dept] = target_uph
    try:
        from services.target_service import normalize_process_name

        canonical_name = normalize_process_name(dept, data) or str(dept or "").strip()
        if canonical_name:
            data.setdefault("process_targets", {})[canonical_name] = float(target_uph or 0)
    except Exception:
        pass
    save_goals(data, tenant_id)


def get_dept_target(dept: str, tenant_id: str = "") -> float:
    data = load_goals(tenant_id)
    try:
        from services.target_service import resolve_target_context

        target_context = resolve_target_context(process_name=dept, goals_data=data)
        return float(target_context.get("target_uph") or 0)
    except Exception:
        return float(data["dept_targets"].get(dept, 0) or 0)


def get_all_targets(tenant_id: str = "") -> dict[str, float]:
    data = load_goals(tenant_id)
    targets = dict(data.get("dept_targets", {}))
    for key, value in (data.get("process_targets") or {}).items():
        targets[str(key)] = float(value or 0)
    return targets


def get_default_target(tenant_id: str = "") -> float:
    return float(load_goals(tenant_id).get("default_target_uph", 0) or 0)


def set_default_target(target_uph: float, tenant_id: str = ""):
    data = load_goals(tenant_id)
    data["default_target_uph"] = float(target_uph or 0)
    save_goals(data, tenant_id)
    _log_target_change(
        "target_changed",
        tenant_id=tenant_id,
        context={"target_type": "default", "target_uph": float(target_uph or 0)},
    )


def get_process_targets(tenant_id: str = "") -> dict[str, float]:
    return dict(load_goals(tenant_id).get("process_targets", {}))


def set_process_target(process_name: str, target_uph: float, tenant_id: str = ""):
    data = load_goals(tenant_id)
    try:
        from services.target_service import normalize_process_name

        canonical_name = normalize_process_name(process_name, data) or str(process_name or "").strip()
    except Exception:
        canonical_name = str(process_name or "").strip()
    if not canonical_name:
        return
    data.setdefault("process_targets", {})[canonical_name] = float(target_uph or 0)
    data.setdefault("dept_targets", {})[canonical_name] = float(target_uph or 0)
    save_goals(data, tenant_id)
    _log_target_change(
        "target_changed",
        tenant_id=tenant_id,
        context={
            "target_type": "process",
            "process_name": str(canonical_name or ""),
            "target_uph": float(target_uph or 0),
        },
    )


def clear_process_target(process_name: str, tenant_id: str = ""):
    data = load_goals(tenant_id)
    try:
        from services.target_service import normalize_process_name

        canonical_name = normalize_process_name(process_name, data) or str(process_name or "").strip()
    except Exception:
        canonical_name = str(process_name or "").strip()
    data.setdefault("process_targets", {}).pop(canonical_name, None)
    data.setdefault("dept_targets", {}).pop(canonical_name, None)
    save_goals(data, tenant_id)
    _log_target_change(
        "target_changed",
        tenant_id=tenant_id,
        context={"target_type": "process", "process_name": str(canonical_name or ""), "cleared": True},
    )


def get_employee_target_overrides(tenant_id: str = "") -> dict[str, dict]:
    return dict(load_goals(tenant_id).get("employee_target_overrides", {}))


def set_employee_target_override(emp_id: str, target_uph: float, process_name: str = "", tenant_id: str = ""):
    data = load_goals(tenant_id)
    data.setdefault("employee_target_overrides", {})[str(emp_id)] = {
        "target_uph": float(target_uph or 0),
        "process_name": str(process_name or "").strip(),
    }
    save_goals(data, tenant_id)
    _log_target_change(
        "target_changed",
        tenant_id=tenant_id,
        context={
            "target_type": "employee_override",
            "employee_id": str(emp_id or ""),
            "target_uph": float(target_uph or 0),
            "process_name": str(process_name or "").strip(),
        },
    )


def clear_employee_target_override(emp_id: str, tenant_id: str = ""):
    data = load_goals(tenant_id)
    data.setdefault("employee_target_overrides", {}).pop(str(emp_id), None)
    save_goals(data, tenant_id)
    _log_target_change(
        "target_changed",
        tenant_id=tenant_id,
        context={"target_type": "employee_override", "employee_id": str(emp_id or ""), "cleared": True},
    )


def get_configured_processes(tenant_id: str = "") -> list[dict]:
    return list(load_goals(tenant_id).get("configured_processes", []))


def save_configured_processes(processes: list[dict], tenant_id: str = ""):
    data = load_goals(tenant_id)
    data["configured_processes"] = list(processes or [])
    save_goals(data, tenant_id)


# ── Employee flagging ──��───────────────────────────���──────────────────────────

def flag_employee(emp_id: str, emp_name: str, dept: str, reason: str = "",
                  flag_type: str = "followup", tenant_id: str = ""):
    """Flag an employee for performance tracking and log to coaching notes.

    flag_type: "followup" (🚩 Follow-up) | "performance" (⚠️ Performance Issue)
    Idempotent — re-flagging updates the type and reason.
    """
    data = load_goals(tenant_id)
    already_active = (emp_id in data["flagged_employees"]
                      and data["flagged_employees"][emp_id].get("active"))
    if emp_id not in data["flagged_employees"]:
        data["flagged_employees"][emp_id] = {
            "name":         emp_name,
            "dept":         dept,
            "flagged_on":   _get_user_timezone_now(tenant_id).strftime("%Y-%m-%d"),
            "reason":       reason,
            "flag_type":    flag_type,
            "notes":        [],
            "context_tags": [],
            "active":       True,
        }
    else:
        data["flagged_employees"][emp_id]["active"]    = True
        data["flagged_employees"][emp_id]["flag_type"] = flag_type
        if reason:
            data["flagged_employees"][emp_id]["reason"] = reason
        if "context_tags" not in data["flagged_employees"][emp_id]:
            data["flagged_employees"][emp_id]["context_tags"] = []
    save_goals(data, tenant_id)
    # Auto-log to coaching notes so the flag always appears in the coaching tab
    if not already_active:
        try:
            from database import add_coaching_note
            note = (f"Flagged ({flag_type}). Reason: {reason}"
                    if reason.strip() else f"Flagged for follow-up ({flag_type}).")
            add_coaching_note(emp_id, note, created_by="System")
        except Exception:
            pass   # non-critical — flag is still saved


def unflag_employee(emp_id: str, tenant_id: str = ""):
    data = load_goals(tenant_id)
    if emp_id in data["flagged_employees"]:
        data["flagged_employees"][emp_id]["active"] = False
        save_goals(data, tenant_id)


def add_note(emp_id: str, note_text: str, tenant_id: str = ""):
    """Append a timestamped note to a flagged employee's record."""
    data = load_goals(tenant_id)
    if emp_id not in data["flagged_employees"]:
        return
    data["flagged_employees"][emp_id]["notes"].append({
        "date": _get_user_timezone_now(tenant_id).strftime("%Y-%m-%d %H:%M"),
        "text": note_text.strip(),
    })
    save_goals(data, tenant_id)


def get_flagged_employees(tenant_id: str = "") -> dict:
    return load_goals(tenant_id).get("flagged_employees", {})


def get_active_flags(tenant_id: str = "") -> dict:
    return {k: v for k, v in get_flagged_employees(tenant_id).items() if v.get("active")}


# ── Trend analysis ───��────────────────────────────────────────────────────────

def analyse_trends(
    history:    list[dict],
    mapping:    dict[str, str],
    weeks:      int = 4,
) -> dict[str, dict]:
    """
    For each employee, calculate their UPH trend over the last N weeks.

    Returns:
        {
            emp_id: {
                "name":      str,
                "dept":      str,
                "direction": "up" | "down" | "flat" | "insufficient_data",
                "weeks":     [{"week": "W12", "avg_uph": 14.2}, ...],
                "change_pct": float,   # % change from first to last week
            }
        }
    """
    id_col   = mapping.get("EmployeeID")   or "EmployeeID"
    name_col = mapping.get("EmployeeName") or "EmployeeName"
    dept_col = mapping.get("Department")   or "Department"
    uph_col  = mapping.get("UPH")          or "UPH"

    # Group UPH values by (emp_id, week)
    weekly: dict[tuple, list[float]] = defaultdict(list)
    emp_meta: dict[str, dict] = {}

    for row in history:
        emp_id = str(row.get(id_col) or "").strip()
        week   = str(row.get("Week") or "").strip()
        if not emp_id or not week:
            continue

        try:
            uph = float(row.get(uph_col) or row.get("UPH") or "")
        except (ValueError, TypeError):
            continue

        weekly[(emp_id, week)].append(uph)

        if emp_id not in emp_meta:
            emp_meta[emp_id] = {
                "name": str(row.get(name_col) or "").strip(),
                "dept": str(row.get(dept_col) or "").strip(),
            }

    # Find the N most recent weeks across all data
    all_weeks = sorted(
        {w for _, w in weekly.keys()},
        key=lambda w: int(w.lstrip("Ww")) if w.lstrip("Ww").isdigit() else 0,
    )
    recent_weeks = all_weeks[-weeks:] if len(all_weeks) >= weeks else all_weeks

    results = {}
    for emp_id, meta in emp_meta.items():
        week_avgs = []
        for w in recent_weeks:
            vals = weekly.get((emp_id, w), [])
            if vals:
                week_avgs.append({"week": w, "avg_uph": round(sum(vals) / len(vals), 2)})

        if len(week_avgs) < 2:
            direction  = "insufficient_data"
            change_pct = 0.0
        else:
            first = week_avgs[0]["avg_uph"]
            last  = week_avgs[-1]["avg_uph"]
            change_pct = round(((last - first) / first * 100) if first else 0, 1)

            if change_pct >= 3:
                direction = "up"
            elif change_pct <= -3:
                direction = "down"
            else:
                direction = "flat"

        results[emp_id] = {
            "name":       meta["name"],
            "dept":       meta["dept"],
            "direction":  direction,
            "weeks":      week_avgs,
            "change_pct": change_pct,
        }

    return results


def build_goal_status(
    ranked:       list[dict],
    dept_targets: dict[str, float],
    trend_data:   dict[str, dict],
    tenant_id:    str = "",
) -> list[dict]:
    """
    Combine ranked employees with their goal status and trend.

    Returns each employee row enriched with:
        goal_status:  "on_goal" | "below_goal" | "no_goal"
        trend:        "up" | "down" | "flat" | "insufficient_data"
        change_pct:   float
        flagged:      bool
    """
    active_flags = get_active_flags(tenant_id)
    results      = []

    for emp in ranked:
        dept        = emp.get("Department", "")
        avg_uph     = float(emp.get("Average UPH", 0) or 0)
        emp_id      = str(emp.get("EmployeeID", emp.get("Employee Name", "")))
        trend_info  = trend_data.get(emp_id, {})
        target = float(dept_targets.get(dept, 0) or 0)
        target_source = "department target"
        resolved_process_name = str(dept or "")
        try:
            from services.target_service import build_comparison_descriptions, resolve_target_context

            target_context = resolve_target_context(
                employee_id=emp_id,
                process_name=dept,
                explicit_target=target,
                tenant_id=tenant_id,
            )
            target = float(target_context.get("target_uph") or 0)
            target_source = str(target_context.get("target_source_label") or "configured target")
            resolved_process_name = str(target_context.get("process_name") or dept or "")
            comparison_breakdown = build_comparison_descriptions(
                target_context=target_context,
                comparison_days=5,
                recent_avg=avg_uph,
                prior_avg=0.0,
            )
        except Exception:
            target_context = {
                "target_uph": target,
                "target_source": "department_target",
                "target_source_label": target_source,
                "process_name": resolved_process_name,
            }
            comparison_breakdown = {
                "compared_to_target": "Compared to target: existing department target.",
                "compared_to_recent_performance": "Compared to recent performance: current observed average.",
                "compared_to_recent_average": "Compared to recent average: trend history provides additional context.",
            }

        if target > 0:
            goal_status = "on_goal" if avg_uph >= target else "below_goal"
        else:
            goal_status = "no_goal"

        results.append({
            **emp,
            "Target UPH":  target if target > 0 else "—",
            "vs Target":   f"+{avg_uph - target:.1f}" if target > 0 and avg_uph >= target
                           else (f"{avg_uph - target:.1f}" if target > 0 else "—"),
            "goal_status": goal_status,
            "trend":       trend_info.get("direction", "insufficient_data"),
            "change_pct":  trend_info.get("change_pct", 0.0),
            "flagged":     emp_id in active_flags,
            "Target Source": target_source,
            "Resolved Process": resolved_process_name,
            "target_context": target_context,
            "comparison_breakdown": comparison_breakdown,
        })

    return results
