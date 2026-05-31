"""Context assembly from canonical thread history."""

from __future__ import annotations

from .threads import thread_conversation_rows


def assemble_context(thread_id: str, user_text: str, max_turns: int = 12) -> dict:
    history = thread_conversation_rows(thread_id)
    turns = []
    for m in history[-max_turns:]:
        role = (m.get("role") or "").strip().lower()
        content = (m.get("content") or "").strip()
        if role and content:
            turns.append(f"{role.upper()}: {content}")
    turns.append(f"USER: {user_text}")

    recent_user_messages = [
        m.get("content", "")
        for m in history
        if (m.get("role") or "").strip().lower() == "user"
    ][-3:]

    return {
        "conversation_text": "\n".join(turns),
        "recent_user_messages": recent_user_messages,
        "history": history,
    }
