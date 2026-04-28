import logging
import requests

from app.config import settings

logger = logging.getLogger(__name__)

MAILERSEND_API_URL = "https://api.mailersend.com/v1/email"


def send_verification_email(to_email: str, token: str) -> None:
    verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"

    if not settings.MAILERSEND_API_KEY or not settings.MAILERSEND_FROM:
        logger.warning(
            "Email not configured — verification link for %s: %s",
            to_email, verification_url
        )
        return

    payload = {
        "from": {"email": settings.MAILERSEND_FROM, "name": "IskoMo"},
        "to": [{"email": to_email}],
        "subject": "Verify your IskoMo email",
        "html": f"""
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
    }

    try:
        response = requests.post(
            MAILERSEND_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.MAILERSEND_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        response.raise_for_status()
        logger.info("Verification email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send verification email to %s: %s", to_email, exc)
        raise RuntimeError(
            "Could not send verification email. Please try again later."
        ) from exc
