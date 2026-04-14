from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from core.runtime import st


ONBOARDING_QUERY_PARAM = "onboarding"
ONBOARDING_CORRELATION_QUERY_PARAM = "onboarding_id"
SAMPLE_DATA_POST_AUTH_INTENT = "sample"
_ONBOARDING_CORRELATION_SESSION_KEY = "_onboarding_correlation_id"


def _normalize_post_auth_intent(intent: str) -> str:
    normalized = str(intent or "").strip().lower()
    if normalized in {"sample", "sample_data"}:
        return SAMPLE_DATA_POST_AUTH_INTENT
    return ""


def _normalize_onboarding_correlation_id(correlation_id: str) -> str:
    normalized = str(correlation_id or "").strip().lower()
    if not normalized:
        return ""
    allowed = {"-"}
    cleaned = "".join(ch for ch in normalized if ch.isalnum() or ch in allowed)
    return cleaned[:64]


def get_onboarding_correlation_id() -> str:
    query_id = _normalize_onboarding_correlation_id(st.query_params.get(ONBOARDING_CORRELATION_QUERY_PARAM, ""))
    if query_id:
        st.session_state[_ONBOARDING_CORRELATION_SESSION_KEY] = query_id
        return query_id

    session_id = _normalize_onboarding_correlation_id(st.session_state.get(_ONBOARDING_CORRELATION_SESSION_KEY, ""))
    if session_id:
        try:
            st.query_params[ONBOARDING_CORRELATION_QUERY_PARAM] = session_id
        except Exception:
            pass
    return session_id


def persist_onboarding_correlation_id(correlation_id: str) -> str:
    normalized = _normalize_onboarding_correlation_id(correlation_id)
    if not normalized:
        clear_onboarding_correlation_id()
        return ""

    st.session_state[_ONBOARDING_CORRELATION_SESSION_KEY] = normalized
    try:
        st.query_params[ONBOARDING_CORRELATION_QUERY_PARAM] = normalized
    except Exception:
        pass
    return normalized


def begin_onboarding_correlation_id() -> str:
    return persist_onboarding_correlation_id(str(uuid4()))


def ensure_onboarding_correlation_id() -> str:
    current = get_onboarding_correlation_id()
    if current:
        return current
    return begin_onboarding_correlation_id()


def clear_onboarding_correlation_id() -> None:
    st.session_state.pop(_ONBOARDING_CORRELATION_SESSION_KEY, None)
    try:
        del st.query_params[ONBOARDING_CORRELATION_QUERY_PARAM]
    except Exception:
        pass


def build_onboarding_event_context(
    context: dict | None = None,
    *,
    correlation_id: str | None = None,
) -> dict:
    merged = dict(context or {})
    normalized = _normalize_onboarding_correlation_id(correlation_id or "") or get_onboarding_correlation_id()
    if normalized:
        merged["onboarding_correlation_id"] = normalized
    return merged


def get_post_auth_intent() -> str:
    get_onboarding_correlation_id()
    query_intent = _normalize_post_auth_intent(st.query_params.get(ONBOARDING_QUERY_PARAM, ""))
    if query_intent:
        return query_intent
    return _normalize_post_auth_intent(st.session_state.get("_post_auth_intent", ""))


def persist_post_auth_intent(intent: str, *, correlation_id: str | None = None) -> None:
    normalized = _normalize_post_auth_intent(intent)
    if not normalized:
        clear_post_auth_intent()
        return

    if correlation_id:
        persist_onboarding_correlation_id(correlation_id)

    st.session_state["_post_auth_intent"] = normalized
    try:
        st.query_params[ONBOARDING_QUERY_PARAM] = normalized
    except Exception:
        pass


def queue_sample_data_post_auth_intent(*, correlation_id: str | None = None) -> None:
    persist_post_auth_intent(SAMPLE_DATA_POST_AUTH_INTENT, correlation_id=correlation_id)


def clear_post_auth_intent() -> None:
    st.session_state.pop("_post_auth_intent", None)
    try:
        del st.query_params[ONBOARDING_QUERY_PARAM]
    except Exception:
        pass


def attach_post_auth_intent(url: str) -> str:
    normalized = get_post_auth_intent()
    correlation_id = get_onboarding_correlation_id()
    if not normalized and not correlation_id:
        return url

    parsed = urlsplit(str(url or ""))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if normalized:
        query[ONBOARDING_QUERY_PARAM] = normalized
    if correlation_id:
        query[ONBOARDING_CORRELATION_QUERY_PARAM] = correlation_id
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )