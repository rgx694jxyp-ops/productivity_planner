"""Target resolution and process normalization for lightweight performance standards."""

from __future__ import annotations

from typing import Any


DEFAULT_PROCESS_DEFINITIONS: list[dict[str, Any]] = [
    {"name": "Picking", "aliases": ["pick", "picker", "order picking", "picking lane"]},
    {"name": "Packing", "aliases": ["pack", "packer", "pack out", "packing lane"]},
    {"name": "Receiving", "aliases": ["receive", "inbound", "receiving dock"]},
    {"name": "Putaway", "aliases": ["put away", "put-away", "replenishment"]},
    {"name": "Sorting", "aliases": ["sort", "sorting lane", "sortation"]},
    {"name": "Unloading", "aliases": ["unload", "dock unload", "trailer unload"]},
]


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _process_key(value: Any) -> str:
    text = " ".join(str(value or "").strip().lower().replace("-", " ").replace("_", " ").split())
    return "".join(ch for ch in text if ch.isalnum() or ch == " ").strip()


def _normalize_process_entry(entry: dict[str, Any]) -> dict[str, Any]:
    name = str(entry.get("name") or "").strip()
    aliases = entry.get("aliases") or []
    normalized_aliases: list[str] = []
    seen_aliases: set[str] = set()
    for raw_alias in [name, *aliases]:
        alias = str(raw_alias or "").strip()
        if not alias:
            continue
        alias_key = _process_key(alias)
        if not alias_key or alias_key in seen_aliases:
            continue
        seen_aliases.add(alias_key)
        normalized_aliases.append(alias)
    return {"name": name, "aliases": normalized_aliases}


def build_process_catalog(goals_data: dict | None = None) -> list[dict[str, Any]]:
    goals_data = goals_data or {}
    configured = goals_data.get("configured_processes") or []
    catalog: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for raw_entry in [*DEFAULT_PROCESS_DEFINITIONS, *configured]:
        if not isinstance(raw_entry, dict):
            continue
        entry = _normalize_process_entry(raw_entry)
        name_key = _process_key(entry.get("name"))
        if not name_key:
            continue
        if name_key in seen_names:
            existing = next((item for item in catalog if _process_key(item.get("name")) == name_key), None)
            if existing is None:
                continue
            merged_aliases = list(existing.get("aliases") or [])
            merged_keys = {_process_key(alias) for alias in merged_aliases}
            for alias in entry.get("aliases") or []:
                alias_key = _process_key(alias)
                if alias_key and alias_key not in merged_keys:
                    merged_aliases.append(alias)
                    merged_keys.add(alias_key)
            existing["aliases"] = merged_aliases
            continue
        seen_names.add(name_key)
        catalog.append(entry)
    return catalog


def normalize_process_name(process_name: Any, goals_data: dict | None = None) -> str:
    raw = str(process_name or "").strip()
    if not raw:
        return ""
    raw_key = _process_key(raw)
    for entry in build_process_catalog(goals_data):
        if raw_key in {_process_key(alias) for alias in entry.get("aliases") or []}:
            return str(entry.get("name") or raw).strip() or raw
    return raw.title() if raw.islower() else raw


def list_configurable_processes(goals_data: dict | None = None) -> list[str]:
    return [str(entry.get("name") or "").strip() for entry in build_process_catalog(goals_data) if str(entry.get("name") or "").strip()]


def resolve_target_context(
    *,
    employee_id: str = "",
    process_name: str = "",
    explicit_target: float = 0.0,
    goals_data: dict | None = None,
    tenant_id: str = "",
) -> dict[str, Any]:
    if goals_data is None:
        try:
            from goals import load_goals

            goals_data = load_goals(tenant_id)
        except Exception:
            goals_data = {}

    goals_data = goals_data or {}
    employee_id = str(employee_id or "").strip()
    canonical_process = normalize_process_name(process_name, goals_data)
    explicit_target = _safe_float(explicit_target)
    default_target = _safe_float(goals_data.get("default_target_uph"))
    process_targets = goals_data.get("process_targets") or {}
    dept_targets = goals_data.get("dept_targets") or {}
    employee_overrides = goals_data.get("employee_target_overrides") or {}

    override_entry = employee_overrides.get(employee_id) or {}
    override_target = 0.0
    override_process = ""
    if isinstance(override_entry, dict):
        override_target = _safe_float(override_entry.get("target_uph"))
        override_process = normalize_process_name(override_entry.get("process_name"), goals_data)
    else:
        override_target = _safe_float(override_entry)

    process_target = 0.0
    if canonical_process:
        process_target = _safe_float(process_targets.get(canonical_process))
        if process_target <= 0:
            process_target = _safe_float(dept_targets.get(canonical_process))
        if process_target <= 0:
            for key, value in dept_targets.items():
                if normalize_process_name(key, goals_data) == canonical_process:
                    process_target = _safe_float(value)
                    break

    if override_target > 0:
        target_uph = override_target
        target_source = "employee_override"
        target_source_label = "employee override"
    elif process_target > 0:
        target_uph = process_target
        target_source = "process_target"
        target_source_label = "process target"
    elif explicit_target > 0:
        target_uph = explicit_target
        target_source = "row_target"
        target_source_label = "current row target"
    elif default_target > 0:
        target_uph = default_target
        target_source = "default_target"
        target_source_label = "default target"
    else:
        target_uph = 0.0
        target_source = "none"
        target_source_label = "no configured target"

    return {
        "employee_id": employee_id,
        "process_name": canonical_process or str(process_name or "").strip(),
        "target_uph": round(target_uph, 2) if target_uph > 0 else 0.0,
        "target_source": target_source,
        "target_source_label": target_source_label,
        "default_target_uph": round(default_target, 2) if default_target > 0 else 0.0,
        "process_target_uph": round(process_target, 2) if process_target > 0 else 0.0,
        "override_target_uph": round(override_target, 2) if override_target > 0 else 0.0,
        "override_process_name": override_process,
    }


def build_comparison_descriptions(
    *,
    target_context: dict | None,
    comparison_days: int,
    recent_avg: float = 0.0,
    prior_avg: float = 0.0,
) -> dict[str, str]:
    target_context = target_context or {}
    target_uph = _safe_float(target_context.get("target_uph"))
    target_source_label = str(target_context.get("target_source_label") or "configured target")
    target_process_name = str(target_context.get("process_name") or "").strip()

    if target_uph > 0:
        process_suffix = f" for {target_process_name}" if target_process_name else ""
        compared_to_target = f"Compared to target: {target_uph:.1f} UPH from the {target_source_label}{process_suffix}."
    else:
        compared_to_target = "Compared to target: no configured target is set yet."

    compared_to_recent_performance = (
        f"Compared to recent performance: the latest {comparison_days} comparable days are used as the current window."
    )

    if recent_avg > 0 and prior_avg > 0:
        compared_to_recent_average = (
            f"Compared to recent average: current window {recent_avg:.1f} UPH versus prior window {prior_avg:.1f} UPH."
        )
    elif recent_avg > 0:
        compared_to_recent_average = (
            f"Compared to recent average: current window is {recent_avg:.1f} UPH; prior window is still limited."
        )
    else:
        compared_to_recent_average = "Compared to recent average: recent comparable data is still limited."

    return {
        "compared_to_target": compared_to_target,
        "compared_to_recent_performance": compared_to_recent_performance,
        "compared_to_recent_average": compared_to_recent_average,
    }