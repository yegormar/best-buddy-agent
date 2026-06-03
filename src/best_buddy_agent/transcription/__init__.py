"""Local speech-to-text (faster-whisper) for inbound Telegram voice."""

from .service import configure_stt, is_configured, transcribe_bytes, transcribe_file
from .startup import TranscriptionStartupError, resolve_effective_device

__all__ = [
    "TranscriptionStartupError",
    "configure_stt",
    "is_configured",
    "resolve_effective_device",
    "transcribe_bytes",
    "transcribe_file",
]
