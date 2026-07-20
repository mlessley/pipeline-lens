# Graph Subsystem Map

A guide to where graph-related code and docs live in this repo. Written as
a navigation aid, not a design doc — update it when files move, don't treat
it as the source of truth for *why* something works the way it does (the
specs in `docs/superpowers/specs/` are that).

## Schema

Neo4j has no enforced schema file the way SQL/GraphQL would — node
labels/properties/relationship types are implicit in whatever Cypher the
writers below actually run. The two places that come closest to "the
schema":

- **`src/scie/graph/schema.py`** — `apply_constraints(driver)`: the only
  *enforced* schema — uniqueness constraints on `Repository.url`,
  `Build.id`, `Commit.sha`, `Artifact.digest`, `Package.purl`,
  `VulnerabilityID.id`, plus a range index on `Build.startTime`.
- **`docs/superpowers/specs/2026-07-16-graph-explorer-design.md` §3** — the
  canonical node/edge diagram in prose. This is what every writer below
  actually implements; if you need to know "what are all the node types
  and how do they connect," this is the doc, not any single code file.

## Data writers (write to Neo4j)

- **`src/scie/graph/synthetic_graph.py`** — `generate_synthetic_graph()`:
  the fake fleet. The only writer that produces `Package`, `IsDependency`,
  `VexStatement`, `VulnerabilityID`, and `Deployment` data — real ingestion
  doesn't touch any of these yet.
- **`src/scie/graph/github_ingest.py`** — `ingest_repository()`: real
  GitHub Actions data for the repos in its `REPOS` list (currently
  `dast-bench` and `pipeline-lens`). Only ever writes `Repository`,
  `Build`, `Commit` — no `Package`/`Artifact`/`Deployment`/vulnerability
  data for real repos yet.
- **`src/scie/graph/seed.py`** — CLI entrypoint (`python -m scie.graph.seed`)
  wiring `schema.py` + `synthetic_graph.py` together.
- **`src/scie/graph/db.py`** — `get_driver()`: the shared Neo4j driver
  singleton every writer/reader below uses.

## Data readers (Cypher query layer)

- **`src/scie/graph/queries.py`** — five named query functions
  (`vuln_blast_radius`, `vuln_origin_trace`, `repo_build_history`,
  `package_usage`, `expand_neighbors`) plus three list functions
  (`list_packages`, `list_vulnerabilities`, `list_repositories`), all
  returning a uniform `{nodes, edges}` shape regardless of which writer
  produced the underlying data (this is why real and synthetic data
  coexist without any UI/query changes).

## API layer

- **`src/scie/api/graph_routes.py`** — FastAPI routes wrapping every
  function in `queries.py`, mounted under `/graph/*`.

## UI / rendering layer

Never touches Neo4j directly — only calls the `/graph/*` API over HTTP.

- **`src/scie/ui/pages/1_Graph_Explorer.py`** — the Streamlit page: search
  dropdowns, session-state management for the accumulated
  graph/table view, node click + lens buttons + "Expand"/"Show as graph".
- **`src/scie/ui/graph_render.py`** — pure rendering-layer transforms, no
  Streamlit/HTTP calls: `collapse_attestations` (folds `VexStatement`/
  `IsDependency` nodes into edge labels), `node_display_label`,
  `_humanize_edge_type`, `to_agraph_elements` (builds
  `streamlit_agraph` `Node`/`Edge` objects — colors, shapes, fonts, margin).
- **`src/scie/ui/build_history_view.py`** — `build_history_rows()`:
  reshapes `{nodes, edges}` into table rows for the Repository "table"
  view.

## Where GUAC actually shows up (and where it doesn't)

- **`docs/phase2-graph-model.md`** — "Prior Art Being Reused" section: the
  original citation of GUAC's attestation-as-node modeling as the basis
  for this schema.
- **`docs/superpowers/specs/2026-07-16-graph-explorer-design.md` §3** —
  explicitly "adapting GUAC's attestation-as-node pattern" for
  `VexStatement`/`IsDependency`.
- **`src/scie/ui/graph_render.py`**, the `_ATTESTATION_EDGE_ROLES` comment:
  "Attestation nodes are always the *source* of both their edges (the GUAC
  convention this schema follows)."
- **What's NOT written down anywhere as a doc**: the later research
  concluding GUAC's own internal type names (`HasSLSA`, `IsDependency`,
  `CertifyVuln`) are *not* a real industry standard worth chasing, and
  that edge/label vocabulary should instead come from whichever real spec
  actually governs that kind of data (SLSA/in-toto for build provenance,
  CycloneDX for SBOM `dependsOn`, the CISA/OASIS VEX spec for
  affected/not_affected/fixed status) — and that most edges don't need a
  label at all once node types are visible. That whole conclusion only
  exists in conversation history and in its result: the exact label text
  in `graph_render.py` and the reasoning in
  `docs/superpowers/specs/2026-07-19-graph-label-polish-design.md`'s
  Purpose section. If this needs to be citable later, it should get
  written up properly rather than left as an unrecorded conversation.

## Design docs, in build order

1. `docs/phase2-graph-model.md` — full future-state design, largely
   unbuilt (real SBOM/SARIF ingestion, `BuildCompletenessWorkflow`,
   Postgres migration).
2. `docs/superpowers/specs/2026-07-16-graph-explorer-design.md` — first
   slice: schema, query layer, basic UI.
3. `docs/superpowers/specs/2026-07-17-graph-explorer-ux-design.md` — UX
   redesign: dropdown search, hierarchical layout, attestation collapsing.
4. `docs/superpowers/specs/2026-07-18-github-ingest-design.md` — real
   GitHub ingestion MVP (single repo, `dast-bench`).
5. `docs/superpowers/specs/2026-07-19-graph-node-shapes-design.md` — node
   shapes (`box`/`diamond`).
6. `docs/superpowers/specs/2026-07-19-graph-label-polish-design.md` — edge/
   node label casing, GUAC-naming research conclusion.
7. `docs/superpowers/specs/2026-07-19-edge-label-toggle-design.md` — the
   sidebar "Show edge labels" toggle.
8. `docs/superpowers/specs/2026-07-19-github-ingest-multirepo-design.md` —
   second real repo (`pipeline-lens` itself).
9. `docs/superpowers/specs/2026-07-20-repo-search-graph-view-design.md` —
   the "Show as graph" button for Repository URL search.
