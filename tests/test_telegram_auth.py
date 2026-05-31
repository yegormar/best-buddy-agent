from best_buddy_agent.channels.telegram import (
    default_thread_id,
    is_authorized,
    new_thread_id,
)


def test_is_authorized_matching_user():
    assert is_authorized(12345, 12345) is True


def test_is_authorized_rejects_other_user():
    assert is_authorized(99999, 12345) is False


def test_is_authorized_rejects_missing():
    assert is_authorized(None, 12345) is False
    assert is_authorized(1, None) is False


def test_default_thread_id():
    assert default_thread_id(42) == "telegram:dm:42"


def test_new_thread_id_has_suffix():
    tid = new_thread_id(42)
    assert tid.startswith("telegram:dm:42:")
    assert len(tid.split(":")) == 4
