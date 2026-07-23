"""Effective access resolution for the portal's role model.

Roles: superadmin > hr_admin / per-module admins. Module access flags hide
tiles and block routes. Legacy rule: employees with is_admin=True and NO
employee_access row act as superadmin (so existing admins keep working
until granular roles are assigned via the employee screen).

Note: employees.is_admin is kept in sync as (superadmin OR kpi_admin)
because the existing KPI admin routes check it directly.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import Employee, EmployeeAccess


@dataclass
class Access:
    superadmin: bool = False
    hr_admin: bool = False
    kpi_admin: bool = False
    expense_admin: bool = False
    ehs_admin: bool = False
    kpi_access: bool = True
    expense_access: bool = True
    ehs_access: bool = True

    @property
    def any_admin(self) -> bool:
        return self.superadmin or self.hr_admin or self.kpi_admin or self.expense_admin or self.ehs_admin

    @property
    def can_manage_employees(self) -> bool:
        return self.superadmin or self.hr_admin

    @property
    def can_admin_expense(self) -> bool:
        return self.superadmin or self.hr_admin or self.expense_admin

    @property
    def can_admin_ehs(self) -> bool:
        return self.superadmin or self.ehs_admin

    @property
    def can_admin_kpi(self) -> bool:
        return self.superadmin or self.kpi_admin


def get_access(db: Session, user: Employee) -> Access:
    row = db.query(EmployeeAccess).filter(EmployeeAccess.employee_id == user.id).first()
    if row is None:
        # Legacy fallback: is_admin => superadmin
        return Access(superadmin=bool(user.is_admin))
    return Access(
        superadmin=row.is_superadmin,
        hr_admin=row.is_hr_admin,
        kpi_admin=row.kpi_admin,
        expense_admin=row.expense_admin,
        ehs_admin=row.ehs_admin,
        kpi_access=row.kpi_access,
        expense_access=row.expense_access,
        ehs_access=row.ehs_access,
    )
