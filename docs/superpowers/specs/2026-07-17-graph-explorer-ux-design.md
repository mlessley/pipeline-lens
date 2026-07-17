# Graph Explorer UX Redesign — Design

## 1. Purpose

The Graph Explorer shipped in `docs/superpowers/specs/2026-07-16-graph-explorer-design.md`
was explicitly scoped as a learning-tool baseline: one free-text search box, one
generic force-directed graph for all four query types, node labels showing the
Neo4j entity type rather than an identifying property, and a raw `st.json` dump
as the node detail panel. That bar has been cleared — running it against a live
Neo4j surfaced the gap directly: every node on the canvas reads "Package" or
"Build" instead of anything you could recognize, results render as a physics-
simulated blob regardless of what question was asked, and clicking a node is a
dead end (a JSON blob) rather than a way to keep exploring.

This spec redesigns the presentation layer to feel like a real investigative
tool — closer to how GUAC's own visualizer (`guacsec/guac-visualizer`) presents
comparable supply-chain graph data: real identifying labels, tree-shaped layouts
scoped to the question asked, attestation relationships collapsed to edge labels
instead of cluttering the canvas with extra nodes, and a detail panel that lets
you jump to a different view instead of stopping.

This is presentation and data-realism work only. It does not touch the Cypher
query layer (`src/scie/graph/queries.py`), the graph schema, or the synthetic
generator's structure — see §7 for what stays out of scope.

## 2. Scope

**In scope:**
- Replace the free-text search box with a dropdown per search mode, backed by
  three new list endpoints
- Purpose-built rendering per query type instead of one generic graph:
  hierarchical tree layout for blast-radius/origin-trace/package-usage, a plain
  table for repository build history
- Collapse attestation nodes (`VexStatement`, `IsDependency`) to edge labels at
  render time only — the Neo4j data model is unchanged
- Real identifying labels on every rendered node (extend `KEY_PROP_BY_LABEL`)
- Redesign the node detail panel: friendly labeled fields instead of raw JSON,
  plus "lens" buttons that jump to a different view centered on the clicked node
- Swap the three fake `CVE-2025-XXXX` IDs in the synthetic generator's
  vulnerability catalog for real, historical CVE IDs matching the (already-real)
  package names/versions they're attached to

**Out of scope (deferred):**
- Any change to `queries.py`'s Cypher or the `{nodes, edges}` return shape
- Any change to the Neo4j schema or `synthetic_graph.py`'s structure/relationships
- Real GitHub ingestion for user-supplied repositories (raised separately —
  remains its own, larger future project)
- A custom React/cytoscape.js frontend — staying in Streamlit + `streamlit_agraph`
  per the earlier trade-off discussion; this spec's job is to get as close to the
  GUAC feel as that stack reasonably allows, not to rebuild the frontend
- Fixing the vis-network double-click stuck-drag cosmetic quirk (already
  identified, deferred as low-priority polish)

## 3. Search UX

Replace the current `st.text_input("Value")` with a dropdown (`st.selectbox`)
whose options are fetched from the API when the mode changes:

```
GET /graph/packages       -> [{"purl": ..., "name": ...}, ...]
GET /graph/vulnerabilities -> [{"id": ...}, ...]
GET /graph/repositories    -> [{"url": ..., "name": ...}, ...]
```

Each is a single flat Cypher query (`MATCH (p:Package) RETURN p.purl, p.name`
etc.) exposed as a new thin FastAPI route alongside the existing `/graph/*`
routes — no new query-layer abstraction, consistent with how the existing four
queries are hand-written functions.

GUAC's visualizer uses a cascading dropdown chain (type → namespace → name →
version) because its package coordinate model has that hierarchy. Our synthetic
model doesn't — PURLs, vuln IDs, and repo URLs are each already a single atomic
identifier — so one dropdown per mode is the right level of fidelity, not a
manufactured hierarchy to imitate the source of inspiration.

## 4. Per-Mode Rendering

### 4.1 Blast radius / origin trace / package usage → hierarchical graph

All three already return a DAG-shaped `{nodes, edges}` result (chain or tree,
never cyclic). Switch `Config` from the current force-directed default to:

```python
Config(directed=True, hierarchical=True, direction="LR", physics=False)
```

`hierarchical` and `direction` are real fields on `streamlit_agraph.Config`
(confirmed by reading the installed package — not assumed), backed by
vis-network's native hierarchical layout engine. No custom layout code needed.

**Attestation collapsing:** before building the `agraph` node/edge lists, any
node whose label is `VexStatement` or `IsDependency` is removed from the node
list; its two outgoing edges (`subject`, plus `dependency`/`vulnerability`) are
merged into a single edge directly connecting the attestation's two neighbors,
labeled with the attestation type and its distinguishing property (e.g.
`CertifyVuln (affected)` for a `VexStatement` with `status=affected`, `DependsOn`
for `IsDependency`). This is a pure rendering-layer transform in
`1_Graph_Explorer.py` — `queries.py` and the Neo4j data are untouched, so the
attestation-as-node pattern the schema deliberately chose (§3 of the prior spec)
is preserved in the data even though the UI no longer draws it as a node.

**Node labels:** add a separate `DISPLAY_LABEL_BY_LABEL` mapping (canvas text
only, distinct from `KEY_PROP_BY_LABEL`) covering every label that can appear
post-collapsing, e.g. `Deployment` → `f"{cluster}/{namespace}"`, `Commit` →
first 7 chars of `sha`. This is intentionally kept separate from
`KEY_PROP_BY_LABEL`, which the Expand button uses as a *unique* lookup key —
`fe429d8` already fixed a bug where `Deployment.cluster` was used there and
wasn't unique enough for that purpose. Display text has no uniqueness
requirement, so it can combine fields freely; every node on screen shows an
identifying value, never a bare type name.

### 4.2 Repository build history → table, not a graph

`repo_build_history` already returns a naturally tabular shape (one row per
build, artifacts nested). Render with `st.dataframe`: columns for build date
(descending), CI system, a ✅/❌ status glyph, and a comma-joined artifact name
list. No `agraph` call in this mode at all — this was never a good fit for a
node-link diagram, and GUAC doesn't force build/provenance history into its
graph view either.

## 5. Detail Panel

Clicking a node in a graph-based view (4.1's three modes) replaces the current
`st.json(clicked_node["properties"])` dump with:

- A friendly labeled field list (property name → value, skipping internal-only
  fields), rendered with `st.write`/markdown rather than a raw JSON tree
- Context-appropriate **lens buttons** based on the clicked node's label,
  mirroring GUAC's Vulnerabilities/SBOM/SLSA buttons but mapped onto our own
  four queries:
  - `Package` → **Show usage** (re-runs `package_usage` centered on this node,
    replaces the current view)
  - `VulnerabilityID` → **Blast radius** and **Origin trace** buttons
  - `Repository` → **Build history**
  - Any node with a key prop in `KEY_PROP_BY_LABEL` keeps the existing
    **Expand** button (calls `expand_neighbors`, merges into the current view)

Lens buttons *replace* the current graph_nodes/graph_edges session state with a
fresh query result (a new investigation), while Expand *merges* into it (growing
the current one) — same distinction as today, just exposed on more node types.

## 6. Data Realism

`synthetic_graph.py`'s `PACKAGE_CATALOG` is already real-looking
(`openssl`, `requests`, `urllib3`, `jinja2`, `pyyaml` with real version
strings) — no change needed. Only `VULNERABILITY_CATALOG`'s three IDs are
obviously synthetic (`CVE-2025-1111/2222/3333`). Replace with real, well-known
historical CVEs tied to those same packages/versions, e.g. `CVE-2014-0160`
(Heartbleed) for `openssl@1.0.0`, plus one real CVE each for the `requests` and
`urllib3` entries already in the catalog. `example-org/*` repo, build, and
commit data stays as clearly-synthetic infrastructure — a raw CVE ID is what
reads as fake or real at a glance, a repo named `inventory-sync-13` doesn't
carry the same "is this a real vulnerability" credibility signal.

## 7. Error Handling & Testing

Same PoC-grade bar as the original slice — no new retry/validation logic.

- The three new list endpoints follow the existing `queries.py` pattern
  (hand-written Cypher, mocked-driver unit tests, no live Neo4j required for
  `pytest`) — same bar as the four existing query functions.
- The attestation-collapsing transform and table rendering are pure Python
  functions over already-tested API response shapes; give them unit tests with
  a fixed `{nodes, edges}` fixture rather than relying on Streamlit's own
  runtime.
- Final validation is manual against the live docker-compose Neo4j + dashboard,
  same as the original slice — this is where the "does it actually look right"
  judgment call has to happen, a unit test can't verify visual layout.

## 8. Relation to Prior Work

This redesigns presentation only. `docs/superpowers/specs/2026-07-16-graph-explorer-design.md`
remains the authoritative reference for the graph schema, the Cypher query set,
and the Neo4j/FastAPI/Streamlit component wiring — none of that changes here.
Real ingestion, the Postgres migration, and `BuildCompletenessWorkflow` (full
Phase 2 scope, `docs/phase2-graph-model.md`) remain untouched and out of scope,
as does building a dedicated React frontend.
