# Graph Explorer UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Graph Explorer's presentation layer — dropdown search, per-query hierarchical/table layouts, attestation-as-edge-label collapsing, a navigable detail panel, and more credible synthetic CVE IDs — per `docs/superpowers/specs/2026-07-17-graph-explorer-ux-design.md`.

**Architecture:** Three new pure/testable Python modules carry the new logic (`queries.py` gains three list functions, a new `graph_render.py` handles node-graph shaping, a new `build_history_view.py` handles table shaping), all consumed by a rewritten `1_Graph_Explorer.py` page. No changes to the Neo4j schema or the four existing named queries' Cypher/return shape.

**Tech Stack:** FastAPI, Neo4j Python driver, Streamlit, `streamlit_agraph` (confirmed installed: `streamlit-agraph>=0.0.45` in `pyproject.toml`), pytest with the existing `FakeDriver`/`FakeSession`/`FakeNode` test doubles in `tests/graph_fakes.py`.

## Global Constraints

- Do not modify the Cypher or `{nodes, edges}` return shape of the four existing query functions (`vuln_blast_radius`, `vuln_origin_trace`, `repo_build_history`, `package_usage`) or `expand_neighbors` — spec §1/§2.
- The Neo4j attestation-as-node data model (`VexStatement`, `IsDependency` as real nodes) stays unchanged — collapsing to edge labels happens only in the Streamlit rendering layer — spec §4.1.
- Stay in Streamlit + `streamlit_agraph`; no new frontend framework — spec §2.
- Same PoC-grade error handling bar as the existing slice: `ServiceUnavailable` → HTTP 503, no other new validation — spec §7.
- New query functions follow the existing hand-written-Cypher-function pattern in `queries.py` — no query-builder abstraction.

---

### Task 1: Graph entity list queries

**Files:**
- Modify: `src/scie/graph/queries.py`
- Test: `tests/test_graph_queries.py`

**Interfaces:**
- Produces: `queries.LIST_PACKAGES_QUERY: str`, `queries.LIST_VULNERABILITIES_QUERY: str`, `queries.LIST_REPOSITORIES_QUERY: str`; `queries.list_packages(driver: Driver) -> list[dict]`, `queries.list_vulnerabilities(driver: Driver) -> list[dict]`, `queries.list_repositories(driver: Driver) -> list[dict]`. Each returns flat records (not the `{element_id, labels, properties}` node envelope) — e.g. `[{"purl": "...", "name": "...", "version": "..."}, ...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_graph_queries.py`:

```python
def test_list_packages_sends_expected_query():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.LIST_PACKAGES_QUERY, [])

    queries.list_packages(driver)

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.LIST_PACKAGES_QUERY
    assert params == {}


def test_list_packages_returns_flat_records():
    driver = FakeDriver()
    driver.fake_session.set_result(
        queries.LIST_PACKAGES_QUERY,
        [{"purl": "pkg:pypi/openssl@1.0.0", "name": "openssl", "version": "1.0.0"}],
    )

    result = queries.list_packages(driver)

    assert result == [{"purl": "pkg:pypi/openssl@1.0.0", "name": "openssl", "version": "1.0.0"}]


def test_list_vulnerabilities_sends_expected_query():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.LIST_VULNERABILITIES_QUERY, [])

    queries.list_vulnerabilities(driver)

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.LIST_VULNERABILITIES_QUERY
    assert params == {}


def test_list_vulnerabilities_returns_flat_records():
    driver = FakeDriver()
    driver.fake_session.set_result(
        queries.LIST_VULNERABILITIES_QUERY, [{"id": "CVE-2014-0160"}],
    )

    result = queries.list_vulnerabilities(driver)

    assert result == [{"id": "CVE-2014-0160"}]


def test_list_repositories_sends_expected_query():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.LIST_REPOSITORIES_QUERY, [])

    queries.list_repositories(driver)

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.LIST_REPOSITORIES_QUERY
    assert params == {}


def test_list_repositories_returns_flat_records():
    driver = FakeDriver()
    driver.fake_session.set_result(
        queries.LIST_REPOSITORIES_QUERY,
        [{"url": "https://github.com/example-org/billing-api-1", "name": "billing-api-1"}],
    )

    result = queries.list_repositories(driver)

    assert result == [
        {"url": "https://github.com/example-org/billing-api-1", "name": "billing-api-1"}
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_queries.py -v -k list_`
Expected: FAIL with `AttributeError: module 'scie.graph.queries' has no attribute 'LIST_PACKAGES_QUERY'` (and similar for the others).

- [ ] **Step 3: Implement the list query functions**

In `src/scie/graph/queries.py`, add after the existing query constants (after `EXPAND_NEIGHBORS_QUERY`, before `_serialize_value`):

```python
LIST_PACKAGES_QUERY = """
MATCH (p:Package)
RETURN p.purl AS purl, p.name AS name, p.version AS version
ORDER BY p.name
"""

LIST_VULNERABILITIES_QUERY = """
MATCH (v:VulnerabilityID)
RETURN v.id AS id
ORDER BY v.id
"""

LIST_REPOSITORIES_QUERY = """
MATCH (r:Repository)
RETURN r.url AS url, r.name AS name
ORDER BY r.name
"""
```

Add after `expand_neighbors` at the end of the file:

```python
def list_packages(driver: Driver) -> list[dict]:
    return _run(driver, LIST_PACKAGES_QUERY)


def list_vulnerabilities(driver: Driver) -> list[dict]:
    return _run(driver, LIST_VULNERABILITIES_QUERY)


def list_repositories(driver: Driver) -> list[dict]:
    return _run(driver, LIST_REPOSITORIES_QUERY)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_queries.py -v`
Expected: all PASS (existing tests plus the 6 new ones).

- [ ] **Step 5: Commit**

```bash
git add src/scie/graph/queries.py tests/test_graph_queries.py
git commit -m "feat: add graph entity list queries for search dropdowns"
```

---

### Task 2: Graph entity list routes

**Files:**
- Modify: `src/scie/api/graph_routes.py`
- Test: `tests/test_graph_routes.py`

**Interfaces:**
- Consumes: `queries.list_packages`, `queries.list_vulnerabilities`, `queries.list_repositories` from Task 1 (called via `graph_routes.queries.<name>`, monkeypatchable the same way the existing route tests patch `graph_routes.queries.vuln_blast_radius` etc.)
- Produces: `GET /graph/packages`, `GET /graph/vulnerabilities`, `GET /graph/repositories`, each returning the `list[dict]` JSON body from the corresponding query function, or 503 on `ServiceUnavailable`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_graph_routes.py`:

```python
def test_list_packages_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "list_packages",
        lambda driver: [{"purl": "pkg:pypi/openssl@1.0.0", "name": "openssl", "version": "1.0.0"}],
    )
    client = TestClient(app)

    response = client.get("/graph/packages")

    assert response.status_code == 200
    assert response.json() == [
        {"purl": "pkg:pypi/openssl@1.0.0", "name": "openssl", "version": "1.0.0"}
    ]


def test_list_vulnerabilities_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "list_vulnerabilities",
        lambda driver: [{"id": "CVE-2014-0160"}],
    )
    client = TestClient(app)

    response = client.get("/graph/vulnerabilities")

    assert response.status_code == 200
    assert response.json() == [{"id": "CVE-2014-0160"}]


def test_list_repositories_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "list_repositories",
        lambda driver: [
            {"url": "https://github.com/example-org/billing-api-1", "name": "billing-api-1"}
        ],
    )
    client = TestClient(app)

    response = client.get("/graph/repositories")

    assert response.status_code == 200
    assert response.json() == [
        {"url": "https://github.com/example-org/billing-api-1", "name": "billing-api-1"}
    ]


def test_list_packages_route_returns_503_when_graph_db_unavailable(monkeypatch):
    def raise_unavailable(driver):
        raise ServiceUnavailable("down")

    monkeypatch.setattr(graph_routes.queries, "list_packages", raise_unavailable)
    client = TestClient(app)

    response = client.get("/graph/packages")

    assert response.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_routes.py -v -k list_`
Expected: FAIL with 404 (routes don't exist yet) — `assert 404 == 200`.

- [ ] **Step 3: Implement the list routes**

In `src/scie/api/graph_routes.py`, insert these three routes right after `router = APIRouter(...)` and before the existing `/vulnerabilities/{vuln_id}/blast-radius` route (static paths before parameterized ones, matching FastAPI convention):

```python
@router.get("/packages")
def get_list_packages() -> list[dict]:
    try:
        return queries.list_packages(get_driver())
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/vulnerabilities")
def get_list_vulnerabilities() -> list[dict]:
    try:
        return queries.list_vulnerabilities(get_driver())
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/repositories")
def get_list_repositories() -> list[dict]:
    try:
        return queries.list_repositories(get_driver())
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_routes.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scie/api/graph_routes.py tests/test_graph_routes.py
git commit -m "feat: add graph entity list routes for search dropdowns"
```

---

### Task 3: Graph rendering helpers (attestation collapsing, real labels)

**Files:**
- Create: `src/scie/ui/graph_render.py`
- Test: `tests/test_graph_render.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure functions over the `{element_id, labels, properties}` node shape and `{source, target, type}` edge shape already produced by every `queries.py` function).
- Produces: `graph_render.NODE_COLORS: dict[str, str]`, `graph_render.node_display_label(node: dict) -> str`, `graph_render.collapse_attestations(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]`, `graph_render.to_agraph_elements(nodes: list[dict], edges: list[dict]) -> tuple[list[Node], list[Edge]]`. Task 6 imports and calls all four.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_graph_render.py`:

```python
from scie.ui.graph_render import collapse_attestations, node_display_label, to_agraph_elements


def _node(element_id, label, **props):
    return {"element_id": element_id, "labels": [label], "properties": props}


def test_node_display_label_uses_identifying_property_per_label():
    assert node_display_label(_node("r1", "Repository", url="https://x/y", name="y")) == "y"
    assert node_display_label(_node("b1", "Build", id="build-0001")) == "build-0001"
    assert node_display_label(_node("c1", "Commit", sha="abcdef1234567890")) == "abcdef1"
    assert node_display_label(_node("a1", "Artifact", digest="sha256:x", name="svc")) == "svc"
    assert node_display_label(_node("p1", "Package", name="openssl", version="1.0.0")) == "openssl@1.0.0"
    assert node_display_label(_node("v1", "VulnerabilityID", id="CVE-2014-0160")) == "CVE-2014-0160"
    assert node_display_label(_node("d1", "Deployment", cluster="scie", namespace="prod")) == "scie/prod"


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
    assert kept_edges == [{"source": "p1", "target": "v1", "type": "CertifyVuln (affected)"}]


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
    assert kept_edges == [{"source": "a1", "target": "p1", "type": "DependsOn"}]


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
    assert agraph_nodes[0].label == "openssl@1.0.0"
    assert agraph_nodes[0].title == ""
    assert agraph_nodes[0].color == "#CCB974"
    assert len(agraph_edges) == 1
    assert agraph_edges[0].source == "p1"
    assert agraph_edges[0].to == "p1"
    assert agraph_edges[0].label == "self"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.ui.graph_render'`.

- [ ] **Step 3: Implement `graph_render.py`**

Create `src/scie/ui/graph_render.py`:

```python
from streamlit_agraph import Edge, Node

NODE_COLORS = {
    "Repository": "#4C72B0",
    "Build": "#55A868",
    "Commit": "#C44E52",
    "Artifact": "#8172B2",
    "Package": "#CCB974",
    "VulnerabilityID": "#DA3B3B",
    "Deployment": "#8C8C8C",
}

# Canvas display text only — distinct from queries.py callers' notion of a
# unique lookup key (see KEY_PROP_BY_LABEL in 1_Graph_Explorer.py, and the
# fe429d8 fix that removed Deployment.cluster from that dict for not being
# unique enough for that purpose). Display text has no uniqueness
# requirement, so it can combine fields freely.
_DISPLAY_LABEL_BUILDERS = {
    "Repository": lambda props: props.get("name") or props.get("url", ""),
    "Build": lambda props: props.get("id", ""),
    "Commit": lambda props: props.get("sha", "")[:7],
    "Artifact": lambda props: props.get("name") or props.get("digest", ""),
    "Package": lambda props: f'{props.get("name", "?")}@{props.get("version", "?")}',
    "VulnerabilityID": lambda props: props.get("id", ""),
    "Deployment": lambda props: f'{props.get("cluster", "?")}/{props.get("namespace", "?")}',
}

# Attestation nodes are always the *source* of both their edges (the GUAC
# convention this schema follows — see the "Graph Schema" section of
# docs/superpowers/specs/2026-07-16-graph-explorer-design.md). Each entry
# names which of an attestation's two outgoing edge types becomes the
# collapsed edge's source-neighbor vs target-neighbor.
_ATTESTATION_EDGE_ROLES = {
    "VexStatement": {"source_edge_type": "subject", "target_edge_type": "vulnerability"},
    "IsDependency": {"source_edge_type": "subject", "target_edge_type": "dependency"},
}


def node_display_label(node: dict) -> str:
    label = node["labels"][0]
    builder = _DISPLAY_LABEL_BUILDERS.get(label)
    if builder is None:
        return label
    return builder(node["properties"]) or label


def _attestation_edge_label(node: dict) -> str:
    label = node["labels"][0]
    if label == "VexStatement":
        return f'CertifyVuln ({node["properties"].get("status", "?")})'
    return "DependsOn"


def collapse_attestations(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse VexStatement/IsDependency attestation nodes into a single
    labeled edge between their two neighbors. Pure rendering-layer transform
    — the Neo4j data model and queries.py are untouched."""
    attestation_nodes = {
        n["element_id"]: n for n in nodes if n["labels"][0] in _ATTESTATION_EDGE_ROLES
    }
    kept_nodes = [n for n in nodes if n["element_id"] not in attestation_nodes]

    edges_by_attestation: dict[str, dict[str, str]] = {}
    kept_edges = []
    for edge in edges:
        if edge["source"] in attestation_nodes:
            edges_by_attestation.setdefault(edge["source"], {})[edge["type"]] = edge["target"]
        else:
            kept_edges.append(edge)

    for attestation_id, by_type in edges_by_attestation.items():
        attestation_node = attestation_nodes[attestation_id]
        roles = _ATTESTATION_EDGE_ROLES[attestation_node["labels"][0]]
        source_id = by_type.get(roles["source_edge_type"])
        target_id = by_type.get(roles["target_edge_type"])
        if source_id is None or target_id is None:
            continue
        kept_edges.append({
            "source": source_id,
            "target": target_id,
            "type": _attestation_edge_label(attestation_node),
        })

    return kept_nodes, kept_edges


def to_agraph_elements(nodes: list[dict], edges: list[dict]) -> tuple[list[Node], list[Edge]]:
    agraph_nodes = []
    for node in nodes:
        label = node["labels"][0]
        agraph_node = Node(
            id=node["element_id"],
            label=node_display_label(node),
            color=NODE_COLORS.get(label, "#999999"),
        )
        # streamlit_agraph defaults title to id and opens it via window.open()
        # on double-click; Node(title=...) falls back to id for any falsy
        # value, so the attribute must be cleared after construction.
        agraph_node.title = ""
        agraph_nodes.append(agraph_node)
    agraph_edges = [
        Edge(source=edge["source"], target=edge["target"], label=edge["type"])
        for edge in edges
    ]
    return agraph_nodes, agraph_edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_render.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scie/ui/graph_render.py tests/test_graph_render.py
git commit -m "feat: add graph rendering helpers with attestation-as-edge-label collapsing"
```

---

### Task 4: Build history table shaping

**Files:**
- Create: `src/scie/ui/build_history_view.py`
- Test: `tests/test_build_history_view.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure function over the `{nodes, edges}` shape `repo_build_history` already returns).
- Produces: `build_history_view.build_history_rows(nodes: list[dict], edges: list[dict]) -> list[dict]`, each row `{"Start Time": str, "CI System": str, "Status": str, "Artifacts": str}`, sorted by start time descending. Task 6 imports and calls this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_build_history_view.py`:

```python
from scie.ui.build_history_view import build_history_rows


def _node(element_id, label, **props):
    return {"element_id": element_id, "labels": [label], "properties": props}


def test_build_history_rows_includes_artifact_names_and_status_glyph():
    nodes = [
        _node(
            "b1", "Build", id="build-0001",
            startTime="2026-01-01T00:00:00+00:00", ciSystem="github-actions", status="success",
        ),
        _node("a1", "Artifact", digest="sha256:x", name="svc-a"),
    ]
    edges = [{"source": "b1", "target": "a1", "type": "PRODUCED"}]

    rows = build_history_rows(nodes, edges)

    assert rows == [{
        "Start Time": "2026-01-01T00:00:00+00:00",
        "CI System": "github-actions",
        "Status": "✅",
        "Artifacts": "svc-a",
    }]


def test_build_history_rows_uses_failure_glyph_for_non_success_status():
    nodes = [
        _node(
            "b1", "Build", id="build-0001",
            startTime="2026-01-01T00:00:00+00:00", ciSystem="github-actions", status="failed",
        ),
    ]

    rows = build_history_rows(nodes, [])

    assert rows[0]["Status"] == "❌"


def test_build_history_rows_sorted_by_start_time_descending():
    nodes = [
        _node(
            "b1", "Build", id="build-0001",
            startTime="2026-01-01T00:00:00+00:00", ciSystem="x", status="success",
        ),
        _node(
            "b2", "Build", id="build-0002",
            startTime="2026-01-02T00:00:00+00:00", ciSystem="x", status="success",
        ),
    ]

    rows = build_history_rows(nodes, [])

    assert [row["Start Time"] for row in rows] == [
        "2026-01-02T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
    ]


def test_build_history_rows_handles_build_with_no_artifacts():
    nodes = [
        _node(
            "b1", "Build", id="build-0001",
            startTime="2026-01-01T00:00:00+00:00", ciSystem="x", status="success",
        ),
    ]

    rows = build_history_rows(nodes, [])

    assert rows[0]["Artifacts"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_build_history_view.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.ui.build_history_view'`.

- [ ] **Step 3: Implement `build_history_view.py`**

Create `src/scie/ui/build_history_view.py`:

```python
def build_history_rows(nodes: list[dict], edges: list[dict]) -> list[dict]:
    nodes_by_id = {node["element_id"]: node for node in nodes}
    builds = [node for node in nodes if node["labels"][0] == "Build"]

    artifact_names_by_build: dict[str, list[str]] = {}
    for edge in edges:
        if edge["type"] != "PRODUCED":
            continue
        artifact = nodes_by_id.get(edge["target"])
        if artifact is None:
            continue
        name = artifact["properties"].get("name") or artifact["properties"].get("digest", "")
        artifact_names_by_build.setdefault(edge["source"], []).append(name)

    rows = []
    for build in builds:
        props = build["properties"]
        rows.append({
            "Start Time": props.get("startTime", ""),
            "CI System": props.get("ciSystem", ""),
            "Status": "✅" if props.get("status") == "success" else "❌",
            "Artifacts": ", ".join(artifact_names_by_build.get(build["element_id"], [])),
        })

    rows.sort(key=lambda row: row["Start Time"], reverse=True)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_build_history_view.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scie/ui/build_history_view.py tests/test_build_history_view.py
git commit -m "feat: add build history table shaping for Graph Explorer"
```

---

### Task 5: Real CVE IDs in the synthetic data catalog

**Files:**
- Modify: `src/scie/graph/synthetic_graph.py:25-29`

**Interfaces:**
- Consumes: nothing.
- Produces: `synthetic_graph.VULNERABILITY_CATALOG` — same name, same `list[tuple[str, str]]` shape, new values. `tests/test_graph_synthetic.py::test_writes_a_vex_statement_for_every_catalog_vulnerability` already derives its expected IDs from this constant by import, so it self-updates — no test file changes needed for this task.

- [ ] **Step 1: Confirm the existing test currently passes (baseline)**

Run: `uv run pytest tests/test_graph_synthetic.py -v`
Expected: all PASS (this is the pre-change baseline — the test reads `VULNERABILITY_CATALOG` by reference, so it can't fail from a values-only change, but confirm it's green before touching the file).

- [ ] **Step 2: Replace the fake CVE IDs with real, historical ones**

In `src/scie/graph/synthetic_graph.py`, replace lines 25-29:

```python
VULNERABILITY_CATALOG = [
    ("CVE-2025-1111", "pkg:pypi/openssl@1.0.0"),
    ("CVE-2025-2222", "pkg:pypi/requests@2.25.0"),
    ("CVE-2025-3333", "pkg:pypi/urllib3@1.26.0"),
]
```

with:

```python
VULNERABILITY_CATALOG = [
    # Real, historical CVE IDs paired with the (already-real) package names
    # above, so the graph reads as credible rather than obviously synthetic.
    # CVE-2014-0160 (Heartbleed) is the most recognizable pairing for
    # openssl and is used for that reason; it technically affects the 1.0.1
    # branch rather than the 1.0.0 version string already in PACKAGE_CATALOG
    # above. Every repo/build/commit in this dataset is synthetic anyway —
    # "reads as a real CVE ID" is the bar here, not exact version accuracy.
    # requests/urllib3 below are both real CVEs that do match the paired
    # version.
    ("CVE-2014-0160", "pkg:pypi/openssl@1.0.0"),
    ("CVE-2023-32681", "pkg:pypi/requests@2.25.0"),
    ("CVE-2021-33503", "pkg:pypi/urllib3@1.26.0"),
]
```

- [ ] **Step 3: Run tests to verify nothing broke**

Run: `uv run pytest tests/test_graph_synthetic.py tests/test_graph_queries.py -v`
Expected: all PASS. (`test_graph_queries.py`'s tests pass CVE IDs as literal test-fixture arguments independent of this catalog, so they're unaffected.)

- [ ] **Step 4: Commit**

```bash
git add src/scie/graph/synthetic_graph.py
git commit -m "fix: use real historical CVE IDs in synthetic graph data"
```

---

### Task 6: Rewrite the Graph Explorer page

**Files:**
- Modify: `src/scie/ui/pages/1_Graph_Explorer.py` (full rewrite)

**Interfaces:**
- Consumes: `graph_render.collapse_attestations`, `graph_render.to_agraph_elements` (Task 3); `build_history_view.build_history_rows` (Task 4); the new `GET /graph/packages`, `/graph/vulnerabilities`, `/graph/repositories` list routes (Task 2); the existing `/graph/vulnerabilities/{id}/blast-radius`, `/graph/vulnerabilities/{id}/origin`, `/graph/packages/{purl}/usage`, `/graph/repositories/{url}/history`, `/graph/expand/{label}/{key_prop}/{key_value}` routes (unchanged).
- Produces: the rendered page. No other task depends on this file.

There is no existing automated test coverage for Streamlit page files in this
codebase (`tests/` has no `AppTest`/Streamlit-runtime tests for
`streamlit_app.py` either) — this task's verification is a syntax check here
plus the full manual walkthrough in Task 7, consistent with spec §7 ("a unit
test can't verify visual layout").

- [ ] **Step 1: Replace the file contents**

Replace all of `src/scie/ui/pages/1_Graph_Explorer.py` with:

```python
import os

import requests
import streamlit as st
from streamlit_agraph import Config, agraph

from scie.ui.build_history_view import build_history_rows
from scie.ui.graph_render import collapse_attestations, to_agraph_elements

API_URL = os.environ.get("SCIE_API_URL", "http://localhost:8000")

KEY_PROP_BY_LABEL = {
    "Repository": "url",
    "Build": "id",
    "Commit": "sha",
    "Artifact": "digest",
    "Package": "purl",
    "VulnerabilityID": "id",
}

st.set_page_config(page_title="Graph Explorer", layout="wide")
st.title("Graph Explorer")

if "graph_nodes" not in st.session_state:
    st.session_state.graph_nodes = {}
    st.session_state.graph_edges = {}
    st.session_state.view_kind = "graph"


def _replace(result: dict, view_kind: str) -> None:
    st.session_state.graph_nodes = {node["element_id"]: node for node in result["nodes"]}
    st.session_state.graph_edges = {
        (edge["source"], edge["target"], edge["type"]): edge for edge in result["edges"]
    }
    st.session_state.view_kind = view_kind


def _merge(result: dict) -> None:
    for node in result["nodes"]:
        st.session_state.graph_nodes[node["element_id"]] = node
    for edge in result["edges"]:
        key = (edge["source"], edge["target"], edge["type"])
        st.session_state.graph_edges[key] = edge


def _fetch(path: str) -> dict | list:
    response = requests.get(f"{API_URL}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


def _run_query_and_rerun(path: str, view_kind: str) -> None:
    _replace(_fetch(path), view_kind)
    st.rerun()


mode = st.selectbox("Search by", ["Vulnerability ID", "Package PURL", "Repository URL"])

if mode == "Vulnerability ID":
    options = _fetch("/graph/vulnerabilities")
    option_labels = [opt["id"] for opt in options]
elif mode == "Package PURL":
    options = _fetch("/graph/packages")
    option_labels = [f'{opt["name"]}@{opt["version"]}' for opt in options]
else:
    options = _fetch("/graph/repositories")
    option_labels = [opt["name"] or opt["url"] for opt in options]

selected_index = None
if option_labels:
    selected_index = st.selectbox(
        "Value", options=range(len(option_labels)), format_func=lambda i: option_labels[i],
    )
else:
    st.info("No data seeded yet for this search mode.")

if st.button("Search") and selected_index is not None:
    selected = options[selected_index]
    if mode == "Vulnerability ID":
        _run_query_and_rerun(f"/graph/vulnerabilities/{selected['id']}/blast-radius", "graph")
    elif mode == "Package PURL":
        _run_query_and_rerun(f"/graph/packages/{selected['purl']}/usage", "graph")
    else:
        _run_query_and_rerun(f"/graph/repositories/{selected['url']}/history", "table")

if st.session_state.graph_nodes:
    if st.session_state.view_kind == "table":
        rows = build_history_rows(
            list(st.session_state.graph_nodes.values()),
            list(st.session_state.graph_edges.values()),
        )
        st.dataframe(rows, use_container_width=True)
    else:
        nodes, edges = collapse_attestations(
            list(st.session_state.graph_nodes.values()),
            list(st.session_state.graph_edges.values()),
        )
        agraph_nodes, agraph_edges = to_agraph_elements(nodes, edges)
        config = Config(
            width=1000, height=600, directed=True,
            hierarchical=True, direction="LR", physics=False,
        )
        clicked_id = agraph(nodes=agraph_nodes, edges=agraph_edges, config=config)

        if clicked_id and clicked_id in st.session_state.graph_nodes:
            clicked_node = st.session_state.graph_nodes[clicked_id]
            label = clicked_node["labels"][0]
            props = clicked_node["properties"]
            st.subheader(label)
            for key, value in props.items():
                st.write(f"**{key}:** {value}")

            if label == "Package" and "purl" in props:
                if st.button("Show usage"):
                    _run_query_and_rerun(f"/graph/packages/{props['purl']}/usage", "graph")
            elif label == "VulnerabilityID" and "id" in props:
                lens_col1, lens_col2 = st.columns(2)
                with lens_col1:
                    if st.button("Blast radius"):
                        _run_query_and_rerun(
                            f"/graph/vulnerabilities/{props['id']}/blast-radius", "graph"
                        )
                with lens_col2:
                    if st.button("Origin trace"):
                        _run_query_and_rerun(
                            f"/graph/vulnerabilities/{props['id']}/origin", "graph"
                        )
            elif label == "Repository" and "url" in props:
                if st.button("Build history"):
                    _run_query_and_rerun(f"/graph/repositories/{props['url']}/history", "table")

            key_prop = KEY_PROP_BY_LABEL.get(label)
            if key_prop and key_prop in props:
                if st.button(f"Expand {label}"):
                    result = _fetch(f"/graph/expand/{label}/{key_prop}/{props[key_prop]}")
                    _merge(result)
                    st.rerun()
else:
    st.info("No graph data loaded yet — run a search above.")
```

- [ ] **Step 2: Syntax-check the file**

Run: `uv run python -c "import ast; ast.parse(open('src/scie/ui/pages/1_Graph_Explorer.py').read())"`
Expected: no output, exit code 0.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `uv run pytest -v`
Expected: all PASS (this file has no direct test coverage, but confirms nothing else broke, e.g. import errors surfaced via collection).

- [ ] **Step 4: Commit**

```bash
git add src/scie/ui/pages/1_Graph_Explorer.py
git commit -m "feat: redesign Graph Explorer search, layout, and detail panel"
```

---

### Task 7: Manual end-to-end verification

**Files:** none — this task exercises the running stack, no code changes.

This is the step that actually answers "does it look right" — spec §7 is
explicit that a unit test can't verify visual layout, so this has to be a
human looking at a real browser, the same way Task 6 of the original
Graph Explorer slice was verified.

- [ ] **Step 1: Rebuild and restart the dashboard and api services**

The `src/` directory is `COPY`'d into the Docker image at build time (no bind
mount), so a plain restart will not pick up the code changes from Tasks 1-6.

Run: `docker compose up -d --build api dashboard`
Expected: both containers rebuild and report `Started`.

- [ ] **Step 2: Clear and reseed Neo4j so the old fake CVE IDs don't linger**

`seed.py` uses `MERGE`, which is idempotent for unchanged data but does not
delete nodes that are no longer produced by the generator — the old
`CVE-2025-1111/2222/3333` nodes from Task 5's change would otherwise remain
as orphaned leftovers alongside the new real CVE IDs.

Run:
```bash
docker exec pipeline-lens-neo4j-1 cypher-shell -u neo4j -p devpassword "MATCH (n) DETACH DELETE n"
docker exec pipeline-lens-api-1 uv run python -m scie.graph.seed
```
Expected: the delete returns with no error; the seed command prints
`Seeded a synthetic graph with 15 repository chains.`

- [ ] **Step 3: Verify the new list endpoints against live data**

Run:
```bash
curl -s --max-time 5 "http://172.19.0.1:18000/graph/vulnerabilities"
curl -s --max-time 5 "http://172.19.0.1:18000/graph/packages"
curl -s --max-time 5 "http://172.19.0.1:18000/graph/repositories"
```
(Use `172.19.0.1` — the `devx_default` bridge gateway — rather than
`localhost`, per the DooD networking note from this session: this sandbox
container reaches the Docker host's published ports through the bridge
gateway, not through its own loopback.)

Expected: three JSON arrays; the vulnerabilities one contains
`CVE-2014-0160`, `CVE-2023-32681`, `CVE-2021-33503` and none of the old
`CVE-2025-*` IDs.

- [ ] **Step 4: Walk through the UI at `http://localhost:8501` → Graph Explorer**

Report back on each of these:
- Vulnerability ID mode: dropdown lists real CVE IDs; searching
  `CVE-2014-0160` renders a left-to-right tree (not a physics blob); every
  node shows a real name/id, never a bare "Package"/"Deployment" label; no
  `VexStatement` circle is visible, its info instead appears as a
  `CertifyVuln (affected)` edge label.
- Click a `VulnerabilityID` node → detail panel shows labeled fields (not
  raw JSON) plus **Blast radius** and **Origin trace** buttons; clicking
  **Origin trace** swaps to a fresh tree ending at a `Repository`/`Commit`
  instead of a `Deployment` (this view was previously unreachable from the
  UI at all).
- Package PURL mode: dropdown lists `name@version` pairs; search renders a
  usage tree; click a `Package` node → **Show usage** button re-centers the
  view.
- Repository URL mode: dropdown lists repo names; search renders an
  `st.dataframe` table (build date, CI system, ✅/❌, artifact names) — not
  a graph.
- Click a `Repository` node reached via Expand from another view →
  **Build history** button switches to the table view for that repo.
- The Expand button still works and still merges into the current view
  rather than replacing it (contrast with Search/lens buttons, which
  replace).

- [ ] **Step 5: Fix forward if anything in Step 4 doesn't match**

If a specific check fails, note which one and go back to the relevant task
above rather than patching ad hoc — e.g. a wrong edge direction on collapsed
attestation edges means revisiting Task 3's `_ATTESTATION_EDGE_ROLES` logic,
not a one-off tweak in the page file.
