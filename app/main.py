"""Metfraa Portal — main FastAPI application.

One app, one login: KPI Tracker + Expense + EHS. Built on the KPI Tracker
foundation — KPI routes stay flat so existing bookmarks keep working.
"""
import os
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import logging
import pathlib
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
from .routes import gatepass as gatepass_routes
from .routes import gatepass_public as gatepass_public_routes
from .routes import tgt26 as tgt26_routes
from .routes import ehs as ehs_routes
from .routes import ehs_ui as ehs_ui_routes
from .routes import expense as expense_routes
from .routes import expense_ui as expense_ui_routes
from .routes import people as people_routes
from .services.scheduler import start_scheduler
from .startup_migrations import run_startup_migrations

settings = get_settings()

IS_VERCEL = bool(os.getenv("VERCEL"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Init DB + scheduler. On Vercel: skip create_all unless INIT_DB=true,
    never run APScheduler (vercel.json crons hit /cron/* instead)."""
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
        print("[startup] Vercel detected — APScheduler off, using /cron endpoints")
    elif os.getenv("DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
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
    version="3.1.0",
    lifespan=lifespan,
)

_STATIC = pathlib.Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
# EHS parity assets — reference served these at /css /js /img; prefixed with /ehs.
# Guarded: StaticFiles raises at import if a directory is absent, which would
# crash every route in the portal, not just EHS.
_EHS_STATIC = _STATIC / "ehs"
for _sub in ("css", "js", "img"):
    _dir = _EHS_STATIC / _sub
    if _dir.is_dir():
        app.mount(f"/ehs/{_sub}", StaticFiles(directory=str(_dir)), name=f"ehs-{_sub}")
    else:
        logging.getLogger(__name__).error(
            "EHS static dir missing, /ehs/%s will 404: %s", _sub, _dir)

# Expense parity assets — reference served these at /css /js /assets.
_EXP_STATIC = _STATIC / "expense"
for _sub in ("css", "js", "assets"):
    _dir = _EXP_STATIC / _sub
    if _dir.is_dir():
        app.mount(f"/expense/{_sub}", StaticFiles(directory=str(_dir)), name=f"expense-{_sub}")
    else:
        logging.getLogger(__name__).error(
            "Expense static dir missing, /expense/%s will 404: %s", _sub, _dir)
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent / "templates"))

# Routers
app.include_router(auth_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(admin_routes.router)
app.include_router(reports_routes.router)
app.include_router(task_reports_routes.router)
app.include_router(monthly_kpi_routes.router)
app.include_router(site_visits_routes.router)
app.include_router(cron_routes.router)
app.include_router(gatepass_routes.router)
# Root-mounted: WhatsApp button URLs may only vary in the last path segment.
app.include_router(gatepass_public_routes.router)
app.include_router(tgt26_routes.router)   # Team Get Together 2026 passes (same rationale)
app.include_router(ehs_ui_routes.router)   # parity pages + contract (must precede ehs_routes)
app.include_router(ehs_routes.router)
app.include_router(expense_ui_routes.router)   # parity SPA + bootstrap (precedes expense_routes)
app.include_router(expense_routes.router)
app.include_router(people_routes.router)


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

    from .access import get_access

    access = get_access(db, user)
    admin_stats = None
    if access.any_admin:
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
            from .models import ExpenseSubmission

            exp_pending = (
                db.query(ExpenseSubmission)
                .filter(ExpenseSubmission.status == "pending")
                .count()
            )
        except Exception:
            exp_pending = 0

        try:
            from .models import EHSSubmission

            ehs_pending = (
                db.query(EHSSubmission)
                .filter(EHSSubmission.status == "pending")
                .count()
            )
        except Exception:
            ehs_pending = 0

        # Guarded like the others: a module whose tables aren't migrated yet
        # must not take down the whole home page.
        try:
            from .models import OutpassRequest
            gatepass_open = (
                db.query(OutpassRequest)
                .filter(OutpassRequest.type == "gatepass",
                        OutpassRequest.status == "approved",
                        OutpassRequest.returned_at.is_(None))
                .count()
            )
            gatepass_pending = (
                db.query(OutpassRequest)
                .filter(OutpassRequest.status == "pending")
                .count()
            )
        except Exception:
            db.rollback()
            gatepass_open = gatepass_pending = 0

        admin_stats = {
            "gatepass_open": gatepass_open,
            "gatepass_pending": gatepass_pending,
            "exp_pending": exp_pending,
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
        {"user": user, "admin_stats": admin_stats, "access": access},
    )




@app.get("/sw.js", include_in_schema=False)
def service_worker():
    from fastapi.responses import FileResponse

    return FileResponse(str(_STATIC / "sw.js"), media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    from fastapi.responses import FileResponse

    return FileResponse(str(_STATIC / "manifest.json"), media_type="application/manifest+json")


@app.get("/health")
def health():
    return {"status": "ok"}
