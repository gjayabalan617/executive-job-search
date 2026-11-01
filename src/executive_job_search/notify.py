"""Optional SMTP notification adapter with a transactional outbox.

Delivery semantics are AT-LEAST-ONCE. If the SMTP server accepts a message but the connection fails before the
client sees the final reply (an *ambiguous* send failure), the outbox row stays 'pending' and the message may be
delivered a second time on retry. This is a deliberate trade-off against silently losing a notification.

Sending is OFF by default: it requires EJS_NOTIFY_SEND_ENABLED=true plus SMTP host/from/to. No email is ever
built or sent when there are zero new qualifying roles.
"""
from __future__ import annotations

import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Callable, Optional

from .config import Settings
from .logs import get_logger
from .store import Store

log = get_logger("notify")

SUBJECT_LINKEDIN = "New Director/VP Roles on LinkedIn"
SUBJECT_EMPLOYER = "New Executive Technology Roles — Employer Direct"


def subject_for(source: str) -> str:
    return SUBJECT_LINKEDIN if source == "linkedin" else SUBJECT_EMPLOYER


def _one_line(row: dict) -> str:
    text = (row.get("match_explanation") or "").strip()
    return (text.split(". ")[0] + ("." if not text.split(". ")[0].endswith(".") else "")) if text else "Strong match on the stated criteria."


def caveats_for(row: dict) -> list[str]:
    out: list[str] = []
    ra = row.get("remote_assessment") or {}
    if ra.get("scope") == "state_restricted":
        out.append("State-restricted remote: " + ", ".join(ra.get("eligible_states") or []))
    if ra.get("travel_flag"):
        out.append("Material travel: " + (ra.get("travel") or ""))
    if row.get("freshness") == "unknown_date":
        out.append("Source posting date unavailable; not confirmed as newly posted.")
    if not (row.get("salary_text") or row.get("salary_max")):
        out.append("Salary not disclosed.")
    if row.get("score_source") != "llm":
        out.append("Deterministic score; operator-reviewed before this notification.")
    return out


def build_entry(row: dict) -> str:
    link = row.get("application_url") or row.get("posting_url")
    lines = [
        f"{row['title']} — {row['company']} — {row.get('location') or 'Location not stated'}",
        f"Fit Score: {row['total_score']:.0f}/100",
        f"Why it fits: {_one_line(row)}",
        f"Apply: {link}",
    ]
    cav = caveats_for(row)
    if cav:
        lines.append("Caveats: " + " | ".join(cav))
    return "\n".join(lines)


class SmtpSender:
    def __init__(self, settings: Settings, factory: Callable[..., smtplib.SMTP] = smtplib.SMTP):
        self.s, self.factory = settings, factory

    def send(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self.s.smtp_from, self.s.smtp_to
        msg.set_content(body)
        with self.factory(self.s.smtp_host, self.s.smtp_port, timeout=30) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            if self.s.smtp_user and self.s.smtp_password:
                smtp.login(self.s.smtp_user, self.s.smtp_password.get_secret_value())
            smtp.send_message(msg)


def process_outbox(store: Store, settings: Settings, now: datetime, sender: Optional[SmtpSender] = None) -> dict:
    due = store.due_outbox(now)
    if not due:
        return {"status": "nothing_to_send", "sent": 0, "failed": 0}
    if not settings.notify_send_enabled:
        return {"status": "disabled: EJS_NOTIFY_SEND_ENABLED is not true; entries remain queued in the outbox", "sent": 0, "failed": 0, "queued": len(due)}
    if not settings.smtp_configured:
        return {"status": "not_configured: SMTP host/from/to missing; entries remain queued", "sent": 0, "failed": 0, "queued": len(due)}
    sender = sender or SmtpSender(settings)
    sent = failed = 0
    by_source: dict[str, list[dict]] = {}
    for e in due:
        by_source.setdefault(e["source"], []).append(e)
    for source, entries in by_source.items():
        ids = [e["id"] for e in entries]
        body = "\n\n".join(e["body"] for e in entries)
        try:
            sender.send(subject_for(source), body)
        except Exception as exc:  # noqa: BLE001 - any send failure is retried with backoff
            attempts = max(e["attempts"] for e in entries) + 1
            nxt = now + timedelta(minutes=min(360, 5 * 2**attempts))
            store.mark_send_failed(ids, f"{type(exc).__name__}: {exc}", now, nxt, settings.notify_max_attempts)
            failed += len(ids)
            log.warning("notification send failed", extra={"ctx": {"entries": len(ids), "error": type(exc).__name__}})
        else:
            store.mark_sent(ids, now)
            sent += len(ids)
    status = f"sent:{sent}" if not failed else f"retry_scheduled:{failed} (sent:{sent})"
    return {"status": status, "sent": sent, "failed": failed}
