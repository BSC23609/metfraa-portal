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
