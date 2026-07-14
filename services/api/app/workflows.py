"""Workflow engine: JSON step lists with variables, conditions, loops, retries.

A workflow is an ordered list of steps. Steps read/write a shared variable
dict; `{var}` and `{var.key}` placeholders interpolate anywhere in step
config. Event-triggered workflows receive the event payload as `{event.*}`.

Step types
----------
search         {query, limit?, out?}            → list of hits
context        {query, max_tokens?, out?}       → RAG context dict
summarize      {text, out?}                     → generated/extractive summary
create_memory  {content, memory_type?, tags?}   → stored memory id
tool           {tool, args, out?}               → sandboxed tool result
condition      {left, op, right}                → stops the run (status ok,
                                                  "skipped") when false
for_each       {items, steps, max_iterations?}  → runs sub-steps per item
                                                  (item available as {item})

Every step supports  retry: N  and  timeout_s: S  (soft wall-clock check).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from sqlalchemy.orm import Session

from . import observability
from .events import emit, subscribe
from .models import _now_iso
from .models_platform import Workflow, WorkflowRun

MAX_STEPS = 50
MAX_LOOP_ITER = 25

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


class WorkflowError(Exception):
    pass


def _lookup(variables: dict, dotted: str) -> Any:
    cur: Any = variables
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def interpolate(value: Any, variables: dict) -> Any:
    """Replace {var} placeholders in strings (recursively through dict/list)."""
    if isinstance(value, str):
        exact = _PLACEHOLDER.fullmatch(value.strip())
        if exact:  # whole-string placeholder keeps the native type
            found = _lookup(variables, exact.group(1))
            return value if found is None else found
        def _sub(m: re.Match) -> str:
            found = _lookup(variables, m.group(1))
            return "" if found is None else str(found)

        return _PLACEHOLDER.sub(_sub, value)
    if isinstance(value, dict):
        return {k: interpolate(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, variables) for v in value]
    return value


# ---------------------------------------------------------------------------
# Step handlers
# ---------------------------------------------------------------------------


def _step_search(db: Session, ws: str, cfg: dict, variables: dict) -> Any:
    from .search import hybrid_search

    hits = hybrid_search(db, ws, str(cfg["query"]), limit=int(cfg.get("limit", 5)))
    return [
        {"id": h.memory.id, "title": h.memory.title,
         "content": h.memory.content[:400], "score": h.final}
        for h in hits
    ]


def _step_context(db: Session, ws: str, cfg: dict, variables: dict) -> Any:
    from .rag import build_context

    return build_context(db, ws, str(cfg["query"]),
                         max_tokens=int(cfg.get("max_tokens", 1200)))


def _step_summarize(db: Session, ws: str, cfg: dict, variables: dict) -> Any:
    from .ai import get_generator

    text = cfg.get("text", "")
    if not isinstance(text, str):
        text = json.dumps(text, default=str)
    return get_generator().generate(
        f"Summarize concisely:\n\n{text[:6000]}", source_text=text[:6000]
    )


def _step_create_memory(db: Session, ws: str, cfg: dict, variables: dict) -> Any:
    from .pipeline import ingest_memory

    content = cfg.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, default=str)
    mem = ingest_memory(db, workspace_id=ws, content=content[:100_000],
                        type_=str(cfg.get("memory_type", "note")),
                        tags=list(cfg.get("tags", []))[:10])
    return {"id": mem.id, "title": mem.title}


def _step_tool(db: Session, ws: str, cfg: dict, variables: dict) -> Any:
    from .tools import execute

    return execute(db, str(cfg["tool"]), dict(cfg.get("args", {})),
                   workspace_id=ws, caller="workflow")


_OPS = {
    "==": lambda a, b: str(a) == str(b),
    "!=": lambda a, b: str(a) != str(b),
    "contains": lambda a, b: str(b).lower() in str(a).lower(),
    ">": lambda a, b: float(a) > float(b),
    "<": lambda a, b: float(a) < float(b),
    ">=": lambda a, b: float(a) >= float(b),
    "<=": lambda a, b: float(a) <= float(b),
}


def _step_condition(db: Session, ws: str, cfg: dict, variables: dict) -> Any:
    op = str(cfg.get("op", "=="))
    if op not in _OPS:
        raise WorkflowError(f"unknown condition op {op!r}")
    return bool(_OPS[op](cfg.get("left", ""), cfg.get("right", "")))


_HANDLERS = {
    "search": _step_search,
    "context": _step_context,
    "summarize": _step_summarize,
    "create_memory": _step_create_memory,
    "tool": _step_tool,
    "condition": _step_condition,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _run_steps(db: Session, ws: str, steps: list[dict], variables: dict,
               log: list[dict], depth: int = 0) -> str:
    """Returns final status: ok | skipped | failed."""
    if depth > 2:
        raise WorkflowError("loop nesting too deep")
    for idx, raw_step in enumerate(steps[:MAX_STEPS]):
        step = interpolate(dict(raw_step), variables)
        stype = str(step.get("type", ""))
        entry: dict = {"step": idx, "type": stype, "status": "ok"}
        started = time.perf_counter()
        try:
            if stype == "for_each":
                items = step.get("items", [])
                if isinstance(items, str):
                    items = []
                sub_steps = raw_step.get("steps", [])
                n = min(len(items), int(step.get("max_iterations", MAX_LOOP_ITER)), MAX_LOOP_ITER)
                for i in range(n):
                    loop_vars = {**variables, "item": items[i], "index": i}
                    status = _run_steps(db, ws, sub_steps, loop_vars, log, depth + 1)
                    if status == "failed":
                        raise WorkflowError(f"iteration {i} failed")
                entry["iterations"] = n
            elif stype in _HANDLERS:
                retries = max(0, min(int(step.get("retry", 0)), 5))
                timeout_s = float(step.get("timeout_s", 60))
                last_exc: Exception | None = None
                result = None
                for attempt in range(retries + 1):
                    try:
                        result = _HANDLERS[stype](db, ws, step, variables)
                        last_exc = None
                        break
                    except Exception as e:  # noqa: BLE001
                        last_exc = e
                        entry["attempts"] = attempt + 1
                    if time.perf_counter() - started > timeout_s:
                        raise WorkflowError(f"step {idx} exceeded {timeout_s}s")
                if last_exc is not None:
                    raise last_exc
                if stype == "condition" and result is False:
                    entry["status"] = "stopped"
                    log.append(entry)
                    return "skipped"
                out = raw_step.get("out")
                if out:
                    variables[str(out)] = result
                entry["preview"] = json.dumps(result, default=str)[:300]
            else:
                raise WorkflowError(f"unknown step type {stype!r}")
        except Exception as e:  # noqa: BLE001
            entry["status"] = "failed"
            entry["error"] = f"{type(e).__name__}: {e}"[:300]
            log.append(entry)
            return "failed"
        finally:
            entry["ms"] = round((time.perf_counter() - started) * 1000, 1)
        log.append(entry)
    return "ok"


def run_workflow(
    db: Session,
    workflow: Workflow,
    *,
    variables: dict | None = None,
    trigger: str = "manual",
) -> WorkflowRun:
    run = WorkflowRun(
        workflow_id=workflow.id, workspace_id=workflow.workspace_id, trigger=trigger,
        variables_json=json.dumps(variables or {}, default=str)[:4000],
    )
    db.add(run)
    db.flush()
    emit(db, "WorkflowStarted", {"workflow": workflow.name, "run_id": run.id},
         workspace_id=workflow.workspace_id)

    log: list[dict] = []
    with observability.timed("workflow"):
        status = _run_steps(db, workflow.workspace_id, workflow.steps,
                            dict(variables or {}), log)
    run.status = "ok" if status in ("ok", "skipped") else "failed"
    run.log_json = json.dumps(log, default=str)
    run.finished_at = _now_iso()
    emit(db, "WorkflowFinished",
         {"workflow": workflow.name, "run_id": run.id, "status": run.status},
         workspace_id=workflow.workspace_id)
    observability.count(f"workflows.{run.status}")
    return run


# ---------------------------------------------------------------------------
# Event trigger subscription
# ---------------------------------------------------------------------------


def _on_event(db: Session, event) -> None:
    """Run every enabled workflow whose trigger matches the event type."""
    from sqlalchemy import select

    rows = db.execute(
        select(Workflow).where(
            Workflow.workspace_id == event.workspace_id,
            Workflow.trigger_event == event.type,
            Workflow.enabled == 1,
        )
    ).scalars().all()
    for wf in rows:
        run_workflow(db, wf, variables={"event": event.payload}, trigger=event.type)


subscribe("workflow-engine", "*", _on_event)
