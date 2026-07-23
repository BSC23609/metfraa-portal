"""Report generation routes — monthly PDF + master Excel sync to OneDrive.

v2 (Sub-batch 5): reads from MonthlyKPIActual instead of DailyEntry.
"""
import calendar
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
import io

from ..database import get_db
from ..models import Employee, MonthlyReport, MonthlyKPIActual, AuditLog
from ..deps import get_current_user, require_admin
from ..services.pdf_report import generate_monthly_pdf, report_filename
from ..services.excel_master import build_master_workbook
from ..services import onedrive
from ..config import get_settings

router = APIRouter(prefix="/reports", tags=["reports"])
settings = get_settings()


def _save_report_record(db, employee_id, year, month, final_score, onedrive_path,
                        pdf_url, generated_by):
    existing = (
        db.query(MonthlyReport)
        .filter_by(employee_id=employee_id, year=year, month=month)
        .first()
    )
    if existing:
        existing.final_score = final_score
        existing.onedrive_path = onedrive_path
        existing.pdf_url = pdf_url
        existing.generated_by = generated_by
    else:
        db.add(MonthlyReport(
            employee_id=employee_id, year=year, month=month,
            final_score=final_score,
            onedrive_path=onedrive_path, pdf_url=pdf_url,
            generated_by=generated_by,
        ))
    db.commit()


def _compute_final_score(db: Session, employee_id: int, year: int, month: int) -> float:
    """Read monthly actuals and compute the weighted final score."""
    from ..routes.monthly_kpi import compute_weighted_score
    actuals = (
        db.query(MonthlyKPIActual)
        .filter_by(employee_id=employee_id, year=year, month=month)
        .all()
    )
    if not actuals:
        return 0.0
    return compute_weighted_score(actuals)["final_score"]


def _has_any_submission(db: Session, employee_id: int, year: int, month: int) -> bool:
    return db.query(MonthlyKPIActual).filter_by(
        employee_id=employee_id, year=year, month=month
    ).first() is not None


@router.post("/generate-mine/{year}/{month}")
def generate_my_monthly_report(
    year: int, month: int,
    user: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """User triggers their own monthly PDF.

    Requires: user has submitted at least one MonthlyKPIActual for this period.
    """
    return _do_generate(db, user, year, month, generated_by=user.email or user.employee_code)


@router.post("/admin-generate/{employee_id}/{year}/{month}")
def admin_generate_report(
    employee_id: int, year: int, month: int,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin manually re-triggers PDF for any employee + month (no submission required)."""
    target = db.query(Employee).filter_by(id=employee_id).first()
    if not target:
        raise HTTPException(404, "Employee not found")
    return _do_generate(db, target, year, month,
                        generated_by=admin.email or admin.employee_code,
                        skip_submission_check=True)


def _do_generate(db, employee, year, month, generated_by, skip_submission_check=False):
    today = date.today()

    if (year, month) > (today.year, today.month):
        raise HTTPException(400, "Cannot generate report for a future month")

    if not skip_submission_check and not _has_any_submission(db, employee.id, year, month):
        raise HTTPException(
            400,
            f"You must submit your KPI actuals for {calendar.month_name[month]} {year} "
            f"before generating the report."
        )

    # Generate PDF
    try:
        pdf_bytes = generate_monthly_pdf(db, employee.id, year, month, generated_by=generated_by)
    except Exception as e:
        raise HTTPException(500, f"PDF generation failed: {e}")

    fname = report_filename(employee, year, month)

    # Upload to OneDrive
    onedrive_path = f"{settings.onedrive_folder}/Reports/{year}-{month:02d}"
    pdf_url = None
    upload_status = "skipped"

    if settings.ms_client_id and settings.ms_client_secret and settings.ms_tenant_id:
        try:
            info = onedrive.upload_file(pdf_bytes, fname, onedrive_path)
            pdf_url = info.get("webUrl")
            upload_status = "uploaded"
        except Exception as e:
            upload_status = f"failed: {e}"
            print(f"[reports] OneDrive upload failed: {e}")

    # Save record
    final_score = _compute_final_score(db, employee.id, year, month)
    _save_report_record(
        db, employee.id, year, month, final_score,
        f"{onedrive_path}/{fname}", pdf_url, generated_by,
    )

    # Audit
    db.add(AuditLog(
        actor_email=generated_by,
        action="generate_pdf",
        details={
            "employee_id": employee.id,
            "year": year, "month": month,
            "filename": fname,
            "onedrive_status": upload_status,
            "final_score": final_score,
        },
    ))
    db.commit()

    return JSONResponse({
        "success": True,
        "filename": fname,
        "onedrive_status": upload_status,
        "onedrive_url": pdf_url,
        "final_score": final_score,
        "download_url": f"/reports/download/{employee.id}/{year}/{month}",
    })


@router.get("/download/{employee_id}/{year}/{month}")
def download_pdf(
    employee_id: int, year: int, month: int,
    user: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download the PDF directly. Users can only download their own; admins can download anyone's."""
    target = db.query(Employee).filter_by(id=employee_id).first()
    if not target:
        raise HTTPException(404, "Employee not found")
    if not user.is_admin and user.id != employee_id:
        raise HTTPException(403, "Forbidden")

    pdf_bytes = generate_monthly_pdf(db, employee_id, year, month,
                                     generated_by=user.email or user.employee_code)
    fname = report_filename(target, year, month)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/admin/sync-master-excel")
def sync_master_excel(
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Build the master Excel and upload to OneDrive."""
    xlsx_bytes = build_master_workbook(db)
    fname = "Metfraa_KPI_Master.xlsx"
    onedrive_path = settings.onedrive_folder
    upload_status = "skipped"
    url = None
    if settings.ms_client_id and settings.ms_client_secret and settings.ms_tenant_id:
        try:
            info = onedrive.upload_file(xlsx_bytes, fname, onedrive_path)
            url = info.get("webUrl")
            upload_status = "uploaded"
        except Exception as e:
            upload_status = f"failed: {e}"
            print(f"[reports] OneDrive Excel upload failed: {e}")
    db.add(AuditLog(
        actor_email=admin.email,
        action="sync_master_excel",
        details={"status": upload_status, "url": url},
    ))
    db.commit()
    return {
        "success": True,
        "onedrive_status": upload_status,
        "onedrive_url": url,
        "download_url": "/reports/admin/download-master-excel",
    }


@router.get("/admin/download-master-excel")
def download_master_excel(
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Download the master Excel directly."""
    xlsx_bytes = build_master_workbook(db)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Metfraa_KPI_Master.xlsx"'},
    )


@router.get("/list")
def list_reports(
    user: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List monthly reports — user sees their own, admin sees all."""
    q = db.query(MonthlyReport).order_by(MonthlyReport.year.desc(), MonthlyReport.month.desc())
    if not user.is_admin:
        q = q.filter_by(employee_id=user.id)
    reports = q.limit(120).all()
    # Manually load employees (avoid .employee relationship — see models.py note)
    emp_ids = list({r.employee_id for r in reports})
    emp_map = {}
    if emp_ids:
        emps = db.query(Employee).filter(Employee.id.in_(emp_ids)).all()
        emp_map = {e.id: e for e in emps}
    rows = []
    for r in reports:
        emp = emp_map.get(r.employee_id)
        rows.append({
            "id": r.id,
            "employee_id": r.employee_id,
            "employee_name": emp.name if emp else "(deleted)",
            "year": r.year, "month": r.month,
            "final_score": r.final_score,
            "onedrive_path": r.onedrive_path,
            "pdf_url": r.pdf_url,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "generated_by": r.generated_by,
        })
    return rows
