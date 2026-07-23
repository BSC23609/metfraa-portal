"""Email service using aiosmtplib (Office 365 SMTP)."""
import asyncio
import os
from email.message import EmailMessage
import aiosmtplib
from ..config import get_settings

settings = get_settings()

HR_EMAIL = os.getenv("HR_EMAIL", "admin@metfraa.com")


async def send_email_async(
    to: str,
    subject: str,
    html_body: str,
    text_body: str = "",
    cc: list[str] | None = None,
    attachments: list | None = None,
) -> bool:
    """Send an email. Attachments: list of (filename, bytes, mime_type) tuples."""
    if not settings.smtp_user or not settings.smtp_password:
        print(f"[email] SMTP not configured — skipping email to {to}")
        return False

    msg = EmailMessage()
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from}>"
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    if text_body:
        msg.set_content(text_body)
    else:
        msg.set_content("This email has HTML content. Please use an HTML-capable email client.")
    msg.add_alternative(html_body, subtype="html")

    # Attachments
    if attachments:
        for att in attachments:
            try:
                filename, data, mime_type = att
                maintype, _, subtype = mime_type.partition("/")
                if not subtype:
                    maintype, subtype = "application", "octet-stream"
                msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
            except Exception as e:
                print(f"[email] Failed to add attachment: {e}")

    recipients = [to] + (cc or [])

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
            timeout=30,
            recipients=recipients,
        )
        return True
    except Exception as e:
        print(f"[email] Failed to send to {to}: {e}")
        return False


def send_email(to: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Sync wrapper."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Schedule in background
            asyncio.create_task(send_email_async(to, subject, html_body, text_body))
            return True
    except RuntimeError:
        pass
    return asyncio.run(send_email_async(to, subject, html_body, text_body))


def reminder_email_html(employee_name: str, base_url: str) -> str:
    return f"""
    <html><body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #f3f4f6; padding: 24px;">
      <div style="max-width: 560px; margin: auto; background: white; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
        <div style="background: #0a0a0a; padding: 16px 24px; border-bottom: 3px solid #3B82F6;">
          <div style="color: white; font-size: 18px; font-weight: bold; letter-spacing: 1px;">METFRAA</div>
          <div style="color: #9ca3af; font-size: 11px;">Steeling the Future</div>
        </div>
        <div style="padding: 28px 24px;">
          <h2 style="margin: 0 0 12px; color: #0a0a0a;">Daily KPI reminder</h2>
          <p style="color: #374151; line-height: 1.5;">Hi {employee_name},</p>
          <p style="color: #374151; line-height: 1.5;">
            This is your end-of-day reminder to log today's KPI entries.
            Please record your work, leave, or off-day status before midnight.
          </p>
          <a href="{base_url}/"
             style="display: inline-block; background: #3B82F6; color: white;
                    padding: 12px 22px; text-decoration: none; border-radius: 6px;
                    font-weight: 600; margin-top: 12px;">
            Open KPI Tracker
          </a>
          <p style="color: #6b7280; font-size: 12px; margin-top: 32px;">
            Submissions can still be back-filled but cannot be edited once locked.
          </p>
        </div>
        <div style="background: #f9fafb; padding: 12px 24px; color: #6b7280; font-size: 11px; text-align: center;">
          Metfraa Steel Buildings Pvt. Ltd.
        </div>
      </div>
    </body></html>
    """


def missed_day_email_html(employee_name: str, missed_date: str, base_url: str) -> str:
    return f"""
    <html><body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #f3f4f6; padding: 24px;">
      <div style="max-width: 560px; margin: auto; background: white; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
        <div style="background: #0a0a0a; padding: 16px 24px; border-bottom: 3px solid #EF4444;">
          <div style="color: white; font-size: 18px; font-weight: bold; letter-spacing: 1px;">METFRAA</div>
          <div style="color: #9ca3af; font-size: 11px;">Steeling the Future</div>
        </div>
        <div style="padding: 28px 24px;">
          <h2 style="margin: 0 0 12px; color: #b91c1c;">Missed entry: {missed_date}</h2>
          <p style="color: #374151; line-height: 1.5;">Hi {employee_name},</p>
          <p style="color: #374151; line-height: 1.5;">
            Our system noticed you didn't record an entry for <b>{missed_date}</b>.
            Please log a back-fill entry — work, leave, site/remote, holiday, or Sunday — at your earliest convenience.
          </p>
          <a href="{base_url}/dashboard"
             style="display: inline-block; background: #0a0a0a; color: white;
                    padding: 12px 22px; text-decoration: none; border-radius: 6px;
                    font-weight: 600; margin-top: 12px;">
            Submit back-fill entry
          </a>
        </div>
        <div style="background: #f9fafb; padding: 12px 24px; color: #6b7280; font-size: 11px; text-align: center;">
          Metfraa Steel Buildings Pvt. Ltd.
        </div>
      </div>
    </body></html>
    """


# ============================================================
# PASSWORD RESET REQUEST — Phase 1B
# ============================================================

def _password_reset_request_html(
    employee_name: str,
    employee_code: str,
    reason: str,
    reset_link: str,
    expires_at,
) -> str:
    expiry_str = expires_at.strftime("%d %b %Y, %H:%M UTC") if expires_at else ""
    return f"""
    <html><body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #f3f4f6; padding: 24px;">
      <div style="max-width: 560px; margin: auto; background: white; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
        <div style="background: #0a0a0a; padding: 16px 24px; border-bottom: 3px solid #F59E0B;">
          <div style="color: white; font-size: 18px; font-weight: bold; letter-spacing: 1px;">METFRAA</div>
          <div style="color: #9ca3af; font-size: 11px;">Steeling the Future</div>
        </div>
        <div style="padding: 28px 24px;">
          <h2 style="margin: 0 0 12px; color: #0a0a0a;">Password Reset Request</h2>
          <p style="color: #374151; line-height: 1.5;">
            An employee has requested a password reset. Please review the details below and approve or deny.
          </p>

          <table style="width: 100%; border-collapse: collapse; margin: 20px 0; background: #f9fafb; border-radius: 6px; padding: 12px;">
            <tr>
              <td style="padding: 8px 12px; font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700; width: 40%;">Employee</td>
              <td style="padding: 8px 12px; font-size: 14px; color: #111827; font-weight: 600;">{employee_name}</td>
            </tr>
            <tr>
              <td style="padding: 8px 12px; font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700;">Employee Code</td>
              <td style="padding: 8px 12px; font-size: 14px; color: #111827; font-family: ui-monospace, monospace;">{employee_code}</td>
            </tr>
            <tr>
              <td style="padding: 8px 12px; font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700; vertical-align: top;">Reason</td>
              <td style="padding: 8px 12px; font-size: 14px; color: #374151;">{reason}</td>
            </tr>
            <tr>
              <td style="padding: 8px 12px; font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700;">Link expires</td>
              <td style="padding: 8px 12px; font-size: 13px; color: #6b7280; font-family: ui-monospace, monospace;">{expiry_str}</td>
            </tr>
          </table>

          <a href="{reset_link}"
             style="display: inline-block; background: #1E3A8A; color: white;
                    padding: 12px 24px; text-decoration: none; border-radius: 6px;
                    font-weight: 600;">
            Review & Approve
          </a>

          <p style="color: #6b7280; font-size: 12px; margin-top: 32px; border-top: 1px solid #e5e7eb; padding-top: 16px;">
            Click "Review & Approve" to open the request. You'll be asked to sign in to the KPI Tracker.
            Approving resets the user's password to <b style="font-family: ui-monospace, monospace;">Metfraa@123</b>
            — they'll be forced to change it on next login.
          </p>
        </div>
        <div style="background: #f9fafb; padding: 12px 24px; color: #6b7280; font-size: 11px; text-align: center;">
          Metfraa Steel Buildings Pvt. Ltd.
        </div>
      </div>
    </body></html>
    """


async def send_password_reset_request_email(
    employee_name: str,
    employee_code: str,
    reason: str,
    reset_link: str,
    expires_at,
    hr_email: str | None = None,
) -> bool:
    """Send the password-reset request email to HR (Sheela).

    Best-effort — logs and returns False on failure so the caller can continue.
    """
    to_email = hr_email or HR_EMAIL
    subject = f"Password reset requested — {employee_name} ({employee_code})"
    html = _password_reset_request_html(
        employee_name=employee_name,
        employee_code=employee_code,
        reason=reason,
        reset_link=reset_link,
        expires_at=expires_at,
    )
    return await send_email_async(to=to_email, subject=subject, html_body=html)
