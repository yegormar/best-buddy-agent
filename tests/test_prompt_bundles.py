"""Validate en/ru prompt bundles: completeness, parity, and consistency."""

from __future__ import annotations

import re
from string import Formatter
from typing import Iterable

import pytest

from best_buddy_agent.prompt_loader import PROMPT_FILES, TOOL_NAMES, load_prompt_catalog

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
CONF_DIR = ROOT / "conf"
PROMPTS_ROOT = CONF_DIR / "prompts"
PROMPT_LANGUAGES = ("en", "ru")

MEMORY_CATEGORIES = (
    "person",
    "preference",
    "fact",
    "event",
    "place",
    "project",
    "skill",
    "organisation",
    "concept",
    "media",
    "self_knowledge",
)

JSON_FIELD_NAMES = (
    "category",
    "subject",
    "content",
    "aliases",
    "relation_type",
    "source_subject",
    "target_subject",
    "confidence",
    "has_relation",
)

TOOL_PARAM_NAMES = (
    "source_id",
    "target_id",
    "relation_type",
    "memory_id",
    "entity_id",
    "hops",
    "category",
    "content",
    "aliases",
    "tags",
)

CATEGORY_PROMPT_KEYS = frozenset(
    {
        "agent_system",
        "import_turn",
        "tools/save_memory",
        "background/extraction",
    }
)

JSON_PROMPT_KEYS = frozenset(
    {
        "background/extraction",
        "dream/infer",
        "dream/insights",
    }
)

TOOL_DOC_KEYS = frozenset(f"tools/{name}" for name in TOOL_NAMES)


def _prompt_keys() -> list[str]:
    return sorted(PROMPT_FILES) + [f"tools/{name}" for name in TOOL_NAMES]


def _expected_relative_paths() -> set[str]:
    paths = set(PROMPT_FILES.values())
    paths.update(f"tools/{name}.txt" for name in TOOL_NAMES)
    return paths


def _list_bundle_files(language: str) -> set[str]:
    root = PROMPTS_ROOT / language
    return {
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*.txt")
    }


def _format_placeholders(text: str) -> frozenset[str]:
    names: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(text):
        if field_name is None:
            continue
        root = field_name.split("!")[0].split(":")[0].split(".")[0].split("[")[0]
        if root:
            names.add(root)
    return frozenset(names)


def _tokens_present(text: str, tokens: Iterable[str]) -> frozenset[str]:
    found: set[str] = set()
    for token in tokens:
        if re.search(rf"\b{re.escape(token)}\b", text):
            found.add(token)
    return frozenset(found)


def _load_bundles() -> dict[str, dict[str, str]]:
    bundles: dict[str, dict[str, str]] = {}
    for language in PROMPT_LANGUAGES:
        catalog = load_prompt_catalog(conf_dir=CONF_DIR, language=language)
        bundles[language] = {key: catalog.get(key) for key in _prompt_keys()}
    return bundles


@pytest.mark.parametrize("language", PROMPT_LANGUAGES)
def test_prompt_bundle_loads(language: str) -> None:
    catalog = load_prompt_catalog(conf_dir=CONF_DIR, language=language)
    for key in _prompt_keys():
        assert catalog.get(key).strip(), f"{language}/{key} is empty"


def test_prompt_bundle_file_parity() -> None:
    expected = _expected_relative_paths()
    by_language = {language: _list_bundle_files(language) for language in PROMPT_LANGUAGES}

    for language, files in by_language.items():
        missing = expected - files
        extra = files - expected
        assert not missing, f"{language} missing prompt files: {sorted(missing)}"
        assert not extra, f"{language} has unexpected prompt files: {sorted(extra)}"

    en_files, ru_files = by_language["en"], by_language["ru"]
    assert en_files == ru_files


def test_prompt_placeholder_parity_across_languages() -> None:
    bundles = _load_bundles()
    mismatches: list[str] = []

    for key in _prompt_keys():
        en_ph = _format_placeholders(bundles["en"][key])
        ru_ph = _format_placeholders(bundles["ru"][key])
        if en_ph != ru_ph:
            mismatches.append(
                f"{key}: en={sorted(en_ph)} ru={sorted(ru_ph)}"
            )

    assert not mismatches, "Placeholder mismatch between en and ru:\n" + "\n".join(mismatches)


def test_prompt_bundles_format_with_dummy_placeholders() -> None:
    bundles = _load_bundles()
    failures: list[str] = []

    for language in PROMPT_LANGUAGES:
        for key, text in bundles[language].items():
            placeholders = _format_placeholders(text)
            kwargs = {name: f"<{name}>" for name in placeholders}
            try:
                text.format(**kwargs)
            except (KeyError, ValueError) as exc:
                failures.append(f"{language}/{key}: {exc}")

    assert not failures, "Prompt .format() failed:\n" + "\n".join(failures)


def test_prompt_bundles_preserve_technical_tokens() -> None:
    """Translated prompts must keep API tokens that English documents for the LLM."""
    bundles = _load_bundles()
    mismatches: list[str] = []

    for key in _prompt_keys():
        en_text = bundles["en"][key]
        ru_text = bundles["ru"][key]

        en_tools = _tokens_present(en_text, TOOL_NAMES)
        ru_tools = _tokens_present(ru_text, TOOL_NAMES)
        missing_tools = en_tools - ru_tools
        if missing_tools:
            mismatches.append(f"{key} missing tools in ru: {sorted(missing_tools)}")

        if key in CATEGORY_PROMPT_KEYS:
            en_categories = _tokens_present(en_text, MEMORY_CATEGORIES)
            ru_categories = _tokens_present(ru_text, MEMORY_CATEGORIES)
            missing_categories = en_categories - ru_categories
            if missing_categories:
                mismatches.append(
                    f"{key} missing categories in ru: {sorted(missing_categories)}"
                )

        if key in JSON_PROMPT_KEYS:
            en_json = _tokens_present(en_text, JSON_FIELD_NAMES)
            ru_json = _tokens_present(ru_text, JSON_FIELD_NAMES)
            missing_json = en_json - ru_json
            if missing_json:
                mismatches.append(
                    f"{key} missing json_fields in ru: {sorted(missing_json)}"
                )

        if key in TOOL_DOC_KEYS:
            en_params = _tokens_present(en_text, TOOL_PARAM_NAMES)
            ru_params = _tokens_present(ru_text, TOOL_PARAM_NAMES)
            missing_params = en_params - ru_params
            if missing_params:
                mismatches.append(
                    f"{key} missing tool params in ru: {sorted(missing_params)}"
                )

    assert not mismatches, "Technical token mismatch:\n" + "\n".join(mismatches)


def test_russian_prompts_are_translated_not_copies() -> None:
    bundles = _load_bundles()
    identical: list[str] = []

    for key in _prompt_keys():
        if bundles["en"][key] == bundles["ru"][key]:
            identical.append(key)

    assert not identical, (
        "Russian prompts still identical to English (likely untranslated):\n"
        + "\n".join(identical)
    )


def test_contradiction_keyword_matches_prompt() -> None:
    bundles = _load_bundles()
    for lang in PROMPT_LANGUAGES:
        keyword = bundles[lang]["keywords/contradiction_no"].strip()
        contradiction = bundles[lang]["background/contradiction"]
        assert keyword, f"{lang}/keywords/contradiction_no is empty"
        assert keyword in contradiction, (
            f"{lang}/background/contradiction must mention the no-keyword {keyword!r}"
        )


def test_import_turn_maps_narrator_to_user() -> None:
    """Narrator must normalize to subject User; must not conflict with Entities spelling rule."""
    bundles = _load_bundles()
    en = bundles["en"]["import_turn"]
    ru = bundles["ru"]["import_turn"]

    assert 'subject "User"' in en or "subject='User'" in en
    assert 'subject "User"' in ru or "subject='User'" in ru or 'subject="User"' in ru

    assert "Рассказчик" in ru
    assert "NOT save" in en or "Do NOT save" in en
    assert "НЕ создавайте" in ru

    for text in (en, ru):
        assert "EXCEPT" in text or "КРОМЕ" in text, "narrator exception must override Entities spelling"
        assert "User" in text
