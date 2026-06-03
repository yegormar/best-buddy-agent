"""Apply Hugging Face cache paths from config (read-only model use at runtime)."""

from __future__ import annotations

import os


def apply_hf_env(hf_home: str, hf_hub_cache: str) -> None:
    home = (hf_home or "").strip()
    hub = (hf_hub_cache or "").strip()
    if not home or not hub:
        raise ValueError("hf_home and hf_hub_cache must be non-empty when STT is enabled")
    os.environ["HF_HOME"] = home
    os.environ["HF_HUB_CACHE"] = hub
    os.environ["HUGGINGFACE_HUB_CACHE"] = hub
