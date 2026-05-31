from best_buddy_agent.channels.telegram_format import MAX_TG_MESSAGE_LEN, split_message


def test_split_short_unchanged():
    text = "hello"
    assert split_message(text) == ["hello"]


def test_split_long_message():
    text = "word " * 900
    chunks = split_message(text, max_len=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_max_len_constant():
    assert MAX_TG_MESSAGE_LEN == 4096
