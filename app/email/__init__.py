"""Email sending via SMTP."""

from app.email.sender import generate_setup_otp_email, render_email_template, send_email

__all__ = ["send_email", "generate_setup_otp_email", "render_email_template"]
