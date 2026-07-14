"""Multi-agent orchestrator.

A run takes a goal and a team of role agents. Phases:

1. **plan**     — the orchestrator decomposes the goal into one sub-question
                  per agent (recorded as `plan` messages).
2. **research** — each agent retrieves from its memory scope (private scope =
                  its own tag filter; shared scope = whole workspace) and
                  produces a finding via the generation provider.
3. **debate**   — agents see each other's findings and may raise objections
                  (contradiction heuristics + generator critique).
4. **vote**     — each agent scores every finding for relevance; low scorers
                  are dropped.
5. **merge**    — the orchestrator merges surviving findings into a cited
                  conclusion, stored back into memory (type=note, tag=agent).

Every message is persisted (AgentMessage) so the UI can render the full
collaboration timeline. Works with zero API keys: the local generator makes
research/merge extractive rather than generative — the orchestration
contract is identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import observability
from .ai import _tokens, get_generator
from .events import emit
from .models import _now_iso
from .models_platform import AgentMessage, AgentRun


@dataclass
class AgentSpec:
    name: str
    role: str                       # human-readable purpose
    focus: str                      # appended to retrieval queries
    types: list[str] = field(default_factory=list)   # memory-type scope
    tools: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=lambda: ["search", "summarize"])


DEFAULT_TEAM: dict[str, AgentSpec] = {
    "research": AgentSpec("research", "Research Agent",
                          "background facts, sources, prior findings",
                          types=["research_paper", "website", "document", "bookmark"]),
    "coding": AgentSpec("coding", "Coding Agent",
                        "code, implementation details, technical gotchas",
                        types=["code", "note"]),
    "planning": AgentSpec("planning", "Planning Agent",
                          "decisions, timelines, action items",
                          types=["meeting_notes", "task", "calendar_event"]),
    "memory": AgentSpec("memory", "Memory Agent",
                        "anything relevant across all memory", types=[]),
    "analyst": AgentSpec("analyst", "Data Analyst",
                         "numbers, metrics, comparisons", types=["document", "api_response", "note"]),
}


def _say(db: Session, run: AgentRun, seq: int, sender: str, kind: str,
         content: str, recipient: str = "all") -> int:
    db.add(AgentMessage(run_id=run.id, seq=seq, sender=sender,
                        recipient=recipient, kind=kind, content=content[:4000]))
    return seq + 1


def _retrieve(db: Session, workspace_id: str, agent: AgentSpec, question: str) -> list:
    from .search import hybrid_search

    return hybrid_search(db, workspace_id, f"{question} {agent.focus}",
                         limit=4, types=agent.types or None)


def _contradicts(a: str, b: str) -> bool:
    """Cheap contradiction heuristic: high token overlap + opposing polarity."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / min(len(ta), len(tb))
    negations = {"not", "never", "no", "dont", "cant", "wont", "isnt", "arent"}
    pol_a = bool(negations & {w.lower() for w in a.split()})
    pol_b = bool(negations & {w.lower() for w in b.split()})
    return overlap > 0.5 and pol_a != pol_b


def run_agents(
    db: Session,
    workspace_id: str,
    goal: str,
    *,
    team: list[str] | None = None,
) -> AgentRun:
    import json

    names = [n for n in (team or ["research", "memory", "planning"]) if n in DEFAULT_TEAM]
    if not names:
        raise ValueError("no valid agents in team")
    agents = [DEFAULT_TEAM[n] for n in names]

    run = AgentRun(workspace_id=workspace_id, goal=goal[:2000],
                   agents_json=json.dumps(names))
    db.add(run)
    db.flush()
    emit(db, "AgentStarted", {"run_id": run.id, "goal": goal[:200], "team": names},
         workspace_id=workspace_id)

    gen = get_generator()
    seq = 0

    with observability.timed("agent_run"):
        # 1. plan — one sub-question per agent
        sub_questions: dict[str, str] = {}
        for a in agents:
            q = f"What does memory say about: {goal} — focusing on {a.focus}?"
            sub_questions[a.name] = q
            seq = _say(db, run, seq, "orchestrator", "plan", q, recipient=a.name)

        # 2. research — retrieval + finding per agent
        findings: dict[str, str] = {}
        evidence_count: dict[str, int] = {}
        for a in agents:
            hits = _retrieve(db, workspace_id, a, goal)
            evidence_count[a.name] = len(hits)
            if not hits:
                finding = f"({a.role}) No relevant memories found for this goal."
            else:
                corpus = "\n".join(f"- {h.memory.title}: {h.memory.content[:300]}" for h in hits)
                finding = gen.generate(
                    f"You are the {a.role}. Answer from these memories only:\n"
                    f"{corpus}\n\nQuestion: {sub_questions[a.name]}",
                    source_text=corpus,
                )[:1500] or corpus[:800]
            findings[a.name] = finding
            seq = _say(db, run, seq, a.name, "finding", finding)

        # 3. debate — contradiction pass
        agent_names = list(findings)
        for i, x in enumerate(agent_names):
            for y in agent_names[i + 1:]:
                if _contradicts(findings[x], findings[y]):
                    note = (f"Possible contradiction between {x} and {y}; both cite "
                            f"overlapping facts with opposing polarity. Flagging for merge.")
                    seq = _say(db, run, seq, "orchestrator", "debate", note)
                    emit(db, "ContradictionDetected",
                         {"run_id": run.id, "agents": [x, y]}, workspace_id=workspace_id)

        # 4. vote — agents with no evidence abstain; findings need one vote
        votes: dict[str, int] = {n: 0 for n in agent_names}
        for voter in agents:
            for n in agent_names:
                if n == voter.name:
                    continue
                if evidence_count[n] > 0:
                    votes[n] += 1
                    seq = _say(db, run, seq, voter.name, "vote",
                               f"+1 {n} (grounded in {evidence_count[n]} memories)",
                               recipient=n)
        kept = [n for n in agent_names if votes[n] > 0 or evidence_count[n] > 0]
        if not kept:
            kept = agent_names

        # 5. merge
        merged_input = "\n\n".join(f"[{n}] {findings[n]}" for n in kept)
        conclusion = gen.generate(
            f"Merge these agent findings into one conclusion for the goal "
            f"'{goal}'. Note disagreements explicitly:\n\n{merged_input}",
            source_text=merged_input,
        )[:2000] or merged_input[:1200]
        seq = _say(db, run, seq, "orchestrator", "merge", conclusion)

        # persist conclusion as a memory so it feeds future retrieval
        from .pipeline import ingest_memory

        mem = ingest_memory(
            db, workspace_id=workspace_id,
            content=f"Agent conclusion for goal: {goal}\n\n{conclusion}",
            type_="note", tags=["agents", "conclusion"],
        )
        run.conclusion = conclusion
        run.conclusion_memory_id = mem.id
        run.status = "ok"
        run.finished_at = _now_iso()

    emit(db, "AgentFinished", {"run_id": run.id, "status": run.status},
         workspace_id=workspace_id)
    observability.count("agents.runs")
    return run
