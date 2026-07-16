# Graph Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first slice of Phase 2's graph model: a Neo4j-backed graph populated with synthetic but schema-faithful supply-chain data, four named Cypher queries plus a generic neighbor-expansion query, FastAPI routes exposing them, and a clickable "Graph Explorer" page in the existing Streamlit dashboard.

**Architecture:** Neo4j runs as a new Docker Compose service, independent of the v1 SQLite `PipelineRun` store. A `scie.graph` package holds a driver singleton, schema constraints, a synthetic data generator (`MERGE`s identity nodes, `CREATE`s attestation nodes per the GUAC attestation-as-node pattern), and a query layer of hand-written Cypher functions that each return a uniform `{"nodes": [...], "edges": [...]}` shape keyed by Neo4j's internal `element_id`. A new FastAPI router exposes those functions as JSON; a new Streamlit page renders them with `streamlit-agraph` and lets you click a node to expand its neighbors.

**Tech Stack:** Python 3.12, uv, the official `neo4j` Python driver, `streamlit-agraph`, FastAPI, Streamlit, pytest (existing project stack, per `docs/superpowers/plans/2026-07-04-supply-chain-insights-engine-v1.md`).

## Global Constraints

- Package/project management: `uv` exclusively — no pip/poetry/conda commands.
- The Python package stays named `scie` (matches existing imports, `docker-compose.yml` commands, CI, Terraform) — "Pipeline Lens" is the outward-facing/repo brand only.
- This dataset is independent of v1's SQLite `PipelineRun` data — no shared identifiers, no coupling between the two generators.
- SQLite remains v1's store as-is; no Postgres migration in this plan.
- No real SBOM/SARIF/provenance ingestion in this plan — data comes only from the synthetic generator.
- Phase: PoC, same bar as v1 — no retry/validation/error-handling beyond what each task specifies. Neo4j connection errors surface as an HTTP 503, not swallowed.
- Attestation nodes (`IsDependency`, `VexStatement`) are always the *source* of their edges (`-[:subject]->` the thing they're about, plus one more named edge) — never the target. Identity nodes (`Repository`, `Build`, `Commit`, `Artifact`, `Package`, `VulnerabilityID`) are `MERGE`d on their natural key; attestation nodes (`IsDependency`, `VexStatement`) and point-in-time nodes (`Deployment`) are `CREATE`d fresh, no natural uniqueness key.
- Every query function in `scie.graph.queries` returns the same shape: `{"nodes": [{"element_id", "labels", "properties"}, ...], "edges": [{"source", "target", "type"}, ...]}`, using Neo4j's internal `element_id` (not a business key) to identify nodes — this is what lets the Streamlit page merge results from different queries into one graph without per-query-type special-casing.

---

## File Structure

```
src/scie/graph/
  ├── __init__.py
  ├── db.py               # get_driver()
  ├── schema.py            # apply_constraints(driver)
  ├── synthetic_graph.py   # generate_synthetic_graph(driver, count, seed)
  ├── queries.py            # vuln_blast_radius, vuln_origin_trace, repo_build_history,
  │                          #   package_usage, expand_neighbors
  └── seed.py               # CLI: apply_constraints() + generate_synthetic_graph()

src/scie/api/graph_routes.py       # new FastAPI router, mounted into the existing app
src/scie/ui/pages/1_Graph_Explorer.py  # new Streamlit page (auto-discovered sibling of streamlit_app.py)

tests/
  ├── graph_fakes.py        # FakeDriver, FakeSession, FakeNode test doubles (not collected as tests)
  ├── test_graph_db.py
  ├── test_graph_schema.py
  ├── test_graph_synthetic.py
  ├── test_graph_seed.py
  ├── test_graph_queries.py
  └── test_graph_routes.py
```

---

### Task 1: Neo4j Docker Compose service and Python dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml`

**Interfaces:**
- Produces: `neo4j` and `streamlit_agraph` importable from the project's venv; a running `neo4j` container reachable at `bolt://neo4j:7687` from other Compose services and `bolt://localhost:7687` from the host; `api` service configured with `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` env vars — used by Task 2's `get_driver()`.

- [ ] **Step 1: Add the neo4j and streamlit-agraph dependencies**

Run:
```bash
uv add neo4j streamlit-agraph
```

- [ ] **Step 2: Verify the packages import**

Run: `uv run python -c "import neo4j, streamlit_agraph; print('ok')"`
Expected: prints `ok` with no import errors.

- [ ] **Step 3: Add the neo4j service to docker-compose.yml**

Add a new `neo4j` service (alongside the existing `redpanda`/`postgres`/`temporal` services) and add a `neo4j-data` volume:

```yaml
  neo4j:
    image: neo4j:5-community
    environment:
      - NEO4J_AUTH=neo4j/devpassword
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j-data:/data
```

Add `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` to the `api` service's `environment` list and add `neo4j` to its `depends_on`:

```yaml
  api:
    build: .
    ports:
      - "${SCIE_API_PORT:-8000}:8000"
    environment:
      - REDPANDA_BROKERS=redpanda:9092
      - TEMPORAL_ADDRESS=temporal:7233
      - SCIE_DATABASE_URL=sqlite:////data/scie.db
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=devpassword
    volumes:
      - scie-data:/data
    depends_on:
      - redpanda
      - temporal
      - neo4j
```

Add `neo4j-data:` to the top-level `volumes:` block, next to the existing `scie-data:`.

- [ ] **Step 4: Verify Compose config is valid**

Run: `docker compose config --quiet`
Expected: no output, exit code 0 (confirms the YAML parses and service references resolve).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock docker-compose.yml
git commit -m "chore: add Neo4j service and graph dependencies"
```

---

### Task 2: Neo4j driver singleton

**Files:**
- Create: `src/scie/graph/__init__.py`
- Create: `src/scie/graph/db.py`
- Test: `tests/test_graph_db.py`

**Interfaces:**
- Produces: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `get_driver() -> Driver` from `scie.graph.db` — used by Task 5 (seed) and Task 7 (routes).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph_db.py
from unittest.mock import MagicMock

import scie.graph.db as graph_db


def test_get_driver_constructs_with_configured_uri_and_auth(monkeypatch):
    monkeypatch.setattr(graph_db, "_driver", None)
    fake_driver = MagicMock()
    captured = {}

    def fake_driver_factory(uri, auth):
        captured["uri"] = uri
        captured["auth"] = auth
        return fake_driver

    monkeypatch.setattr(graph_db.GraphDatabase, "driver", fake_driver_factory)

    driver = graph_db.get_driver()

    assert driver is fake_driver
    assert captured["uri"] == graph_db.NEO4J_URI
    assert captured["auth"] == (graph_db.NEO4J_USER, graph_db.NEO4J_PASSWORD)


def test_get_driver_returns_cached_instance(monkeypatch):
    monkeypatch.setattr(graph_db, "_driver", None)
    fake_driver = MagicMock()
    monkeypatch.setattr(graph_db.GraphDatabase, "driver", lambda uri, auth: fake_driver)

    first = graph_db.get_driver()
    second = graph_db.get_driver()

    assert first is second
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.graph'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/graph/__init__.py
```

```python
# src/scie/graph/db.py
import os

from neo4j import Driver, GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "devpassword")

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_db.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/graph/__init__.py src/scie/graph/db.py tests/test_graph_db.py
git commit -m "feat: add Neo4j driver singleton"
```

---

### Task 3: Graph schema constraints

**Files:**
- Create: `src/scie/graph/schema.py`
- Create: `tests/graph_fakes.py`
- Test: `tests/test_graph_schema.py`

**Interfaces:**
- Produces: `CONSTRAINTS: list[str]`, `apply_constraints(driver) -> None` from `scie.graph.schema` — used by Task 5 (seed). `FakeDriver`, `FakeSession`, `FakeNode` from `tests/graph_fakes.py` — used by every later graph test file (imported as plain `from graph_fakes import ...`, since `tests/` has no `__init__.py` and pytest adds it to `sys.path`).

- [ ] **Step 1: Write the shared test doubles**

```python
# tests/graph_fakes.py
class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._results: dict[str, list] = {}

    def set_result(self, statement: str, records: list) -> None:
        self._results[statement] = records

    def run(self, statement: str, **params):
        self.calls.append((statement, params))
        return self._results.get(statement, [])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeDriver:
    def __init__(self):
        self.fake_session = FakeSession()

    def session(self):
        return self.fake_session


class FakeNode:
    def __init__(self, element_id: str, labels: list[str], properties: dict):
        self.element_id = element_id
        self.labels = labels
        self._properties = properties

    def items(self):
        return self._properties.items()

    def keys(self):
        return self._properties.keys()

    def __getitem__(self, key):
        return self._properties[key]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_graph_schema.py
from graph_fakes import FakeDriver

from scie.graph.schema import CONSTRAINTS, apply_constraints


def test_apply_constraints_runs_every_statement_in_order():
    driver = FakeDriver()

    apply_constraints(driver)

    ran_statements = [call[0] for call in driver.fake_session.calls]
    assert ran_statements == CONSTRAINTS
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_graph_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.graph.schema'`

- [ ] **Step 4: Write the implementation**

```python
# src/scie/graph/schema.py
CONSTRAINTS = [
    "CREATE CONSTRAINT repository_url IF NOT EXISTS FOR (r:Repository) REQUIRE r.url IS UNIQUE",
    "CREATE CONSTRAINT build_id IF NOT EXISTS FOR (b:Build) REQUIRE b.id IS UNIQUE",
    "CREATE CONSTRAINT commit_sha IF NOT EXISTS FOR (c:Commit) REQUIRE c.sha IS UNIQUE",
    "CREATE CONSTRAINT artifact_digest IF NOT EXISTS FOR (a:Artifact) REQUIRE a.digest IS UNIQUE",
    "CREATE CONSTRAINT package_purl IF NOT EXISTS FOR (p:Package) REQUIRE p.purl IS UNIQUE",
    "CREATE CONSTRAINT vulnerability_id IF NOT EXISTS FOR (v:VulnerabilityID) REQUIRE v.id IS UNIQUE",
    "CREATE INDEX build_start_time IF NOT EXISTS FOR (b:Build) ON (b.startTime)",
]


def apply_constraints(driver) -> None:
    with driver.session() as session:
        for statement in CONSTRAINTS:
            session.run(statement)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_graph_schema.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add src/scie/graph/schema.py tests/graph_fakes.py tests/test_graph_schema.py
git commit -m "feat: add Neo4j schema constraints"
```

---

### Task 4: Synthetic graph data generator

**Files:**
- Create: `src/scie/graph/synthetic_graph.py`
- Test: `tests/test_graph_synthetic.py`

**Interfaces:**
- Consumes: `FakeDriver` (Task 3, tests only).
- Produces: `SERVICE_NAMES`, `PACKAGE_CATALOG`, `VULNERABILITY_CATALOG`, `generate_synthetic_graph(driver, count=10, seed=None) -> None` from `scie.graph.synthetic_graph` — used by Task 5 (seed).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph_synthetic.py
from graph_fakes import FakeDriver

from scie.graph.synthetic_graph import VULNERABILITY_CATALOG, generate_synthetic_graph


def test_generates_one_repository_merge_per_count():
    driver = FakeDriver()

    generate_synthetic_graph(driver, count=5, seed=42)

    repo_merges = [
        call for call in driver.fake_session.calls
        if call[0].strip().startswith("MERGE (r:Repository")
    ]
    assert len(repo_merges) == 5


def test_same_seed_is_deterministic():
    first_driver = FakeDriver()
    generate_synthetic_graph(first_driver, count=5, seed=7)

    second_driver = FakeDriver()
    generate_synthetic_graph(second_driver, count=5, seed=7)

    assert first_driver.fake_session.calls == second_driver.fake_session.calls


def test_writes_a_vex_statement_for_every_catalog_vulnerability():
    driver = FakeDriver()

    generate_synthetic_graph(driver, count=5, seed=42)

    vuln_merges = [
        call for call in driver.fake_session.calls
        if call[0].strip().startswith("MERGE (v:VulnerabilityID")
    ]
    seen_vuln_ids = {call[1]["id"] for call in vuln_merges}
    expected_vuln_ids = {vuln_id for vuln_id, _purl in VULNERABILITY_CATALOG}
    assert seen_vuln_ids == expected_vuln_ids


def test_writes_at_least_one_vex_statement_create_per_vulnerability():
    driver = FakeDriver()

    generate_synthetic_graph(driver, count=5, seed=42)

    vex_creates = [
        call for call in driver.fake_session.calls
        if "CREATE (vex:VexStatement" in call[0]
    ]
    assert len(vex_creates) >= len(VULNERABILITY_CATALOG)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_synthetic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.graph.synthetic_graph'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/graph/synthetic_graph.py
import random
from datetime import datetime, timedelta, timezone

from neo4j import Driver

SERVICE_NAMES = [
    "billing-api",
    "auth-service",
    "notification-worker",
    "inventory-sync",
    "payments-gateway",
    "user-profile",
    "search-indexer",
    "audit-logger",
]

PACKAGE_CATALOG = [
    ("pkg:pypi/openssl@1.0.0", "openssl", "1.0.0"),
    ("pkg:pypi/requests@2.25.0", "requests", "2.25.0"),
    ("pkg:pypi/urllib3@1.26.0", "urllib3", "1.26.0"),
    ("pkg:pypi/jinja2@2.11.0", "jinja2", "2.11.0"),
    ("pkg:pypi/pyyaml@5.3.1", "pyyaml", "5.3.1"),
]

VULNERABILITY_CATALOG = [
    ("CVE-2025-1111", "pkg:pypi/openssl@1.0.0"),
    ("CVE-2025-2222", "pkg:pypi/requests@2.25.0"),
    ("CVE-2025-3333", "pkg:pypi/urllib3@1.26.0"),
]

VEX_ORIGINS = ["grype-scan", "vendor-vex-feed"]
VEX_STATUSES = ["affected", "affected", "not_affected", "fixed"]
ENVIRONMENTS = ["prod", "staging", "dev"]


def generate_synthetic_graph(driver: Driver, count: int = 10, seed: int | None = None) -> None:
    rng = random.Random(seed)
    with driver.session() as session:
        for i in range(count):
            _write_chain(session, rng, i)
        for vuln_id, purl in VULNERABILITY_CATALOG:
            _write_vex_statements(session, rng, vuln_id, purl)


def _write_chain(session, rng: random.Random, i: int) -> None:
    service_name = f"{rng.choice(SERVICE_NAMES)}-{i}"
    repo_url = f"https://github.com/example-org/{service_name}"
    commit_sha = f"synthetic{i:04d}"
    build_id = f"build-{i:04d}"
    digest = f"sha256:artifact{i:04d}"
    base_time = datetime.now(timezone.utc) - timedelta(hours=rng.randint(0, 72))

    session.run(
        "MERGE (r:Repository {url: $url}) SET r.name = $name",
        url=repo_url,
        name=service_name,
    )
    session.run(
        """
        MATCH (r:Repository {url: $repo_url})
        MERGE (b:Build {id: $build_id})
        SET b.startTime = $start_time, b.ciSystem = 'github-actions', b.status = 'success'
        MERGE (r)-[:HAS_BUILD]->(b)
        """,
        repo_url=repo_url,
        build_id=build_id,
        start_time=base_time.isoformat(),
    )
    session.run(
        """
        MATCH (b:Build {id: $build_id})
        MERGE (c:Commit {sha: $sha})
        SET c.author = $author, c.timestamp = $timestamp
        MERGE (b)-[:FOR_COMMIT]->(c)
        """,
        build_id=build_id,
        sha=commit_sha,
        author=rng.choice(["alice", "bob", "carol"]),
        timestamp=base_time.isoformat(),
    )
    session.run(
        """
        MATCH (b:Build {id: $build_id})
        MERGE (a:Artifact {digest: $digest})
        SET a.name = $name
        MERGE (b)-[:PRODUCED]->(a)
        """,
        build_id=build_id,
        digest=digest,
        name=service_name,
    )

    package_count = rng.choice([1, 1, 2, 3])
    for purl, name, version in rng.sample(PACKAGE_CATALOG, package_count):
        session.run(
            """
            MATCH (a:Artifact {digest: $digest})
            MERGE (p:Package {purl: $purl})
            SET p.name = $name, p.version = $version
            CREATE (dep:IsDependency {origin: 'synthetic-sbom'})
            CREATE (dep)-[:subject]->(a)
            CREATE (dep)-[:dependency]->(p)
            """,
            digest=digest,
            purl=purl,
            name=name,
            version=version,
        )

    if rng.random() < 0.7:
        environment = rng.choice(ENVIRONMENTS)
        session.run(
            """
            MATCH (a:Artifact {digest: $digest})
            CREATE (d:Deployment {
                cluster: 'scie', namespace: $environment, environment: $environment,
                deployed_at: $deployed_at
            })
            CREATE (a)-[:DEPLOYED_TO]->(d)
            """,
            digest=digest,
            environment=environment,
            deployed_at=(base_time + timedelta(minutes=8)).isoformat(),
        )


def _write_vex_statements(session, rng: random.Random, vuln_id: str, purl: str) -> None:
    session.run("MERGE (v:VulnerabilityID {id: $id})", id=vuln_id)

    statement_count = rng.choice([1, 1, 2])
    for _ in range(statement_count):
        session.run(
            """
            MATCH (p:Package {purl: $purl})
            MATCH (v:VulnerabilityID {id: $vuln_id})
            CREATE (vex:VexStatement {status: $status, origin: $origin})
            CREATE (vex)-[:subject]->(p)
            CREATE (vex)-[:vulnerability]->(v)
            """,
            purl=purl,
            vuln_id=vuln_id,
            status=rng.choice(VEX_STATUSES),
            origin=rng.choice(VEX_ORIGINS),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_synthetic.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/graph/synthetic_graph.py tests/test_graph_synthetic.py
git commit -m "feat: add synthetic graph data generator"
```

---

### Task 5: Graph seed CLI

**Files:**
- Create: `src/scie/graph/seed.py`
- Test: `tests/test_graph_seed.py`

**Interfaces:**
- Consumes: `get_driver` (Task 2); `apply_constraints` (Task 3); `generate_synthetic_graph` (Task 4).
- Produces: `main(count: int = 15) -> None` from `scie.graph.seed`, runnable as `python -m scie.graph.seed`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_seed.py
from graph_fakes import FakeDriver

import scie.graph.seed as seed


def test_main_applies_constraints_and_generates_graph(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(seed, "get_driver", lambda: driver)

    seed.main(count=3)

    ran_statements = [call[0] for call in driver.fake_session.calls]
    assert any(
        stmt.startswith("CREATE CONSTRAINT repository_url") for stmt in ran_statements
    )
    repo_merges = [s for s in ran_statements if s.strip().startswith("MERGE (r:Repository")]
    assert len(repo_merges) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph_seed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.graph.seed'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/graph/seed.py
from scie.graph.db import get_driver
from scie.graph.schema import apply_constraints
from scie.graph.synthetic_graph import generate_synthetic_graph


def main(count: int = 15) -> None:
    driver = get_driver()
    apply_constraints(driver)
    generate_synthetic_graph(driver, count=count)
    print(f"Seeded a synthetic graph with {count} repository chains.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph_seed.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/graph/seed.py tests/test_graph_seed.py
git commit -m "feat: add graph seed CLI"
```

---

### Task 6: Graph query layer

**Files:**
- Create: `src/scie/graph/queries.py`
- Test: `tests/test_graph_queries.py`

**Interfaces:**
- Consumes: `FakeDriver`, `FakeNode` (Task 3, tests only).
- Produces: `vuln_blast_radius(driver, vuln_id) -> dict`, `vuln_origin_trace(driver, vuln_id) -> dict`, `repo_build_history(driver, repo_url) -> dict`, `package_usage(driver, purl) -> dict`, `expand_neighbors(driver, node_label, key_prop, key_value) -> dict` from `scie.graph.queries` — each returns `{"nodes": [...], "edges": [...]}`. Used by Task 7 (routes).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph_queries.py
from graph_fakes import FakeDriver, FakeNode

from scie.graph import queries


def test_vuln_blast_radius_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.VULN_BLAST_RADIUS_QUERY, [])

    queries.vuln_blast_radius(driver, "CVE-2025-1111")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.VULN_BLAST_RADIUS_QUERY
    assert params == {"vuln_id": "CVE-2025-1111"}


def test_vuln_blast_radius_builds_nodes_and_edges_from_records():
    driver = FakeDriver()
    v = FakeNode("v1", ["VulnerabilityID"], {"id": "CVE-2025-1111"})
    vex = FakeNode("vex1", ["VexStatement"], {"status": "affected", "origin": "grype-scan"})
    p = FakeNode("p1", ["Package"], {"purl": "pkg:pypi/openssl@1.0.0"})
    dep = FakeNode("dep1", ["IsDependency"], {"origin": "synthetic-sbom"})
    a = FakeNode("a1", ["Artifact"], {"digest": "sha256:artifact0001"})
    d = FakeNode("d1", ["Deployment"], {"cluster": "scie", "environment": "prod"})
    driver.fake_session.set_result(
        queries.VULN_BLAST_RADIUS_QUERY,
        [{"v": v, "vex": vex, "p": p, "dep": dep, "a": a, "d": d}],
    )

    result = queries.vuln_blast_radius(driver, "CVE-2025-1111")

    node_ids = {node["element_id"] for node in result["nodes"]}
    assert node_ids == {"v1", "vex1", "p1", "dep1", "a1", "d1"}
    assert {"source": "vex1", "target": "v1", "type": "vulnerability"} in result["edges"]
    assert {"source": "vex1", "target": "p1", "type": "subject"} in result["edges"]
    assert {"source": "dep1", "target": "p1", "type": "dependency"} in result["edges"]
    assert {"source": "dep1", "target": "a1", "type": "subject"} in result["edges"]
    assert {"source": "a1", "target": "d1", "type": "DEPLOYED_TO"} in result["edges"]


def test_vuln_origin_trace_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.VULN_ORIGIN_TRACE_QUERY, [])

    queries.vuln_origin_trace(driver, "CVE-2025-1111")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.VULN_ORIGIN_TRACE_QUERY
    assert params == {"vuln_id": "CVE-2025-1111"}


def test_vuln_origin_trace_builds_nodes_and_edges_from_records():
    driver = FakeDriver()
    v = FakeNode("v1", ["VulnerabilityID"], {"id": "CVE-2025-1111"})
    vex = FakeNode("vex1", ["VexStatement"], {"status": "affected"})
    p = FakeNode("p1", ["Package"], {"purl": "pkg:pypi/openssl@1.0.0"})
    dep = FakeNode("dep1", ["IsDependency"], {"origin": "synthetic-sbom"})
    a = FakeNode("a1", ["Artifact"], {"digest": "sha256:artifact0001"})
    b = FakeNode("b1", ["Build"], {"id": "build-0001"})
    c = FakeNode("c1", ["Commit"], {"sha": "synthetic0001"})
    r = FakeNode("r1", ["Repository"], {"url": "https://github.com/example-org/billing-api-1"})
    driver.fake_session.set_result(
        queries.VULN_ORIGIN_TRACE_QUERY,
        [{"v": v, "vex": vex, "p": p, "dep": dep, "a": a, "b": b, "c": c, "r": r}],
    )

    result = queries.vuln_origin_trace(driver, "CVE-2025-1111")

    node_ids = {node["element_id"] for node in result["nodes"]}
    assert node_ids == {"v1", "vex1", "p1", "dep1", "a1", "b1", "c1", "r1"}
    assert {"source": "b1", "target": "a1", "type": "PRODUCED"} in result["edges"]
    assert {"source": "b1", "target": "c1", "type": "FOR_COMMIT"} in result["edges"]
    assert {"source": "r1", "target": "b1", "type": "HAS_BUILD"} in result["edges"]


def test_repo_build_history_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.REPO_BUILD_HISTORY_QUERY, [])

    queries.repo_build_history(driver, "https://github.com/example-org/billing-api-1")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.REPO_BUILD_HISTORY_QUERY
    assert params == {"repo_url": "https://github.com/example-org/billing-api-1"}


def test_repo_build_history_builds_nodes_and_edges_including_artifact_list():
    driver = FakeDriver()
    r = FakeNode("r1", ["Repository"], {"url": "https://github.com/example-org/billing-api-1"})
    b = FakeNode("b1", ["Build"], {"id": "build-0001"})
    a = FakeNode("a1", ["Artifact"], {"digest": "sha256:artifact0001"})
    driver.fake_session.set_result(
        queries.REPO_BUILD_HISTORY_QUERY,
        [{"r": r, "b": b, "artifacts": [a]}],
    )

    result = queries.repo_build_history(driver, "https://github.com/example-org/billing-api-1")

    node_ids = {node["element_id"] for node in result["nodes"]}
    assert node_ids == {"r1", "b1", "a1"}
    assert {"source": "r1", "target": "b1", "type": "HAS_BUILD"} in result["edges"]
    assert {"source": "b1", "target": "a1", "type": "PRODUCED"} in result["edges"]


def test_package_usage_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.PACKAGE_USAGE_QUERY, [])

    queries.package_usage(driver, "pkg:pypi/openssl@1.0.0")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.PACKAGE_USAGE_QUERY
    assert params == {"purl": "pkg:pypi/openssl@1.0.0"}


def test_package_usage_builds_nodes_and_edges_from_records():
    driver = FakeDriver()
    r = FakeNode("r1", ["Repository"], {"url": "https://github.com/example-org/billing-api-1"})
    b = FakeNode("b1", ["Build"], {"id": "build-0001"})
    a = FakeNode("a1", ["Artifact"], {"digest": "sha256:artifact0001"})
    p = FakeNode("p1", ["Package"], {"purl": "pkg:pypi/openssl@1.0.0"})
    dep = FakeNode("dep1", ["IsDependency"], {"origin": "synthetic-sbom"})
    driver.fake_session.set_result(
        queries.PACKAGE_USAGE_QUERY,
        [{"r": r, "b": b, "a": a, "p": p, "dep": dep}],
    )

    result = queries.package_usage(driver, "pkg:pypi/openssl@1.0.0")

    node_ids = {node["element_id"] for node in result["nodes"]}
    assert node_ids == {"r1", "b1", "a1", "p1", "dep1"}
    assert {"source": "r1", "target": "b1", "type": "HAS_BUILD"} in result["edges"]
    assert {"source": "b1", "target": "a1", "type": "PRODUCED"} in result["edges"]
    assert {"source": "dep1", "target": "a1", "type": "subject"} in result["edges"]
    assert {"source": "dep1", "target": "p1", "type": "dependency"} in result["edges"]


def test_expand_neighbors_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.EXPAND_NEIGHBORS_QUERY, [])

    queries.expand_neighbors(driver, "Package", "purl", "pkg:pypi/openssl@1.0.0")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.EXPAND_NEIGHBORS_QUERY
    assert params == {
        "node_label": "Package",
        "key_prop": "purl",
        "key_value": "pkg:pypi/openssl@1.0.0",
    }


def test_expand_neighbors_respects_relationship_direction():
    driver = FakeDriver()
    n = FakeNode("p1", ["Package"], {"purl": "pkg:pypi/openssl@1.0.0"})
    neighbor = FakeNode("dep1", ["IsDependency"], {"origin": "synthetic-sbom"})
    driver.fake_session.set_result(
        queries.EXPAND_NEIGHBORS_QUERY,
        [{"n": n, "rel_type": "dependency", "neighbor": neighbor, "rel_from_n": False}],
    )

    result = queries.expand_neighbors(driver, "Package", "purl", "pkg:pypi/openssl@1.0.0")

    assert {"source": "dep1", "target": "p1", "type": "dependency"} in result["edges"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_queries.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.graph.queries'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/graph/queries.py
from neo4j import Driver

VULN_BLAST_RADIUS_QUERY = """
MATCH (v:VulnerabilityID {id: $vuln_id})<-[:vulnerability]-(vex:VexStatement {status: 'affected'})-[:subject]->(p:Package)
MATCH (dep:IsDependency)-[:dependency]->(p)
MATCH (dep)-[:subject]->(a:Artifact)-[:DEPLOYED_TO]->(d:Deployment)
RETURN v, vex, p, dep, a, d
"""

VULN_ORIGIN_TRACE_QUERY = """
MATCH (v:VulnerabilityID {id: $vuln_id})<-[:vulnerability]-(vex:VexStatement {status: 'affected'})-[:subject]->(p:Package)
MATCH (dep:IsDependency)-[:dependency]->(p)
MATCH (dep)-[:subject]->(a:Artifact)
MATCH (b:Build)-[:PRODUCED]->(a)
MATCH (b)-[:FOR_COMMIT]->(c:Commit)
MATCH (r:Repository)-[:HAS_BUILD]->(b)
RETURN v, vex, p, dep, a, b, c, r
"""

REPO_BUILD_HISTORY_QUERY = """
MATCH (r:Repository {url: $repo_url})-[:HAS_BUILD]->(b:Build)
OPTIONAL MATCH (b)-[:PRODUCED]->(a:Artifact)
RETURN r, b, collect(a) AS artifacts
ORDER BY b.startTime DESC
"""

PACKAGE_USAGE_QUERY = """
MATCH (p:Package {purl: $purl})<-[:dependency]-(dep:IsDependency)-[:subject]->(a:Artifact)
MATCH (b:Build)-[:PRODUCED]->(a)
MATCH (r:Repository)-[:HAS_BUILD]->(b)
RETURN r, b, a, p, dep
"""

EXPAND_NEIGHBORS_QUERY = """
MATCH (n) WHERE $node_label IN labels(n) AND n[$key_prop] = $key_value
MATCH (n)-[rel]-(neighbor)
RETURN n, type(rel) AS rel_type, neighbor, startNode(rel) = n AS rel_from_n
"""


def _serialize_value(value):
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if hasattr(value, "labels") and hasattr(value, "items"):
        return {
            "element_id": value.element_id,
            "labels": list(value.labels),
            "properties": dict(value),
        }
    return value


def _run(driver: Driver, query: str, **params) -> list[dict]:
    with driver.session() as session:
        result = session.run(query, **params)
        return [
            {key: _serialize_value(value) for key, value in record.items()}
            for record in result
        ]


def vuln_blast_radius(driver: Driver, vuln_id: str) -> dict:
    records = _run(driver, VULN_BLAST_RADIUS_QUERY, vuln_id=vuln_id)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        v, vex, p, dep, a, d = (
            record["v"], record["vex"], record["p"],
            record["dep"], record["a"], record["d"],
        )
        for node in (v, vex, p, dep, a, d):
            nodes[node["element_id"]] = node
        edges.append({"source": vex["element_id"], "target": v["element_id"], "type": "vulnerability"})
        edges.append({"source": vex["element_id"], "target": p["element_id"], "type": "subject"})
        edges.append({"source": dep["element_id"], "target": p["element_id"], "type": "dependency"})
        edges.append({"source": dep["element_id"], "target": a["element_id"], "type": "subject"})
        edges.append({"source": a["element_id"], "target": d["element_id"], "type": "DEPLOYED_TO"})
    return {"nodes": list(nodes.values()), "edges": edges}


def vuln_origin_trace(driver: Driver, vuln_id: str) -> dict:
    records = _run(driver, VULN_ORIGIN_TRACE_QUERY, vuln_id=vuln_id)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        v, vex, p, dep, a, b, c, r = (
            record["v"], record["vex"], record["p"], record["dep"],
            record["a"], record["b"], record["c"], record["r"],
        )
        for node in (v, vex, p, dep, a, b, c, r):
            nodes[node["element_id"]] = node
        edges.append({"source": vex["element_id"], "target": v["element_id"], "type": "vulnerability"})
        edges.append({"source": vex["element_id"], "target": p["element_id"], "type": "subject"})
        edges.append({"source": dep["element_id"], "target": p["element_id"], "type": "dependency"})
        edges.append({"source": dep["element_id"], "target": a["element_id"], "type": "subject"})
        edges.append({"source": b["element_id"], "target": a["element_id"], "type": "PRODUCED"})
        edges.append({"source": b["element_id"], "target": c["element_id"], "type": "FOR_COMMIT"})
        edges.append({"source": r["element_id"], "target": b["element_id"], "type": "HAS_BUILD"})
    return {"nodes": list(nodes.values()), "edges": edges}


def repo_build_history(driver: Driver, repo_url: str) -> dict:
    records = _run(driver, REPO_BUILD_HISTORY_QUERY, repo_url=repo_url)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        r, b, artifacts = record["r"], record["b"], record["artifacts"]
        nodes[r["element_id"]] = r
        nodes[b["element_id"]] = b
        edges.append({"source": r["element_id"], "target": b["element_id"], "type": "HAS_BUILD"})
        for artifact in artifacts:
            nodes[artifact["element_id"]] = artifact
            edges.append({"source": b["element_id"], "target": artifact["element_id"], "type": "PRODUCED"})
    return {"nodes": list(nodes.values()), "edges": edges}


def package_usage(driver: Driver, purl: str) -> dict:
    records = _run(driver, PACKAGE_USAGE_QUERY, purl=purl)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        r, b, a, p, dep = record["r"], record["b"], record["a"], record["p"], record["dep"]
        for node in (r, b, a, p, dep):
            nodes[node["element_id"]] = node
        edges.append({"source": r["element_id"], "target": b["element_id"], "type": "HAS_BUILD"})
        edges.append({"source": b["element_id"], "target": a["element_id"], "type": "PRODUCED"})
        edges.append({"source": dep["element_id"], "target": a["element_id"], "type": "subject"})
        edges.append({"source": dep["element_id"], "target": p["element_id"], "type": "dependency"})
    return {"nodes": list(nodes.values()), "edges": edges}


def expand_neighbors(driver: Driver, node_label: str, key_prop: str, key_value: str) -> dict:
    records = _run(
        driver, EXPAND_NEIGHBORS_QUERY,
        node_label=node_label, key_prop=key_prop, key_value=key_value,
    )
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        n, neighbor = record["n"], record["neighbor"]
        nodes[n["element_id"]] = n
        nodes[neighbor["element_id"]] = neighbor
        source, target = (n, neighbor) if record["rel_from_n"] else (neighbor, n)
        edges.append({
            "source": source["element_id"],
            "target": target["element_id"],
            "type": record["rel_type"],
        })
    return {"nodes": list(nodes.values()), "edges": edges}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_queries.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/graph/queries.py tests/test_graph_queries.py
git commit -m "feat: add graph query layer"
```

---

### Task 7: FastAPI graph routes

**Files:**
- Create: `src/scie/api/graph_routes.py`
- Modify: `src/scie/api/app.py`
- Test: `tests/test_graph_routes.py`

**Interfaces:**
- Consumes: `get_driver` (Task 2); `vuln_blast_radius`, `vuln_origin_trace`, `repo_build_history`, `package_usage`, `expand_neighbors` (Task 6).
- Produces: `router: APIRouter` from `scie.api.graph_routes`, mounted into the existing `app` — routes `GET /graph/vulnerabilities/{vuln_id}/blast-radius`, `GET /graph/vulnerabilities/{vuln_id}/origin`, `GET /graph/repositories/{repo_url:path}/history`, `GET /graph/packages/{purl:path}/usage`, `GET /graph/expand/{node_label}/{key_prop}/{key_value:path}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph_routes.py
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from scie.api import graph_routes
from scie.api.app import app


def test_vuln_blast_radius_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "vuln_blast_radius",
        lambda driver, vuln_id: {"nodes": [{"element_id": vuln_id}], "edges": []},
    )
    client = TestClient(app)

    response = client.get("/graph/vulnerabilities/CVE-2025-1111/blast-radius")

    assert response.status_code == 200
    assert response.json() == {"nodes": [{"element_id": "CVE-2025-1111"}], "edges": []}


def test_vuln_origin_trace_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "vuln_origin_trace",
        lambda driver, vuln_id: {"nodes": [], "edges": []},
    )
    client = TestClient(app)

    response = client.get("/graph/vulnerabilities/CVE-2025-1111/origin")

    assert response.status_code == 200
    assert response.json() == {"nodes": [], "edges": []}


def test_repo_build_history_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "repo_build_history",
        lambda driver, repo_url: {"nodes": [], "edges": [], "repo_url": repo_url},
    )
    client = TestClient(app)

    response = client.get(
        "/graph/repositories/https://github.com/example-org/billing-api-1/history"
    )

    assert response.status_code == 200
    assert response.json()["repo_url"] == "https://github.com/example-org/billing-api-1"


def test_package_usage_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "package_usage",
        lambda driver, purl: {"nodes": [], "edges": [], "purl": purl},
    )
    client = TestClient(app)

    response = client.get("/graph/packages/pkg:pypi/openssl@1.0.0/usage")

    assert response.status_code == 200
    assert response.json()["purl"] == "pkg:pypi/openssl@1.0.0"


def test_expand_neighbors_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "expand_neighbors",
        lambda driver, node_label, key_prop, key_value: {
            "nodes": [], "edges": [], "args": [node_label, key_prop, key_value],
        },
    )
    client = TestClient(app)

    response = client.get("/graph/expand/Package/purl/pkg:pypi/openssl@1.0.0")

    assert response.status_code == 200
    assert response.json()["args"] == ["Package", "purl", "pkg:pypi/openssl@1.0.0"]


def test_vuln_blast_radius_route_returns_503_when_graph_db_unavailable(monkeypatch):
    def raise_unavailable(driver, vuln_id):
        raise ServiceUnavailable("down")

    monkeypatch.setattr(graph_routes.queries, "vuln_blast_radius", raise_unavailable)
    client = TestClient(app)

    response = client.get("/graph/vulnerabilities/CVE-2025-1111/blast-radius")

    assert response.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_routes.py -v`
Expected: FAIL with 404 on every route (router doesn't exist / isn't mounted yet)

- [ ] **Step 3: Write the implementation**

```python
# src/scie/api/graph_routes.py
from fastapi import APIRouter, HTTPException
from neo4j.exceptions import ServiceUnavailable

from scie.graph import queries
from scie.graph.db import get_driver

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/vulnerabilities/{vuln_id}/blast-radius")
def get_vuln_blast_radius(vuln_id: str) -> dict:
    try:
        return queries.vuln_blast_radius(get_driver(), vuln_id)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/vulnerabilities/{vuln_id}/origin")
def get_vuln_origin_trace(vuln_id: str) -> dict:
    try:
        return queries.vuln_origin_trace(get_driver(), vuln_id)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/repositories/{repo_url:path}/history")
def get_repo_build_history(repo_url: str) -> dict:
    try:
        return queries.repo_build_history(get_driver(), repo_url)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/packages/{purl:path}/usage")
def get_package_usage(purl: str) -> dict:
    try:
        return queries.package_usage(get_driver(), purl)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/expand/{node_label}/{key_prop}/{key_value:path}")
def get_expand_neighbors(node_label: str, key_prop: str, key_value: str) -> dict:
    try:
        return queries.expand_neighbors(get_driver(), node_label, key_prop, key_value)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")
```

Add to `src/scie/api/app.py`, after the existing imports:

```python
from scie.api.graph_routes import router as graph_router
```

Add after `app = FastAPI(title="Supply Chain Insights Engine")`:

```python
app.include_router(graph_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_routes.py -v`
Expected: 6 passed

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (v1's existing tests plus every graph test added so far)

- [ ] **Step 6: Commit**

```bash
git add src/scie/api/graph_routes.py src/scie/api/app.py tests/test_graph_routes.py
git commit -m "feat: add FastAPI graph query routes"
```

---

### Task 8: Streamlit Graph Explorer page and README update

**Files:**
- Create: `src/scie/ui/pages/1_Graph_Explorer.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `GET /graph/vulnerabilities/{vuln_id}/blast-radius`, `GET /graph/packages/{purl}/usage`, `GET /graph/repositories/{repo_url}/history`, `GET /graph/expand/{node_label}/{key_prop}/{key_value}` (Task 7, over HTTP).
- Produces: a "Graph Explorer" page, auto-discovered by Streamlit as a sibling of `streamlit_app.py`'s `pages/` directory — no code changes to `streamlit_app.py` itself.

This task has no automated test — it's a UI page consumed interactively. Verify it by running the stack (Step 4).

- [ ] **Step 1: Write the Streamlit page**

```python
# src/scie/ui/pages/1_Graph_Explorer.py
import os

import requests
import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

API_URL = os.environ.get("SCIE_API_URL", "http://localhost:8000")

NODE_COLORS = {
    "Repository": "#4C72B0",
    "Build": "#55A868",
    "Commit": "#C44E52",
    "Artifact": "#8172B2",
    "Package": "#CCB974",
    "VulnerabilityID": "#DA3B3B",
    "VexStatement": "#64B5CD",
    "IsDependency": "#B0B0B0",
    "Deployment": "#8C8C8C",
}

KEY_PROP_BY_LABEL = {
    "Repository": "url",
    "Build": "id",
    "Commit": "sha",
    "Artifact": "digest",
    "Package": "purl",
    "VulnerabilityID": "id",
    "Deployment": "cluster",
}

st.set_page_config(page_title="Graph Explorer", layout="wide")
st.title("Graph Explorer")

if "graph_nodes" not in st.session_state:
    st.session_state.graph_nodes = {}
    st.session_state.graph_edges = {}


def _absorb(result: dict) -> None:
    for node in result["nodes"]:
        st.session_state.graph_nodes[node["element_id"]] = node
    for edge in result["edges"]:
        key = (edge["source"], edge["target"], edge["type"])
        st.session_state.graph_edges[key] = edge


mode = st.selectbox("Search by", ["Vulnerability ID", "Package PURL", "Repository URL"])
query_value = st.text_input("Value")

if st.button("Search") and query_value:
    if mode == "Vulnerability ID":
        response = requests.get(
            f"{API_URL}/graph/vulnerabilities/{query_value}/blast-radius", timeout=10
        )
    elif mode == "Package PURL":
        response = requests.get(f"{API_URL}/graph/packages/{query_value}/usage", timeout=10)
    else:
        response = requests.get(
            f"{API_URL}/graph/repositories/{query_value}/history", timeout=10
        )
    response.raise_for_status()
    _absorb(response.json())

if st.session_state.graph_nodes:
    nodes = [
        Node(
            id=element_id,
            label=node["labels"][0],
            color=NODE_COLORS.get(node["labels"][0], "#999999"),
        )
        for element_id, node in st.session_state.graph_nodes.items()
    ]
    edges = [
        Edge(source=edge["source"], target=edge["target"], label=edge["type"])
        for edge in st.session_state.graph_edges.values()
    ]
    config = Config(width=1000, height=600, directed=True, physics=True)
    clicked_id = agraph(nodes=nodes, edges=edges, config=config)

    if clicked_id and clicked_id in st.session_state.graph_nodes:
        clicked_node = st.session_state.graph_nodes[clicked_id]
        label = clicked_node["labels"][0]
        st.subheader(label)
        st.json(clicked_node["properties"])

        key_prop = KEY_PROP_BY_LABEL.get(label)
        if key_prop and key_prop in clicked_node["properties"]:
            if st.button(f"Expand {label}"):
                key_value = clicked_node["properties"][key_prop]
                response = requests.get(
                    f"{API_URL}/graph/expand/{label}/{key_prop}/{key_value}", timeout=10
                )
                response.raise_for_status()
                _absorb(response.json())
                st.rerun()
else:
    st.info("No graph data loaded yet — run a search above.")
```

- [ ] **Step 2: Update the README**

In `README.md`, replace the "Running Locally" section's code block and following line:

```
docker compose up -d
docker compose exec api uv run python -m scie.seed
```

Then open the dashboard at `http://localhost:8501` (API at `http://localhost:8000`).
```

with:

```
docker compose up -d
docker compose exec api uv run python -m scie.seed
docker compose exec api uv run python -m scie.graph.seed
```

Then open the dashboard at `http://localhost:8501` (API at `http://localhost:8000`) — the
"Graph Explorer" page is in the sidebar. Neo4j Browser is available directly at
`http://localhost:7474` (user `neo4j`, password `devpassword`) for sanity-checking the
seeded graph.
```

- [ ] **Step 3: Bring up the stack and seed both datasets**

Run:
```bash
docker compose up -d
docker compose exec api uv run python -m scie.seed
docker compose exec api uv run python -m scie.graph.seed
```
Expected: all containers start; both seed commands print a success message with no errors.

- [ ] **Step 4: Manually verify the Graph Explorer page**

Open `http://localhost:8501`, go to the "Graph Explorer" page. Search by "Package PURL" for
`pkg:pypi/openssl@1.0.0` (from `PACKAGE_CATALOG` in `synthetic_graph.py`).
Expected: a graph renders with `Repository`, `Build`, `Artifact`, `Package`, and `IsDependency`
nodes connected by labeled edges. Click a node — its properties appear below the graph, and
(for node types with a natural key) an "Expand" button appears; clicking it pulls in that
node's direct neighbors and re-renders.

Then search by "Vulnerability ID" for `CVE-2025-1111`.
Expected: a graph renders showing which `Package`/`Artifact`/`Deployment` combinations are
affected — some deployments may not appear if none of that CVE's affected packages happen to
be deployed in this run (seed data is randomized per run unless a `seed=` is passed).

- [ ] **Step 5: Run the full test suite one more time**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/scie/ui/pages/1_Graph_Explorer.py README.md
git commit -m "feat: add clickable Graph Explorer dashboard page"
```

---

## Self-Review Notes

- **Spec coverage:** §3 schema → Tasks 3–4; §4 components → Tasks 1–2, 5–8; §5 query set → Task 6; §6 visualization → Task 8; §7 error handling/testing → Tasks 6–7 (mocked-driver unit tests, 503 on `ServiceUnavailable`); §8 relation to v1 → enforced via Global Constraints (independent generator, no shared state with `scie.seed`/`scie.synthetic`).
- **Type consistency:** every query function in Task 6 returns `{"nodes": [...], "edges": [...]}`; Task 7's routes return that dict unchanged; Task 8's Streamlit page consumes exactly that shape (`result["nodes"]`, `result["edges"]`, each node's `element_id`/`labels`/`properties`, each edge's `source`/`target`/`type`) with no transformation in between — confirmed consistent across all three tasks.
- **IsDependency/VexStatement direction:** fixed during spec self-review (see `99fe0d6`) to have the attestation node as the source of both its edges; Tasks 4 and 6 both use the corrected direction consistently.
