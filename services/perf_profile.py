"""Lightweight structured profiling helpers for targeted hotspot instrumentation.

This module is intentionally small and easy to remove once profiling is complete.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

from services.observability import log_operational_event


def _session_execution_count(counter_key: str) -> int:
    try:
        import streamlit as st

        current = int(st.session_state.get(counter_key, 0) or 0) + 1
        st.session_state[counter_key] = current
        return current
    except Exception:
        return 1


class PerfProfile:
    def __init__(
        self,
        name: str,
        *,
        tenant_id: str = "",
        user_email: str = "",
        context: dict[str, Any] | None = None,
        execution_key: str = "",
    ) -> None:
        self.name = str(name or "perf_profile")
        self.tenant_id = str(tenant_id or "")
        self.user_email = str(user_email or "")
        self.context = dict(context or {})
        self.execution_key = str(execution_key or "")
        self.started_at = time.perf_counter()
        self.metrics: dict[str, Any] = {}
        self.status = "completed"
        self.error_text = ""

        if self.execution_key:
            execution_count = _session_execution_count(self.execution_key)
            self.metrics["execution_count"] = execution_count
            self.metrics["repeated_execution"] = bool(execution_count > 1)

    def increment(self, key: str, amount: int = 1) -> None:
        self.metrics[key] = int(self.metrics.get(key, 0) or 0) + int(amount or 0)

    def set(self, key: str, value: Any) -> None:
        self.metrics[key] = value

    def observe_rows(self, key: str, rows: list[Any] | tuple[Any, ...] | set[Any] | None) -> None:
        self.metrics[key] = len(rows or [])

    def query(self, *, rows: int | None = None, count: int = 1) -> None:
        self.increment("db_query_count_visible", count)
        if rows is not None:
            self.increment("db_rows_visible", int(rows or 0))

    def cache_hit(self, key: str = "cache") -> None:
        self.increment(f"{key}_hits", 1)

    def cache_miss(self, key: str = "cache") -> None:
        self.increment(f"{key}_misses", 1)

    @contextmanager
    def stage(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.metrics[f"stage_{name}_ms"] = int((time.perf_counter() - started) * 1000)

    def fail(self, error: Exception) -> None:
        self.status = "failed"
        self.error_text = str(error or "")

    def _normalized_metrics_for_emit(self) -> dict[str, Any]:
        metrics = dict(self.metrics)
        if self.name != "action_state.lookup_batched":
            return metrics

        legacy_query_count = int(metrics.get("db_query_count_visible", 0) or 0)
        legacy_visible_rows = int(metrics.get("db_rows_visible", 0) or 0)
        legacy_actions_query_ms = int(metrics.get("stage_batched_actions_read_ms", 0) or 0)
        legacy_generic_probe_ms = int(metrics.get("stage_batched_generic_employee_events_probe_ms", 0) or 0)
        legacy_followups_probe_ms = int(metrics.get("stage_shared_followup_probe_ms", 0) or 0)
        legacy_service_work_ms = int(metrics.get("service_work_ms", 0) or 0)

        metrics.setdefault("actions_rows", 0)
        metrics.setdefault("generic_employee_event_rows", 0)
        metrics.setdefault("followup_rows", 0)
        metrics.setdefault("actions_query_ms", legacy_actions_query_ms)
        metrics.setdefault("generic_employee_events_probe_ms", legacy_generic_probe_ms)
        metrics.setdefault("followups_probe_ms", legacy_followups_probe_ms)
        metrics.setdefault("service_work_ms", legacy_service_work_ms)
        metrics.setdefault("perf_emit_overhead_ms", 0)
        metrics.setdefault("total_wall_ms", 0)
        metrics.setdefault("actions_query_skipped", False)
        metrics.setdefault("generic_employee_events_query_skipped", False)
        metrics.setdefault("followups_query_skipped", False)
        metrics.setdefault("query_count", legacy_query_count)
        metrics.setdefault("visible_db_rows", legacy_visible_rows)
        return metrics

    def emit(self) -> None:
        emit_started = time.perf_counter()
        metrics = self._normalized_metrics_for_emit()
        duration_ms = int((emit_started - self.started_at) * 1000)

        if self.name == "action_state.lookup_batched":
            service_work_ms = int(metrics.get("service_work_ms", 0) or 0)
            if service_work_ms <= 0:
                service_work_ms = duration_ms
            metrics["service_work_ms"] = int(max(0, service_work_ms))
            # This makes boundary overhead explicit at the point immediately before log emission.
            metrics["perf_emit_overhead_ms"] = int(max(0, duration_ms - metrics["service_work_ms"]))
            metrics["total_wall_ms"] = int(max(0, duration_ms))

        context = {
            "profile": self.name,
            "duration_ms": duration_ms,
            **self.context,
            **metrics,
        }
        if self.error_text:
            context["error"] = self.error_text
        log_operational_event(
            "perf_profile",
            status=self.status,
            detail=self.name,
            tenant_id=self.tenant_id,
            user_email=self.user_email,
            context=context,
        )


@contextmanager
def profile_block(
    name: str,
    *,
    tenant_id: str = "",
    user_email: str = "",
    context: dict[str, Any] | None = None,
    execution_key: str = "",
):
    profile = PerfProfile(
        name,
        tenant_id=tenant_id,
        user_email=user_email,
        context=context,
        execution_key=execution_key,
    )
    try:
        yield profile
    except Exception as error:
        profile.fail(error)
        raise
    finally:
        profile.emit()