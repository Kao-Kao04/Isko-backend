import asyncio
import logging
import resend

from app.config import settings

logger = logging.getLogger(__name__)


async def _send(to_email: str, subject: str, html: str) -> None:
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — email to %s skipped. Subject: %s", to_email, subject)
        return

    resend.api_key = settings.RESEND_API_KEY
    try:
        await asyncio.to_thread(resend.Emails.send, {
            "from": settings.RESEND_FROM or "IskoMo <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        })
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc)
        raise RuntimeError("Could not send email. Please try again later.") from exc


async def send_reset_email(to_email: str, reset_url: str) -> None:
    logger.info("Password reset link for %s: %s", to_email, reset_url)
    await _send(
        to_email=to_email,
        subject="Reset your IskoMo password",
        html=f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
            <h2 style="color: #800000;">Reset your password</h2>
            <p>Click the button below to set a new password. This link expires in 30 minutes.</p>
            <a href="{reset_url}" style="display: inline-block; padding: 12px 28px;
               background: #800000; color: white; text-decoration: none; border-radius: 8px;
               font-weight: bold; margin: 16px 0;">
                Reset Password
            </a>
            <p style="color: #6b7280; font-size: 13px; margin-top: 24px;">
                If you did not request this, ignore this email.
            </p>
        </div>
        """,
    )


async def send_application_status_email(to_email: str, scholarship_name: str, status: str, remarks: str | None = None) -> None:
    if status == "rejected":
        subject = f"Application for {scholarship_name} — Not Approved"
        body_line = "Unfortunately, your application was not approved."
    elif status == "incomplete":
        subject = f"Action Required: Application for {scholarship_name}"
        body_line = "Your application requires additional documents or corrections before it can be reviewed."
    else:
        return  # approved notifications are celebratory — keep in-app only for now

    remarks_block = (
        f'<p style="margin-top:12px;"><strong>Remarks:</strong> {remarks}</p>'
        if remarks else ""
    )
    await _send(
        to_email=to_email,
        subject=subject,
        html=f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
            <h2 style="color: #800000;">IskoMo Scholarship Update</h2>
            <p>{body_line}</p>
            <p><strong>Scholarship:</strong> {scholarship_name}</p>
            {remarks_block}
            <p style="color: #6b7280; font-size: 13px; margin-top: 24px;">
                Log in to <a href="{settings.FRONTEND_URL}">IskoMo</a> to view your application details.
            </p>
        </div>
        """,
    )


async def send_scholar_terminated_email(to_email: str, reason: str | None = None) -> None:
    reason_block = (
        f'<p style="margin-top:12px;"><strong>Reason:</strong> {reason}</p>'
        if reason else ""
    )
    await _send(
        to_email=to_email,
        subject="Important: Your IskoMo Scholarship Has Been Terminated",
        html=f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
            <h2 style="color: #800000;">Scholarship Termination Notice</h2>
            <p>Your scholarship has been terminated by the Office of Scholarship and Financial Assistance (OSFA).</p>
            {reason_block}
            <p>If you believe this is in error or would like to file an appeal, please contact the OSFA directly
               or log in to <a href="{settings.FRONTEND_URL}">IskoMo</a> to submit an appeal.</p>
            <p style="color: #6b7280; font-size: 13px; margin-top: 24px;">
                Polytechnic University of the Philippines — Office of Scholarship and Financial Assistance (OSFA)<br>
                W-119 PUP A. Mabini Campus, Anonas Street, Sta. Mesa, Manila<br>
                Tel: 5335-1764 | 5335-1787 | 5335-1777 Local 339 | scholarship@pup.edu.ph
            </p>
        </div>
        """,
    )


async def send_reminder_email(to_email: str, student_name: str, scholarship_name: str, reminder_type: str) -> None:
    messages = {
        "schedule_interview": (
            f"Action Required: Schedule Your Interview — {scholarship_name}",
            f"Hi {student_name}, your application for <strong>{scholarship_name}</strong> is ready for interview scheduling. "
            f"Please log in to IskoMo and select your preferred interview slot as soon as possible.",
        ),
        "submit_revision": (
            f"Action Required: Resubmit Documents — {scholarship_name}",
            f"Hi {student_name}, OSFA has requested revisions on your application for <strong>{scholarship_name}</strong>. "
            f"Please log in to IskoMo and re-upload your documents to continue.",
        ),
        "submit_completion": (
            f"Action Required: Submit Completion Documents — {scholarship_name}",
            f"Hi {student_name}, congratulations on your scholarship approval for <strong>{scholarship_name}</strong>! "
            f"Please log in to IskoMo and submit your completion requirements to finalize your scholar onboarding.",
        ),
        "deadline_approaching": (
            f"Reminder: Scholarship Deadline Approaching — {scholarship_name}",
            f"Hi {student_name}, the application deadline for <strong>{scholarship_name}</strong> is approaching. "
            f"Make sure your application is complete and all required documents are uploaded.",
        ),
    }
    subject, body = messages.get(reminder_type, (f"IskoMo Reminder — {scholarship_name}", f"Hi {student_name}, you have a pending action on your IskoMo application."))
    await _send(
        to_email=to_email,
        subject=subject,
        html=f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
            <h2 style="color: #800000;">IskoMo — Action Required</h2>
            <p>{body}</p>
            <a href="{settings.FRONTEND_URL}/student/applications" style="display: inline-block; padding: 12px 28px;
               background: #800000; color: white; text-decoration: none; border-radius: 8px;
               font-weight: bold; margin: 16px 0;">
                View My Application
            </a>
            <p style="color: #6b7280; font-size: 13px; margin-top: 24px;">
                Polytechnic University of the Philippines — Office of Scholarship and Financial Assistance (OSFA)<br>
                W-119 PUP A. Mabini Campus, Anonas Street, Sta. Mesa, Manila<br>
                Tel: 5335-1764 | 5335-1787 | 5335-1777 Local 339 | scholarship@pup.edu.ph
            </p>
        </div>
        """,
    )


async def send_verification_email(to_email: str, token: str) -> None:
    verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    logger.info("Verification link for %s: %s", to_email, verification_url)
    await _send(
        to_email=to_email,
        subject="Verify your IskoMo email",
        html=f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
            <h2 style="color: #800000;">Verify your IskoMo account</h2>
            <p>Click the button below to verify your email and continue your registration.</p>
            <a href="{verification_url}" style="display: inline-block; padding: 12px 28px;
               background: #800000; color: white; text-decoration: none; border-radius: 8px;
               font-weight: bold; margin: 16px 0;">
                Verify Email
            </a>
            <p style="color: #6b7280; font-size: 13px; margin-top: 24px;">
                This link expires in 24 hours. If you did not request this, ignore this email.
            </p>
        </div>
        """,
    )
