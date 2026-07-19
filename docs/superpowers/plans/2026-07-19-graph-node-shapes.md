# Graph Explorer Node Shapes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Graph Explorer nodes a shape per type (rectangles, diamond for `VulnerabilityID`) as a second visual signal alongside the existing per-type color, per `docs/superpowers/specs/2026-07-19-graph-node-shapes-design.md`.

**Architecture:** One dict (`SHAPE_BY_LABEL`) added next to the existing `NODE_COLORS` dict in `src/scie/ui/graph_render.py`, wired into the same `Node(...)` construction that already sets `color=`.

**Tech Stack:** `streamlit_agraph` (already a dependency; confirmed by inspecting its built frontend bundle that the `shape` field passes straight through to vis-network with no validation — no library change needed).

## Global Constraints

- No changes to `queries.py`, the Neo4j schema, or the API — pure rendering-layer change (spec §2).
- `"box"` for every current node type except `VulnerabilityID`, which gets `"diamond"` (spec §2).
- No icon/image shapes — only native vis-network vector shapes (`box`, `diamond`), no asset dependency (spec §2).

---

### Task 1: Add per-type node shapes

**Files:**
- Modify: `src/scie/ui/graph_render.py`
- Test: `tests/test_graph_render.py`

**Interfaces:**
- Consumes: nothing new — this modifies the existing `to_agraph_elements(nodes: list[dict], edges: list[dict]) -> tuple[list[Node], list[Edge]]` function in place; its signature and callers (`src/scie/ui/pages/1_Graph_Explorer.py`) are unchanged.
- Produces: `graph_render.SHAPE_BY_LABEL: dict[str, str]` (same shape as the existing `NODE_COLORS`). No other task in this plan depends on it — this is the whole feature.

- [ ] **Step 1: Write the failing tests**

In `tests/test_graph_render.py`, find the existing test:

```python
def test_to_agraph_elements_builds_nodes_with_empty_title_and_display_label():
    nodes = [_node("p1", "Package", name="openssl", version="1.0.0")]
    edges = [{"source": "p1", "target": "p1", "type": "self"}]

    agraph_nodes, agraph_edges = to_agraph_elements(nodes, edges)

    assert len(agraph_nodes) == 1
    assert agraph_nodes[0].id == "p1"
    assert agraph_nodes[0].label == "openssl@1.0.0"
    assert agraph_nodes[0].title == ""
    assert agraph_nodes[0].color == "#CCB974"
    assert len(agraph_edges) == 1
    assert agraph_edges[0].source == "p1"
    assert agraph_edges[0].to == "p1"
    assert agraph_edges[0].label == "self"
```

Add a `shape` assertion to it, and add a new test after it:

```python
def test_to_agraph_elements_builds_nodes_with_empty_title_and_display_label():
    nodes = [_node("p1", "Package", name="openssl", version="1.0.0")]
    edges = [{"source": "p1", "target": "p1", "type": "self"}]

    agraph_nodes, agraph_edges = to_agraph_elements(nodes, edges)

    assert len(agraph_nodes) == 1
    assert agraph_nodes[0].id == "p1"
    assert agraph_nodes[0].label == "openssl@1.0.0"
    assert agraph_nodes[0].title == ""
    assert agraph_nodes[0].color == "#CCB974"
    assert agraph_nodes[0].shape == "box"
    assert len(agraph_edges) == 1
    assert agraph_edges[0].source == "p1"
    assert agraph_edges[0].to == "p1"
    assert agraph_edges[0].label == "self"


def test_to_agraph_elements_gives_vulnerability_nodes_a_diamond_shape():
    nodes = [_node("v1", "VulnerabilityID", id="CVE-2014-0160")]

    agraph_nodes, _ = to_agraph_elements(nodes, [])

    assert agraph_nodes[0].shape == "diamond"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_render.py -v -k to_agraph_elements`
Expected: `test_to_agraph_elements_builds_nodes_with_empty_title_and_display_label` FAILs on `assert agraph_nodes[0].shape == "box"` with `AttributeError: 'Node' object has no attribute 'shape'` (Node's constructor default is `shape="dot"`, so this specific assertion should actually fail on a value mismatch, not a missing attribute — either way, confirm it fails). `test_to_agraph_elements_gives_vulnerability_nodes_a_diamond_shape` FAILs the same way.

- [ ] **Step 3: Add `SHAPE_BY_LABEL` and wire it in**

In `src/scie/ui/graph_render.py`, add this dict immediately after the existing `NODE_COLORS` dict:

```python
# vis-network node shapes (streamlit_agraph passes this straight through with
# no validation — confirmed by inspecting the built frontend bundle). Every
# type is a rectangle sized to its label text except VulnerabilityID, which
# gets a diamond so CVEs visually stand out as the "risk" node type rather
# than blending in as just another colored box.
SHAPE_BY_LABEL = {
    "Repository": "box",
    "Build": "box",
    "Commit": "box",
    "Artifact": "box",
    "Package": "box",
    "VulnerabilityID": "diamond",
    "Deployment": "box",
}
```

Then in `to_agraph_elements`, change the `Node(...)` construction from:

```python
        agraph_node = Node(
            id=node["element_id"],
            label=node_display_label(node),
            color=NODE_COLORS.get(label, "#999999"),
        )
```

to:

```python
        agraph_node = Node(
            id=node["element_id"],
            label=node_display_label(node),
            color=NODE_COLORS.get(label, "#999999"),
            shape=SHAPE_BY_LABEL.get(label, "box"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_render.py -v`
Expected: all 8 tests PASS (6 pre-existing + 2 new/modified).

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all PASS (87 pre-existing + 1 net-new = 88), no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/scie/ui/graph_render.py tests/test_graph_render.py
git commit -m "feat: give Graph Explorer nodes a shape per type"
```

---

### Task 2: Manual verification

**Files:** none — this task exercises the running stack, no code changes.

There is no automated way to confirm a shape actually renders as a rectangle
vs. a diamond in a browser — same limitation as every other visual change
made to this page.

- [ ] **Step 1: Rebuild the dashboard container**

The `src/` directory is `COPY`'d into the Docker image at build time — a
plain restart won't pick up the change.

Run: `docker compose -p pipeline-lens up -d --build dashboard`
Expected: the container rebuilds and reports `Started`.

Note: as of this plan being written, `pipeline-lens-neo4j-1` was unable to
start due to an unrelated `guac-lab-neo4j-1` container holding ports
7474/7687 — resolve that (see the conversation this plan came from) before
this step, or `dashboard`/`api` may come up without a working Neo4j behind
them.

- [ ] **Step 2: Look at it**

Open `http://localhost:8501` → Graph Explorer, run any search that returns
a graph (not the Repository/build-history table view). Confirm: every node
renders as a rectangle sized to its label text, except `VulnerabilityID`
nodes, which render as a diamond. Report back what you see.

- [ ] **Step 3: Fix forward if it doesn't match**

If shapes don't render as expected, check the browser console for a
vis-network error first (an invalid shape string would likely show there)
before changing code — Task 1's tests already confirm the Python side sets
the right string.
