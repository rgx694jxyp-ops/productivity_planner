"""
database.py
-----------
Single place for all Supabase interactions.
Every other module calls functions from here — nothing else touches the DB directly.

Credentials are loaded from environment variables or Streamlit secrets.
See SETUP.md for configuration instructions.
"""

import json
import math
import os
from datetime import date, datetime
from typing import Optional


def _get_config(key: str) -> str:
    """Read from env var, then Streamlit secrets. Raises if not found."""
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        import streamlit as st
        val = st.secrets.get(key, "")
        if val:
            return val
    except Exception:
        pass
    return ""


SUPABASE_URL = _get_config("SUPABASE_URL")
SUPABASE_KEY = _get_config("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    _missing = []
    if not SUPABASE_URL:
        _missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        _missing.append("SUPABASE_KEY")
    raise RuntimeError(
        f"Missing required credentials: {', '.join(_missing)}.\n"
        "Set them as environment variables or in .streamlit/secrets.toml.\n"
        "See SETUP.md for instructions."
    )


def get_client():
    """Return an authenticated Supabase client, cached per browser session.
    Automatically refreshes expired tokens (Supabase tokens expire after 1 hour)."""
    import time as _time

    try:
        import streamlit as st
        cached = st.session_state.get("_sb_client")
        if cached is not None:
            # Check if token needs refresh (refresh 5 min before expiry)
            expires_at = st.session_state.get("_sb_token_expires_at", 0)
            if _time.time() > expires_at - 300:
                session = st.session_state.get("supabase_session")
                if session and session.get("refresh_token"):
                    try:
                        resp = cached.auth.refresh_session(session["refresh_token"])
                        if resp and resp.session:
                            st.session_state["supabase_session"] = {
                                "access_token":  resp.session.access_token,
                                "refresh_token": resp.session.refresh_token,
                            }
                            st.session_state["_sb_token_expires_at"] = (
                                resp.session.expires_at
                                if hasattr(resp.session, "expires_at") and resp.session.expires_at
                                else _time.time() + 3600
                            )
                            cached.auth.set_session(
                                resp.session.access_token,
                                resp.session.refresh_token,
                            )
                    except Exception:
                        # Refresh failed — force re-login on next request
                        st.session_state.pop("_sb_client", None)
                        st.session_state.pop("supabase_session", None)
                        return get_client()
            return cached
    except Exception:
        pass

    try:
        from supabase import create_client
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        try:
            import streamlit as st
            session = st.session_state.get("supabase_session")
            if session:
                client.auth.set_session(
                    session["access_token"],
                    session["refresh_token"],
                )
                # Store expiry — default 1 hour from now if not available
                st.session_state["_sb_token_expires_at"] = _time.time() + 3600
            st.session_state["_sb_client"] = client
        except Exception:
            pass
        return client
    except ImportError:
        raise RuntimeError(
            "Supabase library not installed.\n"
            "Run:  pip3 install supabase"
        )


def get_user_id() -> str:
    """Return the current user's id from session state."""
    try:
        import streamlit as st
        return st.session_state.get("user_id", "")
    except Exception:
        return ""


def get_tenant_id() -> str:
    """Return the current tenant id from session state."""
    try:
        import streamlit as st
        return st.session_state.get("tenant_id", "")
    except Exception:
        return ""


def _tenant_fields() -> dict:
    """Return {'tenant_id': value} only if a tenant_id is set, else empty dict.
    This lets inserts work cleanly when auth is bypassed."""
    tid = get_tenant_id()
    return {"tenant_id": tid} if tid else {}


def _tq(query):
    """Apply tenant_id filter to a Supabase query if a tenant is set."""
    tid = get_tenant_id()
    return query.eq("tenant_id", tid) if tid else query


def _finite_float(value, default: float = 0.0) -> float:
    """Return a JSON-safe finite float."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


# ── Clients ───────────────────────────────────────────────────────────────────

def get_clients() -> list[dict]:
    sb = get_client()
    r  = _tq(sb.table("clients").select("*")).order("name").execute()
    return r.data or []


def create_client_record(name: str, contact: str = "", email: str = "", notes: str = "") -> dict:
    sb = get_client()
    r  = sb.table("clients").insert({
        "name": name.strip(), "contact": contact, "email": email, "notes": notes,
        **_tenant_fields(),
    }).execute()
    return r.data[0] if r.data else {}


def update_client(client_id: str, **kwargs) -> dict:
    sb = get_client()
    r  = _tq(sb.table("clients").update(kwargs).eq("id", client_id)).execute()
    return r.data[0] if r.data else {}


def delete_client(client_id: str):
    sb = get_client()
    _tq(sb.table("clients").delete().eq("id", client_id)).execute()


# ── Orders ────────────────────────────────────────────────────────────────────

def get_orders(client_id: str = None, status: str = None) -> list[dict]:
    sb = get_client()
    q  = sb.table("orders").select("*, clients(name)")
    if client_id:
        q = q.eq("client_id", client_id)
    if status:
        q = q.eq("status", status)
    r = q.order("created_at", desc=True).execute()
    return r.data or []


def get_order(order_id: str) -> dict:
    sb = get_client()
    r  = sb.table("orders").select("*, clients(name)").eq("id", order_id).execute()
    return r.data[0] if r.data else {}


def create_order(client_id: str, order_number: str, description: str,
                 total_units: float, target_uph: float = None,
                 target_date: str = None, shift_length_hrs: float = 8.0,
                 notes: str = "") -> dict:
    sb = get_client()
    r  = sb.table("orders").insert({
        "client_id":        client_id,
        "order_number":     order_number.strip(),
        "description":      description.strip(),
        "total_units":      total_units,
        "units_completed":  0,
        "target_uph":       target_uph,
        "target_date":      target_date,
        "shift_length_hrs": shift_length_hrs,
        "notes":            notes,
        "status":           "open",
        "tenant_id":        get_tenant_id(),
    }).execute()
    return r.data[0] if r.data else {}


def update_order(order_id: str, **kwargs) -> dict:
    sb = get_client()
    r  = sb.table("orders").update(kwargs).eq("id", order_id).execute()
    return r.data[0] if r.data else {}


def complete_order(order_id: str) -> dict:
    return update_order(order_id, status="complete",
                        completed_at=datetime.utcnow().isoformat())


def add_units_to_order(order_id: str, units: float):
    """Increment units_completed on an order."""
    sb    = get_client()
    order = get_order(order_id)
    new_total = float(order.get("units_completed", 0)) + units
    total     = float(order.get("total_units", 0))
    # Auto-complete if fully done
    if new_total >= total:
        update_order(order_id, units_completed=new_total, status="complete",
                     completed_at=datetime.utcnow().isoformat())
    else:
        update_order(order_id, units_completed=new_total)


# ── Employees ─────────────────────────────────────────────────────────────────

def get_employees() -> list[dict]:
    sb = get_client()
    r  = _tq(sb.table("employees").select("*")).order("name").execute()
    return r.data or []


def get_employee(emp_id: str) -> dict | None:
    sb = get_client()
    r  = _tq(sb.table("employees").select("*").eq("emp_id", emp_id)).execute()
    return r.data[0] if r.data else None


def upsert_employee(emp_id: str, name: str, department: str = "",
                    shift: str = "") -> dict:
    """Insert or update a single employee record."""
    sb       = get_client()
    # First check with tenant filter (normal path)
    existing = get_employee(emp_id)
    if existing:
        r = _tq(sb.table("employees").update({
            "name": name, "department": department, "shift": shift, "is_new": False
        }).eq("emp_id", emp_id)).execute()
        return r.data[0] if r.data else {}

    # Check WITHOUT tenant filter — row may exist with NULL/different tenant_id
    r_any = sb.table("employees").select("id").eq("emp_id", emp_id).execute()
    if r_any.data:
        # Claim the orphaned row for this tenant
        update_data = {
            "name": name, "department": department, "shift": shift, "is_new": False,
            **_tenant_fields(),
        }
        r = sb.table("employees").update(update_data).eq("emp_id", emp_id).execute()
        return r.data[0] if r.data else {}

    r = sb.table("employees").insert({
        "emp_id": emp_id, "name": name,
        "department": department, "shift": shift, "is_new": True,
        **_tenant_fields(),
    }).execute()
    return r.data[0] if r.data else {}


def batch_upsert_employees(employees: list[dict]):
    """
    Upsert many employees in as few round-trips as possible.
    employees: list of {emp_id, name, department, shift}
    Uses upsert with on_conflict so existing rows are updated, new ones inserted.
    """
    if not employees:
        return
    sb = get_client()
    _tf  = _tenant_fields()
    rows = [{
        "emp_id":     e["emp_id"],
        "name":       e.get("name",""),
        "department": e.get("department",""),
        "shift":      e.get("shift",""),
        "is_new":     False,
        **_tf,
    } for e in employees]
    # Supabase upsert — on conflict on emp_id+tenant_id, update the other fields
    try:
        sb.table("employees").upsert(rows, on_conflict="emp_id,tenant_id").execute()
        return  # success
    except Exception as _batch_err:
        log_error("employees", f"Batch upsert failed ({len(rows)} rows): {_batch_err}",
                  severity="warning")
        # Fallback: individual upserts
        _fail_count = 0
        _last_err = None
        for e in employees:
            try:
                upsert_employee(e["emp_id"], e.get("name",""),
                                e.get("department",""), e.get("shift",""))
            except Exception as _ind_err:
                _fail_count += 1
                _last_err = _ind_err
        if _fail_count == len(employees):
            log_error("employees",
                      f"All {_fail_count} individual employee upserts failed: {_last_err}",
                      severity="error")
            raise RuntimeError(
                f"Could not store any employees — batch and individual upserts both failed: {_last_err}"
            ) from _last_err


def mark_employee_not_new(emp_id: str):
    sb = get_client()
    _tq(sb.table("employees").update({"is_new": False}).eq("emp_id", emp_id)).execute()


# ── Order Assignments ─────────────────────────────────────────────────────────

def get_assignments(order_id: str = None, emp_id: str = None,
                    active_only: bool = True) -> list[dict]:
    sb = get_client()
    q  = sb.table("order_assignments").select("*")
    if order_id:
        q = q.eq("order_id", order_id)
    if emp_id:
        q = q.eq("emp_id", emp_id)
    if active_only:
        q = q.eq("is_active", True)
    r = q.execute()
    return r.data or []


def assign_employee_to_order(order_id: str, emp_id: str) -> dict:
    """Assign an employee to an order. Deactivates any previous active assignments for that employee."""
    sb = get_client()
    # Deactivate old active assignments for this employee
    sb.table("order_assignments").update({"is_active": False}).eq(
        "emp_id", emp_id).eq("is_active", True).execute()
    # Create new assignment
    r = sb.table("order_assignments").insert({
        "order_id": order_id, "emp_id": emp_id,
        "assigned_on": date.today().isoformat(), "is_active": True,
        **_tenant_fields(),
    }).execute()
    return r.data[0] if r.data else {}


def assign_employee_split(emp_id: str, order_assignments: list[dict]):
    """
    Assign an employee to multiple orders for a split day.
    order_assignments = [{"order_id": "...", "units": 80}, ...]
    Deactivates all previous assignments first.
    """
    sb = get_client()
    sb.table("order_assignments").update({"is_active": False}).eq(
        "emp_id", emp_id).eq("is_active", True).execute()
    for a in order_assignments:
        sb.table("order_assignments").insert({
            "order_id":    a["order_id"],
            "emp_id":      emp_id,
            "assigned_on": date.today().isoformat(),
            "is_active":   True,
            "tenant_id":   get_tenant_id(),
        }).execute()


def get_assigned_order_for_employee(emp_id: str) -> str | None:
    """Return the single active order_id for an employee, or None."""
    assignments = get_assignments(emp_id=emp_id, active_only=True)
    return assignments[0]["order_id"] if assignments else None


def get_unassigned_employees() -> list[dict]:
    """Return employees with no active order assignment."""
    all_emps    = get_employees()
    assigned    = {a["emp_id"] for a in get_assignments(active_only=True)}
    return [e for e in all_emps if e["emp_id"] not in assigned]


# ── Unit Submissions ──────────────────────────────────────────────────────────

def submit_units(order_id: str, emp_id: str, units: float,
                 uph: float, hours_worked: float,
                 work_date: str, source_file: str = "") -> dict:
    sb = get_client()
    units = _finite_float(units)
    uph = _finite_float(uph)
    hours_worked = _finite_float(hours_worked)
    r  = sb.table("unit_submissions").insert({
        "order_id":    order_id,
        "emp_id":      emp_id,
        "units":       units,
        "uph":         uph,
        "hours_worked": hours_worked,
        "work_date":   work_date,
        "source_file": source_file,
        "tenant_id":   get_tenant_id(),
    }).execute()
    # Update order progress
    add_units_to_order(order_id, units)
    # Store in UPH history
    store_uph_history(emp_id, work_date, uph, units, hours_worked, order_id=order_id)
    return r.data[0] if r.data else {}


def bulk_submit_units(subs: list, source_file: str = "") -> tuple:
    """
    Submit all allocations in as few DB round-trips as possible.
    - One batch insert for unit_submissions
    - One batch insert for uph_history
    - One update per affected order (read current, add totals, write once)
    Returns (committed_count, errors_list).
    """
    if not subs:
        return 0, []

    sb     = get_client()
    errors = []

    # ── 1. Batch insert all unit_submissions ──────────────────────────────────
    _tf      = _tenant_fields()
    sub_rows = [{
        "order_id":    s["order_id"],
        "emp_id":      s["emp_id"],
        "units":       _finite_float(s.get("units", 0)),
        "uph":         _finite_float(s.get("uph", 0)),
        "hours_worked":_finite_float(s.get("hours", 0)),
        "work_date":   s.get("date", ""),
        "source_file": source_file,
        **_tf,
    } for s in subs]

    try:
        sb.table("unit_submissions").insert(sub_rows).execute()
    except Exception as e:
        return 0, [str(e)]

    # ── 2. Batch insert all uph_history rows ──────────────────────────────────
    uph_rows = [{
        "emp_id":      s["emp_id"],
        "work_date":   s.get("date", ""),
        "uph":         _finite_float(s.get("uph", 0)),
        "units":       _finite_float(s.get("units", 0)),
        "hours_worked":_finite_float(s.get("hours", 0)),
        "department":  s.get("dept", ""),
        "order_id":    s["order_id"],
        **_tf,
    } for s in subs]

    try:
        sb.table("uph_history").insert(uph_rows).execute()
    except Exception as e:
        errors.append(f"UPH history: {e}")   # non-fatal

    # ── 3. Update each affected order once ───────────────────────────────────
    # Aggregate total units added per order across all subs
    from collections import defaultdict
    order_units = defaultdict(float)
    for s in subs:
        order_units[s["order_id"]] += float(s["units"])

    for order_id, added in order_units.items():
        try:
            add_units_to_order(order_id, added)
        except Exception as e:
            errors.append(f"Order {order_id}: {e}")

    committed = len(subs) if not errors else len(subs) - len([e for e in errors if "Order" in e])
    return committed, errors


def get_submissions(order_id: str = None, emp_id: str = None,
                    from_date: str = None) -> list[dict]:
    sb = get_client()
    q  = sb.table("unit_submissions").select("*").order("work_date", desc=True)
    if order_id: q = q.eq("order_id", order_id)
    if emp_id:   q = q.eq("emp_id", emp_id)
    if from_date: q = q.gte("work_date", from_date)
    r = q.execute()
    return r.data or []


def get_order_hours_worked(order_id: str) -> float:
    """Total hours logged against an order."""
    subs = get_submissions(order_id=order_id)
    return sum(float(s.get("hours_worked") or 0) for s in subs)


# ── UPH History ───────────────────────────────────────────────────────────────

def store_uph_history(emp_id: str, work_date: str, uph: float,
                      units: float, hours_worked: float,
                      department: str = "", order_id: str = None):
    """Insert or update a single UPH history record (dedup on tenant+emp+date+dept)."""
    sb = get_client()
    uph = _finite_float(uph)
    units = _finite_float(units)
    hours_worked = _finite_float(hours_worked)
    sb.table("uph_history").upsert({
        "emp_id":       emp_id,
        "work_date":    work_date,
        "uph":          uph,
        "units":        units,
        "hours_worked": hours_worked,
        "department":   department,
        "order_id":     order_id,
        "tenant_id":    get_tenant_id(),
    }, on_conflict="tenant_id,emp_id,work_date,department").execute()


def batch_store_uph_history(records: list[dict]):
    """
    Insert UPH history records in bulk (500 per chunk).
    Silently skips if a chunk fails (e.g. duplicates already stored).
    """
    if not records:
        return

    def _json_safe_value(v):
        if isinstance(v, float):
            return v if math.isfinite(v) else 0.0
        if isinstance(v, list):
            return [_json_safe_value(x) for x in v]
        if isinstance(v, dict):
            return {k: _json_safe_value(val) for k, val in v.items()}
        return v

    sb  = get_client()
    # Only inject tenant_id if not already present in the records
    if not records[0].get("tenant_id"):
        _tf = _tenant_fields()
        if _tf:
            records = [{**r, **_tf} for r in records]

    for i in range(0, len(records), 500):
        chunk = records[i:i+500]
        safe_chunk = []
        for r in chunk:
            try:
                uph_val = float(r.get("uph", 0) or 0)
            except (TypeError, ValueError):
                uph_val = 0.0
            if not math.isfinite(uph_val):
                uph_val = 0.0

            try:
                units_val = float(r.get("units", 0) or 0)
            except (TypeError, ValueError):
                units_val = 0.0
            if not math.isfinite(units_val):
                units_val = 0.0

            try:
                hours_val = float(r.get("hours_worked", 0) or 0)
            except (TypeError, ValueError):
                hours_val = 0.0
            if not math.isfinite(hours_val):
                hours_val = 0.0

            safe_chunk.append({
                **r,
                "uph": uph_val,
                "units": units_val,
                "hours_worked": hours_val,
            })
        safe_chunk = [_json_safe_value(r) for r in safe_chunk]
        try:
            # Fail fast with a clear error if anything non-JSON-safe remains.
            json.dumps(safe_chunk, allow_nan=False)
            sb.table("uph_history").upsert(
                safe_chunk,
                on_conflict="tenant_id,emp_id,work_date,department",
            ).execute()
        except Exception as _e:
            log_error("uph_history", f"UPH batch upsert failed: {_e}",
                      detail=f"chunk_size={len(safe_chunk)}, sample={safe_chunk[0] if safe_chunk else 'empty'}",
                      severity="error")
            raise


def delete_duplicate_uph_history():
    """
    Remove duplicate uph_history rows (same emp_id + work_date).
    Tries a Postgres RPC first for speed; falls back to Python dedup.
    Returns count of rows deleted.
    """
    sb = get_client()

    # Fetch all IDs for this tenant, find dupes in Python, delete in batches
    all_rows  = []
    page_size = 1000
    offset    = 0
    while True:
        try:
            r = _tq(sb.table("uph_history").select("id, emp_id, work_date")) \
                  .order("id").range(offset, offset + page_size - 1).execute()
            batch = r.data or []
        except Exception:
            break
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    seen, to_delete = {}, []
    for row in all_rows:
        key = (row.get("emp_id",""), row.get("work_date",""))
        if key in seen:
            to_delete.append(row["id"])
        else:
            seen[key] = row["id"]

    if not to_delete:
        return 0   # nothing to delete — do NOT call .delete() with empty list

    deleted = 0
    for i in range(0, len(to_delete), 500):
        chunk = to_delete[i:i+500]
        if not chunk:
            continue   # safety guard — never delete with empty filter
        try:
            sb.table("uph_history").delete().in_("id", chunk).execute()
            deleted += len(chunk)
        except Exception:
            pass
    return deleted


def get_uph_history(emp_id: str, days: int = 90) -> list[dict]:
    from datetime import timedelta
    sb       = get_client()
    cutoff   = (date.today() - timedelta(days=days)).isoformat()
    r        = _tq(sb.table("uph_history").select("*").eq(
        "emp_id", emp_id).gte("work_date", cutoff)).order("work_date").execute()
    return r.data or []


def get_all_uph_history(days: int = 0) -> list[dict]:
    """All UPH history records. Paginates to get past Supabase 1000-row default cap."""
    from datetime import timedelta
    sb     = get_client()
    all_rows = []
    page_size = 1000
    offset    = 0
    while True:
        q = _tq(sb.table("uph_history").select(
            "emp_id, work_date, uph, units, hours_worked, department"
        )).order("work_date", desc=False).range(offset, offset + page_size - 1)
        if days > 0:
            cutoff = (date.today() - timedelta(days=days)).isoformat()
            q = q.gte("work_date", cutoff)
        r = q.execute()
        batch = r.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return all_rows


def get_avg_uph(emp_id: str, days: int = 30) -> float | None:
    """Return average UPH for the last N days. Returns None for brand-new employees."""
    rows = get_uph_history(emp_id, days=days)
    if not rows:
        return None
    vals = [float(r["uph"]) for r in rows if r.get("uph")]
    return round(sum(vals) / len(vals), 2) if vals else None


# ── Coaching Notes ────────────────────────────────────────────────────────────

def add_coaching_note(emp_id: str, note: str, created_by: str = "") -> dict:
    sb = get_client()
    r  = sb.table("coaching_notes").insert({
        "emp_id": emp_id, "note": note.strip(), "created_by": created_by,
        **_tenant_fields(),
    }).execute()
    return r.data[0] if r.data else {}


def get_coaching_notes(emp_id: str, include_archived: bool = False) -> list[dict]:
    sb   = get_client()
    r    = _tq(sb.table("coaching_notes").select("*").eq(
        "emp_id", emp_id)).order("created_at", desc=True).execute()
    rows = r.data or []
    if not include_archived:
        rows = [row for row in rows if not row.get("archived", False)]
    return rows


def delete_coaching_note(note_id: str):
    sb = get_client()
    _tq(sb.table("coaching_notes").delete().eq("id", note_id)).execute()


def archive_coaching_notes(emp_id: str):
    """Mark all notes for an employee as archived (soft delete)."""
    sb = get_client()
    try:
        _tq(sb.table("coaching_notes").update({"archived": True}).eq("emp_id", emp_id)).execute()
    except Exception:
        # archived column may not exist — fall back to hard delete
        _tq(sb.table("coaching_notes").delete().eq("emp_id", emp_id)).execute()


# ── Shifts ────────────────────────────────────────────────────────────────────

def create_shift(shift_name: str, shift_date: str, shift_length: float = 8.0) -> dict:
    sb = get_client()
    r  = sb.table("shifts").insert({
        "shift_name":   shift_name,
        "shift_date":   shift_date,
        "shift_length": shift_length,
        "tenant_id":    get_tenant_id(),
    }).execute()
    return r.data[0] if r.data else {}


def get_shifts(from_date: str = None) -> list[dict]:
    sb = get_client()
    q  = _tq(sb.table("shifts").select("*")).order("shift_date", desc=True)
    if from_date:
        q = q.gte("shift_date", from_date)
    r = q.execute()
    return r.data or []


# ── Uploaded Files ────────────────────────────────────────────────────────────

def log_uploaded_file(filename: str, row_count: int,
                      header_mapping: dict) -> dict:
    sb = get_client()
    r  = sb.table("uploaded_files").insert({
        "filename":       filename,
        "row_count":      row_count,
        "header_mapping": header_mapping,
        "is_active":      True,
        "tenant_id":      get_tenant_id(),
    }).execute()
    return r.data[0] if r.data else {}


def get_active_uploaded_files() -> list[dict]:
    sb = get_client()
    r  = _tq(sb.table("uploaded_files").select("*").eq(
        "is_active", True)).order("uploaded_at", desc=True).execute()
    return r.data or []


def deactivate_uploaded_file(file_id: str):
    sb = get_client()
    _tq(sb.table("uploaded_files").update({"is_active": False}).eq("id", file_id)).execute()


# ── Client Trends ─────────────────────────────────────────────────────────────

def store_client_trend(client_id: str, period: str, avg_uph: float,
                       total_units: float, orders_completed: int = 0):
    sb = get_client()
    sb.table("client_trends").insert({
        "client_id":        client_id,
        "period":           period,
        "avg_uph":          avg_uph,
        "total_units":      total_units,
        "orders_completed": orders_completed,
        "tenant_id":        get_tenant_id(),
    }).execute()


def get_client_trends(client_id: str) -> list[dict]:
    sb = get_client()
    r  = sb.table("client_trends").select("*").eq(
        "client_id", client_id).order("period").execute()
    return r.data or []


# ── Suggestions ───────────────────────────────────────────────────────────────

def suggest_employees_for_order(order_id: str,
                                 new_emp_default_uph: float = 10.0) -> list[dict]:
    """
    Return unassigned employees ranked by avg UPH (last 30 days).
    New employees with no history get new_emp_default_uph as their estimate.
    """
    from datetime import timedelta
    order        = get_order(order_id)
    unassigned   = get_unassigned_employees()
    target_uph   = float(order.get("target_uph") or 0)
    units_left   = float(order.get("total_units", 0)) - float(order.get("units_completed", 0))
    shift_length = float(order.get("shift_length_hrs") or 8)

    # Batch-fetch UPH history for all unassigned employees in one query
    # instead of one round-trip per employee.
    avg_uph_map: dict[str, float] = {}
    if unassigned:
        sb      = get_client()
        cutoff  = (date.today() - timedelta(days=30)).isoformat()
        emp_ids = [e["emp_id"] for e in unassigned]
        chunk_size = 200
        all_history: list[dict] = []
        for i in range(0, len(emp_ids), chunk_size):
            chunk = emp_ids[i:i + chunk_size]
            try:
                r = sb.table("uph_history").select("emp_id, uph") \
                      .in_("emp_id", chunk).gte("work_date", cutoff).execute()
                all_history.extend(r.data or [])
            except Exception:
                pass
        # Compute per-employee average from the single batch result
        from collections import defaultdict
        uph_vals: dict[str, list] = defaultdict(list)
        for row in all_history:
            if row.get("uph"):
                uph_vals[row["emp_id"]].append(float(row["uph"]))
        for eid, vals in uph_vals.items():
            avg_uph_map[eid] = round(sum(vals) / len(vals), 2)

    suggestions = []
    for emp in unassigned:
        avg = avg_uph_map.get(emp["emp_id"])
        is_new = avg is None
        effective_uph = avg if avg is not None else new_emp_default_uph
        suggestions.append({
            **emp,
            "avg_uph":      effective_uph,
            "is_new":       is_new,
            "units_per_shift": round(effective_uph * shift_length, 0),
        })

    suggestions.sort(key=lambda e: e["avg_uph"], reverse=True)

    # Estimate cumulative completion times
    cumulative_uph = 0.0
    for s in suggestions:
        cumulative_uph += s["avg_uph"]
        shifts_needed = round(units_left / (cumulative_uph * shift_length), 1) if cumulative_uph > 0 else None
        s["shifts_to_complete_with_team"] = shifts_needed

    return suggestions


# ── Export helpers ────────────────────────────────────────────────────────────

def export_order_to_dict(order_id: str) -> dict:
    """Return a complete order record with all submissions for Excel export."""
    order = get_order(order_id)
    subs  = get_submissions(order_id=order_id)
    assig = get_assignments(order_id=order_id, active_only=False)
    return {"order": order, "submissions": subs, "assignments": assig}


def export_client_to_dict(client_id: str) -> dict:
    """Return full client history for Excel export."""
    client = get_clients()
    client = next((c for c in client if c["id"] == client_id), {})
    orders = get_orders(client_id=client_id)
    trends = get_client_trends(client_id)
    return {"client": client, "orders": orders, "trends": trends}


# ── Tenant Goals (DB-backed) ───────────────────────────────────────────────

def load_goals_db(tenant_id: str = "") -> dict:
    """Load goals from tenant_goals table. Returns {dept_targets:{}, flagged_employees:{}}."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return {"dept_targets": {}, "flagged_employees": {}}
    try:
        sb = get_client()
        r = sb.table("tenant_goals").select("*").eq("tenant_id", tid).execute()
        if r.data:
            row = r.data[0]
            return {
                "dept_targets": row.get("dept_targets") or {},
                "flagged_employees": row.get("flagged_employees") or {},
            }
    except Exception:
        pass
    return {"dept_targets": {}, "flagged_employees": {}}


def save_goals_db(data: dict, tenant_id: str = ""):
    """Save goals to tenant_goals table (upsert)."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return
    try:
        sb = get_client()
        sb.table("tenant_goals").upsert({
            "tenant_id": tid,
            "dept_targets": data.get("dept_targets", {}),
            "flagged_employees": data.get("flagged_employees", {}),
        }, on_conflict="tenant_id").execute()
    except Exception as e:
        print(f"[Warning] Could not save goals to DB: {e}")


# ── Tenant Settings (DB-backed) ────────────────────────────────────────────

def load_settings_db(tenant_id: str = "") -> dict:
    """Load settings from tenant_settings table."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return {}
    try:
        sb = get_client()
        r = sb.table("tenant_settings").select("config").eq("tenant_id", tid).execute()
        if r.data:
            return r.data[0].get("config") or {}
    except Exception:
        pass
    return {}


def save_settings_db(config: dict, tenant_id: str = ""):
    """Save settings to tenant_settings table (upsert)."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return
    try:
        sb = get_client()
        sb.table("tenant_settings").upsert({
            "tenant_id": tid,
            "config": config,
        }, on_conflict="tenant_id").execute()
    except Exception as e:
        print(f"[Warning] Could not save settings to DB: {e}")


# ── Tenant Email Config (DB-backed) ─────────────────────────────────────────

def load_email_config_db(tenant_id: str = "") -> dict:
    """Load email config from tenant_email_config table."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return {"smtp": {}, "recipients": [], "schedules": []}
    try:
        sb = get_client()
        r = sb.table("tenant_email_config").select("*").eq("tenant_id", tid).execute()
        if r.data:
            row = r.data[0]
            return {
                "smtp": row.get("smtp") or {},
                "recipients": row.get("recipients") or [],
                "schedules": row.get("schedules") or [],
            }
    except Exception:
        pass
    return {"smtp": {}, "recipients": [], "schedules": []}


def save_email_config_db(data: dict, tenant_id: str = ""):
    """Save email config to tenant_email_config table (upsert)."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return
    try:
        sb = get_client()
        sb.table("tenant_email_config").upsert({
            "tenant_id": tid,
            "smtp": data.get("smtp", {}),
            "recipients": data.get("recipients", []),
            "schedules": data.get("schedules", []),
        }, on_conflict="tenant_id").execute()
    except Exception as e:
        print(f"[Warning] Could not save email config to DB: {e}")


# ── GDPR: data export & account deletion ─────────────────────────────────────

_TENANT_TABLES = [
    "employees", "uph_history", "coaching_notes", "shifts",
    "uploaded_files", "clients", "orders", "order_assignments",
    "unit_submissions", "client_trends",
    "tenant_goals", "tenant_settings", "tenant_email_config",
    "subscriptions",
]


# ── Subscriptions (Stripe) ─────────────────────────────────────────────────────

PLAN_LIMITS = {
    "starter":  25,
    "pro":      100,
    "business": -1,   # unlimited
    "trial":    10,
}


def get_subscription(tenant_id: str = "") -> Optional[dict]:
    """Return the subscription row for the current tenant, or None."""
    sb = get_client()
    tid = tenant_id or get_tenant_id()
    if not tid:
        return None
    try:
        resp = sb.table("subscriptions").select("*").eq("tenant_id", tid).execute()
        if resp.data:
            return resp.data[0]
    except Exception:
        pass
    return None


def has_active_subscription(tenant_id: str = "") -> bool:
    """Check if the current tenant has an active (or trialing/past_due) subscription."""
    sub = get_subscription(tenant_id)
    if not sub:
        return False
    return sub.get("status") in ("active", "past_due", "trialing")


def get_employee_limit(tenant_id: str = "") -> int:
    """Return the employee limit for the current plan. 0 if no sub, -1 if unlimited."""
    sub = get_subscription(tenant_id)
    if not sub or sub.get("status") not in ("active", "past_due", "trialing"):
        return 0
    return sub.get("employee_limit", 0)


def get_employee_count(tenant_id: str = "") -> int:
    """Return current number of employees for the tenant."""
    sb = get_client()
    tid = tenant_id or get_tenant_id()
    if not tid:
        return 0
    try:
        resp = sb.table("employees").select("emp_id", count="exact").eq("tenant_id", tid).execute()
        return resp.count or 0
    except Exception:
        return 0


def can_add_employees(count: int = 1, tenant_id: str = "") -> bool:
    """Check if adding `count` employees would exceed the plan limit."""
    limit = get_employee_limit(tenant_id)
    if limit == -1:
        return True  # unlimited
    if limit == 0:
        return False  # no active plan
    current = get_employee_count(tenant_id)
    return (current + count) <= limit


def create_stripe_checkout_url(price_id: str, success_url: str, cancel_url: str,
                                tenant_id: str = "") -> tuple:
    """Create a Stripe Checkout Session. Returns (url, error_msg)."""
    import requests
    stripe_key = _get_config("STRIPE_SECRET_KEY")
    if not stripe_key:
        return None, "STRIPE_SECRET_KEY not configured"

    tid = tenant_id or get_tenant_id()
    if not tid:
        return None, "No tenant_id found"

    # Get or create Stripe customer
    sb = get_client()
    stripe_cid = None
    try:
        tenant_resp = sb.table("tenants").select("stripe_customer_id, name").eq("id", tid).execute()
        stripe_cid = (tenant_resp.data[0].get("stripe_customer_id") if tenant_resp.data else None)
    except Exception as e:
        return None, f"Tenant lookup failed: {e}"

    if not stripe_cid:
        # Create Stripe customer
        email = ""
        try:
            import streamlit as st
            email = st.session_state.get("user_email", "")
        except Exception:
            pass
        cust_resp = requests.post(
            "https://api.stripe.com/v1/customers",
            auth=(stripe_key, ""),
            data={"email": email, "metadata[tenant_id]": tid},
            timeout=10,
        )
        if cust_resp.status_code == 200:
            stripe_cid = cust_resp.json().get("id")
            try:
                sb.table("tenants").update({"stripe_customer_id": stripe_cid}).eq("id", tid).execute()
            except Exception:
                pass
        else:
            return None, f"Stripe customer creation failed: {cust_resp.status_code} {cust_resp.text[:200]}"

    # Create Checkout Session
    checkout_resp = requests.post(
        "https://api.stripe.com/v1/checkout/sessions",
        auth=(stripe_key, ""),
        data={
            "mode": "subscription",
            "customer": stripe_cid,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": 1,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": tid,
            "subscription_data[metadata][tenant_id]": tid,
        },
        timeout=10,
    )
    if checkout_resp.status_code == 200:
        return checkout_resp.json().get("url"), None
    return None, f"Checkout creation failed: {checkout_resp.status_code} {checkout_resp.text[:200]}"


def create_billing_portal_url(
    return_url: str,
    tenant_id: str = "",
    target_price_id: str = "",
    flow: str = "",
) -> Optional[str]:
    """Create a Stripe Billing Portal session for the current tenant.

    Args:
        return_url: URL users return to from Stripe portal.
        tenant_id: Optional tenant override.
        target_price_id: Optional Stripe Price ID for plan-targeted update flow.
        flow: Optional deep-link flow: "subscription_update", "subscription_cancel",
            or "payment_method_update".
    """
    import requests
    stripe_key = _get_config("STRIPE_SECRET_KEY")
    if not stripe_key:
        return None

    tid = tenant_id or get_tenant_id()
    sb = get_client()
    try:
        resp = sb.table("tenants").select("stripe_customer_id").eq("id", tid).execute()
        stripe_cid = resp.data[0].get("stripe_customer_id") if resp.data else None
    except Exception:
        return None

    if not stripe_cid:
        return None

    stripe_sub_id = ""
    try:
        sub_resp = (
            sb.table("subscriptions")
            .select("stripe_subscription_id")
            .eq("tenant_id", tid)
            .execute()
        )
        if sub_resp.data:
            stripe_sub_id = sub_resp.data[0].get("stripe_subscription_id") or ""
    except Exception:
        stripe_sub_id = ""

    payload = {"customer": stripe_cid, "return_url": return_url}
    if flow == "payment_method_update":
        payload["flow_data[type]"] = "payment_method_update"
    elif flow == "subscription_cancel" and stripe_sub_id:
        payload["flow_data[type]"] = "subscription_cancel"
        payload["flow_data[subscription_cancel][subscription]"] = stripe_sub_id
    elif flow == "subscription_update":
        if target_price_id and stripe_sub_id:
            # Preselect target plan while keeping Stripe's proration/confirmation UX.
            # Stripe expects the subscription item id for update_confirm flows.
            sub_item_id = ""
            sub_item_qty = ""
            current_price_id = ""
            try:
                sub_get = requests.get(
                    f"https://api.stripe.com/v1/subscriptions/{stripe_sub_id}",
                    auth=(stripe_key, ""),
                    timeout=10,
                )
                if sub_get.status_code == 200:
                    sub_obj = sub_get.json()
                    items = ((sub_obj.get("items") or {}).get("data") or [])
                    if items:
                        sub_item_id = items[0].get("id") or ""
                        current_price_id = items[0].get("price", {}).get("id") or ""
                        _qty = items[0].get("quantity")
                        if _qty is not None:
                            sub_item_qty = str(_qty)
            except Exception:
                sub_item_id = ""
                current_price_id = ""

            # Only use subscription_update_confirm if the target price is DIFFERENT
            if sub_item_id and current_price_id and current_price_id != target_price_id:
                payload["flow_data[type]"] = "subscription_update_confirm"
                payload["flow_data[subscription_update_confirm][subscription]"] = stripe_sub_id
                payload["flow_data[subscription_update_confirm][items][0][id]"] = sub_item_id
                payload["flow_data[subscription_update_confirm][items][0][price]"] = target_price_id
                if sub_item_qty:
                    payload["flow_data[subscription_update_confirm][items][0][quantity]"] = sub_item_qty
                payload["flow_data[after_completion][type]"] = "redirect"
                payload["flow_data[after_completion][redirect][return_url]"] = return_url
            else:
                # Current price matches target, or item lookup failed → use generic subscription_update
                payload["flow_data[type]"] = "subscription_update"
                if stripe_sub_id:
                    payload["flow_data[subscription_update][subscription]"] = stripe_sub_id
        elif stripe_sub_id:
            payload["flow_data[type]"] = "subscription_update"
            payload["flow_data[subscription_update][subscription]"] = stripe_sub_id

    portal_resp = requests.post(
        "https://api.stripe.com/v1/billing_portal/sessions",
        auth=(stripe_key, ""),
        data=payload,
        timeout=10,
    )
    if portal_resp.status_code == 200:
        return portal_resp.json().get("url")

    # Fallback to the generic portal if deep-link flow params are rejected.
    if flow:
        fallback_resp = requests.post(
            "https://api.stripe.com/v1/billing_portal/sessions",
            auth=(stripe_key, ""),
            data={"customer": stripe_cid, "return_url": return_url},
            timeout=10,
        )
        if fallback_resp.status_code == 200:
            return fallback_resp.json().get("url")

    return None


def _resolve_plan_from_price_id(price_id: str) -> str:
    """Map a Stripe price id to the local plan key."""
    if not price_id:
        return "starter"
    price_map = {
        _get_config("STRIPE_PRICE_STARTER"): "starter",
        _get_config("STRIPE_PRICE_PRO"): "pro",
        _get_config("STRIPE_PRICE_BUSINESS"): "business",
    }
    return price_map.get(price_id, "starter")


def get_live_stripe_subscription_status(tenant_id: str = "") -> Optional[dict]:
    """Fetch live Stripe subscription details, including pending plan changes."""
    import requests

    stripe_key = _get_config("STRIPE_SECRET_KEY")
    if not stripe_key:
        return None

    tid = tenant_id or get_tenant_id()
    if not tid:
        return None

    sb = get_client()
    try:
        resp = (
            sb.table("subscriptions")
            .select("stripe_customer_id, stripe_subscription_id, plan, status, employee_limit, current_period_end")
            .eq("tenant_id", tid)
            .limit(1)
            .execute()
        )
        row = (resp.data or [{}])[0]
    except Exception:
        return None

    stripe_sub_id = row.get("stripe_subscription_id") or ""
    stripe_cid = row.get("stripe_customer_id") or ""
    if not stripe_sub_id:
        return None

    sub_resp = requests.get(
        f"https://api.stripe.com/v1/subscriptions/{stripe_sub_id}",
        auth=(stripe_key, ""),
        params={
            "expand[]": [
                "items.data.price",
                "pending_update.subscription_items",
                "latest_invoice.payment_intent",
                "latest_invoice.charge",
            ]
        },
        timeout=10,
    )
    if sub_resp.status_code != 200:
        return {
            "error": f"Stripe lookup failed: {sub_resp.status_code} {sub_resp.text[:200]}",
            "tenant_id": tid,
        }

    sub_obj = sub_resp.json()
    current_item = ((sub_obj.get("items") or {}).get("data") or [{}])[0]
    current_price = current_item.get("price") or {}
    current_price_id = current_price.get("id") or ""
    current_plan = (
        (sub_obj.get("metadata") or {}).get("plan")
        or (current_price.get("metadata") or {}).get("plan")
        or _resolve_plan_from_price_id(current_price_id)
    )
    current_plan = (current_plan or "starter").lower()

    pending_update = sub_obj.get("pending_update") or {}
    pending_item = (pending_update.get("subscription_items") or [{}])[0]
    pending_price = pending_item.get("price") or ""
    if isinstance(pending_price, dict):
        pending_price_id = pending_price.get("id") or ""
    else:
        pending_price_id = pending_price or ""
    pending_plan = _resolve_plan_from_price_id(pending_price_id) if pending_price_id else ""

    latest_invoice = sub_obj.get("latest_invoice") or {}
    payment_intent = latest_invoice.get("payment_intent") or {}
    charge = latest_invoice.get("charge") or {}
    if isinstance(charge, str):
        charge_id = charge
    else:
        charge_id = charge.get("id") or ""
    latest_charge = payment_intent.get("latest_charge") or ""
    if not charge_id:
        if isinstance(latest_charge, dict):
            charge_id = latest_charge.get("id") or ""
        else:
            charge_id = latest_charge or ""

    return {
        "tenant_id": tid,
        "stripe_customer_id": stripe_cid,
        "stripe_subscription_id": stripe_sub_id,
        "status": sub_obj.get("status") or row.get("status") or "",
        "current_plan": current_plan,
        "current_price_id": current_price_id,
        "current_period_end": sub_obj.get("current_period_end"),
        "cancel_at_period_end": bool(sub_obj.get("cancel_at_period_end")),
        "db_plan": row.get("plan") or "",
        "db_status": row.get("status") or "",
        "db_employee_limit": row.get("employee_limit"),
        "db_current_period_end": row.get("current_period_end") or "",
        "has_pending_update": bool(pending_update),
        "pending_plan": pending_plan,
        "pending_price_id": pending_price_id,
        "latest_invoice_id": latest_invoice.get("id") or "",
        "latest_invoice_status": latest_invoice.get("status") or "",
        "latest_payment_intent_status": payment_intent.get("status") or "",
        "latest_charge_id": charge_id,
    }


def refund_latest_subscription_payment(tenant_id: str = "", reason: str = "requested_by_customer") -> tuple[bool, str]:
    """Issue a full refund for the latest paid subscription charge."""
    import requests

    stripe_key = _get_config("STRIPE_SECRET_KEY")
    if not stripe_key:
        return False, "STRIPE_SECRET_KEY not configured"

    live = get_live_stripe_subscription_status(tenant_id)
    if not live:
        return False, "No live Stripe subscription found"
    if live.get("error"):
        return False, live["error"]

    charge_id = live.get("latest_charge_id") or ""
    if not charge_id:
        return False, "No refundable charge found on the latest invoice"

    refund_resp = requests.post(
        "https://api.stripe.com/v1/refunds",
        auth=(stripe_key, ""),
        data={
            "charge": charge_id,
            "reason": reason,
        },
        timeout=10,
    )
    if refund_resp.status_code == 200:
        refund_id = refund_resp.json().get("id") or ""
        return True, refund_id or "Refund issued"

    return False, f"Refund failed: {refund_resp.status_code} {refund_resp.text[:200]}"


def export_all_tenant_data(tenant_id: str = "") -> dict:
    """Export all data belonging to a tenant as a dict of table_name -> rows."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return {}
    sb = get_client()
    export = {}
    for table in _TENANT_TABLES:
        try:
            r = sb.table(table).select("*").eq("tenant_id", tid).execute()
            if r.data:
                export[table] = r.data
        except Exception:
            pass
    return export


def delete_all_tenant_data(tenant_id: str = ""):
    """Permanently delete all data for a tenant across all tables, then remove the tenant itself."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return
    sb = get_client()
    # Delete data tables first (order matters for foreign keys)
    for table in _TENANT_TABLES:
        try:
            sb.table(table).delete().eq("tenant_id", tid).execute()
        except Exception:
            pass
    # Delete user profile and tenant record
    try:
        sb.table("user_profiles").delete().eq("tenant_id", tid).execute()
    except Exception:
        pass
    try:
        sb.table("tenants").delete().eq("id", tid).execute()
    except Exception:
        pass


# ── Error reporting ──────────────────────────────────────────────────────────

def log_error(category: str, message: str, detail: str = "",
              user_email: str = "", severity: str = "error",
              tenant_id: str = ""):
    """Log a structured error to the error_reports table.
    Silently fails if table doesn't exist yet — never raises."""
    tid = tenant_id or get_tenant_id()
    try:
        sb = get_client()
        row = {
            "category":   category[:100],
            "message":    message[:2000],
            "detail":     (detail or "")[:10000],
            "severity":   severity,
        }
        if tid:
            row["tenant_id"] = tid
        if user_email:
            row["user_email"] = user_email[:320]
        sb.table("error_reports").insert(row).execute()
    except Exception:
        # Fallback: print to console so it appears in server logs
        print(f"[ERROR_REPORT] [{severity}] [{category}] {message}")
        if detail:
            print(f"  detail: {detail[:500]}")


def get_error_reports(tenant_id: str = "", limit: int = 100,
                      category: str = "", severity: str = "") -> list[dict]:
    """Fetch recent error reports for the current tenant."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return []
    try:
        sb = get_client()
        q = sb.table("error_reports").select("*").eq("tenant_id", tid)
        if category:
            q = q.eq("category", category)
        if severity:
            q = q.eq("severity", severity)
        q = q.order("created_at", desc=True).limit(limit)
        r = q.execute()
        return r.data or []
    except Exception:
        return []


def clear_error_reports(tenant_id: str = ""):
    """Delete all error reports for the current tenant."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return
    try:
        sb = get_client()
        sb.table("error_reports").delete().eq("tenant_id", tid).execute()
    except Exception:
        pass
