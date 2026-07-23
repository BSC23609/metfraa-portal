"""Computes weighted monthly KPI score for an employee."""
import calendar
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import extract
from ..models import Employee, KPI, DailyEntry, KPIEntry


def compute_monthly_score(
    db: Session,
    employee_id: int,
    year: int,
    month: int,
) -> dict:
    """Compute the monthly weighted score for an employee.

    Returns:
        {
            "employee": Employee,
            "year": int,
            "month": int,
            "kpi_results": [
                {
                    "kpi": KPI,
                    "actual": float,
                    "target": float,
                    "achievement_pct": float,   # capped 100
                    "weight": float,
                    "weighted_score": float,    # achievement_pct * weight / 100
                }, ...
            ],
            "final_score": float,             # 0–100
            "attendance": {
                "work_days": int,
                "leave_days": int,
                "site_remote_days": int,
                "sundays": int,
                "holidays": int,
                "missed_days": int,
                "total_calendar_days": int,
            },
        }
    """
    emp = db.query(Employee).filter_by(id=employee_id).first()
    if not emp:
        raise ValueError(f"Employee {employee_id} not found")

    kpis = (
        db.query(KPI)
        .filter_by(employee_id=employee_id, is_active=True)
        .order_by(KPI.display_order)
        .all()
    )

    # Sum each KPI value across the month (only for "work" entries)
    kpi_results = []
    for k in kpis:
        actual = (
            db.query(KPIEntry)
            .join(DailyEntry, DailyEntry.id == KPIEntry.daily_entry_id)
            .filter(
                KPIEntry.kpi_id == k.id,
                DailyEntry.entry_type == "work",
                extract("year", DailyEntry.entry_date) == year,
                extract("month", DailyEntry.entry_date) == month,
            )
            .all()
        )
        actual_sum = sum(ke.value for ke in actual)
        target = k.monthly_target or 0
        if target > 0:
            achievement = min(100.0, (actual_sum / target) * 100.0)
        else:
            achievement = 0.0
        weighted = achievement * (k.weight / 100.0)
        kpi_results.append({
            "kpi": k,
            "actual": actual_sum,
            "target": target,
            "achievement_pct": round(achievement, 1),
            "weight": k.weight,
            "weighted_score": round(weighted, 2),
        })

    final_score = round(sum(r["weighted_score"] for r in kpi_results), 2)

    # Attendance
    days_in_month = calendar.monthrange(year, month)[1]
    entries = (
        db.query(DailyEntry)
        .filter(
            DailyEntry.employee_id == employee_id,
            extract("year", DailyEntry.entry_date) == year,
            extract("month", DailyEntry.entry_date) == month,
        )
        .all()
    )
    counts = {"work": 0, "casual_leave": 0, "site_remote": 0, "sunday": 0, "holiday": 0}
    for e in entries:
        counts[e.entry_type] = counts.get(e.entry_type, 0) + 1

    submitted_days = len(entries)
    # If month is current/future, missed_days only counts past days
    today = date.today()
    if year == today.year and month == today.month:
        max_day = today.day
    elif (year, month) > (today.year, today.month):
        max_day = 0
    else:
        max_day = days_in_month

    missed = max(0, max_day - submitted_days)

    return {
        "employee": emp,
        "year": year,
        "month": month,
        "kpi_results": kpi_results,
        "final_score": final_score,
        "attendance": {
            "work_days": counts.get("work", 0),
            "leave_days": counts.get("casual_leave", 0),
            "site_remote_days": counts.get("site_remote", 0),
            "sundays": counts.get("sunday", 0),
            "holidays": counts.get("holiday", 0),
            "missed_days": missed,
            "total_calendar_days": days_in_month,
        },
    }


def get_daily_kpi_trend(
    db: Session,
    employee_id: int,
    year: int,
    month: int,
) -> dict:
    """Per-day KPI trend for the month — used for charts."""
    days_in_month = calendar.monthrange(year, month)[1]
    days = [date(year, month, d) for d in range(1, days_in_month + 1)]

    kpis = (
        db.query(KPI)
        .filter_by(employee_id=employee_id, is_active=True)
        .order_by(KPI.display_order)
        .all()
    )

    # Build per-day per-kpi totals
    series = {k.id: {"name": k.name, "values": [0.0] * days_in_month} for k in kpis}
    daily_totals = [0.0] * days_in_month

    entries = (
        db.query(DailyEntry)
        .filter(
            DailyEntry.employee_id == employee_id,
            extract("year", DailyEntry.entry_date) == year,
            extract("month", DailyEntry.entry_date) == month,
        )
        .all()
    )
    for entry in entries:
        if entry.entry_type != "work":
            continue
        d_idx = entry.entry_date.day - 1
        for kv in entry.kpi_values:
            if kv.kpi_id in series:
                series[kv.kpi_id]["values"][d_idx] += kv.value
                daily_totals[d_idx] += kv.value

    return {
        "days": [d.isoformat() for d in days],
        "series": list(series.values()),
        "daily_totals": daily_totals,
    }
