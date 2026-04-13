import streamlit as st

from database import get_all_uph_history, get_coaching_notes, get_employees


def tenant_id() -> str:
    return st.session_state.get("tenant_id", "")


@st.cache_data(ttl=300, show_spinner=False)
def raw_cached_employees(_tid_key: str = ""):
    try:
        result = get_employees()
        return result or []
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def raw_cached_targets(_tid_key: str = "") -> dict:
    try:
        from goals import get_all_targets
        return get_all_targets(_tid_key)
    except Exception:
        return {}


@st.cache_data(ttl=180, show_spinner=False)
def raw_cached_active_flags(_tid_key: str = "") -> dict:
    try:
        from goals import get_active_flags
        return get_active_flags(_tid_key)
    except Exception:
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def raw_cached_uph_history(_tid_key: str = ""):
    try:
        return get_all_uph_history(days=30)
    except Exception:
        return []


@st.cache_data(ttl=180, show_spinner=False)
def raw_cached_all_coaching_notes(_tid_key: str = ""):
    try:
        from database import get_client as _get_sb, _tq

        sb = _get_sb()
        r = _tq(sb.table("coaching_notes").select("emp_id").eq("archived", False)).execute()
        return {row["emp_id"] for row in (r.data or [])}
    except Exception:
        return set()


@st.cache_data(ttl=180, show_spinner=False)
def raw_cached_open_coaching_note_counts(_tid_key: str = "") -> dict:
    try:
        from database import get_client as _get_sb, _tq

        sb = _get_sb()
        r = _tq(sb.table("coaching_notes").select("emp_id").eq("archived", False)).execute()
        counts: dict[str, int] = {}
        for row in (r.data or []):
            emp_id = str(row.get("emp_id") or "").strip()
            if not emp_id:
                continue
            counts[emp_id] = int(counts.get(emp_id, 0) or 0) + 1
        return counts
    except Exception:
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def raw_cached_coaching_notes_for(emp_id: str, _tid_key: str = "") -> list:
    try:
        return get_coaching_notes(emp_id)
    except Exception:
        return []


def cached_employees():
    return raw_cached_employees(tenant_id())


def cached_targets():
    return raw_cached_targets(tenant_id())


def cached_active_flags():
    return raw_cached_active_flags(tenant_id())


def cached_uph_history():
    return raw_cached_uph_history(tenant_id())


def cached_all_coaching_notes():
    return raw_cached_all_coaching_notes(tenant_id())


def cached_open_coaching_note_counts():
    return raw_cached_open_coaching_note_counts(tenant_id())


def cached_coaching_notes_for(emp_id: str):
    return raw_cached_coaching_notes_for(emp_id, tenant_id())


def bust_cache():
    raw_cached_employees.clear()
    raw_cached_targets.clear()
    raw_cached_uph_history.clear()
    raw_cached_all_coaching_notes.clear()
    raw_cached_open_coaching_note_counts.clear()
    raw_cached_active_flags.clear()
    raw_cached_coaching_notes_for.clear()
    st.session_state.pop("_current_plan", None)
