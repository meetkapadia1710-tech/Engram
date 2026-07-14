"""Platform-layer ORM models: plugins, events, workflows, agents, tools.

Kept separate from models.py (the memory core) so the kernel can evolve
without touching the storage layer the pipeline depends on.
"""

from __future__ import annotations

import json

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import _now_iso, _uuid


class _JsonColumn:
    """Mixin helper: JSON text column exposed as a Python object property."""

    @staticmethod
    def loads(raw: str, default):
        try:
            return json.loads(raw) if raw else default
        except json.JSONDecodeError:
            return default


# ---------------------------------------------------------------------------
# Kernel: plugins / apps
# ---------------------------------------------------------------------------


class Plugin(Base):
    """A published app/plugin in the marketplace (catalog entry)."""

    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), default="app")  # app|plugin|workflow|prompt_pack|knowledge_pack
    description: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    first_party: Mapped[int] = mapped_column(Integer, default=0)
    latest_version: Mapped[str] = mapped_column(String(40), default="0.1.0")
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    versions: Mapped[list["PluginVersion"]] = relationship(
        back_populates="plugin", cascade="all, delete-orphan"
    )
    installs: Mapped[list["PluginInstall"]] = relationship(
        back_populates="plugin", cascade="all, delete-orphan"
    )


class PluginVersion(Base):
    """Immutable published version: manifest + content signature."""

    __tablename__ = "plugin_versions"
    __table_args__ = (Index("ix_plugver_unique", "plugin_id", "version", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    plugin_id: Mapped[str] = mapped_column(
        ForeignKey("plugins.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(40))
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    signature: Mapped[str] = mapped_column(String(128), default="")  # sha256 of manifest
    min_platform: Mapped[str] = mapped_column(String(40), default="0.1.0")
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    plugin: Mapped[Plugin] = relationship(back_populates="versions")

    @property
    def manifest(self) -> dict:
        return _JsonColumn.loads(self.manifest_json, {})


class PluginInstall(Base):
    """A plugin installed into a workspace, pinned to a version."""

    __tablename__ = "plugin_installs"
    __table_args__ = (
        Index("ix_install_unique", "workspace_id", "plugin_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    plugin_id: Mapped[str] = mapped_column(
        ForeignKey("plugins.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(40))
    previous_version: Mapped[str] = mapped_column(String(40), default="")  # for rollback
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    granted_permissions_json: Mapped[str] = mapped_column(Text, default="[]")
    auto_update: Mapped[int] = mapped_column(Integer, default=1)
    installed_at: Mapped[str] = mapped_column(String(40), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    plugin: Mapped[Plugin] = relationship(back_populates="installs")

    @property
    def granted_permissions(self) -> list[str]:
        return _JsonColumn.loads(self.granted_permissions_json, [])

    @granted_permissions.setter
    def granted_permissions(self, value: list[str]) -> None:
        self.granted_permissions_json = json.dumps(value)


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    __table_args__ = (Index("ix_flag_unique", "workspace_id", "key", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(32), default="", index=True)  # "" = global
    key: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[str] = mapped_column(String(40), default=_now_iso)


class QuotaUsage(Base):
    """Daily API-call counter per workspace (storage is computed live)."""

    __tablename__ = "quota_usage"
    __table_args__ = (Index("ix_quota_unique", "workspace_id", "day", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    api_calls: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class EventRecord(Base):
    """Append-only event log; `seq` gives total ordering for replay."""

    __tablename__ = "events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(32), unique=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    type: Mapped[str] = mapped_column(String(80), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1)
    trace_id: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso, index=True)

    @property
    def payload(self) -> dict:
        return _JsonColumn.loads(self.payload_json, {})


class EventDelivery(Base):
    """Per-subscriber delivery attempt; failed deliveries land in the DLQ
    (status=dead) after max retries and can be replayed."""

    __tablename__ = "event_deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(32), index=True)
    subscriber: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # ok|retrying|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(String(40), default=_now_iso)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    trigger_event: Mapped[str] = mapped_column(String(80), default="")  # "" = manual only
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)
    updated_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    @property
    def steps(self) -> list[dict]:
        return _JsonColumn.loads(self.steps_json, [])


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)  # running|ok|failed
    trigger: Mapped[str] = mapped_column(String(80), default="manual")
    log_json: Mapped[str] = mapped_column(Text, default="[]")  # per-step results
    variables_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[str] = mapped_column(String(40), default=_now_iso)
    finished_at: Mapped[str] = mapped_column(String(40), default="")

    @property
    def log(self) -> list[dict]:
        return _JsonColumn.loads(self.log_json, [])


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class AgentRun(Base):
    """One orchestration: a goal handed to a team of agents."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    goal: Mapped[str] = mapped_column(Text)
    agents_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="running")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    conclusion_memory_id: Mapped[str] = mapped_column(String(32), default="")
    started_at: Mapped[str] = mapped_column(String(40), default=_now_iso)
    finished_at: Mapped[str] = mapped_column(String(40), default="")

    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentMessage(Base):
    """Recorded inter-agent communication (question, finding, vote, merge…)."""

    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=0)
    sender: Mapped[str] = mapped_column(String(80))
    recipient: Mapped[str] = mapped_column(String(80), default="all")
    kind: Mapped[str] = mapped_column(String(30), default="finding")  # plan|question|finding|vote|debate|merge
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    run: Mapped[AgentRun] = relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# Tool execution audit
# ---------------------------------------------------------------------------


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    tool: Mapped[str] = mapped_column(String(80), index=True)
    caller: Mapped[str] = mapped_column(String(120), default="")  # agent/workflow/user
    args_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok|denied|error|timeout
    result_preview: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)


# ---------------------------------------------------------------------------
# Digital Twin
# ---------------------------------------------------------------------------


class DigitalTwin(Base):
    """Continuously evolving user profile built from memory analysis.

    Stores a JSON snapshot per workspace of the inferred user model:
    coding style, writing patterns, skill graph, behavior graph, predictions.
    Re-computed incrementally by digital_twin.py whenever memories cross a
    threshold or a scheduled job runs.
    """

    __tablename__ = "digital_twins"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True, index=True
    )
    # Skill graph: {"python": 0.9, "kubernetes": 0.6, ...}
    skills_json: Mapped[str] = mapped_column(Text, default="{}")
    # Writing/coding/thinking style metrics
    style_json: Mapped[str] = mapped_column(Text, default="{}")
    # Top tools/tech encountered in memories
    favorite_tools_json: Mapped[str] = mapped_column(Text, default="[]")
    # Predicted future interests
    predictions_json: Mapped[str] = mapped_column(Text, default="[]")
    # Detected weaknesses / knowledge gaps
    gaps_json: Mapped[str] = mapped_column(Text, default="[]")
    # Productivity patterns: hour-of-day buckets, days-of-week, etc.
    productivity_json: Mapped[str] = mapped_column(Text, default="{}")
    # Decision history summary
    decision_summary: Mapped[str] = mapped_column(Text, default="")
    memory_count_at_last_update: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    @property
    def skills(self) -> dict:
        return _JsonColumn.loads(self.skills_json, {})

    @skills.setter
    def skills(self, v: dict) -> None:
        self.skills_json = json.dumps(v)

    @property
    def style(self) -> dict:
        return _JsonColumn.loads(self.style_json, {})

    @style.setter
    def style(self, v: dict) -> None:
        self.style_json = json.dumps(v)

    @property
    def favorite_tools(self) -> list:
        return _JsonColumn.loads(self.favorite_tools_json, [])

    @favorite_tools.setter
    def favorite_tools(self, v: list) -> None:
        self.favorite_tools_json = json.dumps(v)

    @property
    def predictions(self) -> list:
        return _JsonColumn.loads(self.predictions_json, [])

    @predictions.setter
    def predictions(self, v: list) -> None:
        self.predictions_json = json.dumps(v)

    @property
    def gaps(self) -> list:
        return _JsonColumn.loads(self.gaps_json, [])

    @gaps.setter
    def gaps(self, v: list) -> None:
        self.gaps_json = json.dumps(v)

    @property
    def productivity(self) -> dict:
        return _JsonColumn.loads(self.productivity_json, {})

    @productivity.setter
    def productivity(self, v: dict) -> None:
        self.productivity_json = json.dumps(v)


# ---------------------------------------------------------------------------
# Knowledge Evolution
# ---------------------------------------------------------------------------


class EvolutionLog(Base):
    """One entry per evolution action applied to a memory or the knowledge graph.

    Actions: decay | merged | improved_summary | contradiction | insight_generated
    """

    __tablename__ = "evolution_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    # ID of the primary memory affected (may be blank for workspace-level actions)
    memory_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    # Secondary memory (e.g. merged-into target)
    target_memory_id: Mapped[str] = mapped_column(String(32), default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    @property
    def detail(self) -> dict:
        return _JsonColumn.loads(self.detail_json, {})


# ---------------------------------------------------------------------------
# AI Evaluation Framework
# ---------------------------------------------------------------------------


class EvaluationReport(Base):
    """Weekly (or on-demand) evaluation snapshot for a workspace.

    Captures retrieval quality, hallucination rate, grounding accuracy,
    ranking quality, agent performance, and prompt performance metrics.
    """

    __tablename__ = "evaluation_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    period_start: Mapped[str] = mapped_column(String(40))   # ISO date
    period_end: Mapped[str] = mapped_column(String(40))     # ISO date
    # Core metrics stored as JSON floats
    retrieval_quality: Mapped[float] = mapped_column(Float, default=0.0)
    hallucination_rate: Mapped[float] = mapped_column(Float, default=0.0)
    grounding_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    citation_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    ranking_ndcg: Mapped[float] = mapped_column(Float, default=0.0)
    agent_success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    # Raw per-query samples for drill-down
    samples_json: Mapped[str] = mapped_column(Text, default="[]")
    # Narrative summary generated by the evaluator
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_now_iso)

    @property
    def samples(self) -> list:
        return _JsonColumn.loads(self.samples_json, [])
