"""STT startup validation (no silent GPU→CPU fallback at runtime)."""

from __future__ import annotations

import ctypes
import logging
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TranscriptionStartupError(Exception):
    """Transcription cannot run with the configured device."""


def resolve_effective_device(mode: str) -> str:
    """Return ``cpu`` or ``cuda`` from config mode (``auto`` picks CUDA only if devices exist)."""
    m = (mode or "auto").strip().lower()
    if m == "cpu":
        return "cpu"
    if m == "cuda":
        return "cuda"
    if m == "auto":
        try:
            import ctranslate2

            return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception as exc:
            raise TranscriptionStartupError(
                f"transcription_device=auto but ctranslate2 is unusable: {exc}"
            ) from exc
    raise TranscriptionStartupError(
        f"Invalid transcription device {mode!r}; use cpu, cuda, or auto."
    )


def _offline_model_help(model: str, *, hf_home: str, hf_hub_cache: str) -> str:
    return (
        f"Model {model!r} is not available locally (local_files_only=True). "
        f"Prefetch into HF_HOME={hf_home} and HF_HUB_CACHE={hf_hub_cache}, "
        "or run with network once to populate the cache."
    )


def _write_short_silent_wav(path: Path, *, duration_sec: float = 0.25) -> None:
    nchannels, sampwidth, framerate = 1, 2, 16000
    nframes = int(framerate * duration_sec)
    with wave.open(str(path), "w") as w:
        w.setnchannels(nchannels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.writeframes(b"\x00\x00" * nframes)


def _validate_faster_whisper(
    *,
    device: str,
    model_name: str,
    compute_type: str,
    transcribe_kwargs: dict[str, Any],
    hf_home: str,
    hf_hub_cache: str,
) -> None:
    if device == "cuda":
        try:
            import ctranslate2

            n = ctranslate2.get_cuda_device_count()
        except Exception as exc:
            raise TranscriptionStartupError(
                f"CUDA transcription required but ctranslate2 failed: {exc}"
            ) from exc
        if n < 1:
            raise TranscriptionStartupError(
                "transcription_device is cuda (or auto→cuda) but no CUDA devices are available."
            )
        if sys.platform != "win32":
            try:
                ctypes.CDLL("libcublas.so.12")
            except OSError as exc:
                raise TranscriptionStartupError(
                    "CUDA transcription requires libcublas.so.12 (e.g. "
                    "LD_LIBRARY_PATH=/usr/local/lib/ollama/cuda_v12). "
                    f"Loader error: {exc}"
                ) from exc

    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            local_files_only=True,
        )
    except Exception as exc:
        msg = f"STT startup failed loading faster-whisper on {device}: {exc}"
        err = str(exc).lower()
        if "out of memory" in err or "cuda" in err and "memory" in err:
            msg = (
                f"{msg}\n\nGPU VRAM is likely full (e.g. Ollama + another STT instance). "
                "Use stt.device = cpu on this instance, a smaller model, or disable [stt] "
                "if you only need photos/text."
            )
        else:
            msg = f"{msg}\n\n{_offline_model_help(model_name, hf_home=hf_home, hf_hub_cache=hf_hub_cache)}"
        raise TranscriptionStartupError(msg) from exc

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    try:
        _write_short_silent_wav(wav_path)
        list(model.transcribe(str(wav_path), **transcribe_kwargs))
    except Exception as exc:
        msg = f"STT startup failed during transcribe on {device}: {exc}"
        raise TranscriptionStartupError(msg) from exc
    finally:
        wav_path.unlink(missing_ok=True)


def _assert_compute_type_supported(device: str, compute_type: str) -> None:
    try:
        import ctranslate2

        supported = set(ctranslate2.get_supported_compute_types(device))
    except Exception as exc:
        raise TranscriptionStartupError(
            f"Could not query CTranslate2 compute types for device={device!r}: {exc}"
        ) from exc
    if compute_type not in supported:
        raise TranscriptionStartupError(
            f"compute_type={compute_type!r} is not supported on device={device!r}. "
            f"Supported: {sorted(supported)}."
        )


def run_transcription_startup(
    *,
    device_mode: str,
    model_name: str,
    compute_type_cpu: str,
    compute_type_cuda: str,
    transcribe_kwargs: dict[str, Any],
    hf_home: str,
    hf_hub_cache: str,
) -> tuple[str, str]:
    """Resolve device, validate compute type, prove faster-whisper works. Returns (device, compute_type)."""
    effective = resolve_effective_device(device_mode)
    compute_type = (
        compute_type_cuda.strip().lower()
        if effective == "cuda"
        else compute_type_cpu.strip().lower()
    )
    if not compute_type:
        raise TranscriptionStartupError("transcription compute_type must be non-empty")
    _assert_compute_type_supported(effective, compute_type)
    _validate_faster_whisper(
        device=effective,
        model_name=model_name,
        compute_type=compute_type,
        transcribe_kwargs=transcribe_kwargs,
        hf_home=hf_home,
        hf_hub_cache=hf_hub_cache,
    )
    logger.info(
        "STT startup OK: model=%s device=%s compute_type=%s",
        model_name,
        effective,
        compute_type,
    )
    return effective, compute_type
