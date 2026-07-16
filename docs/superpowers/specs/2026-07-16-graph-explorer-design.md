# Graph Explorer — Design

## 1. Purpose

Phase 2 (`docs/phase2-graph-model.md`) lays out a full graph model for supply-chain
data (SBOM, SARIF, provenance, VEX) plus a real ingestion architecture, but that's
a large amount of surface to build before any of it is tangible. This spec scopes
a first, self-contained slice: stand up Neo4j, populate it with synthetic but
schema-faithful data, write real Cypher against it, and put a clickable
visualization on top — so the graph model becomes something to work with directly
rather than something read about in a design doc.

Real SBOM/SARIF/provenance ingestion, the Postgres migration, and the
`BuildCompletenessWorkflow` all remain scoped to later phases (see §7).

## 2. Scope

**In scope:**
- Neo4j running locally via Docker Compose
- A synthetic data generator that writes directly into Neo4j using the schema
  below (independent of the v1 SQLite `PipelineRun` data — no coupling between
  the two)
- Four named Cypher queries covering: vuln-in-prod, vuln-origin-trace,
  repo build history, package usage — plus one generic neighbor-expansion query
- FastAPI routes exposing those queries as JSON
- A new "Graph Explorer" page in the existing Streamlit dashboard: search,
  render results as a clickable graph, click a node to expand its neighbors
- Unit tests for the query layer using a mocked Neo4j driver/session

**Out of scope (deferred to a later phase):**
- Real SBOM (CycloneDX) / SARIF / in-toto provenance parsing and ingestion
- The `IngestArtifact` Temporal workflow and OCI-referrers / code-scanning-API
  watchers described in design doc §6
- The `BuildCompletenessWorkflow` (design doc §7)
- Migrating the relational store from SQLite to Postgres (design doc §6.5) —
  not needed yet since there's no ingestion ledger to write in this slice
- Monorepo component-level history (design doc §5.4)

## 3. Graph Schema

A trimmed subset of the full design doc's model, keeping the attestation-as-node
pattern (GUAC's core idea) rather than flattening it away:

```
(:Repository {url, name})
  -[:HAS_BUILD]->(:Build {id, startTime, ciSystem, status})
     -[:FOR_COMMIT]->(:Commit {sha, author, timestamp})
     -[:PRODUCED]->(:Artifact {digest, name})
        -[:DEPLOYED_TO]->(:Deployment {cluster, namespace, environment, deployed_at})

(:IsDependency {origin})-[:subject]->(:Artifact)
(:IsDependency {origin})-[:dependency]->(:Package {purl, name, version})

(:VexStatement {status, origin})-[:subject]->(:Package)
(:VexStatement {status, origin})-[:vulnerability]->(:VulnerabilityID {id})
```

Both `IsDependency` and `VexStatement` are attestation nodes: the attestation is always the *source* of its edges (`-[:subject]->` the thing it's about, plus one more edge naming the relationship) — never the target. This is the consistent GUAC convention from the design doc, applied uniformly rather than flipped per-edge.

`VexStatement.status` (`affected` / `not_affected` / `fixed`) is the field that
actually answers "is this exposed right now" — the same package+CVE pairing can
be triaged differently in different contexts, which is the reason this needs to
be a graph rather than a flat table. The synthetic generator produces a mix of
statuses so that distinction shows up in real query results.

**Constraints/indexes** (applied by `schema.py`):
- Uniqueness: `Repository.url`, `Artifact.digest`, `Package.purl`, `VulnerabilityID.id`
- Range index: `Build.startTime`, `Commit.sha`

## 4. Components & Data Flow

```
docker-compose.yml
  + neo4j service (neo4j:5-community; bolt on :7687, browser UI on :7474)

src/scie/graph/
  ├── __init__.py
  ├── schema.py           # apply_constraints(driver)
  ├── synthetic_graph.py  # generate_synthetic_graph(driver, count, seed) — MERGEs
  │                        #   nodes/edges per the schema above, deterministic
  │                        #   like v1's synthetic.py
  ├── queries.py           # named functions, one hand-written Cypher query each
  └── seed.py              # CLI entrypoint: apply_constraints() + generate_synthetic_graph()

src/scie/api/graph_routes.py   # new FastAPI router, mounted into the existing app
src/scie/ui/graph_explorer.py  # new Streamlit page (streamlit-agraph)
```

`docker compose exec api uv run python -m scie.graph.seed` populates Neo4j the
same way `python -m scie.seed` populates SQLite today. The FastAPI graph router
calls `queries.py` functions directly — no store/ORM layer between the route and
the Cypher. Streamlit calls the API and renders the returned nodes/edges with
`streamlit-agraph`.

The package stays named `scie` throughout (matches existing imports,
`docker-compose.yml` commands, CI, and Terraform) — "Pipeline Lens" remains the
outward-facing/repo-level brand only, established at the `65a735a` rebrand.

## 5. Query Set

Four scenario queries, each a single named function wrapping one hand-written
Cypher query — no query-builder abstraction in between:

```cypher
-- vuln_blast_radius(vuln_id): "do we have this vuln in prod"
MATCH (:VulnerabilityID {id: $vuln_id})<-[:vulnerability]-(vex:VexStatement {status: 'affected'})-[:subject]->(p:Package)
MATCH (dep:IsDependency)-[:dependency]->(p)
MATCH (dep)-[:subject]->(a:Artifact)-[:DEPLOYED_TO]->(d:Deployment)
RETURN d, a, p, vex

-- vuln_origin_trace(vuln_id): trace back through the Build that produced the artifact
MATCH (:VulnerabilityID {id: $vuln_id})<-[:vulnerability]-(:VexStatement {status: 'affected'})-[:subject]->(p:Package)
MATCH (dep:IsDependency)-[:dependency]->(p)
MATCH (dep)-[:subject]->(a:Artifact)
MATCH (b:Build)-[:PRODUCED]->(a)
MATCH (b)-[:FOR_COMMIT]->(c:Commit)
MATCH (r:Repository)-[:HAS_BUILD]->(b)
RETURN r, b, c, a, p

-- repo_build_history(repo_url): per design doc §5.3
MATCH (r:Repository {url: $repo_url})-[:HAS_BUILD]->(b:Build)
OPTIONAL MATCH (b)-[:PRODUCED]->(a:Artifact)
RETURN b.startTime, b.ciSystem, b.status, collect(a) AS artifacts
ORDER BY b.startTime DESC

-- package_usage(purl): which builds/artifacts pull in this package
MATCH (p:Package {purl: $purl})<-[:dependency]-(dep:IsDependency)-[:subject]->(a:Artifact)
MATCH (b:Build)-[:PRODUCED]->(a)
MATCH (r:Repository)-[:HAS_BUILD]->(b)
RETURN r, b, a, p
```

Plus one generic supporting query, not tied to a specific scenario:

```cypher
-- expand_neighbors(node_label, key_prop, key_value): everything directly
-- connected to one node
MATCH (n) WHERE n[$key_prop] = $key_value AND $node_label IN labels(n)
MATCH (n)-[rel]-(neighbor)
RETURN n, rel, neighbor
```

`expand_neighbors` is what makes the visualization actually clickable rather
than four fixed reports — clicking any node in a result calls it, and the
returned nodes/edges get merged into the current view.

## 6. Visualization

New "Graph Explorer" page in the existing Streamlit dashboard:

- Search bar with a mode selector: Vulnerability ID / Package PURL / Repository URL
- Running a search calls the matching `/graph/...` route and renders the result
  as an `agraph()`, with nodes colored/shaped by label (Repository, Build,
  Commit, Artifact, Package, VulnerabilityID, VexStatement, Deployment each get
  a distinct color) and edges labeled by relationship type
- Clicking a node calls `GET /graph/expand/{label}/{key}/{value}`
  (`expand_neighbors`), merges the new nodes/edges into Streamlit session state,
  and re-renders — this is the drill-down interaction
- A side panel shows the clicked node's raw properties as a plain dict dump —
  sufficient for a learning tool, no dedicated property inspector needed

## 7. Error Handling & Testing

Same PoC-grade bar as v1 — no retry/validation beyond what's needed. Neo4j
connection errors surface as a 503 from the FastAPI graph routes rather than
being swallowed.

Tests follow the same pattern v1 uses for `activities.py` (mocking boto3/k8s
clients instead of hitting real AWS): `queries.py` functions get unit tests
against a mocked Neo4j driver/session, verifying the right Cypher text and
parameters are sent and that results get shaped correctly. No live Neo4j
instance is required for `pytest`. End-to-end correctness against real data is
verified manually via the docker-compose Neo4j instance — Neo4j Browser is
useful for sanity-checking the seeded graph before trusting the API/viz layer.

## 8. Relation to v1

The graph dataset is entirely independent of the v1 SQLite `PipelineRun` data —
different generator, different service names, no shared identifiers. This
avoids coupling two systems before the graph model itself is proven out. SQLite
remains the v1 store as-is; the design doc's Postgres migration (§6.5) is
deferred to whenever real ingestion (ledger writes) actually needs it.
