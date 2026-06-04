"""Pydantic-ai agent runtime for best_buddy_agent."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.tools import RunContext, ToolApproved, ToolDenied
from pydantic_ai.usage import UsageLimits

from . import agent_trace
from .agent_context import redact_data_uris
from .approval import InterruptResult
from .capabilities_hooks import build_capabilities
from .config import AgentConfig
from .prompt_loader import PromptCatalog
from .context_layer import assemble_context
from .exceptions import AgentEmptyResponseError
from .memory_layer import recall_context_for_turn_with_meta
from .model_factory import agent_config_fingerprint, build_ollama_model
from .multimodal import UserImage, build_native_user_prompt, image_trace_summary
from .threads import append_turn_messages, load_thread_message_history, thread_conversation_rows
from .tools import filesystem as fs_tools
from .tools import calendar_tools
from .tools import gmail_tools as gmail_tools
from .tools import memory_tools as mem_tools
from .tools import workflow_tools as wf_tools
from .tools import vision_tools
from .tools import web_tools
from .vision_cache import strip_images_for_storage

TurnResult = str | InterruptResult

# Trace-only mirror of registered tool descriptions (loaded from prompt files at runtime).
AGENT_TOOL_CATALOG: list[tuple[str, str]] = []


@dataclass(slots=True)
class BestBuddyDeps:
    config: AgentConfig
    thread_id: str
    workflow_context: dict[str, Any] | None = None
    approval_resolver: Callable[[dict[str, Any]], bool] | None = None
    turn_user_text: str = ""
    memory_source: str | None = None


def thread_to_message_history(thread_id: str) -> list[ModelMessage]:
    return load_thread_message_history(thread_id)


def _history_trace_lines(thread_id: str) -> list[str]:
    lines: list[str] = []
    for row in thread_conversation_rows(thread_id):
        role = row.get("role", "?")
        content = row.get("content", "")
        if len(content) > 400:
            content = content[:400] + "..."
        lines.append(f"  {role}: {content}")
    return lines


def _compose_instructions(
    deps: BestBuddyDeps,
    user_text: str,
) -> tuple[str, str, dict[str, object]]:
    cfg = deps.config
    prompts = cfg.prompts
    if deps.thread_id == "memory-import":
        # Bulk facts import: payload is in user_text; skip live-chat recall (avoids huge prompts).
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = prompts.format("fragments/datetime", now=now).strip()
        return text, "", {"recall_path": "skipped_import", "recall_query": ""}

    context = assemble_context(thread_id=deps.thread_id, user_text=user_text, max_turns=12)
    memory_block, recall_meta = recall_context_for_turn_with_meta(
        user_messages=context["recent_user_messages"],
        user_text=user_text,
        top_k=8,
        memory_recall_header=prompts.get("fragments/memory_recall_header"),
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if cfg.deadline_watch.enabled:
        try:
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(cfg.deadline_watch.timezone)).strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            )
        except Exception:
            pass
    parts = [
        prompts.format(
            "fragments/assistant_identity",
            assistant_name=cfg.assistant_name,
        ),
        cfg.agent_system_prompt,
        prompts.format("fragments/datetime", now=now),
    ]
    if memory_block:
        parts.append(redact_data_uris(memory_block))
    if deps.workflow_context:
        parts.append(
            prompts.get("fragments/workflow_context_header")
            + "\n"
            + json.dumps(deps.workflow_context, ensure_ascii=False, indent=2)
        )
    if cfg.gmail.is_ready():
        parts.append(prompts.get("fragments/gmail_available"))
    if cfg.web.enabled:
        parts.append(prompts.get("fragments/web_available"))
    if cfg.vision.enabled:
        parts.append(prompts.get("fragments/vision_available"))
    if cfg.calendar.is_ready():
        parts.append(prompts.get("fragments/calendar_available"))
    elif cfg.deadline_watch.enabled:
        parts.append(
            "Reminders/time: call get_current_datetime before scheduling; "
            f"timezone is {cfg.deadline_watch.timezone}."
        )
    if cfg.deadline_watch.enabled:
        parts.append(prompts.get("fragments/deadline_watch"))
    text = "\n\n".join(p for p in parts if p.strip())
    return text, memory_block, recall_meta


def _instructions_text(ctx: RunContext[BestBuddyDeps]) -> str:
    text, _, _ = _compose_instructions(ctx.deps, ctx.deps.turn_user_text)
    return redact_data_uris(text)


def _trace_tool_invoke(
    config: AgentConfig,
    name: str,
    args: dict[str, Any],
    fn: Callable[[], str],
) -> str:
    agent_trace.trace_tool_call(config, name, args)
    try:
        result = fn()
        agent_trace.trace_tool_result(config, name, result)
        return result
    except (
        fs_tools.ToolError,
        mem_tools.ToolError,
        wf_tools.ToolError,
        gmail_tools.ToolError,
        web_tools.ToolError,
        vision_tools.ToolError,
    ) as exc:
        message = str(exc)
        agent_trace.trace_tool_result(config, name, message, error=True)
        return message


def _bind_tool(
    agent: Agent[BestBuddyDeps, TurnResult],
    prompts: PromptCatalog,
    name: str,
    fn: Callable[..., str],
    *,
    requires_approval: bool = False,
) -> None:
    fn.__doc__ = prompts.get(f"tools/{name}")
    decorator = agent.tool(requires_approval=True) if requires_approval else agent.tool
    decorator(fn)


def _register_tools(
    agent: Agent[BestBuddyDeps, TurnResult],
    config: AgentConfig,
    prompts: PromptCatalog,
) -> None:
    def read_file(ctx: RunContext[BestBuddyDeps], path: str) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "read_file",
            {"path": path},
            lambda: fs_tools.read_file(ctx.deps.config, path),
        )

    def list_files(ctx: RunContext[BestBuddyDeps], pattern: str = "*", max_entries: int = 200) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "list_files",
            {"pattern": pattern, "max_entries": max_entries},
            lambda: fs_tools.list_files(
                ctx.deps.config, pattern=pattern, max_entries=max_entries
            ),
        )

    def write_file(ctx: RunContext[BestBuddyDeps], path: str, content: str) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "write_file",
            {"path": path, "content_len": len(content)},
            lambda: fs_tools.write_file(ctx.deps.config, path, content),
        )

    def search_memory(ctx: RunContext[BestBuddyDeps], query: str, top_k: int = 8) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "search_memory",
            {"query": query, "top_k": top_k},
            lambda: mem_tools.search_memory(query, top_k=top_k),
        )

    def save_memory(
        ctx: RunContext[BestBuddyDeps],
        category: str,
        subject: str,
        content: str,
        tags: str = "",
    ) -> str:
        mem_source = ctx.deps.memory_source or "live"
        return _trace_tool_invoke(
            ctx.deps.config,
            "save_memory",
            {"category": category, "subject": subject, "tags": tags},
            lambda: mem_tools.save_memory_entry(
                category, subject, content, tags=tags, source=mem_source
            ),
        )

    def list_memories(ctx: RunContext[BestBuddyDeps], category: str = "", limit: int = 30) -> str:
        cat = category.strip() or None
        return _trace_tool_invoke(
            ctx.deps.config,
            "list_memories",
            {"category": category, "limit": limit},
            lambda: mem_tools.list_memories(category=cat, limit=limit),
        )

    def get_memory(ctx: RunContext[BestBuddyDeps], memory_id: str) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "get_memory",
            {"memory_id": memory_id},
            lambda: mem_tools.get_memory_by_id(memory_id),
        )

    def delete_memory(ctx: RunContext[BestBuddyDeps], memory_id: str) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "delete_memory",
            {"memory_id": memory_id},
            lambda: mem_tools.delete_memory_by_id(memory_id),
        )

    def link_memories(
        ctx: RunContext[BestBuddyDeps],
        source_id: str,
        target_id: str,
        relation_type: str,
    ) -> str:
        mem_source = ctx.deps.memory_source or "live"
        return _trace_tool_invoke(
            ctx.deps.config,
            "link_memories",
            {"source_id": source_id, "target_id": target_id, "relation_type": relation_type},
            lambda: mem_tools.link_memories_entities(
                source_id, target_id, relation_type, source=mem_source
            ),
        )

    def update_memory(
        ctx: RunContext[BestBuddyDeps],
        memory_id: str,
        content: str,
        subject: str = "",
        aliases: str = "",
        tags: str = "",
        category: str = "",
    ) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "update_memory",
            {"memory_id": memory_id, "subject": subject or "", "tags": tags or ""},
            lambda: mem_tools.update_memory_entry(
                memory_id, content, subject=subject, aliases=aliases,
                tags=tags, category=category,
            ),
        )

    def explore_connections(
        ctx: RunContext[BestBuddyDeps],
        entity_id: str,
        hops: int = 1,
    ) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "explore_connections",
            {"entity_id": entity_id, "hops": hops},
            lambda: mem_tools.explore_connections_for_entity(entity_id, hops),
        )

    def workflow_run_status(ctx: RunContext[BestBuddyDeps], run_id: str) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "workflow_run_status",
            {"run_id": run_id},
            lambda: wf_tools.workflow_run_status(run_id),
        )

    def trigger_workflow(ctx: RunContext[BestBuddyDeps], workflow_id: str) -> str:
        from . import workflow_engine as wf
        from .notifications.telegram_notifier import make_notifier

        def _run() -> str:
            row = wf.get_workflow(workflow_id.strip())
            if not row:
                raise wf_tools.ToolError(f"Unknown workflow: {workflow_id}")
            run_id = wf.run_workflow(
                workflow_id.strip(),
                make_workflow_step_executor(ctx.deps.config),
                notifier=make_notifier(),
            )
            return json.dumps({"workflow_id": workflow_id, "run_id": run_id})

        return _trace_tool_invoke(
            ctx.deps.config,
            "trigger_workflow",
            {"workflow_id": workflow_id},
            _run,
        )

    def list_workflows(ctx: RunContext[BestBuddyDeps]) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "list_workflows",
            {},
            wf_tools.list_workflows,
        )

    def create_workflow(
        ctx: RunContext[BestBuddyDeps],
        name: str,
        steps_json: str = "[]",
        schedule_json: str = "",
        notify_only: bool = False,
        notify_message: str = "",
        enabled: bool = True,
    ) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "create_workflow",
            {"name": name},
            lambda: wf_tools.create_workflow_tool(
                name,
                steps_json=steps_json,
                schedule_json=schedule_json,
                notify_only=notify_only,
                notify_message=notify_message,
                enabled=enabled,
            ),
        )

    def create_reminder(
        ctx: RunContext[BestBuddyDeps],
        name: str,
        message: str,
        at_datetime: str = "",
        minutes_before: int = 15,
        in_minutes: int | None = None,
    ) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "create_reminder",
            {
                "name": name,
                "at_datetime": at_datetime,
                "minutes_before": minutes_before,
                "in_minutes": in_minutes,
            },
            lambda: wf_tools.create_reminder_tool(
                name,
                message,
                at_datetime,
                minutes_before=minutes_before,
                in_minutes=in_minutes,
                timezone=ctx.deps.config.deadline_watch.timezone,
            ),
        )

    def update_workflow(
        ctx: RunContext[BestBuddyDeps],
        workflow_id: str,
        name: str = "",
        steps_json: str = "",
        schedule_json: str = "",
        notify_only: bool | None = None,
        notify_message: str = "",
        enabled: bool | None = None,
    ) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "update_workflow",
            {"workflow_id": workflow_id},
            lambda: wf_tools.update_workflow_tool(
                workflow_id,
                name=name,
                steps_json=steps_json,
                schedule_json=schedule_json,
                notify_only=notify_only,
                notify_message=notify_message,
                enabled=enabled,
            ),
        )

    def delete_workflow(ctx: RunContext[BestBuddyDeps], workflow_id: str) -> str:
        return _trace_tool_invoke(
            ctx.deps.config,
            "delete_workflow",
            {"workflow_id": workflow_id},
            lambda: wf_tools.delete_workflow_tool(workflow_id),
        )

    def run_workflow_now(ctx: RunContext[BestBuddyDeps], workflow_id: str) -> str:
        from . import workflow_engine as wf
        from .notifications.telegram_notifier import make_notifier

        def _run() -> str:
            wid = workflow_id.strip()
            if not wf.get_workflow(wid):
                raise wf_tools.ToolError(f"Unknown workflow: {wid}")
            run_id = wf.run_workflow(
                wid,
                make_workflow_step_executor(ctx.deps.config),
                notifier=make_notifier(),
            )
            return json.dumps({"workflow_id": wid, "run_id": run_id})

        return _trace_tool_invoke(
            ctx.deps.config,
            "run_workflow_now",
            {"workflow_id": workflow_id},
            _run,
        )

    for name, fn in (
        ("read_file", read_file),
        ("list_files", list_files),
        ("search_memory", search_memory),
        ("save_memory", save_memory),
        ("list_memories", list_memories),
        ("get_memory", get_memory),
        ("link_memories", link_memories),
        ("update_memory", update_memory),
        ("explore_connections", explore_connections),
        ("workflow_run_status", workflow_run_status),
        ("trigger_workflow", trigger_workflow),
        ("list_workflows", list_workflows),
        ("create_workflow", create_workflow),
        ("create_reminder", create_reminder),
        ("update_workflow", update_workflow),
        ("delete_workflow", delete_workflow),
        ("run_workflow_now", run_workflow_now),
    ):
        _bind_tool(agent, prompts, name, fn)

    _bind_tool(agent, prompts, "write_file", write_file, requires_approval=True)
    _bind_tool(agent, prompts, "delete_memory", delete_memory, requires_approval=True)

    if config.gmail.is_ready():
        def search_gmail(ctx: RunContext[BestBuddyDeps], query: str, max_results: int = 10) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "search_gmail",
                {"query": query, "max_results": max_results},
                lambda: gmail_tools.search_gmail(
                    ctx.deps.config, query, max_results=max_results
                ),
            )

        def get_gmail_message(ctx: RunContext[BestBuddyDeps], message_id: str) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "get_gmail_message",
                {"message_id": message_id},
                lambda: gmail_tools.get_gmail_message(ctx.deps.config, message_id),
            )

        def get_gmail_thread(ctx: RunContext[BestBuddyDeps], thread_id: str) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "get_gmail_thread",
                {"thread_id": thread_id},
                lambda: gmail_tools.get_gmail_thread(ctx.deps.config, thread_id),
            )

        def create_gmail_draft(
            ctx: RunContext[BestBuddyDeps],
            message: str,
            to: str,
            subject: str,
            cc: str = "",
            bcc: str = "",
            attachments: str = "",
        ) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "create_gmail_draft",
                {"to": to, "subject": subject, "cc": cc or "", "attachments": attachments or ""},
                lambda: gmail_tools.create_gmail_draft(
                    ctx.deps.config,
                    message,
                    to,
                    subject,
                    cc=cc,
                    bcc=bcc,
                    attachments=attachments,
                ),
            )

        for name, fn in (
            ("search_gmail", search_gmail),
            ("get_gmail_message", get_gmail_message),
            ("get_gmail_thread", get_gmail_thread),
        ):
            _bind_tool(agent, prompts, name, fn)
        _bind_tool(
            agent,
            prompts,
            "create_gmail_draft",
            create_gmail_draft,
            requires_approval=True,
        )

    if config.calendar.is_ready():
        def get_current_datetime(ctx: RunContext[BestBuddyDeps]) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "get_current_datetime",
                {},
                lambda: calendar_tools.get_current_datetime(ctx.deps.config),
            )

        def search_events(
            ctx: RunContext[BestBuddyDeps],
            min_datetime: str,
            max_datetime: str,
            max_results: int = 10,
            query: str = "",
        ) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "search_events",
                {"min_datetime": min_datetime, "max_datetime": max_datetime},
                lambda: calendar_tools.search_events(
                    ctx.deps.config,
                    min_datetime,
                    max_datetime,
                    max_results=max_results,
                    query=query,
                ),
            )

        def create_calendar_event(
            ctx: RunContext[BestBuddyDeps],
            summary: str,
            start_datetime: str,
            end_datetime: str = "",
            description: str = "",
            location: str = "",
            calendar_id: str = "primary",
        ) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "create_calendar_event",
                {"summary": summary, "start_datetime": start_datetime},
                lambda: calendar_tools.create_calendar_event(
                    ctx.deps.config,
                    summary,
                    start_datetime,
                    end_datetime=end_datetime,
                    description=description,
                    location=location,
                    calendar_id=calendar_id,
                ),
            )

        def update_calendar_event(
            ctx: RunContext[BestBuddyDeps],
            event_id: str,
            summary: str = "",
            start_datetime: str = "",
            end_datetime: str = "",
            description: str = "",
            calendar_id: str = "primary",
        ) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "update_calendar_event",
                {"event_id": event_id},
                lambda: calendar_tools.update_calendar_event(
                    ctx.deps.config,
                    event_id,
                    summary=summary,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    description=description,
                    calendar_id=calendar_id,
                ),
            )

        for name, fn in (
            ("get_current_datetime", get_current_datetime),
            ("search_events", search_events),
        ):
            _bind_tool(agent, prompts, name, fn)
        _bind_tool(
            agent,
            prompts,
            "create_calendar_event",
            create_calendar_event,
            requires_approval=True,
        )
        _bind_tool(
            agent,
            prompts,
            "update_calendar_event",
            update_calendar_event,
            requires_approval=True,
        )

    elif config.deadline_watch.enabled:

        def get_current_datetime(ctx: RunContext[BestBuddyDeps]) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "get_current_datetime",
                {},
                lambda: calendar_tools.get_current_datetime(ctx.deps.config),
            )

        _bind_tool(agent, prompts, "get_current_datetime", get_current_datetime)


    if config.web.enabled:
        def web_search(ctx: RunContext[BestBuddyDeps], query: str, max_results: int = 8) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "web_search",
                {"query": query, "max_results": max_results},
                lambda: web_tools.web_search(
                    ctx.deps.config.web, query, max_results=max_results
                ),
            )

        def fetch_url(ctx: RunContext[BestBuddyDeps], url: str) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "fetch_url",
                {"url": url},
                lambda: web_tools.fetch_url(ctx.deps.config.web, url),
            )

        for name, fn in (
            ("web_search", web_search),
            ("fetch_url", fetch_url),
        ):
            _bind_tool(agent, prompts, name, fn)

    if config.vision.enabled:

        def revisit_image(
            ctx: RunContext[BestBuddyDeps],
            image_name: str,
            question: str,
        ) -> str:
            return _trace_tool_invoke(
                ctx.deps.config,
                "revisit_image",
                {"image_name": image_name, "question": question[:200]},
                lambda: vision_tools.revisit_image(
                    ctx.deps.config, image_name, question
                ),
            )

        _bind_tool(agent, prompts, "revisit_image", revisit_image)


def build_agent(
    config: AgentConfig,
    *,
    model: Model | None = None,
    use_reliability: bool = True,
) -> Agent[BestBuddyDeps, TurnResult]:
    llm = model or build_ollama_model(config)
    caps = build_capabilities(config, use_reliability=use_reliability)
    agent: Agent[BestBuddyDeps, TurnResult] = Agent(
        llm,
        deps_type=BestBuddyDeps,
        output_type=[str, DeferredToolRequests],
        instructions=_instructions_text,
        capabilities=caps or None,
    )
    _register_tools(agent, config, config.prompts)
    global AGENT_TOOL_CATALOG
    AGENT_TOOL_CATALOG = config.prompts.tool_catalog()
    return agent


def build_planner_agent(
    config: AgentConfig,
    *,
    model: Model | None = None,
    output_type: Any,
    instructions: str,
) -> Agent[None, Any]:
    llm = model or build_ollama_model(config)
    caps = build_capabilities(config, use_reliability=False)
    return Agent(
        llm,
        output_type=output_type,
        instructions=instructions,
        capabilities=caps or None,
    )


def _resolve_deferred(
    deps: BestBuddyDeps,
    requests: DeferredToolRequests,
) -> DeferredToolResults | None:
    resolver = deps.approval_resolver
    if resolver is None:
        return None

    approvals: dict[str, ToolApproved | ToolDenied] = {}
    for call in requests.approvals:
        ctx = {
            "tool_name": call.tool_name,
            "tool_call_id": call.tool_call_id,
            "args": call.args if isinstance(call.args, dict) else {},
            "message": f"Approve tool {call.tool_name}?",
        }
        approved = bool(resolver(ctx))
        agent_trace.trace_deferred_resume(
            deps.config,
            approved,
            f"tool={call.tool_name} call_id={call.tool_call_id}",
        )
        approvals[call.tool_call_id] = ToolApproved() if approved else ToolDenied()

    return DeferredToolResults(approvals=approvals) if approvals else None


def _run_agent_sync(
    agent: Agent[BestBuddyDeps, TurnResult],
    *,
    config: AgentConfig,
    thread_id: str,
    user_text: str,
    workflow_context: dict[str, Any] | None,
    approval_resolver: Callable[[dict[str, Any]], bool] | None,
    message_history: list[ModelMessage] | None,
    deferred_tool_results: DeferredToolResults | None,
    persist_thread: bool = True,
    memory_source: str | None = None,
    user_images: list[UserImage] | None = None,
) -> TurnResult:
    deps = BestBuddyDeps(
        config=config,
        thread_id=thread_id,
        workflow_context=workflow_context,
        approval_resolver=approval_resolver,
        turn_user_text=user_text,
        memory_source=memory_source,
    )
    model_label = getattr(agent.model, "model_name", str(config.llm_model))
    images = user_images or []
    image_summary = image_trace_summary(images)
    agent_trace.trace_turn_start(
        config,
        thread_id=thread_id,
        user_text=user_text,
        workflow_context=workflow_context,
        model_label=model_label,
        image_summary=image_summary,
    )

    history = message_history if message_history is not None else thread_to_message_history(thread_id)
    if config.vision.enabled and history:
        history = strip_images_for_storage(history)
    instructions_text, memory_block, recall_meta = _compose_instructions(deps, user_text)
    agent_trace.trace_instructions(config, instructions_text)
    agent_trace.trace_message_history(config, history)
    agent_trace.trace_routing_snapshot(
        config,
        thread_id=thread_id,
        user_text=user_text,
        recall_meta=recall_meta,
        memory_block=memory_block,
        instructions_text=instructions_text,
        history_lines=_history_trace_lines(thread_id),
        tool_catalog=config.prompts.tool_catalog(),
        max_tool_iterations=config.max_tool_iterations,
    )

    limits = UsageLimits(
        request_limit=config.max_tool_iterations * 3,
        tool_calls_limit=config.max_tool_iterations,
    )

    run_input = build_native_user_prompt(user_text, images)

    t0 = time.perf_counter()
    try:
        result = agent.run_sync(
            run_input,
            deps=deps,
            message_history=history,
            usage_limits=limits,
            deferred_tool_results=deferred_tool_results,
        )
    except Exception as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        agent_trace.trace_turn_end(
            config,
            elapsed_ms=elapsed,
            output_len=0,
            message_count=0,
            error=str(exc),
        )
        raise

    elapsed = int((time.perf_counter() - t0) * 1000)
    messages = result.all_messages()
    new_messages = result.new_messages()
    agent_trace.log_run_messages(config, messages)

    output = result.output
    if isinstance(output, DeferredToolRequests):
        pending: list[dict[str, Any]] = []
        first_name = ""
        first_id = ""
        first_args: dict[str, Any] = {}
        for call in output.approvals:
            first_name = first_name or call.tool_name
            first_id = first_id or call.tool_call_id
            first_args = call.args if isinstance(call.args, dict) else {}
            pending.append(
                {
                    "tool_name": call.tool_name,
                    "tool_call_id": call.tool_call_id,
                    "args": first_args,
                }
            )
        agent_trace.trace_deferred_pending(config, pending)
        agent_trace.trace_turn_end(
            config,
            elapsed_ms=elapsed,
            output_len=0,
            message_count=len(messages),
        )
        if persist_thread and new_messages:
            stored = (
                strip_images_for_storage(new_messages)
                if config.vision.enabled
                else new_messages
            )
            append_turn_messages(thread_id, stored)
        if approval_resolver is None:
            return InterruptResult(
                tool_name=first_name,
                tool_call_id=first_id,
                args=first_args,
                message=f"Approval required for {first_name}",
                pending=pending,
                message_history=(
                    strip_images_for_storage(list(messages))
                    if config.vision.enabled
                    else list(messages)
                ),
            )
        deferred = _resolve_deferred(deps, output)
        if deferred is None:
            return InterruptResult(
                tool_name=first_name,
                tool_call_id=first_id,
                args=first_args,
                pending=pending,
                message_history=(
                    strip_images_for_storage(list(messages))
                    if config.vision.enabled
                    else list(messages)
                ),
            )
        return run_turn(
            config,
            thread_id,
            user_text,
            workflow_context=workflow_context,
            approval_resolver=approval_resolver,
            deferred_tool_results=deferred,
            message_history=(
                strip_images_for_storage(list(messages))
                if config.vision.enabled
                else messages
            ),
            _agent=agent,
            persist_thread=persist_thread,
            memory_source=deps.memory_source,
        )

    text = str(output).strip() if output is not None else ""
    agent_trace.trace_turn_end(
        config,
        elapsed_ms=elapsed,
        output_len=len(text),
        message_count=len(messages),
    )
    if not text:
        raise AgentEmptyResponseError("Model run completed without text output")
    if persist_thread and new_messages:
        stored = (
            strip_images_for_storage(new_messages)
            if config.vision.enabled
            else new_messages
        )
        append_turn_messages(thread_id, stored)
    return text


_agent_cache: Agent[BestBuddyDeps, TurnResult] | None = None
_agent_cache_key: tuple[object, ...] | None = None


def get_agent(config: AgentConfig) -> Agent[BestBuddyDeps, TurnResult]:
    global _agent_cache, _agent_cache_key
    key = agent_config_fingerprint(config)
    if _agent_cache is None or _agent_cache_key != key:
        _agent_cache = build_agent(config)
        _agent_cache_key = key
    return _agent_cache


def run_turn(
    config: AgentConfig,
    thread_id: str,
    user_text: str,
    *,
    workflow_context: dict[str, Any] | None = None,
    approval_resolver: Callable[[dict[str, Any]], bool] | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
    message_history: list[ModelMessage] | None = None,
    persist_thread: bool = True,
    timeout_sec: int = 90,  # noqa: ARG001
    memory_source: str | None = None,
    user_images: list[UserImage] | None = None,
    _agent: Agent[BestBuddyDeps, TurnResult] | None = None,
) -> TurnResult:
    agent = _agent or get_agent(config)
    return _run_agent_sync(
        agent,
        config=config,
        thread_id=thread_id,
        user_text=user_text,
        workflow_context=workflow_context,
        approval_resolver=approval_resolver,
        message_history=message_history,
        deferred_tool_results=deferred_tool_results,
        persist_thread=persist_thread,
        memory_source=memory_source,
        user_images=user_images,
    )


def resume_turn(
    config: AgentConfig,
    thread_id: str,
    user_text: str,
    interrupt: InterruptResult,
    *,
    approved: bool,
    workflow_context: dict[str, Any] | None = None,
    approval_resolver: Callable[[dict[str, Any]], bool] | None = None,
    _agent: Agent[BestBuddyDeps, TurnResult] | None = None,
) -> TurnResult:
    tid = interrupt.tool_call_id
    if not tid:
        return "Nothing to resume."
    results = DeferredToolResults(
        approvals={tid: ToolApproved() if approved else ToolDenied()},
    )
    agent_trace.trace_deferred_resume(
        config,
        approved,
        f"resume tool={interrupt.tool_name} call_id={tid}",
    )
    return run_turn(
        config,
        thread_id,
        user_text,
        workflow_context=workflow_context,
        approval_resolver=approval_resolver,
        deferred_tool_results=results,
        message_history=interrupt.message_history or None,
        _agent=_agent,
    )


def make_workflow_step_executor(
    config: AgentConfig,
    *,
    approval_resolver: Callable[[dict[str, Any]], bool] | None = None,
) -> Callable[[dict], str]:
    def _exec(step: dict, context: dict | None = None) -> str:
        ctx = context or {}
        prompt = str(step.get("prompt") or "").strip()
        if not prompt:
            return ""
        wf_ctx = {
            "workflow_id": ctx.get("workflow_id"),
            "run_id": ctx.get("run_id"),
            "step_id": ctx.get("step_id"),
            "step_outputs": ctx.get("step_outputs") or {},
        }
        thread_id = f"wf-{wf_ctx.get('workflow_id') or 'anon'}"
        out = run_turn(
            config,
            thread_id,
            prompt,
            workflow_context=wf_ctx,
            approval_resolver=approval_resolver,
        )
        if isinstance(out, InterruptResult):
            return f"[approval required: {out.tool_name}]"
        return str(out)

    return _exec


def default_step_executor(step: dict, context: dict | None = None) -> str:
    from .config import load_config

    return make_workflow_step_executor(load_config())(step, context)
