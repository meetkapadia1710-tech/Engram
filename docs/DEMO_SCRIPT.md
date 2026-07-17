# Engram — 3-Minute Demo Script

**Before recording:** all three services are already running and verified —
Supermemory Local (:6767), the Engram API (:8000), the web app (:3000). The
"Personal" workspace has 18 seeded memories. Reload http://localhost:3000
once before you hit record so the dashboard loads warm.

Timings are cumulative — if you're behind, cut the Workflows/Tools aside first.

---

### 0:00–0:20 — Hook + what it is

> "Every AI tool forgets everything the moment your session ends. Engram is a
> memory layer that fixes that — built on Supermemory Local, so everything
> stays on your own machine."

Show the **Dashboard** (already open). Point at the stat tiles and the
14-day activity chart.

> "This isn't a wrapper around Supermemory — it's a full memory operating
> system on top of it: knowledge graph, multi-agent orchestration, workflow
> automation, a plugin marketplace, all built this week."

---

### 0:20–1:00 — Create → the pipeline is visible

Click **New memory**. Type:

> "Docker layer caching makes CI builds dramatically faster by reusing
> unchanged layers."

Hit **Remember**. It lands back on the dashboard — point at the new card:

> "One write. Behind the scenes that just ran the full pipeline — cleaned,
> chunked, embedded, entity-extracted — 'docker' was pulled out automatically
> — and it's now stored durably in Supermemory Local, with a local mirror
> that powers the graph and ranking."

Click into **Settings** for 3 seconds — point at the **Supermemory Local**
card showing "Reachable: yes" with live latency.

> "And this isn't faked — that's a live reachability check against the real
> running Supermemory server."

---

### 1:00–1:40 — Search with visible ranking

Go to **Search**. Type `docker caching`, hit enter.

> "Hybrid search — Supermemory's semantic candidates, re-ranked by Engram
> using importance, recency, access frequency, and graph connectivity."

Click a result to expand the **ranking breakdown** panel.

> "Every score is explainable — this is why this memory ranked where it did,
> not a black box."

---

### 1:40–2:15 — Graph

Go to **Graph**.

> "Every memory and every entity it mentions is a node here — 'docker',
> 'kubernetes', people, projects — auto-linked by similarity and shared
> entities. This updates live as you add memories, and it's what powers
> 'related memories' everywhere else in the app."

Click a node to show the detail panel (importance, connections).

---

### 2:15–2:50 — Agents (the platform layer)

Go to **Agents**. Type a goal:

> "What do we know about our infrastructure?"

Select **Research** + **Memory** agents, hit **Start Run**.

> "This spins up a real multi-agent collaboration — each agent retrieves
> from memory independently, they cross-check each other's findings for
> contradictions, vote, and merge into one cited conclusion — which gets
> written back into memory, so the next question benefits from this one."

Point at the message timeline (plan → finding → merge) while it completes
(~5–10s).

---

### 2:50–3:00 — Close

Quick cut to **Marketplace** (one plugin installed) or **Workflows** if time
allows — one sentence:

> "Plus a plugin marketplace, event-driven workflows, and knowledge evolution
> running underneath — all built on Supermemory Local this week. Repo's
> linked below."

---

## If something looks slow on camera

- **Search right after creating** something new may show fewer results —
  Supermemory indexes asynchronously (a few seconds). Use the pre-seeded
  "Personal" workspace content for search/graph/agents demos, and only use a
  **fresh** create for the "watch it appear on the dashboard" beat, not for
  the search demo immediately after.
- If `/health` shows "degraded" before you start: Supermemory Local isn't
  reachable — check port 6767 before recording, not during.
