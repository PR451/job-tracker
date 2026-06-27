import os
import smtplib
from email.message import EmailMessage


class EmailDeliveryError(Exception):
    pass


def send_password_reset_code(recipient: str, code: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", username or "no-reply@job-tracker.local")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    if not host or not username or not password:
        raise EmailDeliveryError("SMTP settings are not configured.")

    message = EmailMessage()
    message["Subject"] = "Your Job Tracker password reset code"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Use this code to reset your Job Tracker password: "
        f"{code}\n\nThis code expires in 15 minutes."
    )

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
    except Exception as exc:
        raise EmailDeliveryError("Could not send password reset email.") from exc
