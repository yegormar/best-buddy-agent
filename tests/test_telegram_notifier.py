import asyncio

import pytest


def test_send_proactive_noop_when_unregistered():
    from best_buddy_agent.notifications.telegram_notifier import send_proactive

    send_proactive("hello")  # should not raise


def test_make_notifier_delegates(monkeypatch):
    from best_buddy_agent.notifications import telegram_notifier as tn

    calls: list[str] = []
    monkeypatch.setattr(tn, "send_proactive", lambda msg, **kw: calls.append(msg))
    tn.make_notifier()("hello")
    assert calls == ["hello"]


def test_send_async_direct():
    from best_buddy_agent.notifications import telegram_notifier as tn

    sent: list[str] = []

    class FakeBot:
        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            sent.append(text)

    loop = asyncio.new_event_loop()
    try:
        tn.register_telegram_notifier(FakeBot(), loop, chat_id=1)
        loop.run_until_complete(tn._send_async("direct"))
        assert sent == ["direct"]
    finally:
        loop.close()
