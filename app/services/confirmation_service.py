"""Delivery of opt-in email-confirmation links for inconclusive SMTP checks."""
from __future__ import annotations

import os
from email.message import EmailMessage
import aiosmtplib


async def send_confirmation_email(recipient: str, token: str) -> None:
    host = os.getenv("OUTBOUND_SMTP_HOST")
    sender = os.getenv("OUTBOUND_SMTP_FROM")
    if not host or not sender:
        raise RuntimeError("Confirmation delivery is not configured.")
    base_url = os.getenv("PUBLIC_APP_URL", "http://localhost:8000").rstrip("/")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "Confirm your email address"
    message.set_content(
        "Confirm your email address to activate your account:\n\n"
        f"{base_url}/confirm-email?token={token}\n\n"
        "This link expires in 24 hours."
    )
    await aiosmtplib.send(
        message,
        hostname=host,
        port=int(os.getenv("OUTBOUND_SMTP_PORT", "587")),
        username=os.getenv("OUTBOUND_SMTP_USERNAME") or None,
        password=os.getenv("OUTBOUND_SMTP_PASSWORD") or None,
        start_tls=os.getenv("OUTBOUND_SMTP_STARTTLS", "true").lower() == "true",
        timeout=10,
    )
