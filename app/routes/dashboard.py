"""Home / landing page for authenticated users.

Renamed conceptually from 'dashboard' to 'home'. The URL stays /dashboard
so all existing links (base.html nav, employee-facing docs) keep working.

The legacy daily-KPI endpoints (/api/me, /api/entry/*, /api/my-summary,
/api/my-history) that lived here were removed — they were replaced by
/task-reports/ (Sub-batch 2A) and /monthly-kpi/ (Sub-batch 3) and were
serving stale data that broke the old dashboard template.
"""
from datetime import date, datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Employee
from ..deps import get_current_user_ready

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _today_label() -> str:
    """e.g. 'Monday, 20 July 2026'."""
    return datetime.now().strftime("%A, %d %B %Y")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: Employee = Depends(get_current_user_ready),
):
    """Home landing page — module tiles for Daily Tasks, Monthly KPI,
    Site Visits, Admin (if admin), and Change Password.
    """
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "today_label": _today_label(),
        },
    )


# ---- Backwards-compat: /api/me still returns identity for any legacy JS
# still calling it. Everything else that used to live here is gone.

@router.get("/api/me")
def api_me(user: Employee = Depends(get_current_user_ready)):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "employee_code": user.employee_code,
        "designation": user.designation,
        "department": user.department,
        "is_admin": user.is_admin,
    }
