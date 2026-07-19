# Graph Explorer Label Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Graph Explorer's edge-label casing inconsistency and add a node type badge to every node's label, per `docs/superpowers/specs/2026-07-19-graph-label-polish-design.md`.

**Architecture:** Both changes live entirely in `src/scie/ui/graph_render.py`: a new `_humanize_edge_type` function applied when building `agraph_edges` in `to_agraph_elements`, and a two-line format change to `node_display_label`. `_attestation_edge_label`'s two hand-authored strings also gain a space (`"DependsOn"` → `"Depends On"`, `"CertifyVuln (affected)"` → `"Certify Vuln (affected)"`) so they match the Title-Case-with-spaces convention the humanizer produces for backbone edges.

**Tech Stack:** Pure Python — no new dependencies. vis-network's native multi-line label support (`\n` in the label string) does the node-badge rendering; confirmed in the prior node-shapes work that `streamlit_agraph`'s frontend does zero label processing of its own.

## Global Constraints

- No changes to `queries.py`, the Neo4j schema, or the API — pure rendering-layer change (spec §2).
- Raw Neo4j relationship type strings in `queries.py`/`synthetic_graph.py`/`github_ingest.py` are untouched — this is a display-only transform (spec §2).
- `NODE_COLORS` and `SHAPE_BY_LABEL` are untouched — this adds a third, independent signal on top of them (spec §2).

---

### Task 1: Humanize edge labels and add node type badges

**Files:**
- Modify: `src/scie/ui/graph_render.py`
- Test: `tests/test_graph_render.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no new public functions — `node_display_label(node: dict) -> str` keeps its signature but now returns a two-line string (`"{type}\n{value}"`) instead of just the value; `to_agraph_elements`'s edge labels are now humanized. No other task in this plan depends on this — it's the whole feature.

- [ ] **Step 1: Replace the test file with the updated version**

Replace all of `tests/test_graph_render.py` with:

```python
from scie.ui.graph_render import collapse_attestations, node_display_label, to_agraph_elements


def _node(element_id, label, **props):
    return {"element_id": element_id, "labels": [label], "properties": props}


def test_node_display_label_uses_identifying_property_per_label():
    assert node_display_label(_node("r1", "Repository", url="https://x/y", name="y")) == "Repository\ny"
    assert node_display_label(_node("b1", "Build", id="build-0001")) == "Build\nbuild-0001"
    assert node_display_label(_node("c1", "Commit", sha="abcdef1234567890")) == "Commit\nabcdef1"
    assert node_display_label(_node("a1", "Artifact", digest="sha256:x", name="svc")) == "Artifact\nsvc"
    assert node_display_label(_node("p1", "Package", name="openssl", version="1.0.0")) == "Package\nopenssl@1.0.0"
    assert node_display_label(_node("v1", "VulnerabilityID", id="CVE-2014-0160")) == "VulnerabilityID\nCVE-2014-0160"
    assert node_display_label(_node("d1", "Deployment", cluster="scie", namespace="prod")) == "Deployment\nscie/prod"


def test_node_display_label_falls_back_to_label_for_unknown_type():
    assert node_display_label(_node("x1", "SomethingElse")) == "SomethingElse"


def test_collapse_attestations_merges_vex_statement_into_edge_label():
    nodes = [
        _node("v1", "VulnerabilityID", id="CVE-2014-0160"),
        _node("vex1", "VexStatement", status="affected", origin="grype-scan"),
        _node("p1", "Package", name="openssl", version="1.0.0"),
    ]
    edges = [
        {"source": "vex1", "target": "v1", "type": "vulnerability"},
        {"source": "vex1", "target": "p1", "type": "subject"},
    ]

    kept_nodes, kept_edges = collapse_attestations(nodes, edges)

    assert {n["element_id"] for n in kept_nodes} == {"v1", "p1"}
    assert kept_edges == [{"source": "p1", "target": "v1", "type": "Certify Vuln (affected)"}]


def test_collapse_attestations_merges_is_dependency_into_edge_label():
    nodes = [
        _node("a1", "Artifact", digest="sha256:x", name="svc"),
        _node("dep1", "IsDependency", origin="synthetic-sbom"),
        _node("p1", "Package", name="openssl", version="1.0.0"),
    ]
    edges = [
        {"source": "dep1", "target": "p1", "type": "dependency"},
        {"source": "dep1", "target": "a1", "type": "subject"},
    ]

    kept_nodes, kept_edges = collapse_attestations(nodes, edges)

    assert {n["element_id"] for n in kept_nodes} == {"a1", "p1"}
    assert kept_edges == [{"source": "a1", "target": "p1", "type": "Depends On"}]


def test_collapse_attestations_preserves_non_attestation_edges():
    nodes = [_node("r1", "Repository", url="x", name="x"), _node("b1", "Build", id="build-0001")]
    edges = [{"source": "r1", "target": "b1", "type": "HAS_BUILD"}]

    kept_nodes, kept_edges = collapse_attestations(nodes, edges)

    assert kept_nodes == nodes
    assert kept_edges == edges


def test_to_agraph_elements_builds_nodes_with_empty_title_and_display_label():
    nodes = [_node("p1", "Package", name="openssl", version="1.0.0")]
    edges = [{"source": "p1", "target": "p1", "type": "self"}]

    agraph_nodes, agraph_edges = to_agraph_elements(nodes, edges)

    assert len(agraph_nodes) == 1
    assert agraph_nodes[0].id == "p1"
    assert agraph_nodes[0].label == "Package\nopenssl@1.0.0"
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


def test_to_agraph_elements_humanizes_underscored_edge_types():
    nodes = [_node("r1", "Repository", url="x", name="x"), _node("b1", "Build", id="build-0001")]
    edges = [{"source": "r1", "target": "b1", "type": "HAS_BUILD"}]

    _, agraph_edges = to_agraph_elements(nodes, edges)

    assert agraph_edges[0].label == "Has Build"


def test_to_agraph_elements_humanizes_single_word_uppercase_edge_types():
    nodes = [_node("b1", "Build", id="build-0001"), _node("a1", "Artifact", digest="x")]
    edges = [{"source": "b1", "target": "a1", "type": "PRODUCED"}]

    _, agraph_edges = to_agraph_elements(nodes, edges)

    assert agraph_edges[0].label == "Produced"


def test_to_agraph_elements_leaves_already_human_readable_edge_types_unchanged():
    nodes = [_node("a1", "Artifact", digest="x"), _node("p1", "Package", name="x", version="1")]
    edges = [{"source": "a1", "target": "p1", "type": "Depends On"}]

    _, agraph_edges = to_agraph_elements(nodes, edges)

    assert agraph_edges[0].label == "Depends On"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_render.py -v`
Expected: FAIL — the node-label and attestation-label assertions fail on value mismatch (old code produces `"openssl@1.0.0"` / `"DependsOn"` / `"CertifyVuln (affected)"`), and the three new `test_to_agraph_elements_humanizes_*`/`test_to_agraph_elements_leaves_*` tests FAIL because `to_agraph_elements` doesn't humanize edge types yet.

- [ ] **Step 3: Implement the changes**

In `src/scie/ui/graph_render.py`, replace `node_display_label`:

```python
def node_display_label(node: dict) -> str:
    label = node["labels"][0]
    builder = _DISPLAY_LABEL_BUILDERS.get(label)
    identifying_value = builder(node["properties"]) if builder else None
    if not identifying_value:
        return label
    return f"{label}\n{identifying_value}"
```

Replace `_attestation_edge_label`:

```python
def _attestation_edge_label(node: dict) -> str:
    label = node["labels"][0]
    if label == "VexStatement":
        return f'Certify Vuln ({node["properties"].get("status", "?")})'
    return "Depends On"
```

Add `_humanize_edge_type` immediately before `to_agraph_elements`:

```python
def _humanize_edge_type(raw_type: str) -> str:
    """Convert a SCREAMING_SNAKE_CASE Neo4j relationship type (HAS_BUILD,
    PRODUCED) into Title Case with spaces for display. Strings that already
    read as human-readable text — the labels _attestation_edge_label
    produces — pass through unchanged."""
    if "_" not in raw_type and not raw_type.isupper():
        return raw_type
    return raw_type.replace("_", " ").title()
```

In `to_agraph_elements`, change the `agraph_edges` list comprehension from:

```python
    agraph_edges = [
        Edge(source=edge["source"], target=edge["target"], label=edge["type"])
        for edge in edges
    ]
```

to:

```python
    agraph_edges = [
        Edge(source=edge["source"], target=edge["target"], label=_humanize_edge_type(edge["type"]))
        for edge in edges
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_render.py -v`
Expected: all 10 tests PASS (7 pre-existing, some with updated assertions, + 3 new).

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all PASS (88 pre-existing + 3 net-new = 91), no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/scie/ui/graph_render.py tests/test_graph_render.py
git commit -m "feat: humanize edge labels and add node type badges in Graph Explorer"
```

---

### Task 2: Manual verification

**Files:** none — this task exercises the running stack, no code changes.

- [ ] **Step 1: Rebuild the dashboard container**

Run: `docker compose -p pipeline-lens up -d --build dashboard`
Expected: the container rebuilds and reports `Started`.

- [ ] **Step 2: Look at it**

Open `http://localhost:8501` → Graph Explorer, run any search that returns a
graph. Confirm: every node shows its type on the first line and its
identifying value on the second (e.g. "Package" / "openssl@1.0.0" stacked
inside the box); every edge label reads as plain Title Case with spaces
("Has Build", "For Commit", "Produced", "Deployed To", "Depends On",
"Certify Vuln (affected)") — no `SCREAMING_SNAKE_CASE` or unspaced
`PascalCase` anywhere. Report back what you see.

- [ ] **Step 3: Fix forward if it doesn't match**

If a node's text looks cut off or the box doesn't resize to fit two lines,
that's a vis-network layout question, not a data question — Task 1's tests
already confirm the Python side produces the right two-line string.
