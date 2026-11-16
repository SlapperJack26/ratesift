"""
Transactional Email Service for Quotelytics Inc.
Supports SMTP delivery (Postmark / Amazon SES ca-central-1 / standard SMTP) in production
and maintains an in-memory outbox for local development and automated test verification.
"""
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

_SENT_EMAILS_OUTBOX: List[Dict[str, Any]] = []
_MAX_OUTBOX_SIZE = 200


def get_base_url() -> str:
    """Returns canonical base URL for links in transactional emails."""
    env_url = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    if os.getenv("APP_ENV", "").lower() == "production":
        return "https://quotelytics.ca"
    return "http://localhost:8000"


def send_transactional_email(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    category: str = "TRANSACTIONAL",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Sends a transactional email via configured SMTP server if SMTP_HOST is set,
    and records the message in the in-memory outbox for inspection/testing.
    """
    recipient = (to_email or "").strip().lower()
    from_addr = os.getenv("SMTP_FROM", "Quotelytics Security <no-reply@quotelytics.ca>")
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

    delivered_via = "outbox_only"
    if smtp_host:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = recipient
        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                if use_tls:
                    server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            delivered_via = "smtp"
        except Exception as exc:
            delivered_via = f"smtp_error:{type(exc).__name__}"

    record = {
        "to": recipient,
        "from": from_addr,
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body or "",
        "category": category,
        "metadata": metadata or {},
        "delivered_via": delivered_via,
        "sent_at": datetime.utcnow().isoformat() + "Z",
    }
    _SENT_EMAILS_OUTBOX.append(record)
    if len(_SENT_EMAILS_OUTBOX) > _MAX_OUTBOX_SIZE:
        del _SENT_EMAILS_OUTBOX[: len(_SENT_EMAILS_OUTBOX) - _MAX_OUTBOX_SIZE]
    return record


def send_password_reset_email(to_email: str, name: str, raw_token: str) -> Dict[str, Any]:
    """Sends a 1-hour single-use password reset link."""
    base_url = get_base_url()
    reset_url = f"{base_url}/reset-password?token={raw_token}"
    display_name = (name or "Broker").strip()

    subject = "Reset your Quotelytics password"
    text_body = (
        f"Hello {display_name},\n\n"
        f"We received a request to reset the password for your Quotelytics account ({to_email}).\n\n"
        f"Use the single-use link below within 60 minutes to set a new password:\n"
        f"{reset_url}\n\n"
        f"If you did not request a password reset, you can safely ignore this email—your password has not been changed.\n\n"
        f"--\n"
        f"Quotelytics Inc. • Deterministic Freight Rating Engine\n"
        f"Ontario, Canada • Canadian Data Residency (WHC)\n"
    )
    html_body = (
        f"<p>Hello {display_name},</p>"
        f"<p>We received a request to reset the password for your Quotelytics account (<strong>{to_email}</strong>).</p>"
        f"<p><a href=\"{reset_url}\">Click here to reset your password</a> (valid for 60 minutes, single-use).</p>"
        f"<p>If you did not request this reset, you can safely ignore this message.</p>"
        f"<hr><p style=\"font-size:11px;color:#64748b;\">Quotelytics Inc. • Ontario, Canada • Canadian Data Residency (WHC)</p>"
    )
    return send_transactional_email(
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        category="PASSWORD_RESET",
        metadata={"reset_url": reset_url, "token": raw_token},
    )


def send_email_verification_email(to_email: str, name: str, raw_token: str) -> Dict[str, Any]:
    """Sends a 24-hour email verification link upon registration or resend request."""
    base_url = get_base_url()
    verify_url = f"{base_url}/api/auth/verify-email?token={raw_token}"
    display_name = (name or "Broker").strip()

    subject = "Verify your Quotelytics email address"
    text_body = (
        f"Welcome to Quotelytics, {display_name}!\n\n"
        f"Please verify your work email address ({to_email}) by clicking the link below within 24 hours:\n"
        f"{verify_url}\n\n"
        f"--\n"
        f"Quotelytics Inc. • Deterministic Freight Rating Engine\n"
        f"Ontario, Canada • Canadian Data Residency (WHC)\n"
    )
    html_body = (
        f"<p>Welcome to Quotelytics, {display_name}!</p>"
        f"<p>Please verify your work email address (<strong>{to_email}</strong>) by clicking the link below:</p>"
        f"<p><a href=\"{verify_url}\">Verify Email Address</a></p>"
        f"<hr><p style=\"font-size:11px;color:#64748b;\">Quotelytics Inc. • Ontario, Canada • Canadian Data Residency (WHC)</p>"
    )
    return send_transactional_email(
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        category="EMAIL_VERIFY",
        metadata={"verify_url": verify_url, "token": raw_token},
    )


def send_support_ticket_confirmation(
    to_email: str, ticket_id: str, subject: str, message: str, category: str = "GENERAL"
) -> Dict[str, Any]:
    """Sends an automated confirmation receipt to the broker upon ticket creation."""
    recipient = (to_email or "").strip().lower()
    email_subject = f"Quotelytics Support Ticket [{ticket_id}]: {subject}"
    text_body = (
        f"Thank you for contacting Quotelytics Support.\n\n"
        f"We have received your ticket [{ticket_id}]. Our Canadian dispatch engineering team will review it and respond within 4 business hours.\n\n"
        f"Ticket Details:\n"
        f"- ID: {ticket_id}\n"
        f"- Category: {category}\n"
        f"- Subject: {subject}\n\n"
        f"Message:\n{message}\n\n"
        f"For urgent dispatch halts during business hours (Mon-Fri 8am-6pm EST), you may also reach our priority hotline at 289-929-8565.\n\n"
        f"--\n"
        f"Quotelytics Support Desk • support@quotelytics.ca\n"
        f"Quotelytics Inc. • Canadian Data Residency (WHC)\n"
    )
    html_body = (
        f"<p>Thank you for contacting Quotelytics Support.</p>"
        f"<p>We have received your ticket <strong>{ticket_id}</strong>. Our Canadian dispatch engineering team will review it and respond within 4 business hours.</p>"
        f"<div style=\"background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px;margin:12px 0;font-size:13px;\">"
        f"<p><strong>Ticket ID:</strong> {ticket_id}<br>"
        f"<strong>Category:</strong> {category}<br>"
        f"<strong>Subject:</strong> {subject}</p>"
        f"<p style=\"white-space:pre-wrap;margin-top:8px;color:#334155;\">{message}</p>"
        f"</div>"
        f"<p>For urgent dispatch halts (Mon-Fri 8am-6pm EST), reach our priority hotline at <strong>289-929-8565</strong>.</p>"
        f"<hr><p style=\"font-size:11px;color:#64748b;\">Quotelytics Inc. • support@quotelytics.ca • Canadian Data Residency (WHC)</p>"
    )
    return send_transactional_email(
        to_email=recipient,
        subject=email_subject,
        text_body=text_body,
        html_body=html_body,
        category="SUPPORT_CONFIRMATION",
        metadata={"ticket_id": ticket_id, "category": category},
    )


def send_support_ticket_admin_notification(
    ticket_id: str,
    user_email: str,
    category: str,
    subject: str,
    message: str,
    browser_info: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatches internal alert to the Quotelytics support desk inbox."""
    admin_inbox = os.getenv("SUPPORT_INBOX_EMAIL", "support@quotelytics.ca").strip()
    email_subject = f"[SUPPORT ALERT] [{ticket_id}] {category}: {subject}"
    text_body = (
        f"New Support Ticket Received:\n\n"
        f"- Ticket ID: {ticket_id}\n"
        f"- From: {user_email}\n"
        f"- User ID: {user_id or 'Anonymous / Unauthenticated'}\n"
        f"- Category: {category}\n"
        f"- Diagnostics: {browser_info or 'N/A'}\n\n"
        f"Subject: {subject}\n\n"
        f"Message:\n{message}\n"
    )
    html_body = (
        f"<h3>New Support Ticket: {ticket_id}</h3>"
        f"<p><strong>From:</strong> {user_email} (User ID: {user_id or 'Anonymous'})<br>"
        f"<strong>Category:</strong> {category}<br>"
        f"<strong>Diagnostics:</strong> {browser_info or 'N/A'}</p>"
        f"<p><strong>Subject:</strong> {subject}</p>"
        f"<div style=\"background:#f8fafc;border:1px solid #e2e8f0;padding:12px;border-radius:6px;\"><pre style=\"white-space:pre-wrap;\">{message}</pre></div>"
    )
    return send_transactional_email(
        to_email=admin_inbox,
        subject=email_subject,
        text_body=text_body,
        html_body=html_body,
        category="SUPPORT_ALERT",
        metadata={"ticket_id": ticket_id, "user_email": user_email, "user_id": user_id},
    )


def send_parcel_deprecation_notice_email(
    to_email: str, name: str, sunset_date_str: str = "January 2027"
) -> Dict[str, Any]:
    """Sends 14-day advance notice of parcel mode deprecation and Skid/LTL freight transition."""
    base_url = get_base_url()
    export_url = f"{base_url}/console/account"
    display_name = (name or "Broker").strip()

    subject = "Important Update: Quotelytics Transition to 100% Skid/LTL Rating Engine"
    text_body = (
        f"Hello {display_name},\n\n"
        f"Quotelytics is transitioning exclusively to Skid and LTL freight rating to ensure 100% mathematical precision and dedicated Canadian freight tariff automation.\n\n"
        f"What this means for your account:\n"
        f"1. Individual parcel rating is deprecated and will sunset on {sunset_date_str}.\n"
        f"2. All shipments should be rated as palletized LTL freight or skid-based tiers.\n"
        f"3. You can export all your current rate sheets and historical data at any time via {export_url}.\n\n"
        f"If you have custom courier agreements or need assistance migrating tariffs, please contact our support desk at support@quotelytics.ca.\n\n"
        f"--\n"
        f"Quotelytics Operations & Compliance Team\n"
        f"Ontario, Canada • Canadian Data Residency (WHC)\n"
    )
    html_body = (
        f"<p>Hello {display_name},</p>"
        f"<p>Quotelytics is transitioning exclusively to <strong>Skid and LTL freight rating</strong> to ensure 100% mathematical precision and dedicated Canadian freight tariff automation.</p>"
        f"<h3>What this means for your account:</h3>"
        f"<ul>"
        f"<li>Individual parcel rating is deprecated and will sunset on <strong>{sunset_date_str}</strong>.</li>"
        f"<li>All shipments should be rated as palletized LTL freight or skid-based tiers.</li>"
        f"<li>You can pre-export all current rate sheets and historical data at any time in <a href=\"{export_url}\">Account Settings → Data Export</a>.</li>"
        f"</ul>"
        f"<p>If you need assistance migrating tariffs, please reach our dispatch team at <a href=\"mailto:support@quotelytics.ca\">support@quotelytics.ca</a>.</p>"
        f"<hr><p style=\"font-size:11px;color:#64748b;\">Quotelytics Inc. • Ontario, Canada • Canadian Data Residency (WHC)</p>"
    )
    return send_transactional_email(
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        category="PARCEL_DEPRECATION_NOTICE",
        metadata={"sunset_date": sunset_date_str},
    )


def get_sent_emails(to_email: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns captured transactional emails from the in-memory outbox (filtered optionally by recipient/category)."""
    results = list(_SENT_EMAILS_OUTBOX)
    if to_email:
        target = to_email.strip().lower()
        results = [m for m in results if m["to"] == target]
    if category:
        results = [m for m in results if m["category"] == category]
    return results


def clear_sent_emails() -> None:
    """Clears the in-memory outbox (used by automated tests)."""
    _SENT_EMAILS_OUTBOX.clear()
