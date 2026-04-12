"""Email sending via SMTP."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import emails
from jinja2 import Template

from app import config

logger = logging.getLogger(__name__)


def render_email_template(*, template_name: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 email template."""
    template_path = Path(__file__).parent / "templates" / template_name
    template_str = template_path.read_text()
    html_content = Template(template_str).render(context)
    return html_content


def send_email(
    *,
    email_to: str,
    subject: str,
    html_content: str,
) -> None:
    """Send an email via SMTP."""
    if not config.EMAILS_ENABLED:
        logger.warning("Emails disabled — skipping send to %s", email_to)
        return

    message = emails.Message(
        subject=subject,
        html=html_content,
        mail_from=(config.EMAILS_FROM_NAME, config.EMAILS_FROM_EMAIL),
    )
    smtp_options: dict[str, Any] = {
        "host": config.SMTP_HOST,
        "port": config.SMTP_PORT,
    }
    if config.SMTP_TLS:
        smtp_options["tls"] = True
    elif config.SMTP_SSL:
        smtp_options["ssl"] = True
    if config.SMTP_USER:
        smtp_options["user"] = config.SMTP_USER
    if config.SMTP_PASSWORD:
        smtp_options["password"] = config.SMTP_PASSWORD

    response = message.send(to=email_to, smtp=smtp_options)
    logger.info("send email result: %s — to=%s", response, email_to)


def generate_setup_otp_email(email_to: str, otp: str) -> tuple[str, str]:
    """Generate the OTP setup email content. Returns (subject, html_content)."""
    html_content = render_email_template(
        template_name="setup_otp.html",
        context={"otp": otp, "email": email_to},
    )
    subject = "Logios Brain — Your verification code"
    return subject, html_content
