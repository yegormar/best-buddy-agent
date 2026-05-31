"""Start/stop background workflow scheduler and Deadline Watch seed."""

from __future__ import annotations

import logging

from ..config import AgentConfig, TelegramSettings
from .. import workflow_engine as wf

log = logging.getLogger(__name__)

DEADLINE_WATCH_SCAN_ID = "deadline-watch-scan"


def _seed_deadline_watch_scan(config: AgentConfig) -> None:
    if not config.deadline_watch.enabled:
        return
    interval = max(60, int(config.deadline_watch.scan_interval_seconds))
    wf.upsert_workflow(
        DEADLINE_WATCH_SCAN_ID,
        name="Deadline Watch Scan",
        steps=[{"id": "scan", "type": "function", "name": "deadline_watch.scan"}],
        schedule={"type": "interval", "seconds": interval},
        enabled=True,
        metadata={"kind": "deadline_watch_scan"},
    )
    log.info("Deadline Watch scan workflow seeded (interval=%ss)", interval)


def start_background_services(
    config: AgentConfig,
    telegram_settings: TelegramSettings,
    *,
    notifier=None,
) -> None:
    """Start workflow scheduler and seed built-in workflows."""
    from ..notifications.telegram_notifier import make_notifier

    wf.set_workflow_runtime_context(
        {
            "config": config,
            "telegram_settings": telegram_settings,
        }
    )

    try:
        from ..deadline_watch.scanner import register_scan_function

        register_scan_function()
    except ImportError:
        log.debug("deadline_watch not loaded yet")

    _seed_deadline_watch_scan(config)

    if not config.workflows.enabled:
        log.info("Workflow scheduler disabled ([workflows] enabled = false)")
        return

    notify = notifier or make_notifier()
    step_executor = wf.default_agent_step_executor(config)
    wf.start_scheduler_loop(
        step_executor,
        notifier=notify,
        poll_seconds=config.workflows.poll_seconds,
    )
    log.info("Workflow scheduler started (poll=%ss)", config.workflows.poll_seconds)


def stop_background_services() -> None:
    wf.stop_scheduler_loop()
    wf.clear_workflow_runtime_context()
