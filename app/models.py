"""SQLAlchemy models for Metfraa KPI Tracker."""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, Boolean, Text,
    ForeignKey, JSON, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from .database import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)

    # --- Login credentials ---
    employee_code = Column(String(32), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    must_reset_password = Column(Boolean, default=True, nullable=False)

    # --- Identity ---
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(32), nullable=True)
    designation = Column(String(255), nullable=True)
    department = Column(String(255), nullable=True)
    reports_to = Column(String(255), nullable=True)

    # --- Permissions ---
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    can_submit_task_report = Column(Boolean, default=True, nullable=False)

    # --- Metadata ---
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    jrr_text = Column(Text, nullable=True)

    kpis = relationship("KPI", back_populates="employee", cascade="all, delete-orphan")


class KPI(Base):
    __tablename__ = "kpis"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(500), nullable=False)
    unit = Column(String(64), nullable=False, default="Count")
    weight = Column(Float, nullable=False, default=10.0)
    target = Column(Float, nullable=False, default=20.0)
    display_order = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee", back_populates="kpis")


# ============================================================
# LEGACY tables — kept for schema compatibility
# ============================================================

class DailyEntry(Base):
    __tablename__ = "daily_entries"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_date = Column(Date, nullable=False)
    entry_type = Column(String(32), nullable=False, default="work")
    comments = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    locked = Column(Boolean, default=True)

    kpi_values = relationship("KPIEntry", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("employee_id", "entry_date", name="uq_employee_date"),)


class KPIEntry(Base):
    __tablename__ = "kpi_entries"

    id = Column(Integer, primary_key=True, index=True)
    daily_entry_id = Column(Integer, ForeignKey("daily_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    kpi_id = Column(Integer, ForeignKey("kpis.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(Float, nullable=False, default=0)


class MonthlyReport(Base):
    """Existing table kept for backward compat. New reports (v2) write here too."""
    __tablename__ = "monthly_reports"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    final_score = Column(Float, nullable=False, default=0)
    generated_at = Column(DateTime, default=datetime.utcnow)
    pdf_url = Column(String(1024), nullable=True)
    onedrive_path = Column(String(1024), nullable=True)
    generated_by = Column(String(255), nullable=True)
    payload = Column(JSON, nullable=True)
    # NOTE: no .employee relationship — caused mapper init error.
    # Callers should manually join or query Employee by employee_id.


class UnlockRequest(Base):
    """kind: 'legacy_entry' | 'task_report' | 'monthly_kpi'"""
    __tablename__ = "unlock_requests"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_date = Column(Date, nullable=False)
    kind = Column(String(32), default="task_report", nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    admin_response = Column(Text, nullable=True)
    decided_by_email = Column(String(255), nullable=True)
    decided_by_code = Column(String(32), nullable=True)
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)

    employee = relationship("Employee")


class PasswordResetRequest(Base):
    __tablename__ = "password_reset_requests"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(String(20), default="pending", nullable=False)
    requested_at = Column(DateTime, default=datetime.utcnow)
    fulfilled_at = Column(DateTime, nullable=True)
    fulfilled_by_code = Column(String(32), nullable=True)
    expires_at = Column(DateTime, nullable=False)

    employee = relationship("Employee")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    actor_email = Column(String(255), nullable=True)
    actor_code = Column(String(32), nullable=True)
    action = Column(String(255), nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# Phase 2A — Daily Task Reports
# ============================================================

class DailyTaskReport(Base):
    __tablename__ = "daily_task_reports"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    report_date = Column(Date, nullable=False, index=True)
    tomorrow_plan = Column(Text, nullable=True)
    blockers = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    last_edited_at = Column(DateTime, default=datetime.utcnow)
    locked = Column(Boolean, default=False, nullable=False)
    locked_at = Column(DateTime, nullable=True)

    items = relationship(
        "DailyTaskItem",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="DailyTaskItem.sequence",
    )
    employee = relationship("Employee")

    __table_args__ = (
        UniqueConstraint("employee_id", "report_date", name="uq_task_report_employee_date"),
    )


class DailyTaskItem(Base):
    __tablename__ = "daily_task_items"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(
        Integer,
        ForeignKey("daily_task_reports.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sequence = Column(Integer, nullable=False, default=1)
    task_description = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    project = Column(String(255), nullable=True)
    remarks = Column(Text, nullable=True)

    report = relationship("DailyTaskReport", back_populates="items")


# ============================================================
# Phase 3 — Monthly KPI Actuals
# ============================================================

class MonthlyKPIActual(Base):
    """One row per employee×kpi×month, containing the actual value submitted."""
    __tablename__ = "monthly_kpi_actuals"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    kpi_id = Column(Integer, ForeignKey("kpis.id", ondelete="CASCADE"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    month = Column(Integer, nullable=False, index=True)

    actual_value = Column(Float, nullable=False, default=0)
    # Snapshotted from KPI at submission time so historical scores don't shift
    target_snapshot = Column(Float, nullable=False, default=0)
    weight_snapshot = Column(Float, nullable=False, default=0)
    unit_snapshot = Column(String(64), nullable=True)

    submitted_at = Column(DateTime, default=datetime.utcnow)
    last_edited_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("employee_id", "kpi_id", "year", "month", name="uq_monthly_kpi_actual"),
    )



# ============================================================
# Phase 4 — Site Visit CRM
# ============================================================

class SiteVisit(Base):
    """A field visit / lead capture. One per submission.

    Draft state: submitted_at is NULL, no PDF yet.
    Submitted: submitted_at set, PDF generated + emailed + archived.
    Per Q2: NO edit after submit (checked at API level).
    """
    __tablename__ = "site_visits"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(String(32), unique=True, nullable=False, index=True)  # e.g. SV-20260720-3421
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)

    # Visit + contact
    visit_date = Column(Date, nullable=True)
    visited_by = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)
    contact_person = Column(String(255), nullable=True)
    contact_phone = Column(String(64), nullable=True)
    contact_email = Column(String(255), nullable=True)
    site_address = Column(Text, nullable=True)

    # Requirement category
    category = Column(String(32), nullable=True)  # newshed | reroof | extension | other
    details_json = Column(JSON, nullable=True)  # per-category free-form

    # Discussion
    discussion_notes = Column(Text, nullable=True)
    next_steps = Column(Text, nullable=True)
    followup_date = Column(Date, nullable=True)
    priority = Column(String(16), nullable=True)  # Low | Medium | High

    # Lifecycle
    status = Column(String(16), default="draft", nullable=False)  # draft | submitted
    created_at = Column(DateTime, default=datetime.utcnow)
    last_edited_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)

    # PDF / OneDrive
    pdf_filename = Column(String(255), nullable=True)
    pdf_onedrive_url = Column(String(1024), nullable=True)
    photos_onedrive_folder = Column(String(1024), nullable=True)

    photos = relationship("SiteVisitPhoto", back_populates="visit",
                          cascade="all, delete-orphan", order_by="SiteVisitPhoto.sequence")


class SiteVisitPhoto(Base):
    __tablename__ = "site_visit_photos"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("site_visits.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=1)

    caption = Column(String(255), nullable=True)
    original_filename = Column(String(255), nullable=True)
    mime_type = Column(String(64), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    onedrive_url = Column(String(1024), nullable=True)
    onedrive_path = Column(String(1024), nullable=True)

    # Small thumbnail (base64) for the list view — keep tiny (<50KB)
    thumbnail_b64 = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    visit = relationship("SiteVisit", back_populates="photos")


# ============================================================
# EHS module (Phase 1)
# ------------------------------------------------------------
# DB is the source of truth for submissions and workflow state.
# Photos, approval PDFs and per-form _MasterLog.xlsx live in
# OneDrive under Metfraa-EHS/ using the same folder layout the
# old Node app used, so nothing moves for the people using the
# OneDrive folders directly.
# ============================================================

from sqlalchemy import JSON  # noqa: E402


class EHSProject(Base):
    """Master project list for EHS form dropdowns (was _config/projects.json)."""

    __tablename__ = "ehs_projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    active = Column(Boolean, default=True, nullable=False)
    aliases = Column(JSON, default=list)  # legacy free-text names that map here
    created_by = Column(String(200), default="system")
    created_at = Column(DateTime, default=datetime.utcnow)


class EHSSubmission(Base):
    """One submitted EHS form of any type. Fields/checklist stored as JSON
    in the same shape the old app used, which makes the Phase 3 OneDrive
    JSON back-fill a straight import."""

    __tablename__ = "ehs_submissions"

    id = Column(Integer, primary_key=True)
    submission_id = Column(String(64), unique=True, nullable=False, index=True)  # e.g. TBT-20260723-101530-4821
    form_id = Column(String(64), nullable=False, index=True)     # e.g. "toolbox"
    form_code = Column(String(16), nullable=False)               # e.g. "TBT"
    form_title = Column(String(200), nullable=False)

    submitted_by_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    submitted_by_name = Column(String(200), nullable=False)
    submitted_by_email = Column(String(200), nullable=True)
    submitted_at_ist = Column(String(32), nullable=False)        # "YYYY-MM-DD HH:MM:SS" IST

    fields = Column(JSON, default=dict)       # {field_key: value}
    checklist = Column(JSON, default=list)    # [{result, remarks}, ...] aligned to form checklist
    photos = Column(JSON, default=dict)       # {"fields": {key: [{filename, path, webUrl}]}, "checklist": {idx: [...]}}

    status = Column(String(16), default="pending", nullable=False, index=True)  # pending/approved/rejected

    # Approval workflow
    reviewed_by_name = Column(String(200), nullable=True)
    reviewed_by_email = Column(String(200), nullable=True)
    reviewed_at_ist = Column(String(32), nullable=True)
    edits_made = Column(Text, nullable=True)          # audit trail "field: 'old' → 'new'; ..."
    reject_reason = Column(Text, nullable=True)
    pdf_web_url = Column(Text, nullable=True)         # link to the approval PDF in OneDrive

    created_at = Column(DateTime, default=datetime.utcnow)

    submitted_by = relationship("Employee", foreign_keys=[submitted_by_id])


# ============================================================
# Expense module (Phase 2) — Metfraa-only port of bsg-portal
# ============================================================

class ExpenseProject(Base):
    __tablename__ = "expense_projects"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), nullable=True)
    name = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExpenseEmployeeMeta(Base):
    """Expense-policy level per employee (L1/L2/L3). Separate table so no
    ALTER on the shared employees table is needed. Missing row = L1."""

    __tablename__ = "expense_employee_meta"

    employee_id = Column(Integer, ForeignKey("employees.id"), primary_key=True)
    level = Column(String(8), default="L1", nullable=False)


class ExpenseSubmission(Base):
    __tablename__ = "expense_submissions"

    id = Column(Integer, primary_key=True)
    reference = Column(String(40), unique=True, nullable=False, index=True)   # MET-LTA-260723-A4F7
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    employee_name = Column(String(200), nullable=False)
    employee_email = Column(String(200), nullable=True)
    employee_level = Column(String(8), default="L1")
    form_type = Column(String(32), nullable=False, index=True)                # met_local | met_cab | ...
    period = Column(String(7), nullable=True, index=True)                     # YYYY-MM
    payload = Column(JSON, default=dict)                                      # validated form data (source of truth)
    total_amount = Column(Float, default=0.0, nullable=False)
    # pending | approved | draft (returned for edit) | rejected |
    # advance_approved | settlement_pending | settled | settlement_rejected
    status = Column(String(24), default="pending", nullable=False, index=True)

    reviewed_by = Column(String(200), nullable=True)
    reviewed_at_ist = Column(String(32), nullable=True)
    review_note = Column(Text, nullable=True)
    changes_required = Column(Text, nullable=True)   # reject-to-draft message
    returned_at_ist = Column(String(32), nullable=True)

    # Travel-advance settlement (Phase 2B UI; columns ready)
    actuals = Column(JSON, nullable=True)
    settled_at_ist = Column(String(32), nullable=True)
    settlement_reviewed_by = Column(String(200), nullable=True)
    settlement_note = Column(Text, nullable=True)

    pdf_web_url = Column(Text, nullable=True)
    submitted_at_ist = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee", foreign_keys=[employee_id])
    attachments = relationship("ExpenseAttachment", back_populates="submission", cascade="all, delete-orphan")


class ExpenseAttachment(Base):
    """Bill / receipt uploaded with a submission. File lives in OneDrive."""

    __tablename__ = "expense_attachments"

    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("expense_submissions.id"), nullable=False, index=True)
    filename = Column(String(300), nullable=False)
    onedrive_path = Column(Text, nullable=False)
    web_url = Column(Text, nullable=True)
    mime_type = Column(String(100), default="image/jpeg")
    size_bytes = Column(Integer, default=0)
    row_idx = Column(Integer, nullable=True)          # DTR: which entry this bill belongs to
    label = Column(String(200), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("ExpenseSubmission", back_populates="attachments")


class ExpenseMonthlyPayment(Base):
    """One row per (employee, year, month) once HR marks the payout complete."""

    __tablename__ = "expense_monthly_payments"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    amount_paid = Column(Float, nullable=False)
    paid_by = Column(String(200), nullable=False)
    paid_at_ist = Column(String(32), nullable=False)

    __table_args__ = (UniqueConstraint("employee_id", "year", "month", name="uq_emp_month_payment"),)
