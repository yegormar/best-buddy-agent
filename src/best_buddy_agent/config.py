"""Configuration loader for best_buddy_agent."""

from __future__ import annotations

import os
import re
from configparser import ConfigParser
from dataclasses import dataclass, field
from pathlib import Path

from .prompt_loader import PromptCatalog, PromptError, load_prompt_catalog

_LLM_NUM_CTX_K = re.compile(r"^(\d+)\s*[kK]\s*$")
_LLM_NUM_CTX_DIGITS = re.compile(r"^\d+$")


class ConfigError(Exception):
    """Raised when best_buddy_agent config is invalid."""


@dataclass(slots=True)
class GmailSettings:
    """Gmail integration (optional [gmail] section)."""

    enabled: bool = False
    credentials_path: Path = Path.home() / ".best_buddy_agent" / "gmail" / "credentials.json"
    token_path: Path = Path.home() / ".best_buddy_agent" / "gmail" / "token.json"

    def is_ready(self) -> bool:
        return (
            self.enabled
            and self.credentials_path.is_file()
            and self.token_path.is_file()
        )


@dataclass(slots=True)
class TelegramSettings:
    """Telegram channel configuration (optional [telegram] section)."""

    enabled: bool = False
    bot_token: str = ""
    allowed_user_id: int | None = None

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.allowed_user_id is not None)


def parse_llm_num_ctx_value(raw: str) -> int:
    s = (raw or "").strip().replace(" ", "")
    if not s:
        raise ValueError("empty")
    m = _LLM_NUM_CTX_K.match(s)
    if m:
        return int(m.group(1)) * 1024
    if _LLM_NUM_CTX_DIGITS.match(s):
        return int(s)
    raise ValueError("expected integer or K-suffixed size")


@dataclass(slots=True)
class AgentConfig:
    llm_host: str
    llm_port: int
    llm_model: str
    llm_keep_alive: str
    llm_temperature: float
    llm_top_p: float
    llm_num_ctx: int
    llm_think: bool
    prompt_language: str
    prompts: PromptCatalog
    files_root: Path
    max_tool_iterations: int
    log_enabled: bool = False
    log_file: Path | None = None
    log_prompts: bool = True
    log_responses: bool = True
    log_message_history: bool = True
    log_capability_events: bool = True
    log_tool_args: bool = True
    log_llm_wire: bool = False
    reliability_required: bool = False
    assistant_name: str = "BB"
    gmail: GmailSettings = field(default_factory=GmailSettings)

    @property
    def ollama_base_url(self) -> str:
        return f"http://{self.llm_host}:{self.llm_port}"

    @property
    def agent_system_prompt(self) -> str:
        """Agent system instructions (from language prompt bundle)."""
        return self.prompts.get("agent_system")


def _resolve_agent_system_override(llm_section, conf_file: Path) -> Path | None:
    prompt_file = (llm_section.get("agent_system_prompt_file") or "").strip()
    inline = (llm_section.get("agent_system_prompt") or "").strip()
    if prompt_file and inline:
        raise ConfigError(
            "Set either agent_system_prompt_file or agent_system_prompt in [llm], not both"
        )
    if prompt_file:
        p = (conf_file.parent / prompt_file).resolve()
        if not p.is_file():
            raise ConfigError(f"agent_system_prompt_file not found: {p}")
        return p
    if inline:
        raise ConfigError(
            "agent_system_prompt inline text is no longer supported; "
            "use [prompts] language and conf/prompts/{language}/agent_system.txt "
            "or agent_system_prompt_file"
        )
    return None


def _load_prompt_language(parser: ConfigParser, conf_file: Path) -> tuple[str, PromptCatalog]:
    prompts_section = parser["prompts"] if "prompts" in parser else {}
    language = (prompts_section.get("language") or "en").strip()
    if not language:
        raise ConfigError("[prompts] language must be non-empty")

    llm = parser["llm"]
    override = _resolve_agent_system_override(llm, conf_file)
    try:
        catalog = load_prompt_catalog(
            conf_dir=conf_file.parent,
            language=language,
            agent_system_override=override,
        )
    except PromptError as exc:
        raise ConfigError(str(exc)) from exc
    return language, catalog


def load_config(conf_file: str | None = None) -> AgentConfig:
    if conf_file:
        path = Path(conf_file).resolve()
    else:
        env_path = (os.environ.get("BEST_BUDDY_AGENT_CONF") or "").strip()
        if env_path:
            path = Path(env_path).resolve()
        else:
            path = (Path(__file__).resolve().parents[2] / "conf" / "best_buddy_agent.conf").resolve()

    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    parser = ConfigParser()
    parser.read(path, encoding="utf-8")

    if "llm" not in parser:
        raise ConfigError("Missing required [llm] section")
    llm = parser["llm"]

    required = [
        "llm_host",
        "llm_port",
        "llm_model",
        "llm_keep_alive",
        "llm_temperature",
        "llm_top_p",
        "llm_num_ctx",
    ]
    missing = [k for k in required if not (llm.get(k) or "").strip()]
    if missing:
        raise ConfigError(f"Missing required [llm] keys: {', '.join(missing)}")

    try:
        llm_port = int(llm["llm_port"].strip())
    except ValueError as exc:
        raise ConfigError("llm_port must be an integer") from exc
    if llm_port < 1 or llm_port > 65535:
        raise ConfigError("llm_port must be between 1 and 65535")

    try:
        llm_temperature = float(llm["llm_temperature"].strip())
    except ValueError as exc:
        raise ConfigError("llm_temperature must be a number") from exc
    try:
        llm_top_p = float(llm["llm_top_p"].strip())
    except ValueError as exc:
        raise ConfigError("llm_top_p must be a number") from exc

    try:
        llm_num_ctx = parse_llm_num_ctx_value(llm["llm_num_ctx"])
    except ValueError as exc:
        raise ConfigError("llm_num_ctx must be integer or K-suffixed size") from exc

    if llm_num_ctx < 8192 or llm_num_ctx > 262144:
        raise ConfigError("llm_num_ctx must be between 8192 and 262144")

    think_raw = (llm.get("llm_think") or "true").strip()
    try:
        llm_think = ConfigParser.BOOLEAN_STATES[think_raw.lower()]
    except KeyError as exc:
        raise ConfigError("llm_think must be true or false") from exc

    prompt_language, prompts = _load_prompt_language(parser, path)

    tools_section = parser["tools"] if "tools" in parser else {}
    files_root_raw = str(tools_section.get("files_root", "")).strip()
    if files_root_raw:
        files_root = Path(files_root_raw).expanduser()
        if not files_root.is_absolute():
            files_root = (path.parent / files_root).resolve()
        else:
            files_root = files_root.resolve()
    else:
        # Default to project root when config is in <project>/conf/
        files_root = path.parent.parent.resolve()
    if not files_root.exists() or not files_root.is_dir():
        raise ConfigError(f"files_root must be an existing directory: {files_root}")

    max_tool_iterations_raw = str(tools_section.get("max_tool_iterations", "4")).strip()
    try:
        max_tool_iterations = int(max_tool_iterations_raw)
    except ValueError as exc:
        raise ConfigError("max_tool_iterations must be an integer") from exc
    if max_tool_iterations < 1 or max_tool_iterations > 20:
        raise ConfigError("max_tool_iterations must be between 1 and 20")

    logging_section = parser["logging"] if "logging" in parser else None
    enabled_raw = logging_section.get("enabled", "false") if logging_section is not None else "false"
    try:
        log_enabled = ConfigParser.BOOLEAN_STATES[str(enabled_raw).strip().lower()]
    except KeyError as exc:
        raise ConfigError("logging.enabled must be true or false") from exc

    log_file: Path | None = None
    log_file_raw = (
        str(logging_section.get("file", "")).strip()
        if logging_section is not None
        else ""
    )
    if log_enabled:
        if not log_file_raw:
            raise ConfigError("logging.file is required when logging.enabled = true")
        candidate = Path(log_file_raw).expanduser()
        if not candidate.is_absolute():
            candidate = (path.parent / candidate).resolve()
        else:
            candidate = candidate.resolve()
        parent = candidate.parent
        if not parent.exists() or not parent.is_dir():
            raise ConfigError(f"logging.file parent directory does not exist: {parent}")
        log_file = candidate

    def _log_bool(key: str, default: str = "true") -> bool:
        raw = logging_section.get(key, default) if logging_section is not None else default
        try:
            return ConfigParser.BOOLEAN_STATES[str(raw).strip().lower()]
        except KeyError as exc:
            raise ConfigError(f"logging.{key} must be true or false") from exc

    log_prompts = _log_bool("log_prompts")
    log_responses = _log_bool("log_responses")
    log_message_history = _log_bool("log_message_history")
    log_capability_events = _log_bool("log_capability_events")
    log_tool_args = _log_bool("log_tool_args")
    log_llm_wire = _log_bool("log_llm_wire", default="false")

    if log_llm_wire and not log_enabled:
        raise ConfigError("logging.log_llm_wire requires logging.enabled = true")
    if log_llm_wire and log_file is None:
        raise ConfigError("logging.log_llm_wire requires logging.file")

    agent_section = parser["agent"] if "agent" in parser else {}
    reliability_raw = (
        str(agent_section.get("reliability_required", "false")).strip()
        if agent_section
        else "false"
    )
    try:
        reliability_required = ConfigParser.BOOLEAN_STATES[reliability_raw.lower()]
    except KeyError as exc:
        raise ConfigError("agent.reliability_required must be true or false") from exc

    assistant_name = (
        str(agent_section.get("assistant_name", "BB")).strip() if agent_section else "BB"
    )
    if not assistant_name:
        raise ConfigError("agent.assistant_name must be non-empty")

    gmail = _load_gmail_settings(parser, path)

    return AgentConfig(
        llm_host=llm["llm_host"].strip(),
        llm_port=llm_port,
        llm_model=llm["llm_model"].strip(),
        llm_keep_alive=llm["llm_keep_alive"].strip(),
        llm_temperature=llm_temperature,
        llm_top_p=llm_top_p,
        llm_num_ctx=llm_num_ctx,
        llm_think=llm_think,
        prompt_language=prompt_language,
        prompts=prompts,
        files_root=files_root,
        max_tool_iterations=max_tool_iterations,
        log_enabled=log_enabled,
        log_file=log_file,
        log_prompts=log_prompts,
        log_responses=log_responses,
        log_message_history=log_message_history,
        log_capability_events=log_capability_events,
        log_tool_args=log_tool_args,
        log_llm_wire=log_llm_wire,
        reliability_required=reliability_required,
        assistant_name=assistant_name,
        gmail=gmail,
    )


def _resolve_conf_path(raw: str, conf_file: Path) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (conf_file.parent / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def _load_gmail_settings(parser: ConfigParser, conf_file: Path) -> GmailSettings:
    from .gmail_client import DEFAULT_CREDENTIALS_PATH, DEFAULT_TOKEN_PATH

    section = parser["gmail"] if "gmail" in parser else {}
    enabled_raw = str(section.get("enabled", "false")).strip().lower()
    try:
        enabled = ConfigParser.BOOLEAN_STATES[enabled_raw]
    except KeyError as exc:
        raise ConfigError("gmail.enabled must be true or false") from exc

    creds_raw = str(section.get("credentials_path", "")).strip()
    token_raw = str(section.get("token_path", "")).strip()
    credentials_path = (
        _resolve_conf_path(creds_raw, conf_file)
        if creds_raw
        else DEFAULT_CREDENTIALS_PATH.resolve()
    )
    token_path = (
        _resolve_conf_path(token_raw, conf_file)
        if token_raw
        else DEFAULT_TOKEN_PATH.resolve()
    )
    return GmailSettings(
        enabled=enabled,
        credentials_path=credentials_path,
        token_path=token_path,
    )


def load_telegram_settings(conf_file: str | None = None) -> TelegramSettings:
    """Load [telegram] settings; env vars override conf file values."""
    if conf_file:
        path = Path(conf_file).resolve()
    else:
        env_path = (os.environ.get("BEST_BUDDY_AGENT_CONF") or "").strip()
        if env_path:
            path = Path(env_path).resolve()
        else:
            path = (Path(__file__).resolve().parents[2] / "conf" / "best_buddy_agent.conf").resolve()

    enabled = False
    bot_token = ""
    allowed_user_id: int | None = None

    if path.is_file():
        parser = ConfigParser()
        parser.read(path, encoding="utf-8")
        tg_section = parser["telegram"] if "telegram" in parser else {}
        enabled_raw = str(tg_section.get("enabled", "false")).strip().lower()
        try:
            enabled = ConfigParser.BOOLEAN_STATES[enabled_raw]
        except KeyError as exc:
            raise ConfigError("telegram.enabled must be true or false") from exc
        bot_token = str(tg_section.get("bot_token", "")).strip()
        user_raw = str(tg_section.get("allowed_user_id", "")).strip()

        if user_raw.isdigit():
            allowed_user_id = int(user_raw)

    env_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if env_token:
        bot_token = env_token

    env_user = (os.environ.get("TELEGRAM_ALLOWED_USER_ID") or "").strip()
    if env_user.isdigit():
        allowed_user_id = int(env_user)

    env_enabled = (os.environ.get("TELEGRAM_ENABLED") or "").strip().lower()
    if env_enabled in ConfigParser.BOOLEAN_STATES:
        enabled = ConfigParser.BOOLEAN_STATES[env_enabled]

    return TelegramSettings(
        enabled=enabled,
        bot_token=bot_token,
        allowed_user_id=allowed_user_id,
    )


def validate_telegram_startup(settings: TelegramSettings) -> None:
    """Raise ConfigError if Telegram bot cannot start."""
    if not settings.bot_token:
        raise ConfigError(
            "Telegram bot token missing. Set TELEGRAM_BOT_TOKEN or [telegram] bot_token."
        )
    if settings.allowed_user_id is None:
        raise ConfigError(
            "Telegram allowed user id missing. Set TELEGRAM_ALLOWED_USER_ID or "
            "[telegram] allowed_user_id."
        )
