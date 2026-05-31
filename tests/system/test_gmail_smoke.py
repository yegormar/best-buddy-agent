"""Gmail draft smoke test — uses Gmail API directly (safe, no agent loop)."""

from __future__ import annotations

import pytest

from .helpers import delete_drafts_by_subject, find_draft_ids_by_subject

pytestmark = [pytest.mark.system, pytest.mark.gmail]


@pytest.fixture
def draft_subject(expectations):
    subject = (expectations.get("gmail") or {}).get("subject") or "[BB-SYSTEM-TEST] smoke"
    return subject


@pytest.fixture(autouse=True)
def cleanup_drafts(system_config, expectations, draft_subject):
    gmail_cfg = expectations.get("gmail") or {}
    if not gmail_cfg.get("cleanup", True):
        yield
        return
    delete_drafts_by_subject(system_config, draft_subject)
    yield
    delete_drafts_by_subject(system_config, draft_subject)


def test_gmail_create_draft(system_config, expectations, require_gmail, draft_subject):
    """Verify Gmail OAuth + draft API. Intentionally bypasses the agent — see SYSTEM_TESTS.md."""
    from best_buddy_agent.tools import gmail_tools as gt

    gmail_cfg = expectations.get("gmail") or {}
    body = (gmail_cfg.get("draft_body") or "Automated system test draft. Do not send.").strip()
    to_addr = (gmail_cfg.get("draft_to") or "markovyegor7@gmail.com").strip()

    before = find_draft_ids_by_subject(system_config, draft_subject)
    result = gt.create_gmail_draft(
        system_config,
        body,
        to_addr,
        draft_subject,
    )
    after = find_draft_ids_by_subject(system_config, draft_subject)

    assert "Draft created" in result, result
    assert len(after) > len(before), f"Expected draft with subject {draft_subject!r}"
