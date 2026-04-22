import resend
from app.config import settings


def send_verification_email(to_email: str, token: str) -> None:
    resend.api_key = settings.RESEND_API_KEY
    verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    resend.Emails.send({
        "from": settings.EMAIL_FROM,
        "to": to_email,
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
        """
    })
