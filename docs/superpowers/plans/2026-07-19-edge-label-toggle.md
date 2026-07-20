# Graph Explorer Edge Label Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sidebar checkbox that clears all edge labels at once, per `docs/superpowers/specs/2026-07-19-edge-label-toggle-design.md`.

**Architecture:** `graph_render.to_agraph_elements` gains a `show_edge_labels: bool = True` parameter; the page reads a new sidebar checkbox and passes its value straight through on every graph-view render.

**Tech Stack:** No new dependencies.

## Global Constraints

- Node-type icons are explicitly out of scope — dropped due to a real `streamlit_agraph` limitation (no icon font bundled, sandboxed iframe with no injection point), not deferred (spec §1, §2).
- Default `show_edge_labels=True` must preserve exact current behavior — no changes to any existing test that doesn't pass the new parameter (spec §2).
- No per-edge-type filtering, no new session-state key beyond the checkbox's own widget state (spec §2).

---

### Task 1: Add the edge label toggle

**Files:**
- Modify: `src/scie/ui/graph_render.py`
- Modify: `src/scie/ui/pages/1_Graph_Explorer.py`
- Test: `tests/test_graph_render.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `to_agraph_elements(nodes: list[dict], edges: list[dict], show_edge_labels: bool = True) -> tuple[list[Node], list[Edge]]` — same return type as before, new optional third parameter. No other task in this plan depends on this — it's the whole feature.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_graph_render.py`:

```python
def test_to_agraph_elements_clears_edge_labels_when_show_edge_labels_is_false():
    nodes = [_node("r1", "Repository", url="x", name="x"), _node("b1", "Build", id="build-0001")]
    edges = [{"source": "r1", "target": "b1", "type": "HAS_BUILD"}]

    _, agraph_edges = to_agraph_elements(nodes, edges, show_edge_labels=False)

    assert agraph_edges[0].label == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_graph_render.py -v -k show_edge_labels`
Expected: FAIL with `TypeError: to_agraph_elements() got an unexpected keyword argument 'show_edge_labels'`.

- [ ] **Step 3: Implement the parameter**

In `src/scie/ui/graph_render.py`, change the `to_agraph_elements` signature and edge-building block from:

```python
def to_agraph_elements(nodes: list[dict], edges: list[dict]) -> tuple[list[Node], list[Edge]]:
    agraph_nodes = []
    for node in nodes:
        label = node["labels"][0]
        agraph_node = Node(
            id=node["element_id"],
            label=node_display_label(node),
            color=NODE_COLORS.get(label, "#999999"),
            shape=SHAPE_BY_LABEL.get(label, "box"),
            font=NODE_FONT,
            margin=NODE_MARGIN,
        )
        # streamlit_agraph defaults title to id and opens it via window.open()
        # on double-click; Node(title=...) falls back to id for any falsy
        # value, so the attribute must be cleared after construction.
        agraph_node.title = ""
        agraph_nodes.append(agraph_node)
    agraph_edges = [
        Edge(
            source=edge["source"],
            target=edge["target"],
            label=_humanize_edge_type(edge["type"]),
            font=EDGE_FONT,
        )
        for edge in edges
    ]
    return agraph_nodes, agraph_edges
```

to:

```python
def to_agraph_elements(
    nodes: list[dict], edges: list[dict], show_edge_labels: bool = True,
) -> tuple[list[Node], list[Edge]]:
    agraph_nodes = []
    for node in nodes:
        label = node["labels"][0]
        agraph_node = Node(
            id=node["element_id"],
            label=node_display_label(node),
            color=NODE_COLORS.get(label, "#999999"),
            shape=SHAPE_BY_LABEL.get(label, "box"),
            font=NODE_FONT,
            margin=NODE_MARGIN,
        )
        # streamlit_agraph defaults title to id and opens it via window.open()
        # on double-click; Node(title=...) falls back to id for any falsy
        # value, so the attribute must be cleared after construction.
        agraph_node.title = ""
        agraph_nodes.append(agraph_node)
    agraph_edges = [
        Edge(
            source=edge["source"],
            target=edge["target"],
            label=_humanize_edge_type(edge["type"]) if show_edge_labels else "",
            font=EDGE_FONT,
        )
        for edge in edges
    ]
    return agraph_nodes, agraph_edges
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_graph_render.py -v`
Expected: all 11 tests PASS (10 pre-existing + 1 new).

- [ ] **Step 5: Wire the checkbox into the page**

In `src/scie/ui/pages/1_Graph_Explorer.py`, find:

```python
mode = st.selectbox("Search by", ["Vulnerability ID", "Package PURL", "Repository URL"])
```

and add the checkbox immediately before it:

```python
show_edge_labels = st.sidebar.checkbox("Show edge labels", value=True)

mode = st.selectbox("Search by", ["Vulnerability ID", "Package PURL", "Repository URL"])
```

Then find:

```python
        agraph_nodes, agraph_edges = to_agraph_elements(nodes, edges)
```

and change it to:

```python
        agraph_nodes, agraph_edges = to_agraph_elements(nodes, edges, show_edge_labels)
```

- [ ] **Step 6: Syntax-check the page**

Run: `uv run python -c "import ast; ast.parse(open('src/scie/ui/pages/1_Graph_Explorer.py').read())"`
Expected: no output, exit code 0.

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest -v`
Expected: all PASS (91 pre-existing + 1 net-new = 92), no regressions.

- [ ] **Step 8: Commit**

```bash
git add src/scie/ui/graph_render.py src/scie/ui/pages/1_Graph_Explorer.py tests/test_graph_render.py
git commit -m "feat: add sidebar toggle to show/hide Graph Explorer edge labels"
```

---

### Task 2: Manual verification

**Files:** none — this task exercises the running stack, no code changes.

- [ ] **Step 1: Rebuild the dashboard container**

Run: `docker compose -p pipeline-lens up -d --build dashboard`
Expected: the container rebuilds and reports `Started`.

- [ ] **Step 2: Look at it**

Open `http://localhost:8501` → Graph Explorer, run a search that returns a
graph. Confirm: a "Show edge labels" checkbox appears in the sidebar,
checked by default, with all edge labels visible. Uncheck it — every edge
label should disappear (edges still drawn, just no text). Re-check it —
labels come back. Report back what you see.

- [ ] **Step 3: Fix forward if it doesn't match**

If labels don't clear, check the checkbox's value is actually reaching
`to_agraph_elements` (a stale `st.session_state` widget key is the most
likely cause) before touching the humanizer logic — Task 1's test already
confirms `show_edge_labels=False` produces empty labels at the Python level.
