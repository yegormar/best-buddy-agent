"""Lazy faster-whisper transcription for Telegram voice notes."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .huggingface_env import apply_hf_env
from .startup import run_transcription_startup

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SttRuntime:
    device: str
    model_name: str
    compute_type: str
    transcribe_kwargs: dict[str, Any]
    language: str | None


_runtime: SttRuntime | None = None
_model: Any = None
_model_key: tuple[str, str, str] | None = None


def is_configured() -> bool:
    return _runtime is not None


def configure_stt(
    *,
    device_mode: str,
    model_name: str,
    compute_type_cpu: str,
    compute_type_cuda: str,
    transcribe_kwargs: dict[str, Any],
    hf_home: str,
    hf_hub_cache: str,
    language: str | None = None,
) -> SttRuntime:
    """Apply HF env, validate STT at startup, store runtime settings (idempotent)."""
    global _runtime, _model, _model_key

    apply_hf_env(hf_home, hf_hub_cache)
    effective, compute_type = run_transcription_startup(
        device_mode=device_mode,
        model_name=model_name,
        compute_type_cpu=compute_type_cpu,
        compute_type_cuda=compute_type_cuda,
        transcribe_kwargs=transcribe_kwargs,
        hf_home=hf_home,
        hf_hub_cache=hf_hub_cache,
    )
    lang = (language or "").strip() or None
    new_runtime = SttRuntime(
        device=effective,
        model_name=model_name,
        compute_type=compute_type,
        transcribe_kwargs=dict(transcribe_kwargs),
        language=lang,
    )
    key = (model_name, effective, compute_type)
    if _runtime != new_runtime:
        _runtime = new_runtime
        _model = None
        _model_key = None
    elif _model_key != key:
        _model = None
        _model_key = None
    return _runtime


def _get_model() -> Any:
    global _model, _model_key
    if _runtime is None:
        raise RuntimeError("STT is not configured; call configure_stt() first")
    key = (_runtime.model_name, _runtime.device, _runtime.compute_type)
    if _model is not None and _model_key == key:
        return _model
    from faster_whisper import WhisperModel

    logger.info(
        "Loading Whisper model %s (device=%s, compute_type=%s)",
        _runtime.model_name,
        _runtime.device,
        _runtime.compute_type,
    )
    _model = WhisperModel(
        _runtime.model_name,
        device=_runtime.device,
        compute_type=_runtime.compute_type,
        local_files_only=True,
    )
    _model_key = key
    return _model


def transcribe_file(path: str | Path) -> str:
    """Transcribe an audio file path; return plain text (empty string on no speech)."""
    if _runtime is None:
        raise RuntimeError("STT is not configured")
    model = _get_model()
    kwargs = dict(_runtime.transcribe_kwargs)
    if _runtime.language:
        kwargs["language"] = _runtime.language
    segments, _info = model.transcribe(str(path), **kwargs)
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe_bytes(data: bytes, *, file_ext: str = ".ogg") -> str:
    """Write bytes to a temp file, transcribe, delete temp file."""
    ext = file_ext if file_ext.startswith(".") else f".{file_ext}"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return transcribe_file(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def reset_stt_for_tests() -> None:
    """Clear module-level STT state (tests only)."""
    global _runtime, _model, _model_key
    _runtime = None
    _model = None
    _model_key = None
