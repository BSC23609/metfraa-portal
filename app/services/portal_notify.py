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
