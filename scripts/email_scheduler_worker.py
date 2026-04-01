#!/usr/bin/env python3
"""
Standalone email schedule worker.
Runs outside Streamlit so schedule delivery does not depend on active browser sessions.

Usage:
  python3 scripts/email_scheduler_worker.py --once
  python3 scripts/email_scheduler_worker.py --interval 60
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import traceback
from datetime import date, timedelta
from typing import Dict, List, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from database import get_client
from email_engine import (
    get_schedules_due_now,
    get_schedules,
    load_email_config,
    mark_schedule_sent,
    send_report_email,
)
from goals import load_goals
from settings import Settings


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _period_dates(schedule: dict) -> Tuple[date, date]:
    period = schedule.get("report_period", "Prior day")
    today = date.today()
    if period == "Custom":
        try:
            ds = date.fromisoformat(schedule.get("date_start", today.isoformat()))
            de = date.fromisoformat(schedule.get("date_end", ds.isoformat()))
            return ds, de
        except Exception:
            return today - timedelta(days=1), today - timedelta(days=1)
    if period == "Current week":
        return today - timedelta(days=today.weekday()), today
    if period == "Prior week":
        de = today - timedelta(days=today.weekday() + 1)
        return de - timedelta(days=6), de
    if period == "Prior month":
        first = today.replace(day=1)
        de = first - timedelta(days=1)
        return de.replace(day=1), de
    return today - timedelta(days=1), today - timedelta(days=1)


def _build_report_html(
    tenant_id: str,
    ds: date,
    de: date,
    plan_name: str,
    dept_targets: Dict[str, float],
) -> Tuple[bytes | None, str, str]:
    sb = get_client()
    ds_iso, de_iso = ds.isoformat(), de.isoformat()

    emp_rows = (
        sb.table("employees")
        .select("emp_id, name, department")
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )
    emps = {r.get("emp_id", ""): r for r in emp_rows if r.get("emp_id")}

    subs = (
        sb.table("uph_history")
        .select("emp_id, units, hours_worked, uph, work_date, department")
        .eq("tenant_id", tenant_id)
        .gte("work_date", ds_iso)
        .lte("work_date", de_iso)
        .execute()
        .data
        or []
    )

    period = ds_iso if ds_iso == de_iso else f"{ds_iso} - {de_iso}"
    subject = f"Performance Report - All Departments - {period}"

    if not subs:
        body = (
            f"<h2>All Departments - {period}</h2>"
            "<p>No work data found for this period.</p>"
        )
        return None, subject, body

    agg: Dict[str, dict] = {}
    for s in subs:
        eid = s.get("emp_id", "")
        if not eid:
            continue
        if eid not in agg:
            agg[eid] = {"units": 0.0, "hours": 0.0, "dept": ""}
        agg[eid]["units"] += float(s.get("units") or 0)
        agg[eid]["hours"] += float(s.get("hours_worked") or 0)
        agg[eid]["dept"] = s.get("department") or emps.get(eid, {}).get("department", "")

    rows: List[dict] = []
    for eid, v in agg.items():
        uph = round(v["units"] / v["hours"], 2) if v["hours"] > 0 else 0.0
        dept = v["dept"]
        tgt = float(dept_targets.get(dept, 0) or 0)
        rows.append(
            {
                "Employee Name": emps.get(eid, {}).get("name", eid),
                "Department": dept,
                "Average UPH": uph,
                "Units": round(v["units"]),
                "Hours": round(v["hours"], 2),
                "Target UPH": tgt if tgt else "-",
                "goal_status": "on_goal" if tgt and uph >= tgt else ("below_goal" if tgt else "no_goal"),
            }
        )

    rows.sort(key=lambda r: float(r.get("Average UPH", 0)), reverse=True)

    on_goal = sum(1 for r in rows if r["goal_status"] == "on_goal")
    below = sum(1 for r in rows if r["goal_status"] == "below_goal")
    avg_uph = round(sum(float(r["Average UPH"]) for r in rows) / len(rows), 1) if rows else 0

    dept_summary = {}
    for r in rows:
        dept = r.get("Department", "")
        if not dept:
            continue
        dept_summary.setdefault(dept, {"total": 0, "on": 0})
        dept_summary[dept]["total"] += 1
        if r.get("goal_status") == "on_goal":
            dept_summary[dept]["on"] += 1

    dept_html = ""
    if dept_summary:
        dept_html += "<h3>Department Health</h3><ul>"
        for dept in sorted(dept_summary.keys()):
            d = dept_summary[dept]
            pct = round((d["on"] / d["total"] * 100) if d["total"] else 0)
            dept_html += f"<li><strong>{dept}</strong>: {d['on']}/{d['total']} on goal ({pct}%)</li>"
        dept_html += "</ul>"

    top3 = rows[:3]
    top_html = "<h3>Top Performers</h3><ol>"
    for r in top3:
        top_html += f"<li><strong>{r['Employee Name']}</strong> ({r['Department']}) - {r['Average UPH']} UPH</li>"
    top_html += "</ol>"

    risk_html = ""
    cost_html = ""
    if plan_name in ("pro", "business"):
        risk_rows = [r for r in rows if r.get("goal_status") == "below_goal"][:5]
        if risk_rows:
            risk_html += "<h3>Top Risks - Action Required</h3><ul>"
            for r in risk_rows:
                risk_html += f"<li><strong>{r['Employee Name']}</strong> ({r['Department']}) - {r['Average UPH']} vs {r['Target UPH']}</li>"
            risk_html += "</ul>"

        try:
            wage = float(Settings(tenant_id=tenant_id).get("avg_hourly_wage", 18.0))
        except Exception:
            wage = 18.0
        impact = 0.0
        for r in rows:
            try:
                tgt = float(r.get("Target UPH") or 0)
                cur = float(r.get("Average UPH") or 0)
                hrs = float(r.get("Hours") or 0)
                if tgt > 0 and 0 < cur < tgt:
                    impact += max(((tgt - cur) / tgt) * hrs * wage, 0)
            except Exception:
                continue
        cost_html = f"<h3>Cost Impact</h3><p>Estimated labor cost impact this period: <strong>${impact:,.0f}</strong></p>"

    body = (
        f"<h2>All Departments - {period}</h2>"
        f"<p><strong>{len(rows)}</strong> employees | Avg UPH: <strong>{avg_uph}</strong> | "
        f"<strong style='color:green'>{on_goal} on goal</strong> | "
        f"<strong style='color:red'>{below} below goal</strong></p>"
        f"{dept_html}{top_html}{risk_html}{cost_html}"
        "<p style='font-size:12px;color:#666;'>Generated by Productivity Planner Scheduler Worker.</p>"
    )

    return None, subject, body


def _run_once() -> None:
    sb = get_client()
    cfg_rows = (
        sb.table("tenant_email_config")
        .select("tenant_id, schedules")
        .execute()
        .data
        or []
    )

    if not cfg_rows:
        pattern = os.path.join(ROOT_DIR, "dpd_email_config_*.json")
        for path in glob.glob(pattern):
            try:
                tenant_id = os.path.basename(path)[len("dpd_email_config_"):-len(".json")]
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cfg_rows.append({
                    "tenant_id": tenant_id,
                    "schedules": data.get("schedules") or [],
                })
            except Exception:
                continue

    if not cfg_rows:
        _log("No tenant email configs found")
        return

    for row in cfg_rows:
        tid = row.get("tenant_id", "")
        scheds = row.get("schedules") or []
        if not tid or not scheds:
            continue

        tz = Settings(tenant_id=tid).get("timezone", "")
        due = get_schedules_due_now(timezone=tz, tenant_id=tid)
        if not due:
            continue

        goals = load_goals(tenant_id=tid) or {}
        targets = goals.get("dept_targets", {})

        sub = (
            sb.table("subscriptions")
            .select("plan")
            .eq("tenant_id", tid)
            .limit(1)
            .execute()
            .data
            or []
        )
        plan = (sub[0].get("plan") if sub else "starter") or "starter"
        plan = str(plan).lower()

        cfg = load_email_config(tenant_id=tid)
        global_to = [r.get("email", "").strip() for r in (cfg.get("recipients") or []) if r.get("email")]

        for sched in due:
            to_list = sched.get("recipients", []) or global_to
            if not to_list:
                _log(f"[{tid[:8]}] SKIP '{sched.get('name')}' no recipients")
                continue

            ds, de = _period_dates(sched)
            xl_data, subject, body = _build_report_html(tid, ds, de, plan, targets)
            if (sched.get("subject_tpl") or "").strip():
                subject = sched.get("subject_tpl").strip()

            ok, err = send_report_email(to_list, subject, body, xl_data, tenant_id=tid)
            if ok:
                mark_schedule_sent(sched.get("name", ""), timezone=tz, tenant_id=tid)
                _log(f"[{tid[:8]}] SENT '{sched.get('name')}' -> {to_list}")
            else:
                _log(f"[{tid[:8]}] FAILED '{sched.get('name')}': {err}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone schedule email worker")
    parser.add_argument("--once", action="store_true", help="Run one pass and exit")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between runs in daemon mode")
    args = parser.parse_args()

    _log("Email scheduler worker started")
    if args.once:
        _run_once()
        _log("Email scheduler worker finished")
        return

    while True:
        try:
            _run_once()
        except Exception as e:
            _log(f"Unhandled worker error: {e}")
            _log(traceback.format_exc().strip())
        time.sleep(max(args.interval, 15))


if __name__ == "__main__":
    main()
