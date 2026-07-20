# GUAC Adoption Decision — Supply Chain Graph Modeling

## Status

Proposed. Supersedes the "borrow the pattern, build it independently" framing in
`docs/phase2-graph-model.md` §2 for the SBOM/VEX/attestation/vulnerability
slice specifically. Does not touch the CI/build-lineage slice (see below).

## Context

Phase 2's design borrowed GUAC's "attestation-as-node" modeling pattern but
built an independent Neo4j schema rather than running GUAC itself
(`docs/phase2-graph-model.md` §2-3). The SBOM/VEX/vulnerability/attestation
portion of that schema — `Package`, `IsDependency`, `VexStatement`,
`VulnerabilityID` — has never been fed by real data; only the synthetic
fleet generator (`src/scie/graph/synthetic_graph.py`) produces it. This is
the highest-risk part of the system to hand-roll: SBOM/VEX/SLSA parsing and
identity normalization (PURL, digest matching) is easy to get subtly wrong
without deep prior domain background, and errors there are hard to catch
without expert review.

By contrast, real GitHub Actions ingestion (`src/scie/graph/github_ingest.py`)
and the `Repository`→`Build`→`Commit` graph are shipped, tested, and live —
and model CI/CD build lineage, which sits entirely outside GUAC's own scope.

## Decision Drivers

- Avoid reinventing infrastructure a maintained, credibly-backed project
  already solves well, especially in a domain area where subtle correctness
  bugs (identity matching, VEX status semantics) are easy to introduce
  without deep prior expertise.
- Long-term maintainability: whoever inherits this system should be able to
  lean on GUAC's own documentation/community for the composition-graph half,
  rather than auditing bespoke Cypher no one else has context on.
- Don't discard already-working, already-tested code (CI/build lineage) that
  GUAC can't replace regardless of this decision.
- Keep operational footprint proportionate — avoid adding infrastructure
  that duplicates what's already planned elsewhere in Phase 2.

## Options Considered

### A — Full swap to GUAC as sole backend

Run GUAC's full service stack (NATS, collectsub, ingestor, source collectors,
GraphQL/REST API) backed by Postgres+Ent; retire the custom
Package/Vuln/VEX/Artifact schema entirely; UI queries GUAC directly for that
slice.

- **Pros:** strongest "not reinventing" story; GUAC owns the hardest,
  most correctness-sensitive parsing work end to end.
- **Cons:** ~7 additional services to operate. Doesn't actually shrink the
  custom half of the system — CI/build lineage still needs its own model
  regardless, since GUAC doesn't cover it.

### B — Hybrid: GUAC owns composition/vuln, custom graph owns CI/build lineage (recommended)

Run real GUAC (Postgres/Ent backend) for SBOM, VEX, attestation, and
vulnerability data — the slice it's designed for, and the slice that was
never real in pipeline-lens to begin with. Keep the existing Neo4j
`Repository`/`Build`/`Commit` graph untouched, since it's shipped, tested,
and models something GUAC explicitly doesn't attempt. Correlate the two at
the query/API layer using shared identity keys (artifact digest, PURL).

- **Pros:** targets adoption exactly where reinvention risk is highest and
  where nothing real has been built yet; doesn't discard working code;
  GUAC's Postgres/Ent backend reuses infrastructure Phase 2 already planned
  to add (§6.5's ingestion ledger), rather than adding a new datastore
  purely for GUAC's sake.
- **Cons:** two systems to reason about instead of one; requires a defined
  correlation contract between them (digest/PURL join) at the API layer.

### C — Status quo: cite standards, skip running GUAC

Keep the independent Neo4j schema; lean on citing the underlying standards
(CycloneDX, SPDX, SLSA, OSV, OpenVEX) directly rather than running GUAC
itself.

- **Pros:** lowest operational cost, single datastore story.
- **Cons:** weakest answer to "why didn't you just use the project that
  already solves this"; doesn't reduce the risk of hand-rolled
  parsing/identity logic being subtly wrong.

## Verified Facts About GUAC (as of 2026-07-20)

- OpenSSF incubating project; originated 2022 (Google, Kusari, Purdue,
  Citi); actively maintained (v1.1.0, March 2026; 2,356+ commits). Credible
  and citable, but not yet a ubiquitous industry default — no publicly
  documented large-scale production adopters found.
- Architecture: NATS message broker + collectsub + ingestor +
  source-specific collectors (OCI, deps.dev, OSV-certifier, etc.) +
  GraphQL/REST query API.
- Backend datastores: Ent+PostgreSQL is the only backend the project is
  actively committed to maintaining. In-memory keyvalue is supported for
  local/dev use. ArangoDB — GUAC's original backend — and Neo4j/openCypher
  are both now categorized "unsupported, incomplete": community-maintained
  only, not a project commitment.
- Explicit non-scope, confirmed directly from project documentation: GUAC
  does not model CI/CD pipeline execution, build history, or
  deployment/runtime state.
- Consumes/normalizes: CycloneDX, SPDX, SLSA/in-toto attestations, OpenSSF
  Scorecard, OSV vulnerability data, CSAF-VEX/OpenVEX.

## Recommendation

Adopt Option B:

1. Stand up GUAC's reference deployment (docker-compose quickstart) with its
   Postgres/Ent backend for SBOM/VEX/attestation/vulnerability data.
2. Retire `synthetic_graph.py`'s `Package`/`IsDependency`/`VexStatement`/
   `VulnerabilityID` generation and the corresponding constraints in
   `schema.py` — this data was never real, so there's no migration cost.
3. Keep `github_ingest.py`, the `Repository`/`Build`/`Commit` Neo4j schema,
   and the existing `/graph/*` query layer for CI/build lineage untouched.
4. Add a correlation layer at the API level joining GUAC's artifact/PURL
   identities to pipeline-lens's `Build`/`Artifact` nodes where they
   overlap (e.g. "which vulnerabilities affect packages produced by this
   build").
5. Update `docs/phase2-graph-model.md` to reflect this split explicitly —
   replace the "Prior Art Being Reused" framing (GUAC as inspiration) with
   "GUAC as a dependency" for the composition/vulnerability slice.

## Deferred / Not Decided Here

- Concrete GraphQL query shapes against GUAC for the UI.
- Exact correlation/join contract between GUAC identities and
  pipeline-lens's `Build`/`Artifact` nodes.
- Whether to self-host GUAC's collectors (OCI, deps.dev) or write
  pipeline-lens-specific ingestion that pushes into GUAC's ingestor API
  directly.
- Implementation sequencing/timeline — this document captures the decision,
  not a build plan.
