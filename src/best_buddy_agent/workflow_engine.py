"""Workflow engine with NL creation, pipeline steps, state/history, and recurring loop.

This module keeps a compact implementation while preserving high-value concepts
from Thoth's workflow architecture:
- Natural-language workflow definition creation via LLM
- Typed pipeline steps (prompt/condition/approval/subtask/notify)
- Persistent run state and step-level history
- Recurring/monitoring scheduling loop
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

from .config import AgentConfig
from .workflow_models import WorkflowPlan

_DATA_DIR = pathlib.Path(
    os.environ.get("BEST_BUDDY_AGENT_DATA_DIR", pathlib.Path.home() / ".best_buddy_agent")
)
_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = _DATA_DIR / "workflows.db"

# In-flight run guard (workflow_id -> run_id)
_active_runs: dict[str, str] = {}
_active_lock = threading.Lock()

_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()

_function_registry: dict[str, Callable[[dict], str]] = {}
_runtime_context: dict[str, Any] = {}


def register_workflow_function(name: str, fn: Callable[[dict], str]) -> None:
    _function_registry[name] = fn


def set_workflow_runtime_context(ctx: dict[str, Any]) -> None:
    global _runtime_context
    _runtime_context = dict(ctx)


def clear_workflow_runtime_context() -> None:
    global _runtime_context
    _runtime_context = {}


def get_workflow_runtime_context() -> dict[str, Any]:
    return dict(_runtime_context)


class WorkflowError(Exception):
    """Raised for workflow validation/execution errors."""


def _now_iso() -> str:
    return datetime.now().isoformat()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            steps TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            schedule_type TEXT,
            schedule_value TEXT,
            next_run_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_run TEXT,
            notify_only INTEGER DEFAULT 0,
            notify_message TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}'
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            status TEXT NOT NULL,
            status_message TEXT DEFAULT '',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            steps_total INTEGER DEFAULT 0,
            steps_done INTEGER DEFAULT 0,
            output TEXT DEFAULT '',
            state_json TEXT DEFAULT '{}'
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_step_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            step_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            output TEXT DEFAULT ''
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_states (
            run_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            current_step_index INTEGER NOT NULL,
            step_outputs TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    # Light migration support for old DBs
    for sql in (
        "ALTER TABLE workflows ADD COLUMN schedule_type TEXT",
        "ALTER TABLE workflows ADD COLUMN schedule_value TEXT",
        "ALTER TABLE workflows ADD COLUMN next_run_at TEXT",
        "ALTER TABLE workflow_runs ADD COLUMN status_message TEXT DEFAULT ''",
        "ALTER TABLE workflow_runs ADD COLUMN steps_total INTEGER DEFAULT 0",
        "ALTER TABLE workflow_runs ADD COLUMN steps_done INTEGER DEFAULT 0",
        "ALTER TABLE workflow_runs ADD COLUMN state_json TEXT DEFAULT '{}'",
        "ALTER TABLE workflows ADD COLUMN notify_only INTEGER DEFAULT 0",
        "ALTER TABLE workflows ADD COLUMN notify_message TEXT DEFAULT ''",
        "ALTER TABLE workflows ADD COLUMN metadata_json TEXT DEFAULT '{}'",
    ):
        try:
            conn.execute(sql)
        except Exception:
            pass

    return conn


def _normalize_schedule(
    schedule: dict | None,
    *,
    allow_past_once: bool = False,
) -> tuple[str | None, str | None, str | None]:
    """Return (schedule_type, schedule_value_json, next_run_at)."""
    if not schedule:
        return None, None, None

    st = (schedule.get("type") or "").strip().lower()
    if st not in {"interval", "daily", "once"}:
        raise WorkflowError("schedule.type must be one of: interval, daily, once")

    now = datetime.now()

    if st == "interval":
        seconds = int(schedule.get("seconds") or 0)
        if seconds <= 0:
            raise WorkflowError("interval schedule requires positive seconds")
        value = {"seconds": seconds}
        next_run = (now + timedelta(seconds=seconds)).isoformat()
        return st, json.dumps(value), next_run

    if st == "daily":
        hhmm = str(schedule.get("time") or "").strip()
        if not re.fullmatch(r"\d{2}:\d{2}", hhmm):
            raise WorkflowError("daily schedule requires time='HH:MM'")
        h, m = [int(x) for x in hhmm.split(":")]
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        value = {"time": hhmm}
        return st, json.dumps(value), target.isoformat()

    # once
    at = str(schedule.get("at") or "").strip()
    try:
        dt = datetime.fromisoformat(at)
    except ValueError as exc:
        raise WorkflowError("once schedule requires ISO datetime in 'at'") from exc
    now_cmp = datetime.now(dt.tzinfo) if dt.tzinfo is not None else now
    if dt <= now_cmp and not allow_past_once:
        raise WorkflowError("once schedule 'at' must be in the future")
    value = {"at": at}
    next_run = dt.isoformat() if dt > now_cmp else (now_cmp + timedelta(seconds=2)).isoformat()
    return st, json.dumps(value), next_run


def _next_run_after(schedule_type: str | None, schedule_value_json: str | None, now: datetime) -> str | None:
    if not schedule_type or not schedule_value_json:
        return None
    val = json.loads(schedule_value_json)

    if schedule_type == "interval":
        return (now + timedelta(seconds=int(val["seconds"]))).isoformat()

    if schedule_type == "daily":
        h, m = [int(x) for x in str(val["time"]).split(":")]
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.isoformat()

    if schedule_type == "once":
        return None

    return None


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _schedule_is_due(next_run_at: str, *, now: datetime | None = None) -> bool:
    """True when next_run_at is in the past (timezone-aware compare when possible)."""
    if not (next_run_at or "").strip():
        return False
    ref = now or datetime.now().astimezone()
    try:
        due = _parse_iso_datetime(next_run_at)
    except ValueError:
        return next_run_at <= ref.isoformat()
    if due.tzinfo is None:
        ref_cmp = ref.replace(tzinfo=None) if ref.tzinfo else ref
        return due <= ref_cmp
    if ref.tzinfo is None:
        ref = ref.astimezone()
    return due <= ref


def _decode_workflow_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["steps"] = json.loads(d.get("steps") or "[]")
    d["enabled"] = bool(d.get("enabled", 1))
    d["notify_only"] = bool(d.get("notify_only", 0))
    d["notify_message"] = d.get("notify_message") or ""
    try:
        d["metadata"] = json.loads(d.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        d["metadata"] = {}
    d["schedule"] = (
        {"type": d["schedule_type"], **(json.loads(d.get("schedule_value") or "{}"))}
        if d.get("schedule_type")
        else None
    )
    return d


def _validate_steps(steps: list[dict] | None, *, notify_only: bool = False) -> list[dict]:
    if steps is None:
        steps = []
    if not isinstance(steps, list):
        raise WorkflowError("steps must be a list")
    if not steps and not notify_only:
        raise WorkflowError("steps must be a non-empty list (unless notify_only=true)")

    allowed = {"prompt", "condition", "approval", "subtask", "notify", "function"}
    out: list[dict] = []
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            raise WorkflowError(f"step {i} must be an object")
        step = dict(s)
        step.setdefault("id", f"step_{i+1}")
        stype = str(step.get("type") or "prompt").strip().lower()
        if stype not in allowed:
            raise WorkflowError(f"step {step['id']} has unsupported type: {stype}")
        step["type"] = stype
        out.append(step)
    return out


def create_workflow(
    name: str,
    steps: list[dict] | None = None,
    schedule: dict | None = None,
    enabled: bool = True,
    *,
    workflow_id: str | None = None,
    notify_only: bool = False,
    notify_message: str = "",
    metadata: dict | None = None,
    allow_past_once: bool = False,
) -> str:
    wid = (workflow_id or uuid.uuid4().hex[:12]).strip()
    now = _now_iso()
    steps = _validate_steps(steps, notify_only=notify_only)
    st, sv, next_run = _normalize_schedule(schedule, allow_past_once=allow_past_once)
    meta_json = json.dumps(metadata or {})

    c = _conn()
    c.execute(
        """
        INSERT INTO workflows
        (id, name, steps, enabled, schedule_type, schedule_value, next_run_at,
         created_at, updated_at, notify_only, notify_message, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            wid,
            name,
            json.dumps(steps),
            int(enabled),
            st,
            sv,
            next_run,
            now,
            now,
            int(notify_only),
            notify_message or "",
            meta_json,
        ),
    )
    c.commit()
    c.close()
    return wid


def upsert_workflow(workflow_id: str, **kwargs) -> str:
    """Insert or replace workflow by fixed id."""
    wid = workflow_id.strip()
    if get_workflow(wid):
        update_workflow(wid, **kwargs)
        return wid
    return create_workflow(workflow_id=wid, **kwargs)


def create_workflow_from_natural_language(
    *,
    config: AgentConfig,
    intent: str,
    timeout_sec: int = 90,  # noqa: ARG001
) -> tuple[str, dict]:
    """Create workflow from NL intent via pydantic-ai structured output."""
    from .agent_runtime import build_planner_agent

    instructions = config.prompts.get("planner/workflow_nl_system")
    planner = build_planner_agent(
        config,
        output_type=WorkflowPlan,
        instructions=instructions,
    )
    result = planner.run_sync(config.prompts.format("planner/workflow_nl_user", intent=intent))
    plan: WorkflowPlan = result.output
    steps = [s.to_dict() for s in plan.steps]
    if not steps:
        raise WorkflowError("LLM workflow definition missing non-empty 'steps'")
    wid = create_workflow(name=plan.name.strip() or "workflow", steps=steps, schedule=plan.schedule, enabled=True)
    return wid, plan.model_dump()


def list_workflows() -> list[dict]:
    c = _conn()
    rows = c.execute("SELECT * FROM workflows ORDER BY created_at DESC").fetchall()
    c.close()
    return [_decode_workflow_row(r) for r in rows]


def get_workflow(workflow_id: str) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    c.close()
    return _decode_workflow_row(row) if row else None


def update_workflow(workflow_id: str, **kwargs) -> None:
    row = get_workflow(workflow_id)
    if not row:
        raise WorkflowError(f"Unknown workflow: {workflow_id}")

    name = kwargs.get("name", row["name"])
    enabled = bool(kwargs.get("enabled", row["enabled"]))
    notify_only = bool(kwargs.get("notify_only", row.get("notify_only", False)))
    notify_message = kwargs.get("notify_message", row.get("notify_message", ""))
    metadata = kwargs.get("metadata", row.get("metadata", {}))
    steps = _validate_steps(kwargs.get("steps", row["steps"]), notify_only=notify_only)
    schedule = kwargs.get("schedule", row.get("schedule"))
    allow_past_once = bool(kwargs.get("allow_past_once", False))

    st, sv, next_run = _normalize_schedule(schedule, allow_past_once=allow_past_once) if schedule is not None else (
        row.get("schedule_type"),
        row.get("schedule_value"),
        row.get("next_run_at"),
    )

    c = _conn()
    c.execute(
        """
        UPDATE workflows
        SET name = ?, steps = ?, enabled = ?, schedule_type = ?, schedule_value = ?,
            next_run_at = ?, updated_at = ?, notify_only = ?, notify_message = ?, metadata_json = ?
        WHERE id = ?
        """,
        (
            name,
            json.dumps(steps),
            int(enabled),
            st,
            sv,
            next_run,
            _now_iso(),
            int(notify_only),
            notify_message or "",
            json.dumps(metadata or {}),
            workflow_id,
        ),
    )
    c.commit()
    c.close()


def delete_workflow(workflow_id: str) -> None:
    c = _conn()
    c.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
    c.execute("DELETE FROM workflow_runs WHERE workflow_id = ?", (workflow_id,))
    c.execute("DELETE FROM workflow_step_runs WHERE workflow_id = ?", (workflow_id,))
    c.execute("DELETE FROM workflow_states WHERE workflow_id = ?", (workflow_id,))
    c.commit()
    c.close()


def get_run_history(workflow_id: str, limit: int = 20) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM workflow_runs WHERE workflow_id = ? ORDER BY started_at DESC LIMIT ?",
        (workflow_id, limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_step_history(run_id: str) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM workflow_step_runs WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_run_state(run_id: str) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM workflow_states WHERE run_id = ?", (run_id,)).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    d["step_outputs"] = json.loads(d.get("step_outputs") or "{}")
    return d


def _save_run_state(run_id: str, workflow_id: str, current_step_index: int, step_outputs: dict[str, str], status: str) -> None:
    c = _conn()
    c.execute(
        """
        INSERT INTO workflow_states (run_id, workflow_id, current_step_index, step_outputs, status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            current_step_index = excluded.current_step_index,
            step_outputs = excluded.step_outputs,
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (run_id, workflow_id, current_step_index, json.dumps(step_outputs), status, _now_iso()),
    )
    c.commit()
    c.close()


def _record_step(run_id: str, workflow_id: str, step_id: str, step_type: str, status: str, started_at: str, output: str = "") -> None:
    c = _conn()
    c.execute(
        """
        INSERT INTO workflow_step_runs (run_id, workflow_id, step_id, step_type, status, started_at, finished_at, output)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, workflow_id, step_id, step_type, status, started_at, _now_iso(), output),
    )
    c.commit()
    c.close()


def _expand_template(text: str, step_outputs: dict[str, str], workflow_id: str, run_id: str) -> str:
    out = str(text or "")
    prev = list(step_outputs.values())[-1] if step_outputs else ""
    out = out.replace("{{prev_output}}", prev)
    out = out.replace("{{workflow_id}}", workflow_id)
    out = out.replace("{{run_id}}", run_id)

    def _sub(match):
        sid = match.group(1)
        return step_outputs.get(sid, "")

    out = re.sub(r"\{\{step\.([^.]+)\.output\}\}", _sub, out)
    return out


def _call_step_executor(step_executor, step: dict, context: dict) -> str:
    # Backward-compatible function signatures: executor(step) or executor(step, context)
    try:
        return str(step_executor(step, context))
    except TypeError:
        return str(step_executor(step))


def default_agent_step_executor(config: AgentConfig) -> Callable[..., str]:
    """Build prompt-step executor backed by pydantic-ai agent."""
    from .agent_runtime import make_workflow_step_executor

    return make_workflow_step_executor(config)


def _step_index_map(steps: list[dict]) -> dict[str, int]:
    return {str(s.get("id")): i for i, s in enumerate(steps)}


def run_workflow(
    workflow_id: str,
    step_executor: Callable[..., str],
    *,
    notifier: Callable[[str], Any] | None = None,
    approval_resolver: Callable[[dict], bool] | None = None,
    start_step_index: int = 0,
    run_id: str | None = None,
    step_outputs: dict[str, str] | None = None,
) -> str:
    row = get_workflow(workflow_id)
    if not row:
        raise WorkflowError(f"Unknown workflow: {workflow_id}")

    if row.get("notify_only"):
        run_id = run_id or uuid.uuid4().hex[:12]
        c = _conn()
        c.execute(
            """
            INSERT INTO workflow_runs (id, workflow_id, status, started_at, steps_total, steps_done)
            VALUES (?, ?, 'running', ?, 0, 0)
            """,
            (run_id, workflow_id, _now_iso()),
        )
        c.commit()
        c.close()
        msg = row.get("notify_message") or row.get("name") or "Reminder"
        if notifier:
            notifier(msg)
        finished = _now_iso()
        c = _conn()
        c.execute(
            """
            UPDATE workflow_runs
            SET status = ?, finished_at = ?, output = ?, steps_done = 0
            WHERE id = ?
            """,
            ("completed", finished, msg, run_id),
        )
        next_run = _next_run_after(row.get("schedule_type"), row.get("schedule_value"), datetime.now())
        enabled = row.get("enabled", True)
        if row.get("schedule_type") == "once":
            enabled = False
        c.execute(
            "UPDATE workflows SET last_run = ?, next_run_at = ?, enabled = ?, updated_at = ? WHERE id = ?",
            (finished, next_run, int(bool(enabled)), finished, workflow_id),
        )
        c.commit()
        c.close()
        return run_id

    steps = _validate_steps(row["steps"])
    id_to_idx = _step_index_map(steps)

    if run_id is None:
        run_id = uuid.uuid4().hex[:12]
        c = _conn()
        c.execute(
            """
            INSERT INTO workflow_runs (id, workflow_id, status, started_at, steps_total, steps_done)
            VALUES (?, ?, 'running', ?, ?, 0)
            """,
            (run_id, workflow_id, _now_iso(), len(steps)),
        )
        c.commit()
        c.close()

    outputs = dict(step_outputs or {})
    i = start_step_index
    status = "completed"
    status_message = ""

    while i < len(steps):
        step = steps[i]
        sid = str(step.get("id"))
        stype = str(step.get("type") or "prompt").lower()
        started = _now_iso()

        _save_run_state(run_id, workflow_id, i, outputs, "running")

        if stype == "prompt":
            prompt = _expand_template(str(step.get("prompt") or ""), outputs, workflow_id, run_id)
            context = {
                "workflow_id": workflow_id,
                "run_id": run_id,
                "step_outputs": dict(outputs),
                "step_index": i,
                "step_id": sid,
            }
            result = _call_step_executor(step_executor, {**step, "prompt": prompt}, context)
            outputs[sid] = result
            _record_step(run_id, workflow_id, sid, stype, "completed", started, result)
            i += 1

        elif stype == "condition":
            operator = str(step.get("operator") or "contains").strip().lower()
            left = _expand_template(str(step.get("left") or "{{prev_output}}"), outputs, workflow_id, run_id)
            value = _expand_template(str(step.get("value") or ""), outputs, workflow_id, run_id)

            if operator == "contains":
                ok = value in left
            elif operator == "not_contains":
                ok = value not in left
            elif operator == "regex":
                ok = re.search(value, left) is not None
            else:
                raise WorkflowError(f"Unsupported condition operator: {operator}")

            outputs[sid] = "true" if ok else "false"
            _record_step(run_id, workflow_id, sid, stype, "completed", started, outputs[sid])

            target = step.get("if_true") if ok else step.get("if_false")
            if target and str(target) in id_to_idx:
                i = id_to_idx[str(target)]
            else:
                i += 1

        elif stype == "approval":
            msg = _expand_template(str(step.get("message") or "Approval required"), outputs, workflow_id, run_id)
            if approval_resolver is None:
                status = "paused"
                status_message = msg
                _record_step(run_id, workflow_id, sid, stype, "paused", started, msg)
                _save_run_state(run_id, workflow_id, i, outputs, "paused")
                break

            approved = bool(approval_resolver({"workflow_id": workflow_id, "run_id": run_id, "step": step, "message": msg}))
            outputs[sid] = "approved" if approved else "denied"
            _record_step(run_id, workflow_id, sid, stype, "completed", started, outputs[sid])
            target = step.get("if_true") if approved else step.get("if_false")
            if target and str(target) in id_to_idx:
                i = id_to_idx[str(target)]
            else:
                i += 1

        elif stype == "subtask":
            sub_id = str(step.get("workflow_id") or "").strip()
            if not sub_id:
                raise WorkflowError(f"subtask step {sid} missing workflow_id")
            sub_run = run_workflow(
                sub_id,
                step_executor,
                notifier=notifier,
                approval_resolver=approval_resolver,
            )
            outputs[sid] = f"subtask_run:{sub_run}"
            _record_step(run_id, workflow_id, sid, stype, "completed", started, outputs[sid])
            i += 1

        elif stype == "notify":
            msg = _expand_template(str(step.get("message") or ""), outputs, workflow_id, run_id)
            if notifier:
                notifier(msg)
            outputs[sid] = msg
            _record_step(run_id, workflow_id, sid, stype, "completed", started, msg)
            i += 1

        elif stype == "function":
            fn_name = str(step.get("name") or "").strip()
            if not fn_name:
                raise WorkflowError(f"function step {sid} missing name")
            fn = _function_registry.get(fn_name)
            if fn is None:
                raise WorkflowError(f"Unknown workflow function: {fn_name}")
            context = {
                "workflow_id": workflow_id,
                "run_id": run_id,
                "step_outputs": dict(outputs),
                "step_index": i,
                "step_id": sid,
                **_runtime_context,
            }
            result = str(fn(context))
            outputs[sid] = result
            _record_step(run_id, workflow_id, sid, stype, "completed", started, result)
            i += 1

        else:
            raise WorkflowError(f"Unsupported step type: {stype}")

        # progress update
        c = _conn()
        c.execute(
            "UPDATE workflow_runs SET steps_done = ?, state_json = ? WHERE id = ?",
            (len(outputs), json.dumps({"step_outputs": outputs, "current_step_index": i}), run_id),
        )
        c.commit()
        c.close()

    # finalize run
    finished = _now_iso()
    if status == "completed":
        out = "\n".join(outputs.get(str(s.get("id")), "") for s in steps if str(s.get("id")) in outputs)
        c = _conn()
        c.execute(
            """
            UPDATE workflow_runs
            SET status = ?, status_message = ?, finished_at = ?, output = ?, steps_done = ?, state_json = ?
            WHERE id = ?
            """,
            (status, status_message, finished, out, len(outputs), json.dumps({"step_outputs": outputs}), run_id),
        )

        # schedule update
        next_run = _next_run_after(row.get("schedule_type"), row.get("schedule_value"), datetime.now())
        enabled = row.get("enabled", True)
        if row.get("schedule_type") == "once":
            enabled = False

        c.execute(
            "UPDATE workflows SET last_run = ?, next_run_at = ?, enabled = ?, updated_at = ? WHERE id = ?",
            (finished, next_run, int(bool(enabled)), finished, workflow_id),
        )
        c.execute("DELETE FROM workflow_states WHERE run_id = ?", (run_id,))
        c.commit()
        c.close()
    else:
        c = _conn()
        c.execute(
            """
            UPDATE workflow_runs
            SET status = ?, status_message = ?, finished_at = ?, steps_done = ?, state_json = ?
            WHERE id = ?
            """,
            (status, status_message, finished, len(outputs), json.dumps({"step_outputs": outputs, "current_step_index": i}), run_id),
        )
        c.commit()
        c.close()

    return run_id


def resume_workflow(
    run_id: str,
    step_executor: Callable[..., str],
    *,
    notifier: Callable[[str], Any] | None = None,
    approval_resolver: Callable[[dict], bool] | None = None,
) -> str:
    st = get_run_state(run_id)
    if not st:
        raise WorkflowError(f"No saved state for run: {run_id}")
    if st.get("status") != "paused":
        raise WorkflowError(f"Run {run_id} is not paused")
    return run_workflow(
        st["workflow_id"],
        step_executor,
        notifier=notifier,
        approval_resolver=approval_resolver,
        start_step_index=int(st["current_step_index"]),
        run_id=run_id,
        step_outputs=dict(st.get("step_outputs") or {}),
    )


def run_workflow_background(
    workflow_id: str,
    step_executor: Callable[..., str],
    *,
    notifier: Callable[[str], Any] | None = None,
    approval_resolver: Callable[[dict], bool] | None = None,
) -> threading.Thread:
    def _target():
        with _active_lock:
            if workflow_id in _active_runs:
                return
            marker = uuid.uuid4().hex[:8]
            _active_runs[workflow_id] = marker
        try:
            run_workflow(workflow_id, step_executor, notifier=notifier, approval_resolver=approval_resolver)
        finally:
            with _active_lock:
                _active_runs.pop(workflow_id, None)

    t = threading.Thread(target=_target, daemon=True, name=f"workflow-{workflow_id}")
    t.start()
    return t


def run_scheduler_once(
    step_executor: Callable[..., str],
    *,
    notifier: Callable[[str], Any] | None = None,
    approval_resolver: Callable[[dict], bool] | None = None,
) -> int:
    """Dispatch due recurring workflows once. Returns number dispatched."""
    now = datetime.now().astimezone()
    c = _conn()
    rows = c.execute(
        """
        SELECT * FROM workflows
        WHERE enabled = 1 AND next_run_at IS NOT NULL
        ORDER BY next_run_at ASC
        """
    ).fetchall()
    c.close()

    dispatched = 0
    for row in rows:
        if not _schedule_is_due(row["next_run_at"], now=now):
            continue
        wid = row["id"]
        with _active_lock:
            if wid in _active_runs:
                continue
        run_workflow_background(wid, step_executor, notifier=notifier, approval_resolver=approval_resolver)
        dispatched += 1
    return dispatched


def start_scheduler_loop(
    step_executor: Callable[..., str],
    *,
    notifier: Callable[[str], Any] | None = None,
    approval_resolver: Callable[[dict], bool] | None = None,
    poll_seconds: int = 5,
) -> None:
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return

    _scheduler_stop.clear()

    def _loop():
        while not _scheduler_stop.wait(timeout=max(1, poll_seconds)):
            try:
                run_scheduler_once(
                    step_executor,
                    notifier=notifier,
                    approval_resolver=approval_resolver,
                )
            except Exception:
                # keep loop alive
                pass

    _scheduler_thread = threading.Thread(target=_loop, daemon=True, name="workflow-scheduler")
    _scheduler_thread.start()


def stop_scheduler_loop() -> None:
    _scheduler_stop.set()
