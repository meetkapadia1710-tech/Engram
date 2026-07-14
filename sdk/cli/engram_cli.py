"""Engram CLI — command-line interface for the Engram AI Memory OS.

Commands:
    engram workspace list
    engram workspace create <name>
    engram memory list [--workspace ws-id] [--limit N] [--type TYPE]
    engram memory add [--workspace ws-id] [--type TYPE] [--tags t1,t2]
    engram memory delete <id>
    engram search <query> [--workspace ws-id] [--limit N]
    engram context <query> [--workspace ws-id]
    engram agent run <goal> [--workspace ws-id] [--team a,b,c]
    engram workflow list [--workspace ws-id]
    engram workflow trigger <id> [--workspace ws-id]
    engram catalog list [--kind KIND] [--query Q]
    engram install <slug> [--workspace ws-id]
    engram metrics
    engram digital-twin [--workspace ws-id]
    engram eval run [--workspace ws-id]
    engram evolution run [--workspace ws-id]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Bootstrap: prefer local engram package when running from repo
_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root / "sdk" / "python"))

try:
    import typer
    from rich import print as rprint
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
except ImportError:
    print("Install CLI dependencies: pip install typer rich", file=sys.stderr)
    sys.exit(1)

from engram import Engram

app = typer.Typer(
    name="engram",
    help="Engram AI Memory OS — command-line interface",
    rich_markup_mode="rich",
)
console = Console()


def _client() -> Engram:
    base = os.environ.get("ENGRAM_API_URL", "http://localhost:8000")
    key = os.environ.get("ENGRAM_API_KEY", "")
    return Engram(base, api_key=key)


def _ws() -> str:
    ws = os.environ.get("ENGRAM_WORKSPACE_ID", "")
    if not ws:
        console.print(
            "[yellow]Warning:[/] ENGRAM_WORKSPACE_ID not set. "
            "Use --workspace or set the env var."
        )
    return ws


# ─── Workspace ────────────────────────────────────────────────────────────────

ws_app = typer.Typer(help="Workspace management")
app.add_typer(ws_app, name="workspace")


@ws_app.command("list")
def workspace_list():
    """List all workspaces."""
    em = _client()
    data = em._request("GET", "/v1/workspaces")
    table = Table("ID", "Slug", "Name", "Memories")
    for ws in data.get("items", []):
        table.add_row(ws["id"], ws["slug"], ws["name"], str(ws.get("memory_count", 0)))
    console.print(table)


@ws_app.command("create")
def workspace_create(name: str, slug: str = ""):
    """Create a new workspace."""
    em = _client()
    body = {"name": name}
    if slug:
        body["slug"] = slug
    ws = em._request("POST", "/v1/workspaces", json=body)
    console.print(f"[green]✓[/] Created workspace [bold]{ws['name']}[/] id=[cyan]{ws['id']}[/]")


# ─── Memory ───────────────────────────────────────────────────────────────────

mem_app = typer.Typer(help="Memory CRUD")
app.add_typer(mem_app, name="memory")


@mem_app.command("list")
def memory_list(
    workspace: str = typer.Option("", "--workspace", "-w"),
    limit: int = 20,
    type_: str = typer.Option("", "--type", "-t"),
):
    """List recent memories."""
    em = _client()
    ws_id = workspace or _ws()
    p = f"limit={limit}"
    if type_:
        p += f"&type={type_}"
    data = em._request("GET", f"/v1/workspaces/{ws_id}/memories?{p}")
    table = Table("ID", "Type", "Title", "Tags")
    for m in data.get("items", []):
        table.add_row(m["id"][:8], m["type"], m["title"][:50], ", ".join(m.get("tags", [])))
    console.print(table)


@mem_app.command("add")
def memory_add(
    workspace: str = typer.Option("", "--workspace", "-w"),
    type_: str = typer.Option("note", "--type", "-t"),
    tags: str = typer.Option("", "--tags"),
    title: str = typer.Option("", "--title"),
):
    """Add a memory (reads content from stdin or prompts)."""
    em = _client()
    ws_id = workspace or _ws()
    if not sys.stdin.isatty():
        content = sys.stdin.read().strip()
    else:
        content = typer.prompt("Content")
    body: dict = {"content": content, "type": type_}
    if title:
        body["title"] = title
    if tags:
        body["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    mem = em._request("POST", f"/v1/workspaces/{ws_id}/memories", json=body)
    console.print(f"[green]✓[/] Memory [cyan]{mem['id']}[/] — [bold]{mem['title']}[/]")


@mem_app.command("delete")
def memory_delete(memory_id: str):
    """Delete a memory by ID."""
    em = _client()
    em._request("DELETE", f"/v1/memories/{memory_id}")
    console.print(f"[green]✓[/] Deleted {memory_id}")


# ─── Search ───────────────────────────────────────────────────────────────────

@app.command("search")
def search(
    query: str,
    workspace: str = typer.Option("", "--workspace", "-w"),
    limit: int = 5,
    mode: str = "hybrid",
):
    """Semantic search across memories."""
    em = _client()
    ws_id = workspace or _ws()
    results = em._request(
        "POST", f"/v1/workspaces/{ws_id}/search",
        json={"query": query, "limit": limit, "mode": mode},
    )
    for i, r in enumerate(results.get("results", []), 1):
        console.print(f"\n[bold]#{i}[/] [cyan]{r['title']}[/] ([dim]{r['type']}[/]) score={r['score']:.3f}")
        console.print(f"  {r['content'][:120]}…" if len(r["content"]) > 120 else f"  {r['content']}")


@app.command("context")
def context(
    query: str,
    workspace: str = typer.Option("", "--workspace", "-w"),
    max_tokens: int = 1800,
):
    """Build a RAG context block for a query."""
    em = _client()
    ws_id = workspace or _ws()
    result = em._request(
        "POST", f"/v1/workspaces/{ws_id}/context",
        json={"query": query, "max_tokens": max_tokens},
    )
    console.print(Panel(
        result.get("context", ""),
        title=f"[bold]RAG Context[/] ({result.get('token_count', 0)} tokens)",
        border_style="cyan",
    ))


# ─── Agents ───────────────────────────────────────────────────────────────────

agent_app = typer.Typer(help="Multi-agent orchestration")
app.add_typer(agent_app, name="agent")


@agent_app.command("run")
def agent_run(
    goal: str,
    workspace: str = typer.Option("", "--workspace", "-w"),
    team: str = typer.Option("", "--team", help="Comma-separated agent names"),
):
    """Start an agent collaboration run."""
    em = _client()
    ws_id = workspace or _ws()
    body: dict = {"goal": goal}
    if team:
        body["team"] = [t.strip() for t in team.split(",")]
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as p:
        p.add_task("Agents collaborating…")
        run = em._request("POST", f"/v1/workspaces/{ws_id}/agents/run", json=body)
    console.print(f"\n[green]✓[/] Run [cyan]{run['id']}[/] — status=[bold]{run['status']}[/]")
    if run.get("conclusion"):
        console.print(Panel(run["conclusion"], title="[bold]Conclusion[/]", border_style="green"))


# ─── Workflows ────────────────────────────────────────────────────────────────

wf_app = typer.Typer(help="Workflow automation")
app.add_typer(wf_app, name="workflow")


@wf_app.command("list")
def workflow_list(workspace: str = typer.Option("", "--workspace", "-w")):
    """List workflows."""
    em = _client()
    ws_id = workspace or _ws()
    data = em._request("GET", f"/v1/workspaces/{ws_id}/workflows")
    table = Table("ID", "Name", "Trigger", "Steps", "Enabled")
    for wf in data.get("items", []):
        table.add_row(
            wf["id"][:8], wf["name"][:40],
            wf.get("trigger_event") or "manual",
            str(len(wf.get("steps", []))),
            "[green]yes[/]" if wf["enabled"] else "[red]no[/]",
        )
    console.print(table)


@wf_app.command("trigger")
def workflow_trigger(
    workflow_id: str,
    workspace: str = typer.Option("", "--workspace", "-w"),
):
    """Trigger a workflow manually."""
    em = _client()
    ws_id = workspace or _ws()
    run = em._request("POST", f"/v1/workspaces/{ws_id}/workflows/{workflow_id}/trigger", json={})
    console.print(f"[green]✓[/] Run [cyan]{run['id']}[/] — {run['status']}")


# ─── Marketplace ─────────────────────────────────────────────────────────────

catalog_app = typer.Typer(help="Plugin marketplace")
app.add_typer(catalog_app, name="catalog")


@catalog_app.command("list")
def catalog_list(
    kind: str = typer.Option("", "--kind"),
    query: str = typer.Option("", "--query", "-q"),
):
    """Browse the plugin catalog."""
    em = _client()
    p = []
    if kind:
        p.append(f"kind={kind}")
    if query:
        p.append(f"q={query}")
    data = em._request("GET", "/v1/catalog" + ("?" + "&".join(p) if p else ""))
    table = Table("Slug", "Name", "Kind", "Author", "Version")
    for plugin in data.get("items", []):
        table.add_row(
            plugin["slug"], plugin["name"], plugin["kind"],
            plugin.get("author") or "—", plugin.get("latest_version", "—"),
        )
    console.print(table)


@app.command("install")
def install(
    slug: str,
    workspace: str = typer.Option("", "--workspace", "-w"),
    version: str = typer.Option("", "--version"),
):
    """Install a plugin into a workspace."""
    em = _client()
    ws_id = workspace or _ws()
    result = em._request(
        "POST", f"/v1/workspaces/{ws_id}/plugins/{slug}/install",
        json={"version": version},
    )
    console.print(f"[green]✓[/] Installed [bold]{slug}[/] v{result.get('version')}")


# ─── Observability ────────────────────────────────────────────────────────────

@app.command("metrics")
def metrics():
    """Print platform metrics snapshot."""
    em = _client()
    snap = em._request("GET", "/v1/metrics")
    console.print(f"[bold]Uptime:[/] {snap.get('uptime_s', 0):.0f}s")
    console.print("\n[bold]Counters:[/]")
    for k, v in sorted(snap.get("counters", {}).items()):
        console.print(f"  {k}: {v}")
    console.print("\n[bold]Latency:[/]")
    for k, v in snap.get("latency", {}).items():
        console.print(f"  {k}: avg={v.get('avg_ms', 0):.1f}ms p95={v.get('p95_ms', 0):.1f}ms")


# ─── Intelligence ─────────────────────────────────────────────────────────────

@app.command("digital-twin")
def digital_twin(workspace: str = typer.Option("", "--workspace", "-w")):
    """Show your Digital Twin profile."""
    em = _client()
    ws_id = workspace or _ws()
    twin = em._request("GET", f"/v1/workspaces/{ws_id}/digital-twin")
    skills = sorted(twin.get("skills", {}).items(), key=lambda kv: kv[1], reverse=True)[:10]
    table = Table("Skill", "Score")
    for skill, score in skills:
        table.add_row(skill, f"{score*100:.0f}%")
    console.print(table)
    console.print(f"\n[bold]Peak hour:[/] {twin.get('productivity', {}).get('peak_hour')}:00")
    console.print(f"[bold]Predictions:[/] {', '.join(twin.get('predictions', []))}")
    console.print(f"[bold]Gaps:[/] {', '.join(twin.get('gaps', [])[:5])}")


eval_app = typer.Typer(help="AI evaluation framework")
app.add_typer(eval_app, name="eval")


@eval_app.command("run")
def eval_run(workspace: str = typer.Option("", "--workspace", "-w")):
    """Run an AI evaluation and print results."""
    em = _client()
    ws_id = workspace or _ws()
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as p:
        p.add_task("Running evaluation…")
        report = em._request("POST", f"/v1/workspaces/{ws_id}/evaluation/run")
    console.print(f"\n[green]✓[/] Report [cyan]{report['id']}[/]")
    console.print(Panel(
        report.get("summary", ""),
        title="[bold]Evaluation Results[/]",
        border_style="cyan",
    ))


@app.command("evolution")
def evolution(workspace: str = typer.Option("", "--workspace", "-w")):
    """Run a full knowledge evolution pass."""
    em = _client()
    ws_id = workspace or _ws()
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as p:
        p.add_task("Evolving knowledge base…")
        result = em._request("POST", f"/v1/workspaces/{ws_id}/evolution/run")
    console.print(f"[green]✓[/] Decayed: {result['decayed']} | Merged: {result['merged']} | "
                  f"Summaries improved: {result['summaries_improved']} | "
                  f"Insights created: {result['insights_created']}")


if __name__ == "__main__":
    app()
