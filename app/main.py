"""Metfraa Portal — main FastAPI application.

One app, one login: KPI Tracker (live), Expense (coming soon), EHS (coming soon).
Built on the KPI Tracker foundation — KPI routes stay flat (/dashboard, /task-reports/,
/monthly-kpi/, /site-visits/, /admin) so existing bookmarks keep working.
"""
import os
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, engine, get_db
from .deps import get_optional_user
from .models import Employee
from .routes import auth as auth_routes
from .routes import dashboard as dashboard_routes
from .routes import admin as admin_routes
from .routes import reports as reports_routes
from .routes import task_reports as task_reports_routes
from .routes import monthly_kpi as monthly_kpi_routes
from .routes import site_visits as site_visits_routes
from .routes import cron as cron_routes
from .routes import ehs as ehs_routes
from .services.scheduler import start_scheduler
from .startup_migrations import run_startup_migrations

settings = get_settings()


IS_VERCEL = bool(os.getenv("VERCEL"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Init DB tables and start scheduler on startup.

    On Vercel (serverless), lifespan runs on EVERY cold start, so we skip
    create_all + migrations unless INIT_DB=true — the schema already exists
    in the live Neon DB. Run once with INIT_DB=true on a fresh database.
    """
    if not IS_VERCEL:
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(data_dir, exist_ok=True)

    if not IS_VERCEL or os.getenv("INIT_DB", "").lower() in ("1", "true"):
        Base.metadata.create_all(bind=engine)
        try:
            run_startup_migrations()
        except Exception as e:
            print(f"[startup] Migrations failed: {e}")

    sched = None
    if IS_VERCEL:
        # Serverless — no long-running process. Vercel Cron hits /cron/* instead
        # (see vercel.json). Gated by CRON_ENABLED during the parallel run.
        print("[startup] Vercel detected — APScheduler off, using /cron endpoints")
    elif os.getenv("DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
        # During the parallel run, the OLD kpis.metfraa.com service still runs the
        # scheduler. Keep it disabled here to avoid duplicate reminder emails.
        # After cutover (old service killed), remove this env var on Render.
        print("[startup] Scheduler disabled via DISABLE_SCHEDULER env var")
    else:
        try:
            sched = start_scheduler()
        except Exception as e:
            print(f"[startup] Scheduler not started: {e}")

    yield

    if sched:
        sched.shutdown(wait=False)


app = FastAPI(
    title="Metfraa Portal",
    description="KPIs, Expenses & EHS for Metfraa Steel Buildings — one login, one home.",
    version="3.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Routers
app.include_router(auth_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(admin_routes.router)
app.include_router(reports_routes.router)
app.include_router(task_reports_routes.router)
app.include_router(monthly_kpi_routes.router)
app.include_router(site_visits_routes.router)
app.include_router(cron_routes.router)
app.include_router(ehs_routes.router)


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def root(
    request: Request,
    user: Employee | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Portal home — 3 module tiles. Admins additionally see live task counts."""
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    if user.must_reset_password:
        return RedirectResponse("/auth/change-password", status_code=303)

    admin_stats = None
    if user.is_admin:
        from datetime import date

        from .models import (
            MonthlyKPIActual,
            PasswordResetRequest,
            SiteVisit,
            UnlockRequest,
        )

        today = date.today()
        try:
            pending_unlocks = (
                db.query(UnlockRequest)
                .filter(UnlockRequest.status == "pending")
                .count()
            )
            pending_resets = (
                db.query(PasswordResetRequest)
                .filter(PasswordResetRequest.status == "pending")
                .count()
            )
            kpi_submitted = (
                db.query(MonthlyKPIActual.employee_id)
                .filter(
                    MonthlyKPIActual.year == today.year,
                    MonthlyKPIActual.month == today.month,
                )
                .distinct()
                .count()
            )
            kpi_total = (
                db.query(Employee)
                .filter(Employee.is_active == True, Employee.is_admin == False)  # noqa: E712
                .count()
            )
            draft_visits = (
                db.query(SiteVisit).filter(SiteVisit.status == "draft").count()
            )
        except Exception:
            pending_unlocks = pending_resets = kpi_submitted = kpi_total = draft_visits = 0

        try:
            from .models import EHSSubmission

            ehs_pending = (
                db.query(EHSSubmission)
                .filter(EHSSubmission.status == "pending")
                .count()
            )
        except Exception:
            ehs_pending = 0

        admin_stats = {
            "ehs_pending": ehs_pending,
            "pending_unlocks": pending_unlocks,
            "pending_resets": pending_resets,
            "kpi_submitted": kpi_submitted,
            "kpi_total": kpi_total,
            "draft_visits": draft_visits,
        }

    return templates.TemplateResponse(
        request,
        "home.html",
        {"user": user, "admin_stats": admin_stats},
    )


@app.get("/expense/", response_class=HTMLResponse)
@app.get("/expense", response_class=HTMLResponse, include_in_schema=False)
def expense_stub(
    request: Request,
    user: Employee | None = Depends(get_optional_user),
):
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "coming_soon.html",
        {
            "user": user,
            "module_name": "Expense Portal",
            "module_desc": "Local, cab, accommodation, outstation, DTR, advance & payment claims — with bill uploads and approvals.",
            "phase": "Phase 2",
        },
    )




@app.get("/health")
def health():
    return {"status": "ok"}
