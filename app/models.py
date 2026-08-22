"""SQLAlchemy models for Metfraa KPI Tracker."""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, Boolean, Text, LargeBinary,
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

    # --- Direction & bonus (Phase 6) ---
    # direction: "higher_better" (default) — actual/target × 100
    #            "lower_better"  — target/actual × 100 (fewer complaints = better)
    direction = Column(String(16), nullable=False, default="higher_better")
    # allow_bonus: if True, achievement can exceed 100% (capped at 200%)
    #              if False (default), achievement is capped at 100%
    allow_bonus = Column(Boolean, nullable=False, default=False)

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
    # advance_approved | settlement_pending | settled | settlement_rejected |
    # advance_hr_verified | advance_mgmt_approved | settled_offline
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

    # --- Travel-advance 3-stage chain (source: submissions.advance_stage) ---
    #   'hr_review'    -> status pending
    #   'mgmt_review'  -> status advance_hr_verified
    #   'accounts_pay' -> status advance_mgmt_approved
    advance_stage = Column(String(24), nullable=True, index=True)
    advance_hr_verified_by = Column(String(200), nullable=True)
    advance_hr_verified_at = Column(String(32), nullable=True)
    advance_mgmt_approved_by = Column(String(200), nullable=True)
    advance_mgmt_approved_at = Column(String(32), nullable=True)
    advance_paid_by = Column(String(200), nullable=True)
    advance_paid_at = Column(String(32), nullable=True)

    # Settlement deadline = trip_end_date + 72h. Late settlements still go
    # through; the flag and delta are recorded, not blocked.
    trip_end_date = Column(String(32), nullable=True)
    late_settlement = Column(Boolean, default=False)
    late_hours = Column(Float, nullable=True)
    # Computed when HR approves the settlement (actuals vs advance).
    differential_amount = Column(Float, nullable=True)

    # 1 = period lock waived for this row (set when a consolidated report
    # is rejected and its submissions are returned to the employee).
    deadline_bypass = Column(Boolean, default=False)

    # Dashboard categorisation
    purpose_category = Column(String(32), nullable=True, index=True)
    purpose_other_reason = Column(Text, nullable=True)

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
    # Payment is recorded even if the confirmation email fails — the error
    # is kept here rather than blocking the money workflow.
    email_sent_at = Column(String(32), nullable=True)
    email_error = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("employee_id", "year", "month", name="uq_emp_month_payment"),)


# ============================================================
# Access control (Phase 2C) — roles + module access per employee
# ============================================================

class EmployeeAccess(Base):
    """One row per employee. No row = defaults (all modules visible, no roles;
    legacy employees.is_admin=True still acts as superadmin until a row exists)."""

    __tablename__ = "employee_access"

    employee_id = Column(Integer, ForeignKey("employees.id"), primary_key=True)
    is_superadmin = Column(Boolean, default=False, nullable=False)
    is_hr_admin = Column(Boolean, default=False, nullable=False)
    kpi_admin = Column(Boolean, default=False, nullable=False)
    expense_admin = Column(Boolean, default=False, nullable=False)
    ehs_admin = Column(Boolean, default=False, nullable=False)
    kpi_access = Column(Boolean, default=True, nullable=False)
    expense_access = Column(Boolean, default=True, nullable=False)
    ehs_access = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExpensePeriodOverride(Base):
    """A time-boxed waiver of the monthly period lock.

    employee_id NULL means the override is global (applies to everyone).
    A row is inactive once now() >= expires_at, or once revoked_at is set.
    """
    __tablename__ = "expense_period_overrides"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    period = Column(String(7), nullable=False, index=True)      # YYYY-MM
    expires_at = Column(String(32), nullable=False)
    granted_by = Column(String(200), nullable=False)
    granted_at = Column(String(32), nullable=False)
    revoked_at = Column(String(32), nullable=True)
    revoked_by = Column(String(200), nullable=True)
    reason = Column(Text, nullable=True)

    employee = relationship("Employee", foreign_keys=[employee_id])


class ExpenseConsolidatedReport(Base):
    """One consolidated monthly report per (employee, period).

    Aggregates that employee's approved submissions for the month into a
    single navigable PDF, then runs the HR -> Management -> Accounts chain:
      draft -> pending_hr -> pending_mgmt -> approved (sent to accounts)
      rejected at either stage returns the underlying submissions to the
      employee as draft with deadline_bypass set.
    """
    __tablename__ = "expense_consolidated_reports"
    __table_args__ = (UniqueConstraint("employee_id", "period",
                                       name="uq_expense_consolidated_employee_period"),)

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    period = Column(String(7), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="draft", index=True)
    total_amount = Column(Float, nullable=False, default=0.0)
    submission_count = Column(Integer, nullable=False, default=0)
    submission_ids = Column(JSON, default=list)
    pdf_web_url = Column(Text, nullable=True)      # OneDrive path (Vercel has no disk)
    pdf_page_count = Column(Integer, nullable=True)
    generated_at = Column(String(32), nullable=False)
    generated_by = Column(String(200), nullable=True)   # 'cron' or an admin email

    hr_emailed_at = Column(String(32), nullable=True)
    hr_approved_by = Column(String(200), nullable=True)
    hr_approved_at = Column(String(32), nullable=True)
    hr_rejected_reason = Column(Text, nullable=True)
    mgmt_emailed_at = Column(String(32), nullable=True)
    mgmt_approved_by = Column(String(200), nullable=True)
    mgmt_approved_at = Column(String(32), nullable=True)
    mgmt_rejected_reason = Column(Text, nullable=True)
    accounts_sent_at = Column(String(32), nullable=True)
    accounts_email_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee", foreign_keys=[employee_id])


class ExpensePendingUpload(Base):
    """A bill uploaded before its submission exists.

    The source app wrote these to a mounted disk and kept the path. Vercel
    has no writable disk, so the bytes live here keyed by the SPA's
    upload_token and are moved to OneDrive when the form is submitted.
    Rows are deleted once claimed (or by the cleanup of an abandoned token).
    """
    __tablename__ = "expense_pending_uploads"

    id = Column(Integer, primary_key=True)
    upload_token = Column(String(64), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    filename = Column(String(300), nullable=False)
    mime_type = Column(String(100), default="application/octet-stream")
    size_bytes = Column(Integer, default=0)
    row_idx = Column(Integer, nullable=True)
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee", foreign_keys=[employee_id])


# ===================== Outpass / Gatepass =====================
# Ported from the BSC Tickets Portal for Metfraa. Two differences from BSC,
# both deliberate:
#   * notifications are EMAIL (the portal's SMTP), not WATI WhatsApp
#   * routing uses a per-department approver table, seeded from employees.department

class DeptApprover(Base):
    """Who approves outpasses for a department.

    leave_cover_emp_id is used when the requester ticks "my manager is on
    leave", so a request never stalls because one person is away.
    """
    __tablename__ = "gatepass_dept_approvers"

    department = Column(String(255), primary_key=True)
    head_emp_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    leave_cover_emp_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    head = relationship("Employee", foreign_keys=[head_emp_id])
    leave_cover = relationship("Employee", foreign_keys=[leave_cover_emp_id])


class OutpassRequest(Base):
    """An outpass (leaving, no return expected today) or gatepass (out and back).

    Only a gatepass gets expected_back_at and therefore only a gatepass can go
    overdue. Times are stored as IST display strings plus resolved timestamps,
    matching BSC so the two systems stay legible side by side.
    """
    __tablename__ = "outpass_requests"

    id = Column(Integer, primary_key=True)
    ref_no = Column(String(64), unique=True, nullable=False, index=True)
    type = Column(String(16), nullable=False, default="outpass")   # outpass | gatepass
    on_duty = Column(Boolean, default=False)        # official work vs personal
    req_date = Column(Date, nullable=False)
    requester_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    purpose = Column(Text, nullable=False)
    out_time = Column(String(16))                    # 'HH:MM' as entered
    in_time = Column(String(16))                     # gatepass only

    approver_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    approver_label = Column(String(255))
    manager_on_leave = Column(Boolean, default=False)

    status = Column(String(16), nullable=False, default="pending", index=True)
    actioned_by_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    actioned_by_name = Column(String(255))
    actioned_at_ist = Column(String(32))
    reject_reason = Column(Text)

    # Return tracking (gatepass only)
    expected_back_at = Column(DateTime, nullable=True, index=True)
    returned_at = Column(DateTime, nullable=True, index=True)
    returned_by_name = Column(String(255))
    # How the return was recorded, and whether it was inside the geofence.
    # 'gps' = verified at the gate; 'self' = tapped but location unavailable or
    # too far; 'admin' = recorded on someone's behalf. Kept separate from
    # returned_at so a pass always closes, but an unverified close is visible.
    returned_via = Column(String(16), nullable=True)
    return_verified = Column(Boolean, default=False)
    return_lat = Column(Float, nullable=True)
    return_lng = Column(Float, nullable=True)
    return_accuracy_m = Column(Float, nullable=True)
    return_distance_m = Column(Integer, nullable=True)

    # One-tap WhatsApp approve/reject. The unguessable token IS the
    # authorisation — no login on a phone at a factory gate. Cleared once used.
    action_token = Column(String(64), nullable=True, index=True)
    # Unguessable link to the approved pass PDF, sent to the requester.
    pdf_token = Column(String(64), nullable=True, index=True)
    # One-tap "I'm back" from the return reminder. Minted on approval for a
    # gatepass, cleared once the return is recorded.
    return_token = Column(String(64), nullable=True, index=True)

    # Independent alert stamps — each retries until it actually sends, which is
    # the fix BSC needed when one failing send blocked the others.
    overdue_alert_at = Column(DateTime, nullable=True)   # approver told
    hr_alert_at = Column(DateTime, nullable=True)        # HR told
    requester_reminder_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    requester = relationship("Employee", foreign_keys=[requester_id])
    approver = relationship("Employee", foreign_keys=[approver_id])


class WaLog(Base):
    """Every WATI send attempt, successful or not.

    BSC ran for weeks believing HR alerts were going out; this table is how
    the silence was finally proved and diagnosed. Cheap to write, invaluable.
    """
    __tablename__ = "wa_log"

    id = Column(Integer, primary_key=True)
    phone = Column(String(32))
    template = Column(String(64))
    result = Column(String(24), index=True)   # sent|declined|http_error|error|no_phone|skipped
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
