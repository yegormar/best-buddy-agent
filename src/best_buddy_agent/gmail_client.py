"""Gmail API client — OAuth and read/draft helpers (ported from Thoth, no send)."""

from __future__ import annotations

import base64
import email.encoders
import email.mime.base
import email.mime.multipart
import email.mime.text
import json
import logging
import mimetypes
import os
import pathlib
from email.utils import parseaddr
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = pathlib.Path(
    os.environ.get("BEST_BUDDY_AGENT_DATA_DIR", pathlib.Path.home() / ".best_buddy_agent")
)
GMAIL_DIR = _DATA_DIR / "gmail"
DEFAULT_CREDENTIALS_PATH = GMAIL_DIR / "credentials.json"
DEFAULT_TOKEN_PATH = GMAIL_DIR / "token.json"

# Read + compose (drafts). No send tool is exposed to the agent.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


class GmailError(Exception):
    """Raised when Gmail is unavailable or the API call fails."""


def ensure_gmail_dir() -> None:
    GMAIL_DIR.mkdir(parents=True, exist_ok=True)


def credentials_path(path: str | Path | None) -> Path:
    if path:
        p = Path(path).expanduser()
        return p.resolve() if p.is_absolute() else p.resolve()
    return DEFAULT_CREDENTIALS_PATH.resolve()


def token_path(path: str | Path | None) -> Path:
    if path:
        p = Path(path).expanduser()
        return p.resolve() if p.is_absolute() else p.resolve()
    return DEFAULT_TOKEN_PATH.resolve()


def has_credentials(credentials: str | Path | None = None) -> bool:
    return credentials_path(credentials).is_file()


def has_token(token: str | Path | None = None) -> bool:
    return token_path(token).is_file()


def check_token_health(token: str | Path | None = None) -> tuple[str, str]:
    """Return (status, detail): valid, refreshed, expired, missing, error."""
    tp = token_path(token)
    if not tp.is_file():
        return ("missing", "No token file — run best-buddy-agent-gmail-auth")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(tp), scopes=GMAIL_SCOPES)
        if creds.valid:
            return ("valid", "Token is valid")
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                tp.write_text(creds.to_json())
                return ("refreshed", "Token refreshed successfully")
            except Exception as exc:
                err = str(exc).lower()
                if "invalid_grant" in err or "revoked" in err:
                    return ("expired", "Refresh token revoked — re-run best-buddy-agent-gmail-auth")
                return ("error", f"Refresh failed: {exc}")
        return ("expired", "Token expired — re-run best-buddy-agent-gmail-auth")
    except Exception as exc:
        return ("error", f"Token check failed: {exc}")


def run_oauth_flow(
    *,
    credentials: str | Path | None = None,
    token: str | Path | None = None,
) -> Path:
    """Open browser OAuth consent; write token JSON. Returns token path."""
    creds_file = credentials_path(credentials)
    if not creds_file.is_file():
        raise GmailError(f"credentials.json not found: {creds_file}")

    from google_auth_oauthlib.flow import InstalledAppFlow

    ensure_gmail_dir()
    tp = token_path(token)
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)
    tp.write_text(creds.to_json())
    return tp


def build_gmail_service(
    *,
    credentials: str | Path | None = None,
    token: str | Path | None = None,
):
    """Build authenticated Gmail API v1 service."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds_file = credentials_path(credentials)
    tp = token_path(token)
    if not creds_file.is_file():
        raise GmailError(f"Gmail credentials missing: {creds_file}")
    if not tp.is_file():
        raise GmailError("Gmail not authenticated — run best-buddy-agent-gmail-auth")

    creds = Credentials.from_authorized_user_file(str(tp), scopes=GMAIL_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tp.write_text(creds.to_json())
        else:
            raise GmailError("Gmail token invalid — re-run best-buddy-agent-gmail-auth")

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _headers_dict(msg: dict) -> dict[str, str]:
    return {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
        if h.get("name")
    }


def _extract_message_body(msg: dict, *, max_chars: int = 30_000) -> str:
    body = ""
    payload = msg.get("payload", {})
    if payload.get("body", {}).get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    elif payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break
        if not body:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                    break
    if len(body) > max_chars:
        return body[:max_chars] + f"\n\n[Truncated: first {max_chars} chars shown]"
    return body


def _message_summary(msg: dict) -> dict[str, Any]:
    headers = _headers_dict(msg)
    return {
        "id": msg["id"],
        "threadId": msg.get("threadId", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "labels": msg.get("labelIds", []),
    }


def search_messages(service, query: str, *, max_results: int = 10) -> str:
    q = (query or "").strip()
    if not q:
        raise GmailError("query is required (Gmail search syntax, e.g. is:unread newer_than:7d)")
    max_results = max(1, min(int(max_results), 50))
    results = (
        service.users()
        .messages()
        .list(userId="me", q=q, maxResults=max_results)
        .execute()
    )
    metas = results.get("messages") or []
    if not metas:
        return (
            "No emails were found matching that query. "
            "The inbox search returned zero results."
        )
    output = []
    for meta in metas:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=meta["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            .execute()
        )
        output.append(_message_summary(msg))
    return json.dumps(output, ensure_ascii=False, indent=2)


def get_message(service, message_id: str) -> str:
    mid = (message_id or "").strip()
    if not mid:
        raise GmailError("message_id is required")
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=mid, format="full")
        .execute()
    )
    headers = _headers_dict(msg)
    result = {
        "id": msg["id"],
        "threadId": msg.get("threadId", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "labels": msg.get("labelIds", []),
        "body": _extract_message_body(msg),
    }
    if not result["body"].strip():
        return "No message content was returned."
    return json.dumps(result, ensure_ascii=False, indent=2)


def get_thread(service, thread_id: str) -> str:
    tid = (thread_id or "").strip()
    if not tid:
        raise GmailError("thread_id is required")
    thread = (
        service.users()
        .threads()
        .get(userId="me", id=tid, format="full")
        .execute()
    )
    messages = thread.get("messages") or []
    if not messages:
        return "No thread content was returned."
    summaries = [_message_summary(m) for m in messages]
    for i, m in enumerate(messages):
        summaries[i]["body"] = _extract_message_body(m, max_chars=8_000)
    return json.dumps(
        {"threadId": tid, "messages": summaries},
        ensure_ascii=False,
        indent=2,
    )


def _resolve_attachment(path: str, files_root: Path) -> str:
    p = Path(path.strip())
    if not p.is_absolute():
        p = (files_root / p).resolve()
    else:
        p = p.resolve()
    if p.is_file():
        return str(p)
    return path


def _build_mime_message(
    body: str,
    to: str | list[str],
    subject: str,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    attachments: list[str] | None = None,
    *,
    files_root: Path,
) -> email.mime.multipart.MIMEMultipart:
    mime = email.mime.multipart.MIMEMultipart()
    mime.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

    def _fmt_addrs(val: str | list[str]) -> str:
        if isinstance(val, list):
            return ", ".join(val)
        return val

    mime["To"] = _fmt_addrs(to)
    mime["Subject"] = subject
    if cc:
        mime["Cc"] = _fmt_addrs(cc)
    if bcc:
        mime["Bcc"] = _fmt_addrs(bcc)

    for fp in attachments or []:
        resolved = _resolve_attachment(fp, files_root)
        if not os.path.isfile(resolved):
            logger.warning("Attachment not found, skipping: %s", fp)
            continue
        content_type, _ = mimetypes.guess_type(resolved)
        if content_type is None:
            content_type = "application/octet-stream"
        main_type, sub_type = content_type.split("/", 1)
        with open(resolved, "rb") as f:
            part = email.mime.base.MIMEBase(main_type, sub_type)
            part.set_payload(f.read())
        email.encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=os.path.basename(resolved),
        )
        mime.attach(part)
    return mime


def create_draft(
    service,
    *,
    message: str,
    to: str,
    subject: str,
    cc: str = "",
    bcc: str = "",
    attachments: str = "",
    files_root: Path,
) -> str:
    if not (message or "").strip():
        raise GmailError("message body is required")
    if not (to or "").strip():
        raise GmailError("to is required")
    if not (subject or "").strip():
        raise GmailError("subject is required")

    to_addrs = [a.strip() for a in to.split(",") if a.strip()]
    if not to_addrs:
        raise GmailError("to must include at least one email address")
    for addr in to_addrs:
        _, parsed = parseaddr(addr)
        if not parsed or "@" not in parsed:
            raise GmailError(f"Invalid recipient address: {addr!r}")

    cc_list = [a.strip() for a in cc.split(",") if a.strip()] if cc else None
    bcc_list = [a.strip() for a in bcc.split(",") if a.strip()] if bcc else None
    att_list = [a.strip() for a in attachments.split(",") if a.strip()] if attachments else None

    mime = _build_mime_message(
        message.strip(),
        to_addrs,
        subject.strip(),
        cc_list,
        bcc_list,
        att_list,
        files_root=files_root,
    )
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )
    att_note = ""
    if att_list:
        resolved = [
            _resolve_attachment(a, files_root)
            for a in att_list
            if os.path.isfile(_resolve_attachment(a, files_root))
        ]
        if resolved:
            att_note = f" with {len(resolved)} attachment(s)"
    return f"Draft created{att_note}. Draft id: {draft['id']}"
