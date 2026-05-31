"""Deadline Watch package."""

from .approval import apply_proposal, dismiss_proposal
from .scanner import handle_deadline_callback, register_scan_function, run_scan_once, send_proposal_message

__all__ = [
    "apply_proposal",
    "dismiss_proposal",
    "handle_deadline_callback",
    "register_scan_function",
    "run_scan_once",
    "send_proposal_message",
]
