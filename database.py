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


def _normalize_config_value(value: str) -> str:
    """Trim whitespace/quotes so copied secrets still work."""
    out = str(value or "").strip()
    if len(out) >= 2 and out[0] == out[-1] and out[0] in ('"', "'"):
        out = out[1:-1].strip()
    return out.rstrip("/") if out.startswith("http") else out


def _get_config(key: str) -> str:
    """Read from env var, then Streamlit secrets. Raises if not found."""
    val = _normalize_config_value(os.environ.get(key, ""))
    if val:
        return val
    try:
        import streamlit as st
        val = _normalize_config_value(st.secrets.get(key, ""))
        if val:
            return val
    except Exception:
        pass
    return ""


def get_supabase_credentials() -> tuple[str, str]:
    """Return the current Supabase URL/key from env or Streamlit secrets."""
    return _get_config("SUPABASE_URL"), _get_config("SUPABASE_KEY")


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
    url, key = get_supabase_credentials()

    try:
        import streamlit as st
        cached = st.session_state.get("_sb_client")
        if cached is not None:
            # Always re-attach latest session tokens before reusing cached client.
            # Without this, a client created pre-login can stay anonymous and fail
            # INSERT/UPDATE RLS checks even though the UI shows logged in.
            session = st.session_state.get("supabase_session")
            if session and session.get("access_token") and session.get("refresh_token"):
                try:
                    cached.auth.set_session(
                        session["access_token"],
                        session["refresh_token"],
                    )
                except Exception:
                    pass

            # Check if token needs refresh (refresh 5 min before expiry)
            expires_at = st.session_state.get("_sb_token_expires_at", 0)
            if _time.time() > expires_at - 300:
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
        from httpx import Client as HttpxClient, Timeout
        from supabase import create_client
        from supabase.lib.client_options import SyncClientOptions

        options = SyncClientOptions(
            httpx_client=HttpxClient(
                timeout=Timeout(timeout=10.0, connect=5.0),
                verify=True,
                follow_redirects=True,
            )
        )
        client = create_client(url, key, options=options)
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
    """Return the current tenant id.

    Primary source is session_state. If missing, recover from user_profiles using
    the authenticated user id and cache it back into session_state.
    """
    try:
        import streamlit as st
        tid = st.session_state.get("tenant_id", "")
        if tid:
            return tid

        uid = st.session_state.get("user_id", "")
        if not uid:
            return ""

        try:
            sb = get_client()
            resp = sb.table("user_profiles").select("tenant_id").eq("id", uid).limit(1).execute()
            if resp.data:
                tid = (resp.data[0].get("tenant_id") or "").strip()
                if tid:
                    st.session_state["tenant_id"] = tid
                    return tid
        except Exception:
            return ""
        return ""
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


def _first_row(query) -> Optional[dict]:
    try:
        resp = query.limit(1).execute()
        if resp.data:
            return resp.data[0]
    except Exception:
        pass
    return None


def get_tenant(tenant_id: str = "", columns: str = "*") -> Optional[dict]:
    """Compatibility wrapper: delegated to repositories.tenant_repo.get_tenant."""
    from repositories.tenant_repo import get_tenant as _repo_get_tenant

    return _repo_get_tenant(tenant_id=tenant_id, columns=columns)


def set_tenant_stripe_customer_id(stripe_customer_id: str, tenant_id: str = "") -> bool:
    """Compatibility wrapper: delegated to repositories.tenant_repo."""
    from repositories.tenant_repo import set_tenant_stripe_customer_id as _repo_set_stripe_cid

    return _repo_set_stripe_cid(stripe_customer_id=stripe_customer_id, tenant_id=tenant_id)


def _get_tenant_scoped_count(table_name: str, count_column: str, tenant_id: str = "") -> int:
    tid = tenant_id or get_tenant_id()
    if not tid:
        return 0
    try:
        sb = get_client()
        resp = sb.table(table_name).select(count_column, count="exact").eq("tenant_id", tid).execute()
        return int(resp.count or 0)
    except Exception:
        return 0


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
    """Compatibility wrapper: delegated to repositories.employees_repo.get_employees."""
    from repositories.employees_repo import get_employees as _repo_get_employees

    return _repo_get_employees()


def get_employee(emp_id: str) -> dict | None:
    sb = get_client()
    r  = _tq(sb.table("employees").select("*").eq("emp_id", emp_id)).execute()
    return r.data[0] if r.data else None


def get_employee_numeric_id(emp_id: str) -> int | None:
    """Convert text emp_id (e.g. 'EMP009') to numeric employees.id."""
    emp = get_employee(emp_id)
    return emp.get("id") if emp else None


def _get_existing_employee_ids(emp_ids: list[str], tenant_id: str = "") -> set[str]:
    tid = tenant_id or get_tenant_id()
    if not tid or not emp_ids:
        return set()
    try:
        sb = get_client()
        normalized_ids = [str(emp_id).strip() for emp_id in emp_ids if str(emp_id).strip()]
        if not normalized_ids:
            return set()
        resp = sb.table("employees").select("emp_id").eq("tenant_id", tid).in_("emp_id", normalized_ids).execute()
        return {str(row.get("emp_id", "")).strip() for row in (resp.data or []) if str(row.get("emp_id", "")).strip()}
    except Exception:
        return set()


def _enforce_employee_capacity_for_ids(emp_ids: list[str], tenant_id: str = "") -> None:
    tid = tenant_id or get_tenant_id()
    normalized_ids = sorted({str(emp_id).strip() for emp_id in emp_ids if str(emp_id).strip()})
    if not tid or not normalized_ids:
        return

    existing_ids = _get_existing_employee_ids(normalized_ids, tid)
    new_count = len([emp_id for emp_id in normalized_ids if emp_id not in existing_ids])
    if new_count <= 0:
        return

    from services.plan_service import enforce_people_limit

    enforce_people_limit(
        tenant_id=tid,
        current_count=get_employee_count(tid),
        additional_count=new_count,
        limit_type="employee",
    )


def get_team_member_count(tenant_id: str = "") -> int:
    return _get_tenant_scoped_count("user_profiles", "id", tenant_id)


def _get_tenant_id_for_invite_code(invite_code: str) -> str:
    code = str(invite_code or "").strip().lower()
    if not code:
        return ""
    try:
        sb = get_client()
        resp = sb.table("tenants").select("id").eq("invite_code", code).limit(1).execute()
        return str(resp.data[0].get("id") or "") if resp.data else ""
    except Exception:
        return ""


def upsert_employee(emp_id: str, name: str, department: str = "",
                    shift: str = "") -> dict:
    """Insert or update a single employee record."""
    sb       = get_client()
    tid = get_tenant_id()
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
        _enforce_employee_capacity_for_ids([emp_id], tid)
        # Claim the orphaned row for this tenant
        update_data = {
            "name": name, "department": department, "shift": shift, "is_new": False,
            **_tenant_fields(),
        }
        r = sb.table("employees").update(update_data).eq("emp_id", emp_id).execute()
        return r.data[0] if r.data else {}

    _enforce_employee_capacity_for_ids([emp_id], tid)
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
    if not _tf.get("tenant_id"):
        raise RuntimeError(
            "No tenant context found for employee sync. "
            "Please sign out and sign back in, then retry the import."
        )
    _enforce_employee_capacity_for_ids([e.get("emp_id", "") for e in employees], _tf.get("tenant_id", ""))
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
    if not emp_id:
        return
    sb = get_client()

    # uph_history.emp_id references employees.id (bigint), so resolve text employee codes
    # (e.g. E001) to the numeric row id when needed.
    try:
        emp_fk = int(str(emp_id).strip())
    except Exception:
        emp_fk = None
    if emp_fk is None:
        try:
            emp_row = get_employee(str(emp_id).strip())
            if emp_row and emp_row.get("id") is not None:
                emp_fk = int(emp_row.get("id"))
        except Exception:
            emp_fk = None
    if emp_fk is None:
        log_error(
            "uph_history",
            f"Skipping UPH row for unresolved employee id: {emp_id}",
            severity="warning",
        )
        return

    uph = _finite_float(uph)
    units = _finite_float(units)
    hours_worked = _finite_float(hours_worked)
    sb.table("uph_history").upsert({
        "emp_id":       emp_fk,
        "work_date":    work_date,
        "uph":          uph,
        "units":        units,
        "hours_worked": hours_worked,
        "department":   department,
        "order_id":     order_id,
        "tenant_id":    get_tenant_id(),
    }, on_conflict="tenant_id,emp_id,work_date,department").execute()


def batch_store_uph_history(records: list[dict], *, progress_callback=None):
    """Compatibility wrapper: delegated to repositories.import_repo.batch_store_uph_history."""
    from repositories.import_repo import batch_store_uph_history as _repo_batch_store_uph_history

    return _repo_batch_store_uph_history(records, progress_callback=progress_callback)


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
    sb     = get_client()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    # uph_history.emp_id is a bigint FK to employees.id — resolve text code first
    numeric_id = get_employee_numeric_id(emp_id)
    if numeric_id is None:
        return []
    r = _tq(sb.table("uph_history").select("*").eq(
        "emp_id", numeric_id).gte("work_date", cutoff)).order("work_date").execute()
    return r.data or []


def get_all_uph_history(days: int = 30) -> list[dict]:
    """Compatibility wrapper: delegated to repositories.import_repo.get_all_uph_history."""
    from repositories.import_repo import get_all_uph_history as _repo_get_all_uph_history

    return _repo_get_all_uph_history(days=days)


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
    # Convert text emp_id to numeric ID
    numeric_emp_id = get_employee_numeric_id(emp_id)
    if not numeric_emp_id:
        return {}
    
    r  = sb.table("coaching_notes").insert({
        "emp_id": numeric_emp_id, "note": note.strip(), "created_by": created_by,
        **_tenant_fields(),
    }).execute()
    return r.data[0] if r.data else {}


def get_coaching_notes(emp_id: str, include_archived: bool = False) -> list[dict]:
    sb   = get_client()
    # Convert text emp_id to numeric ID
    numeric_emp_id = get_employee_numeric_id(emp_id)
    if not numeric_emp_id:
        return []
    
    r    = _tq(sb.table("coaching_notes").select("*").eq(
        "emp_id", numeric_emp_id)).order("created_at", desc=True).execute()
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
    # Convert text emp_id to numeric ID
    numeric_emp_id = get_employee_numeric_id(emp_id)
    if not numeric_emp_id:
        return
    
    try:
        _tq(sb.table("coaching_notes").update({"archived": True}).eq("emp_id", numeric_emp_id)).execute()
    except Exception:
        # archived column may not exist — fall back to hard delete
        _tq(sb.table("coaching_notes").delete().eq("emp_id", numeric_emp_id)).execute()


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

# ── Shift Plans ──────────────────────────────────────────────────────────────

def save_shift_plan(plan_date: str, shift_start: str, shift_end: str,
                    departments: list, task_baselines: dict, notes: str = "") -> dict:
    """Upsert a daily shift plan for today."""
    sb = get_client()
    tid = get_tenant_id()
    payload = {
        "tenant_id":      tid,
        "plan_date":      plan_date,
        "shift_start":    shift_start,
        "shift_end":      shift_end,
        "departments":    departments,
        "task_baselines": task_baselines,
        "notes":          notes,
        "updated_at":     datetime.utcnow().isoformat() + "Z",
    }
    r = sb.table("shift_plans").upsert(
        payload, on_conflict="tenant_id,plan_date"
    ).execute()
    return r.data[0] if r.data else payload


def get_shift_plan(plan_date: str) -> dict | None:
    """Load a single day's shift plan."""
    sb = get_client()
    r = _tq(sb.table("shift_plans").select("*").eq("plan_date", plan_date)).execute()
    return r.data[0] if r.data else None


def save_shift_checkpoint(plan_date: str, department: str,
                           checkpoint: str, expected: float, actual: float) -> dict:
    """Record an actual vs expected checkpoint reading."""
    sb = get_client()
    r = sb.table("shift_checkpoints").insert({
        "tenant_id":  get_tenant_id(),
        "plan_date":  plan_date,
        "department": department,
        "checkpoint": checkpoint,
        "expected":   expected,
        "actual":     actual,
    }).execute()
    return r.data[0] if r.data else {}


def get_shift_checkpoints(plan_date: str) -> list[dict]:
    """All checkpoint readings for a given date."""
    sb = get_client()
    r = _tq(sb.table("shift_checkpoints").select("*").eq(
        "plan_date", plan_date)).order("recorded_at").execute()
    return r.data or []


# ── Coaching Note Tag helpers ─────────────────────────────────────────────────

def get_all_coaching_notes(days: int = 30) -> list[dict]:
    """All non-archived coaching notes for this tenant within the last N days."""
    from datetime import timedelta
    sb = get_client()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    r = _tq(sb.table("coaching_notes").select(
        "id, emp_id, note, created_by, created_at, issue_type, action_taken, tone, uph_before, uph_after"
    ).eq("archived", False).gte("created_at", cutoff)).order("created_at", desc=True).execute()
    return r.data or []


def update_coaching_note_tags(note_id: str, issue_type: str = "",
                               action_taken: str = "", tone: str = "",
                               uph_before: float | None = None,
                               uph_after: float | None = None):
    """Patch tag columns on an existing coaching note (non-destructive)."""
    sb = get_client()
    payload: dict = {}
    if issue_type:
        payload["issue_type"] = issue_type
    if action_taken:
        payload["action_taken"] = action_taken
    if tone:
        payload["tone"] = tone
    if uph_before is not None:
        payload["uph_before"] = uph_before
    if uph_after is not None:
        payload["uph_after"] = uph_after
    if payload:
        _tq(sb.table("coaching_notes").update(payload).eq("id", note_id)).execute()


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
    """Load goals from tenant_goals table."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return {
            "default_target_uph": 0,
            "dept_targets": {},
            "process_targets": {},
            "employee_target_overrides": {},
            "configured_processes": [],
            "flagged_employees": {},
        }
    try:
        sb = get_client()
        r = sb.table("tenant_goals").select("*").eq("tenant_id", tid).execute()
        if r.data:
            row = r.data[0]
            return {
                "default_target_uph": row.get("default_target_uph") or 0,
                "dept_targets": row.get("dept_targets") or {},
                "process_targets": row.get("process_targets") or {},
                "employee_target_overrides": row.get("employee_target_overrides") or {},
                "configured_processes": row.get("configured_processes") or [],
                "flagged_employees": row.get("flagged_employees") or {},
            }
    except Exception:
        pass
    return {
        "default_target_uph": 0,
        "dept_targets": {},
        "process_targets": {},
        "employee_target_overrides": {},
        "configured_processes": [],
        "flagged_employees": {},
    }


def save_goals_db(data: dict, tenant_id: str = ""):
    """Save goals to tenant_goals table (upsert)."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return
    try:
        sb = get_client()
        sb.table("tenant_goals").upsert({
            "tenant_id": tid,
            "default_target_uph": data.get("default_target_uph", 0),
            "dept_targets": data.get("dept_targets", {}),
            "process_targets": data.get("process_targets", {}),
            "employee_target_overrides": data.get("employee_target_overrides", {}),
            "configured_processes": data.get("configured_processes", []),
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


# ── Coaching Follow-ups (DB-backed) ────────────────────────────────────────

def add_followup_db(emp_id: str, name: str, dept: str, followup_date: str,
                    note_preview: str = "", tenant_id: str = "") -> None:
    """Insert or update a scheduled coaching follow-up."""
    tid = tenant_id or get_tenant_id()
    if not tid or not followup_date:
        return
    try:
        sb = get_client()
        sb.table("coaching_followups").upsert({
            "tenant_id": tid,
            "emp_id": str(emp_id),
            "name": str(name)[:60],
            "dept": str(dept)[:40],
            "followup_date": str(followup_date),
            "note_preview": str(note_preview)[:80],
            "added_on": date.today().isoformat(),
        }, on_conflict="tenant_id,emp_id,followup_date").execute()
    except Exception as e:
        print(f"[Warning] Could not save follow-up to DB: {e}")


def get_followups_db(from_date: str = "", to_date: str = "", tenant_id: str = "") -> list[dict]:
    """Return follow-ups for an inclusive date range."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return []
    from_value = str(from_date or date.today().isoformat())
    to_value = str(to_date or from_value)
    try:
        sb = get_client()
        resp = (
            sb.table("coaching_followups")
            .select("emp_id, name, dept, note_preview, added_on, followup_date")
            .eq("tenant_id", tid)
            .gte("followup_date", from_value)
            .lte("followup_date", to_value)
            .order("followup_date")
            .order("name")
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[Warning] Could not load follow-ups from DB: {e}")
        return []


def remove_followup_db(emp_id: str, followup_date: str, tenant_id: str = "") -> None:
    """Delete a scheduled coaching follow-up."""
    tid = tenant_id or get_tenant_id()
    if not tid or not followup_date:
        return
    try:
        sb = get_client()
        (
            sb.table("coaching_followups")
            .delete()
            .eq("tenant_id", tid)
            .eq("emp_id", str(emp_id))
            .eq("followup_date", str(followup_date))
            .execute()
        )
    except Exception as e:
        print(f"[Warning] Could not remove follow-up from DB: {e}")


# ── Actions (DB-backed) ──────────────────────────────────────────

def log_action_event(
    action_id: str,
    event_type: str,
    employee_id: str,
    performed_by: str = "",
    notes: str = "",
    outcome: str | None = None,
    next_follow_up_at: str | None = None,
    tenant_id: str = "",
) -> dict:
    """Compatibility wrapper: delegated to repositories.action_events_repo."""
    from repositories.action_events_repo import log_action_event as _repo_log_action_event

    return _repo_log_action_event(
        action_id=action_id,
        event_type=event_type,
        employee_id=employee_id,
        performed_by=performed_by,
        notes=notes,
        outcome=outcome,
        next_follow_up_at=next_follow_up_at,
        tenant_id=tenant_id,
    )


def list_action_events(
    action_id: str,
    tenant_id: str = "",
) -> list[dict]:
    """Compatibility wrapper: delegated to repositories.action_events_repo."""
    from repositories.action_events_repo import list_action_events as _repo_list_action_events

    return _repo_list_action_events(action_id=action_id, tenant_id=tenant_id)


def create_action(
    employee_id: str,
    employee_name: str,
    department: str,
    issue_type: str,
    trigger_summary: str,
    action_type: str,
    success_metric: str,
    follow_up_due_at: str,
    note: str = "",
    created_by: str = "",
    baseline_uph: float = 0.0,
    latest_uph: float = 0.0,
    priority: str = "medium",
    tenant_id: str = "",
) -> dict:
    """Compatibility wrapper: delegated to repositories.actions_repo.create_action."""
    from repositories.actions_repo import create_action as _repo_create_action

    return _repo_create_action(
        employee_id=employee_id,
        employee_name=employee_name,
        department=department,
        issue_type=issue_type,
        trigger_summary=trigger_summary,
        action_type=action_type,
        success_metric=success_metric,
        follow_up_due_at=follow_up_due_at,
        note=note,
        created_by=created_by,
        baseline_uph=baseline_uph,
        latest_uph=latest_uph,
        priority=priority,
        tenant_id=tenant_id,
    )


def list_actions(
    tenant_id: str = "",
    statuses: list[str] | None = None,
    employee_id: str = "",
) -> list[dict]:
    """Compatibility wrapper: delegated to repositories.actions_repo.list_actions."""
    from repositories.actions_repo import list_actions as _repo_list_actions

    return _repo_list_actions(tenant_id=tenant_id, statuses=statuses, employee_id=employee_id)


def update_action(action_id: str, updates: dict, tenant_id: str = "") -> dict:
    """Compatibility wrapper: delegated to repositories.actions_repo.update_action."""
    from repositories.actions_repo import update_action as _repo_update_action

    return _repo_update_action(action_id=action_id, updates=updates, tenant_id=tenant_id)


# ── GDPR: data export & account deletion ─────────────────────────────────────

_TENANT_TABLES = [
    "employees", "uph_history", "coaching_notes", "shifts",
    "uploaded_files", "clients", "orders", "order_assignments",
    "unit_submissions", "client_trends",
    "tenant_goals", "tenant_settings", "tenant_email_config", "coaching_followups", "actions", "action_events",
    "subscriptions",
]


# Operational-only reset list used for demo/testing "start fresh" workflows.
# Keep account/team/auth and tenant-level config records intact.
_TENANT_OPERATIONAL_RESET_TABLES = [
    # Derived/precomputed tables first.
    "daily_signals",
    "daily_employee_snapshots",
    "activity_records",
    "operational_exceptions",
    # Action workflow lifecycle.
    "action_events",
    "actions",
    # Legacy workflow and import artifacts.
    "coaching_followups",
    "coaching_notes",
    "uph_history",
    "unit_submissions",
    "order_assignments",
    "orders",
    "client_trends",
    "clients",
    "employees",
    "shifts",
    "uploaded_files",
    # Tenant-scoped diagnostics.
    "error_reports",
]


# ── Subscriptions (Stripe) ─────────────────────────────────────────────────────

PLAN_LIMITS = {
    "starter":  25,
    "pro":      100,
    "business": -1,   # unlimited
    "trial":    10,
}


def _get_live_subscription_fallback(tenant_id: str = "") -> Optional[dict]:
    """Return a synthetic subscription object from Stripe when DB mirror is missing."""
    import requests
    import time as _time

    tid = tenant_id or get_tenant_id()
    if not tid:
        return None

    stripe_key = _get_config("STRIPE_SECRET_KEY")
    if not stripe_key:
        return None

    try:
        import streamlit as st
        _cache_key = f"_live_subscription_fallback_{tid}"
        _ts_key = f"_live_subscription_fallback_ts_{tid}"
        _cached = st.session_state.get(_cache_key)
        _cached_ts = float(st.session_state.get(_ts_key, 0) or 0)
        if _cached and (_time.time() - _cached_ts) < 60:
            return _cached
    except Exception:
        st = None

    cust_id = ""
    tenant = get_tenant(tid, columns="stripe_customer_id") or {}
    cust_id = str(tenant.get("stripe_customer_id") or "").strip()

    if not cust_id:
        try:
            c_resp = requests.get(
                "https://api.stripe.com/v1/customers",
                auth=(stripe_key, ""),
                params={"limit": 100},
                timeout=10,
            )
            if c_resp.status_code == 200:
                for _c in c_resp.json().get("data", []):
                    _meta_tid = ((_c.get("metadata") or {}).get("tenant_id") or "").strip()
                    if _meta_tid == tid:
                        cust_id = (_c.get("id") or "").strip()
                        break
        except Exception:
            cust_id = ""

    # Fallback through recent checkout sessions. This is safer than matching by
    # email because the session carries tenant_id metadata from our app.
    if not cust_id:
        try:
            cs_resp = requests.get(
                "https://api.stripe.com/v1/checkout/sessions",
                auth=(stripe_key, ""),
                params={"limit": 100},
                timeout=10,
            )
            if cs_resp.status_code == 200:
                for _s in cs_resp.json().get("data", []):
                    _meta = _s.get("metadata") or {}
                    _tid = (_meta.get("tenant_id") or "").strip()
                    if _tid == tid:
                        cust_id = ((_s.get("customer") or "").strip())
                        if cust_id:
                            break
        except Exception:
            cust_id = ""

    if not cust_id:
        return None

    try:
        sub_resp = requests.get(
            "https://api.stripe.com/v1/subscriptions",
            auth=(stripe_key, ""),
            params={"customer": cust_id, "status": "all", "limit": 10},
            timeout=10,
        )
        if sub_resp.status_code != 200:
            return None
        subs = sub_resp.json().get("data", [])
    except Exception:
        return None

    if not subs:
        return None

    _preferred = ["active", "trialing", "past_due", "unpaid", "incomplete"]
    subs_sorted = sorted(
        subs,
        key=lambda s: (
            _preferred.index(s.get("status")) if s.get("status") in _preferred else 999,
            -(s.get("created") or 0),
        ),
    )
    stripe_sub = subs_sorted[0]

    plan = ""
    try:
        price_obj = stripe_sub["items"]["data"][0]["price"]
        price_meta = price_obj.get("metadata", {})
        plan = (price_meta.get("plan", "") or "").lower().strip()
    except Exception:
        plan = ""

    if not plan or plan not in PLAN_LIMITS:
        try:
            _price_id = stripe_sub["items"]["data"][0]["price"]["id"]
            plan = _resolve_plan_from_price_id(_price_id)
        except Exception:
            plan = "starter"

    limit = PLAN_LIMITS.get(plan or "starter", 25)

    def _iso_from_ts(_ts):
        if not _ts:
            return None
        try:
            return datetime.fromtimestamp(int(_ts)).isoformat()
        except Exception:
            return None

    out = {
        "tenant_id": tid,
        "stripe_customer_id": cust_id,
        "stripe_subscription_id": stripe_sub.get("id", ""),
        "plan": plan or "starter",
        "status": stripe_sub.get("status", ""),
        "employee_limit": limit,
        "current_period_start": _iso_from_ts(
            stripe_sub.get("current_period_start") or ((stripe_sub.get("items") or {}).get("data") or [{}])[0].get("current_period_start")
        ),
        "current_period_end": _iso_from_ts(
            stripe_sub.get("current_period_end") or ((stripe_sub.get("items") or {}).get("data") or [{}])[0].get("current_period_end")
        ),
        "cancel_at_period_end": bool(stripe_sub.get("cancel_at_period_end")),
        "_source": "stripe_fallback",
    }

    try:
        st.session_state[_cache_key] = out
        st.session_state[_ts_key] = _time.time()
    except Exception:
        pass
    return out


def get_subscription(
    tenant_id: str = "",
    columns: str = "*",
    allow_live_fallback: bool = True,
) -> Optional[dict]:
    """Compatibility wrapper: delegated to repositories.billing_repo.get_subscription."""
    from repositories.billing_repo import get_subscription as _repo_get_subscription

    return _repo_get_subscription(
        tenant_id=tenant_id,
        columns=columns,
        allow_live_fallback=allow_live_fallback,
    )


def update_subscription_state(updates: dict, tenant_id: str = "") -> bool:
    """Compatibility wrapper: delegated to repositories.billing_repo.update_subscription_state."""
    from repositories.billing_repo import update_subscription_state as _repo_update_subscription_state

    return _repo_update_subscription_state(updates=updates, tenant_id=tenant_id)


def has_active_subscription(tenant_id: str = "") -> bool:
    """Check if the current tenant has an active paid subscription."""
    sub = get_subscription(tenant_id)
    if not sub:
        return False
    status = sub.get("status")
    period_end = sub.get("current_period_end")
    # past_due: keep access for 48 h after period end so the user has time to fix
    # their payment before being hard-locked out. The subscription page renders
    # a payment-update prompt for this status.
    if status == "past_due":
        if period_end:
            try:
                from datetime import timezone, timedelta
                pe = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) <= (pe + timedelta(hours=48)):
                    return True
            except Exception:
                pass
        return False
    if status not in ("active", "trialing"):
        return False
    # Safety net: if the DB still says active but the period ended >48 h ago,
    # treat as expired. The webhook should have updated status already, but
    # this prevents stale access if webhook delivery fails.
    if period_end:
        try:
            from datetime import timezone, timedelta
            pe = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > (pe + timedelta(hours=48)):
                return False
        except Exception:
            pass
    return True


def get_employee_limit(tenant_id: str = "") -> int:
    """Return the employee limit for the current plan. 0 if no sub, -1 if unlimited."""
    sub = get_subscription(tenant_id)
    if not sub or sub.get("status") not in ("active", "trialing"):
        return 0
    limit = sub.get("employee_limit")
    if limit is None or limit == 0:
        # DB value is missing or was never written correctly — derive from plan name.
        plan = str(sub.get("plan") or "").lower()
        limit = PLAN_LIMITS.get(plan, 25)
    return limit


def get_employee_count(tenant_id: str = "") -> int:
    """Compatibility wrapper: delegated to repositories.employees_repo.get_employee_count."""
    from repositories.employees_repo import get_employee_count as _repo_get_employee_count

    return _repo_get_employee_count(tenant_id=tenant_id)


def can_add_employees(count: int = 1, tenant_id: str = "") -> bool:
    """Check if adding `count` employees would exceed the plan limit."""
    from services.plan_service import evaluate_people_limit

    tid = tenant_id or get_tenant_id()
    result = evaluate_people_limit(
        tenant_id=tid,
        current_count=get_employee_count(tid),
        additional_count=count,
        limit_type="employee",
    )
    return bool(result.get("allowed"))


def create_stripe_checkout_url(price_id: str, success_url: str, cancel_url: str,
                                tenant_id: str = "", user_id: str = "", user_email: str = "") -> tuple:
    """Create a Stripe Checkout Session. Returns (url, error_msg)."""
    import requests
    stripe_key = _get_config("STRIPE_SECRET_KEY")
    if not stripe_key:
        return None, "STRIPE_SECRET_KEY not configured"

    tid = tenant_id or get_tenant_id()
    if not tid:
        return None, "No tenant_id found"

    user_id = str(user_id or "").strip()

    # Guard: block double-subscription. If already in any live status, block checkout.
    existing_sub = get_subscription(tid)
    if existing_sub and existing_sub.get("status") in ("active", "trialing", "past_due", "unpaid", "incomplete"):
        return None, f"subscription_status_block:{existing_sub.get('status')}"

    # Get or create Stripe customer
    tenant = get_tenant(tid, columns="stripe_customer_id, name")
    if tenant is None:
        return None, "Tenant lookup failed"
    stripe_cid = tenant.get("stripe_customer_id")

    if not stripe_cid:
        # Create Stripe customer
        email = str(user_email or "").strip()
        cust_resp = requests.post(
            "https://api.stripe.com/v1/customers",
            auth=(stripe_key, ""),
            data={"email": email, "metadata[tenant_id]": tid},
            timeout=10,
        )
        if cust_resp.status_code == 200:
            stripe_cid = cust_resp.json().get("id")
            set_tenant_stripe_customer_id(stripe_cid, tid)
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
            "client_reference_id": user_id or tid,
            "metadata[tenant_id]": tid,
            "metadata[user_id]": user_id,
            "subscription_data[metadata][tenant_id]": tid,
            "subscription_data[metadata][user_id]": user_id,
        },
        timeout=10,
    )
    if checkout_resp.status_code == 200:
        return checkout_resp.json().get("url"), None
    return None, f"Checkout creation failed: {checkout_resp.status_code} {checkout_resp.text[:200]}"


def modify_subscription(new_price_id: str, tenant_id: str = "") -> tuple:
    """Change an active subscription via Stripe API.

    Upgrade behavior:
        - Immediate plan change
        - Prorated charge applied immediately

    Downgrade behavior:
        - Stripe subscription is updated with no proration
        - Access remains on current plan until period end
        - Pending downgrade is stored in DB (pending_plan/pending_change_at)

    A tenant cannot submit another plan change while a pending downgrade exists.
    Returns (success: bool, error_msg: str | None).
    """
    import requests
    stripe_key = _get_config("STRIPE_SECRET_KEY")
    if not stripe_key:
        return False, "Stripe not configured"

    tid = tenant_id or get_tenant_id()
    if not tid:
        return False, "No tenant_id"
    if not new_price_id:
        return False, "No price_id provided"

    sub_row = get_subscription(
        tid,
        columns="stripe_subscription_id, plan, pending_plan, pending_change_at",
        allow_live_fallback=False,
    )
    if sub_row is None:
        return False, "Could not read subscription"
    stripe_sub_id = sub_row.get("stripe_subscription_id")

    if not stripe_sub_id:
        return False, "No active subscription found"

    if (sub_row.get("pending_plan") or "").strip():
        return False, "A plan change is already pending for period end. Wait until it takes effect before changing again."

    # Fetch current subscription to get item ID and current price
    sub_get = requests.get(
        f"https://api.stripe.com/v1/subscriptions/{stripe_sub_id}",
        auth=(stripe_key, ""),
        timeout=10,
    )
    if sub_get.status_code != 200:
        return False, f"Stripe error fetching subscription: {sub_get.text[:200]}"

    sub_obj = sub_get.json()
    items = (sub_obj.get("items") or {}).get("data") or []
    if not items:
        return False, "No subscription items found"

    sub_item_id = items[0].get("id", "")
    current_price_id = items[0].get("price", {}).get("id", "")

    if current_price_id == new_price_id:
        return False, "Already on this plan"

    # Determine direction to control billing behavior
    _plan_order = {"starter": 1, "pro": 2, "business": 3}
    _price_to_plan = _price_id_to_plan_map()
    _current_plan = (_price_to_plan.get(current_price_id, "") or sub_row.get("plan") or "starter").lower()
    _target_plan = (_price_to_plan.get(new_price_id, "") or "").lower()
    if not _target_plan:
        return False, "Target plan is not configured in Stripe price mapping"

    _cur_rank = _plan_order.get(_current_plan, 1)
    _new_rank = _plan_order.get(_target_plan, 1)
    is_upgrade = _new_rank > _cur_rank

    _request_data = {
        "items[0][id]": sub_item_id,
        "items[0][price]": new_price_id,
    }
    _period_end_iso = None
    _period_end_ts = sub_obj.get("current_period_end") or items[0].get("current_period_end")
    try:
        if _period_end_ts:
            _period_end_iso = datetime.utcfromtimestamp(int(_period_end_ts)).isoformat() + "Z"
    except Exception:
        _period_end_iso = None

    if is_upgrade:
        # Immediate prorated charge for upgrades.
        _request_data["proration_behavior"] = "create_prorations"
        _request_data["metadata[pending_plan]"] = ""
        _request_data["metadata[pending_change_at]"] = ""
    else:
        # Downgrade billing changes now, but app access is deferred via pending_plan.
        if not _period_end_iso:
            return False, "Could not determine the current billing period end for this downgrade."
        _request_data["proration_behavior"] = "none"
        _request_data["billing_cycle_anchor"] = "unchanged"
        _request_data["metadata[pending_plan]"] = _target_plan
        _request_data["metadata[pending_change_at]"] = _period_end_iso

    modify_resp = requests.post(
        f"https://api.stripe.com/v1/subscriptions/{stripe_sub_id}",
        auth=(stripe_key, ""),
        data=_request_data,
        timeout=15,
    )

    if modify_resp.status_code == 200:
        if is_upgrade:
            update_subscription_state(
                {
                    "pending_plan": None,
                    "pending_change_at": None,
                },
                tid,
            )
        else:
            update_subscription_state(
                {
                    "pending_plan": _target_plan,
                    "pending_change_at": _period_end_iso,
                },
                tid,
            )
        return True, None

    return False, f"Stripe modify failed ({modify_resp.status_code}): {modify_resp.text[:200]}"


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
    tenant = get_tenant(tid, columns="stripe_customer_id")
    stripe_cid = tenant.get("stripe_customer_id") if tenant else None

    if not stripe_cid:
        return None

    sub_row = get_subscription(tid, columns="stripe_subscription_id", allow_live_fallback=False) or {}
    stripe_sub_id = sub_row.get("stripe_subscription_id") or ""

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
    price_map = _price_id_to_plan_map()
    return price_map.get(price_id, "starter")


def _price_id_to_plan_map() -> dict[str, str]:
    """Return configured Stripe price id -> plan mapping."""
    return {
        _get_config("STRIPE_PRICE_STARTER") or "": "starter",
        _get_config("STRIPE_PRICE_PRO") or "": "pro",
        _get_config("STRIPE_PRICE_BUSINESS") or "": "business",
    }


def _resolve_plan_from_price_id_live(price_id: str, stripe_key: str) -> str:
    """Resolve plan key from Stripe price id using local config, then Stripe metadata.

    This avoids mislabeling plan changes when env price mappings are stale.
    """
    if not price_id:
        return ""

    # 1) Fast path: local config mapping.
    starter_id = _get_config("STRIPE_PRICE_STARTER") or ""
    pro_id = _get_config("STRIPE_PRICE_PRO") or ""
    business_id = _get_config("STRIPE_PRICE_BUSINESS") or ""
    if price_id == starter_id:
        return "starter"
    if price_id == pro_id:
        return "pro"
    if price_id == business_id:
        return "business"

    # 2) Stripe lookup for metadata/lookup_key hints.
    try:
        import requests

        p_resp = requests.get(
            f"https://api.stripe.com/v1/prices/{price_id}",
            auth=(stripe_key, ""),
            params={"expand[]": ["product"]},
            timeout=10,
        )
        if p_resp.status_code == 200:
            p_obj = p_resp.json() or {}
            meta_plan = str(((p_obj.get("metadata") or {}).get("plan") or "")).strip().lower()
            if meta_plan in PLAN_LIMITS:
                return meta_plan

            lookup_key = str(p_obj.get("lookup_key") or "").strip().lower()
            for key in ("starter", "pro", "business"):
                if key in lookup_key:
                    return key

            product_obj = p_obj.get("product") or {}
            if isinstance(product_obj, dict):
                prod_name = str(product_obj.get("name") or "").strip().lower()
                for key in ("starter", "pro", "business"):
                    if key in prod_name:
                        return key
    except Exception:
        pass

    return ""


def get_live_stripe_subscription_status(tenant_id: str = "") -> Optional[dict]:
    """Fetch live Stripe subscription details, including pending plan changes."""
    import requests

    stripe_key = _get_config("STRIPE_SECRET_KEY")
    if not stripe_key:
        return None

    tid = tenant_id or get_tenant_id()
    if not tid:
        return None

    row = get_subscription(
        tid,
        columns="stripe_customer_id, stripe_subscription_id, plan, status, employee_limit, current_period_end, pending_plan, pending_change_at",
        allow_live_fallback=False,
    ) or {}
    tenant = get_tenant(tid, columns="stripe_customer_id") or {}

    stripe_cid = row.get("stripe_customer_id") or tenant.get("stripe_customer_id") or ""
    stripe_sub_id_db = row.get("stripe_subscription_id") or ""
    if not stripe_sub_id_db and not stripe_cid:
        return None

    # Prefer resolving the current subscription by customer to avoid stale DB
    # subscription ids masking pending updates.
    sub_obj = None
    stripe_sub_id = stripe_sub_id_db
    debug_candidates = []
    try:
        if stripe_cid:
            list_resp = requests.get(
                "https://api.stripe.com/v1/subscriptions",
                auth=(stripe_key, ""),
                params={
                    "customer": stripe_cid,
                    "status": "all",
                    "limit": 20,
                    "expand[]": [
                        "data.items.data.price",
                        "data.pending_update.subscription_items",
                        "data.schedule.phases.items.price",
                    ],
                },
                timeout=10,
            )
            if list_resp.status_code == 200:
                subs = list_resp.json().get("data", []) or []
                if subs:
                    debug_candidates = [
                        {
                            "id": s.get("id") or "",
                            "status": s.get("status") or "",
                            "created": s.get("created") or 0,
                            "cancel_at_period_end": bool(s.get("cancel_at_period_end")),
                            "has_pending_update": bool(s.get("pending_update")),
                        }
                        for s in subs[:10]
                    ]
                    preferred = ["active", "trialing", "past_due", "unpaid", "incomplete"]
                    subs_sorted = sorted(
                        subs,
                        key=lambda s: (
                            preferred.index(s.get("status")) if s.get("status") in preferred else 999,
                            -(s.get("created") or 0),
                        ),
                    )
                    if stripe_sub_id_db:
                        sub_obj = next((s for s in subs_sorted if (s.get("id") or "") == stripe_sub_id_db), None)
                    if sub_obj is None:
                        sub_obj = subs_sorted[0]
                    stripe_sub_id = sub_obj.get("id") or stripe_sub_id_db
    except Exception:
        sub_obj = None

    # Fallback to direct id lookup if list path didn't produce a subscription.
    if sub_obj is None and stripe_sub_id:
        sub_resp = requests.get(
            f"https://api.stripe.com/v1/subscriptions/{stripe_sub_id}",
            auth=(stripe_key, ""),
            params={
                "expand[]": [
                    "items.data.price",
                    "pending_update.subscription_items",
                    "schedule.phases.items.price",
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

    if sub_obj is None:
        return None
    current_item = ((sub_obj.get("items") or {}).get("data") or [{}])[0]
    current_price = current_item.get("price") or {}
    current_price_id = current_price.get("id") or ""
    current_plan = (
        (sub_obj.get("metadata") or {}).get("plan")
        or (current_price.get("metadata") or {}).get("plan")
        or _resolve_plan_from_price_id_live(current_price_id, stripe_key)
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
    pending_plan = _resolve_plan_from_price_id_live(pending_price_id, stripe_key) if pending_price_id else ""

    # Stripe may represent end-of-period plan changes via subscription schedule
    # instead of pending_update depending on portal/account configuration.
    schedule_obj = sub_obj.get("schedule")
    schedule_pending_plan = ""
    schedule_change_at_ts = None
    schedule_debug_rows = []
    try:
        # If schedule wasn't expanded into an object, fetch it explicitly.
        if isinstance(schedule_obj, str) and schedule_obj:
            sched_resp = requests.get(
                f"https://api.stripe.com/v1/subscription_schedules/{schedule_obj}",
                auth=(stripe_key, ""),
                params={"expand[]": ["phases.items.price"]},
                timeout=10,
            )
            if sched_resp.status_code == 200:
                schedule_obj = sched_resp.json()

        # If subscription has no schedule reference, look up schedules by customer
        # and locate the one bound to this subscription.
        _has_schedule_phases = bool(isinstance(schedule_obj, dict) and (schedule_obj.get("phases") or []))
        if (not _has_schedule_phases) and stripe_cid:
            sched_list = requests.get(
                "https://api.stripe.com/v1/subscription_schedules",
                auth=(stripe_key, ""),
                params={"customer": stripe_cid, "limit": 20, "expand[]": ["data.phases.items.price"]},
                timeout=10,
            )
            if sched_list.status_code == 200:
                _fallback_sched = None
                _sched_rows = (sched_list.json().get("data") or [])
                schedule_debug_rows = [
                    {
                        "id": _s.get("id") or "",
                        "status": _s.get("status") or "",
                        "subscription": (_s.get("subscription", {}) if isinstance(_s.get("subscription"), dict) else _s.get("subscription")) or "",
                        "current_phase_start": (_s.get("current_phase") or {}).get("start_date"),
                        "current_phase_end": (_s.get("current_phase") or {}).get("end_date"),
                        "phase_count": len(_s.get("phases") or []),
                    }
                    for _s in _sched_rows[:20]
                ]
                for _s in _sched_rows:
                    _sub_ref = _s.get("subscription")
                    _sub_id = _sub_ref.get("id") if isinstance(_sub_ref, dict) else _sub_ref
                    if str(_sub_id or "") == stripe_sub_id:
                        schedule_obj = _s
                        break
                    # Some portal-generated schedules are customer-scoped and may
                    # not include a direct subscription reference yet. Keep a
                    # best-effort fallback candidate with a future phase.
                    if _fallback_sched is None and str((_s.get("status") or "")).lower() in ("not_started", "active"):
                        _phases = _s.get("phases") or []
                        _has_future = any(
                            (ph.get("start_date") and int(ph.get("start_date")) > int(time.time()))
                            for ph in _phases
                        )
                        if _has_future:
                            _fallback_sched = _s
                if (not isinstance(schedule_obj, dict) or not (schedule_obj.get("phases") or [])) and _fallback_sched is not None:
                    schedule_obj = _fallback_sched

        # Additional fallback: query schedules by subscription id directly.
        if (not isinstance(schedule_obj, dict) or not (schedule_obj.get("phases") or [])) and stripe_sub_id:
            sched_by_sub = requests.get(
                "https://api.stripe.com/v1/subscription_schedules",
                auth=(stripe_key, ""),
                params={"subscription": stripe_sub_id, "limit": 20, "expand[]": ["data.phases.items.price"]},
                timeout=10,
            )
            if sched_by_sub.status_code == 200:
                _sub_rows = (sched_by_sub.json().get("data") or [])
                if _sub_rows:
                    if not schedule_debug_rows:
                        schedule_debug_rows = [
                            {
                                "id": _s.get("id") or "",
                                "status": _s.get("status") or "",
                                "subscription": (_s.get("subscription", {}) if isinstance(_s.get("subscription"), dict) else _s.get("subscription")) or "",
                                "current_phase_start": (_s.get("current_phase") or {}).get("start_date"),
                                "current_phase_end": (_s.get("current_phase") or {}).get("end_date"),
                                "phase_count": len(_s.get("phases") or []),
                            }
                            for _s in _sub_rows[:20]
                        ]
                    if not isinstance(schedule_obj, dict) or not (schedule_obj.get("phases") or []):
                        schedule_obj = _sub_rows[0]

        if isinstance(schedule_obj, dict):
            phases = schedule_obj.get("phases") or []
            if phases:
                now_ts = int(time.time())
                next_phase = None
                for ph in phases:
                    start_ts = ph.get("start_date")
                    if start_ts and int(start_ts) > now_ts:
                        next_phase = ph
                        break
                if next_phase is not None:
                    phase_items = next_phase.get("items") or []
                    if phase_items:
                        phase_price = phase_items[0].get("price")
                        if isinstance(phase_price, dict):
                            phase_price_id = phase_price.get("id") or ""
                        else:
                            phase_price_id = str(phase_price or "")
                        if phase_price_id:
                            schedule_pending_plan = _resolve_plan_from_price_id_live(phase_price_id, stripe_key) or _resolve_plan_from_price_id(phase_price_id)
                            schedule_change_at_ts = next_phase.get("start_date")
    except Exception:
        schedule_pending_plan = ""
        schedule_change_at_ts = None

    if not pending_plan and schedule_pending_plan:
        pending_plan = schedule_pending_plan

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
        "stripe_subscription_id_db": stripe_sub_id_db,
        "debug_subscription_candidates": debug_candidates,
        "status": sub_obj.get("status") or row.get("status") or "",
        "current_plan": current_plan,
        "current_price_id": current_price_id,
        "current_period_end": sub_obj.get("current_period_end"),
        "cancel_at_period_end": bool(sub_obj.get("cancel_at_period_end")),
        "db_plan": row.get("plan") or "",
        "db_status": row.get("status") or "",
        "db_employee_limit": row.get("employee_limit"),
        "db_current_period_end": row.get("current_period_end") or "",
        "db_pending_plan": row.get("pending_plan") or "",
        "db_pending_change_at": row.get("pending_change_at") or "",
        "has_pending_update": bool(pending_update) or bool(schedule_pending_plan),
        "pending_plan": pending_plan,
        "pending_price_id": pending_price_id,
        "schedule_pending_plan": schedule_pending_plan,
        "schedule_pending_change_at_ts": schedule_change_at_ts,
        "debug_schedule_rows": schedule_debug_rows,
        "pending_change_at_ts": schedule_change_at_ts,
        "pending_change_source": "pending_update" if pending_update else ("schedule" if schedule_pending_plan else ""),
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


def reset_tenant_operational_data(tenant_id: str = "") -> dict:
    """Delete tenant operational data while preserving account/team/auth records.

    Preserved by design:
      - tenants row
      - user_profiles
      - invite/team/auth records
      - tenant_goals / tenant_settings / tenant_email_config / subscriptions
    """
    tid = str(tenant_id or get_tenant_id() or "").strip()
    if not tid:
        return {"tenant_id": "", "attempted_tables": [], "errors": []}

    sb = get_client()
    errors: list[dict] = []
    for table in _TENANT_OPERATIONAL_RESET_TABLES:
        try:
            sb.table(table).delete().eq("tenant_id", tid).execute()
        except Exception as exc:
            errors.append({"table": table, "error": str(exc)})

    return {
        "tenant_id": tid,
        "attempted_tables": list(_TENANT_OPERATIONAL_RESET_TABLES),
        "errors": errors,
    }


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


# ── Team / Invite System ───────────────────────────────────────────────────────

def get_invite_code(tenant_id: str = "") -> str:
    """Return the invite code for this tenant. Creates one if missing."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return ""
    try:
        sb = get_client()
        tenant = get_tenant(tid, columns="invite_code") or {}
        code = str(tenant.get("invite_code") or "")
        if not code:
            # Generate via RPC
            r2 = sb.rpc("regenerate_invite_code", {"p_tenant_id": tid}).execute()
            code = r2.data or ""
        return code
    except Exception:
        return ""


def regenerate_invite_code(tenant_id: str = "") -> str:
    """Rotate the tenant's invite code and return the new one."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return ""
    try:
        sb = get_client()
        r = sb.rpc("regenerate_invite_code", {"p_tenant_id": tid}).execute()
        return r.data or ""
    except Exception:
        return ""


def get_team_members(tenant_id: str = "") -> list[dict]:
    """Return all user_profiles for this tenant."""
    tid = tenant_id or get_tenant_id()
    if not tid:
        return []
    try:
        sb = get_client()
        r = sb.table("user_profiles").select("id, name, role, created_at").eq("tenant_id", tid).order("created_at").execute()
        return r.data or []
    except Exception:
        return []


def remove_team_member(user_id: str, tenant_id: str = "") -> bool:
    """Remove a user from this tenant (deletes their user_profile row).
    Returns True on success."""
    tid = tenant_id or get_tenant_id()
    if not tid or not user_id:
        return False
    try:
        sb = get_client()
        sb.table("user_profiles").delete().eq("id", user_id).eq("tenant_id", tid).execute()
        return True
    except Exception:
        return False


def join_tenant_by_invite(user_id: str, invite_code: str, user_name: str = "") -> str:
    """Join an existing tenant via invite code. Returns tenant_id on success, '' on failure."""
    if not user_id or not invite_code:
        return ""
    try:
        tid = _get_tenant_id_for_invite_code(invite_code)
        if not tid:
            return ""

        from services.plan_service import enforce_people_limit

        enforce_people_limit(
            tenant_id=tid,
            current_count=get_team_member_count(tid),
            additional_count=1,
            limit_type="invite",
        )

        sb = get_client()
        r = sb.rpc("join_tenant_by_invite", {
            "p_user_id":     user_id,
            "p_invite_code": invite_code.strip().lower(),
            "p_user_name":   user_name,
        }).execute()
        return str(r.data) if r.data else ""
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def set_member_role(user_id: str, role: str, tenant_id: str = "") -> bool:
    """Change a team member's role ('admin' or 'member')."""
    tid = tenant_id or get_tenant_id()
    if not tid or not user_id or role not in ("admin", "member"):
        return False
    try:
        sb = get_client()
        sb.table("user_profiles").update({"role": role}).eq("id", user_id).eq("tenant_id", tid).execute()
        return True
    except Exception:
        return False


def get_my_role(tenant_id: str = "") -> str:
    """Return 'admin', 'member', or '' for the current user in this tenant."""
    tid = tenant_id or get_tenant_id()
    uid = get_user_id()
    if not tid or not uid:
        return ""
    try:
        sb = get_client()
        r = sb.table("user_profiles").select("role").eq("id", uid).eq("tenant_id", tid).execute()
        return (r.data[0].get("role") or "member") if r.data else ""
    except Exception:
        return ""
