import logging
import resend

from app.config import settings

logger = logging.getLogger(__name__)


def _send(to_email: str, subject: str, html: str) -> None:
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — email to %s skipped. Subject: %s", to_email, subject)
        return

    resend.api_key = settings.RESEND_API_KEY
    try:
        resend.Emails.send({
            "from": settings.RESEND_FROM or "IskoMo <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        })
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc)
        raise RuntimeError("Could not send email. Please try again later.") from exc


def send_reset_email(to_email: str, reset_url: str) -> None:
    logger.info("Password reset link for %s: %s", to_email, reset_url)
    _send(
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


def send_verification_email(to_email: str, token: str) -> None:
    verification_url = f"{settings.BACKEND_URL}/api/auth/verify-email?token={token}"
    logger.info("Verification link for %s: %s", to_email, verification_url)
    _send(
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
