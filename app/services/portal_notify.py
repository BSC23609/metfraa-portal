"""Lightweight email notifications for EHS + Expense workflows (Phase 2B).

Uses the existing sync send_email() from the KPI email service via FastAPI
BackgroundTasks — fire-and-forget, a failed email never blocks a workflow.
Configure recipients:
  EXPENSE_HR_EMAIL   (default admin@metfraa.com)  — new expense claims
  EHS_NOTIFY_EMAILS  (default: approver emails)   — new EHS submissions
"""
import logging
import os

log = logging.getLogger(__name__)

BASE = lambda: os.getenv("BASE_URL", "https://app.metfraa.com").rstrip("/")  # noqa: E731


def _send(to: str, subject: str, html: str) -> None:
    if not to:
        return
    try:
        from .email_service import send_email

        send_email(to, subject, html)
        log.info(f"[notify] sent '{subject}' to {to}")
    except Exception as e:
        log.warning(f"[notify] email to {to} failed: {e}")


def _card(title: str, lines: list[str], link: str, link_label: str) -> str:
    rows = "".join(f"<p style='margin:4px 0;color:#333'>{l}</p>" for l in lines)
    return f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;max-width:520px;margin:auto">
      <div style="background:#005B96;color:#fff;padding:14px 18px;border-radius:8px 8px 0 0">
        <b>Metfraa Portal</b></div>
      <div style="border:1px solid #dde3ea;border-top:0;padding:18px;border-radius:0 0 8px 8px">
        <h3 style="margin:0 0 8px;color:#1a2332">{title}</h3>
        {rows}
        <p style="margin-top:14px"><a href="{link}" style="background:#005B96;color:#fff;
          padding:8px 14px;border-radius:6px;text-decoration:none">{link_label}</a></p>
      </div></div>"""


# ---- Expense ----

def notify_expense_submitted(bg, sub, form_title: str) -> None:
    hr = os.getenv("EXPENSE_HR_EMAIL", "admin@metfraa.com")
    bg.add_task(_send, hr, f"[Expense] New claim {sub.reference} — ₹{sub.total_amount:,.2f}",
                _card("New expense claim to review",
                      [f"<b>{sub.employee_name}</b> submitted <b>{form_title}</b>",
                       f"Reference: {sub.reference} · Period: {sub.period or '—'}",
                       f"Amount: ₹{sub.total_amount:,.2f}"],
                      f"{BASE()}/expense/review/{sub.reference}", "Review claim"))


def notify_expense_decision(bg, sub, form_title: str) -> None:
    if not sub.employee_email:
        return
    if sub.status in ("approved", "advance_approved", "settled"):
        title, extra = "Your claim was approved ✅", (sub.review_note or "")
    elif sub.status == "draft":
        title, extra = "Your claim was returned for changes", (sub.changes_required or "")
    elif sub.status == "settlement_rejected":
        title, extra = "Your settlement was returned", (sub.settlement_note or "")
    else:
        title, extra = f"Claim update: {sub.status}", ""
    bg.add_task(_send, sub.employee_email, f"[Expense] {sub.reference}: {title}",
                _card(title,
                      [f"{form_title} · {sub.reference} · ₹{sub.total_amount:,.2f}"]
                      + ([f"<i>{extra}</i>"] if extra else []),
                      f"{BASE()}/expense/review/{sub.reference}", "Open claim"))


# ---- EHS ----

def notify_ehs_submitted(bg, sub) -> None:
    raw = os.getenv("EHS_NOTIFY_EMAILS", "")
    if raw.strip():
        recipients = [e.strip() for e in raw.split(",") if e.strip()]
    else:
        from ..ehs.forms import get_approver_emails

        recipients = get_approver_emails()
    for to in recipients:
        bg.add_task(_send, to, f"[EHS] {sub.form_title} pending approval — {sub.submission_id}",
                    _card("New EHS submission to approve",
                          [f"<b>{sub.submitted_by_name}</b> submitted <b>{sub.form_title}</b>",
                           f"ID: {sub.submission_id} · {sub.submitted_at_ist} IST"],
                          f"{BASE()}/ehs/approvals/{sub.submission_id}", "Review now"))


def notify_ehs_decision(bg, sub) -> None:
    if not sub.submitted_by_email:
        return
    ok = sub.status == "approved"
    bg.add_task(_send, sub.submitted_by_email,
                f"[EHS] {sub.submission_id} {'approved ✅' if ok else 'rejected'}",
                _card("Your EHS submission was " + ("approved" if ok else "rejected"),
                      [f"{sub.form_title} · {sub.submission_id}"]
                      + ([f"<i>Reason: {sub.reject_reason}</i>"] if sub.reject_reason else [])
                      + ([f"PDF: <a href='{sub.pdf_web_url}'>open report</a>"] if sub.pdf_web_url else []),
                      f"{BASE()}/ehs/submissions", "View submissions"))


# ---- Expense parity: advance chain, payments, consolidated reports -------
# Recipients mirror the source's env names and defaults so an existing
# deployment's settings carry over unchanged.

def _hr_email() -> str:
    return os.getenv("CONSOLIDATED_HR_EMAIL", os.getenv("EXPENSE_HR_EMAIL", "admin@metfraa.com"))


def _mgmt_email() -> str:
    return os.getenv("CONSOLIDATED_MGMT_EMAIL", "arasu@metfraa.com")


def _accounts_email() -> str:
    return os.getenv("CONSOLIDATED_ACCOUNTS_EMAIL", "accounts@metfraa.com")


def notify_advance_stage(bg, sub, stage: str) -> None:
    """Each advance stage notifies whoever acts next.

    hr_verified -> Management (Arasu) must approve
    mgmt_approved -> Accounts must pay
    paid -> the employee, who can now settle
    """
    amount = f"₹{(sub.total_amount or 0):,.2f}"
    common = [f"<b>{sub.employee_name}</b> — Travel Advance",
              f"Reference: {sub.reference} · Period: {sub.period or '—'}",
              f"Amount: {amount}"]
    if stage == "hr_verified":
        bg.add_task(_send, _mgmt_email(),
                    f"[Advance] Awaiting your approval — {sub.reference} ({amount})",
                    _card("Travel Advance needs management approval",
                          common + ["HR has verified this advance."],
                          f"{BASE()}/expense/", "Open Expense Portal"))
    elif stage == "mgmt_approved":
        bg.add_task(_send, _accounts_email(),
                    f"[Advance] Approved for payment — {sub.reference} ({amount})",
                    _card("Travel Advance approved — please pay",
                          common + ["Management has approved this advance."],
                          f"{BASE()}/expense/", "Open Expense Portal"))
    elif stage == "paid" and sub.employee_email:
        bg.add_task(_send, sub.employee_email,
                    f"[Advance] Payment released — {sub.reference} ({amount})",
                    _card("Your travel advance has been paid",
                          common + ["Settle it with actuals and bills after your trip."],
                          f"{BASE()}/expense/", "File settlement"))


def notify_payment_marked(bg, employee_email: str, employee_name: str,
                          year: int, month: int, amount: float) -> None:
    if not employee_email:
        return
    bg.add_task(_send, employee_email,
                f"[Expense] Reimbursement paid — {year}-{month:02d} (₹{amount:,.2f})",
                _card("Your monthly reimbursement has been paid",
                      [f"Hi {employee_name},",
                       f"Period: {year}-{month:02d}",
                       f"Amount paid: <b>₹{amount:,.2f}</b>"],
                      f"{BASE()}/expense/", "View claims"))


def notify_consolidated_for_review(bg, report, employee_name: str) -> None:
    bg.add_task(_send, _mgmt_email(),
                f"[Monthly Wrap-up] {employee_name} — {report.period} "
                f"(₹{(report.total_amount or 0):,.2f})",
                _card("Consolidated report awaiting your approval",
                      [f"Employee: <b>{employee_name}</b>",
                       f"Period: {report.period}",
                       f"Claims: {report.submission_count}",
                       f"Total payable: <b>₹{(report.total_amount or 0):,.2f}</b>",
                       f"Sent by: {report.hr_approved_by or '—'}"],
                      f"{BASE()}/expense/", "Review report"))


def notify_consolidated_to_accounts(bg, report, employee_name: str) -> None:
    bg.add_task(_send, _accounts_email(),
                f"[Approved] {employee_name} — {report.period} "
                f"(₹{(report.total_amount or 0):,.2f})",
                _card("Consolidated report approved — ready for payment",
                      [f"Employee: <b>{employee_name}</b>",
                       f"Period: {report.period}",
                       f"Claims: {report.submission_count}",
                       f"Total payable: <b>₹{(report.total_amount or 0):,.2f}</b>",
                       f"Approved by: {report.mgmt_approved_by or '—'}"],
                      f"{BASE()}/expense/", "Open Expense Portal"))
    bg.add_task(_send, _hr_email(),
                f"[Approved · copy] {employee_name} — {report.period}",
                _card("Consolidated report approved",
                      [f"{employee_name} · {report.period} — sent to accounts."],
                      f"{BASE()}/expense/", "Open Expense Portal"))


def notify_consolidated_rejected(bg, report, employee_email: str,
                                 employee_name: str, note: str, returned: int) -> None:
    for to, title in ((employee_email, "Your monthly claims were returned"),
                      (_hr_email(), f"Consolidated report rejected — {employee_name}")):
        if not to:
            continue
        bg.add_task(_send, to,
                    f"[Returned] {employee_name} — {report.period}",
                    _card(title,
                          [f"Period: {report.period}",
                           f"Reason: {note}",
                           f"{returned} claim(s) returned for editing."],
                          f"{BASE()}/expense/", "Open Expense Portal"))
