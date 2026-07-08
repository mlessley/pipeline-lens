# pipeline-lens: Phase 2 Design — Supply Chain Graph Model

## 1. Purpose

pipeline-lens models software supply chain and DevSecOps pipeline data (SBOMs, SAST findings, signatures, provenance, VEX, vulnerability data) as a Neo4j graph, so relationships between artifacts, builds, repos, and vulnerabilities can be queried directly instead of reconstructed from scattered tool outputs.

Rather than inventing a new schema from scratch, the design borrows heavily from GUAC (Graph for Understanding Artifact Composition), an existing open-source project (Google/Kusari/OpenSSF) that solves the same core problem, and leans on established data format standards for parsing.

This phase also settles the project's relational storage story: v1's SQLite store isn't a production-appropriate choice and is replaced by Postgres — the same engine already running in this stack for Temporal. Postgres becomes the sole relational store (ingestion ledger, drilldown-friendly parsed artifact data); Neo4j holds only the graph — nodes, edges, and their identity keys, never raw payloads or large binaries. See §6.5 for the full storage split.

## 2. Prior Art Being Reused

| Concern | Standard / Project |
|---|---|
| Graph modeling pattern (attestation-as-node) | GUAC |
| SBOM + VEX format | CycloneDX |
| SAST/DAST findings format | SARIF (OASIS standard) |
| Build provenance | in-toto / SLSA provenance |
| Vulnerability identity | OSV schema (aliases CVE/GHSA) |
| VEX statements | OpenVEX / CSAF-VEX |
| Repo health signals | OpenSSF Scorecard |

GUAC evaluated Neo4j and other graph DBs before settling on ArangoDB for its own scale needs, but its node/edge modeling pattern (attestation-as-node, PURL/digest-keyed identity, evidence trees) is directly portable to a Neo4j-based project and is the core design pattern adopted here.

## 3. Core Modeling Pattern: Attestation-as-Node

Structural facts (a package depends on another package, a build ran on a host) are modeled as simple edges. Facts that carry *justification*, *origin*, or a *source tool* are modeled as first-class nodes sitting between the two things they relate, following GUAC's approach.

Example — dependency relationship:

```
(:Package)<-[:subject]-(:IsDependency {versionRange, justification, origin})-[:dependency]->(:Package)
```

This preserves *why* pipeline-lens believes a relationship exists and *which tool/document* asserted it, which matters when two scanners disagree or when auditing a claim later.

Plain edges are used for facts that don't need justification tracking: `BUILT_BY`, `DEPLOYED_TO`, `RUNS_ON`, `HAS_BUILD`, `FOR_COMMIT`, `PRODUCED`.

## 4. Node Types

- **`Package` / `Component`** — keyed by PURL (Package URL spec), decomposed into type/namespace/name/version fields for partial matching.
- **`Artifact`** — keyed by content digest (sha256); the actual built binary/image/blob.
- **`VulnerabilityID`** — normalized to OSV schema; aliases CVE/GHSA identifiers to a canonical ID.
- **`VexStatement`** — OpenVEX or CSAF-VEX; links a `VulnerabilityID` + `Component` + status (affected / not_affected / fixed).
- **`SASTFinding`** — parsed from SARIF; keyed by rule ID + location + commit SHA.
- **`Attestation` / `Provenance`** — in-toto/SLSA provenance; links an `Artifact` to the `Build` that produced it.
- **`ScorecardResult`** — OpenSSF Scorecard checks per repo.
- **`Repository`** — stable anchor for history; keyed by URL.
- **`Commit`** — keyed by SHA; linked to a `Repository`.
- **`Build`** — a single CI/CD execution; keyed by `(repo, commitSha, buildNumber-or-timestamp)` — **never** by pipeline/job name.
- **Infra nodes** (`Host`, `Container`, `Cluster`) — optional, for extending past build-time into runtime/deployment tracking.

## 5. Repository/Build History Model

### 5.1 Problem

Pipeline tooling identity (Jenkins job, GitHub Actions workflow file, a Temporal-orchestrated runner) is not stable over a project's lifetime. Repositories are. History must anchor to the repo, not to a specific pipeline implementation, or a CI migration silently forks the history into two disconnected chains.

### 5.2 Schema

```
(:Repository {url, name})
  -[:HAS_BUILD]->(:Build {id, startTime, ciSystem, commitSha, status})
     -[:FOR_COMMIT]->(:Commit {sha, author, timestamp})
     -[:PRODUCED]->(:Artifact)
```

`ciSystem` is a **property on `Build`**, not part of any node's identity key. If the CI tooling changes, `Repository` doesn't move and the `Build` timeline simply reflects the property change partway through — no broken chain, no duplicate pipeline entity.

### 5.3 Example query — repo history

```cypher
MATCH (r:Repository {url: $repoUrl})-[:HAS_BUILD]->(b:Build)
OPTIONAL MATCH (b)-[:PRODUCED]->(a:Artifact)
RETURN b.startTime, b.ciSystem, b.status, collect(a) AS artifacts
ORDER BY b.startTime DESC
```

### 5.4 Monorepo consideration (open, not solved yet)

A single `Build` may produce multiple components in a monorepo. If/when this matters:

```
(:Build)-[:PRODUCED]->(:Component {purl})
```

Component-level history becomes its own traversal, separate from repo-level history:

```cypher
MATCH (c:Component {purl: $purl})<-[:PRODUCED]-(b:Build)<-[:HAS_BUILD]-(r:Repository)
RETURN b ORDER BY b.startTime DESC
```

Leave the edge shape open for this now; retrofitting later means backfilling every existing `Build` node.

### 5.5 Indexing

- Uniqueness constraint on `Repository.url`
- Range index on `Build.startTime`
- Range index on `Commit.sha`

These back the two hottest queries: "history of repo, most recent first" and "find the build for this commit."

## 6. Ingestion Architecture

### 6.1 Design principle: watch artifact types, not pipelines

Initial instinct was one Temporal workflow per pipeline run, following that pipeline's outputs. This doesn't scale — pipelines are infinite in variety (Jenkins, GitHub Actions, future tooling), but the *artifact types* they emit (SBOM, SARIF, signature, provenance) are a small, closed set. Ingestion is designed around artifact type, not pipeline identity, so any pipeline that emits a recognized artifact type is automatically supported with no new integration work.

### 6.2 One generic `IngestArtifact` workflow

A single Temporal workflow definition, parameterized by artifact type, dispatches to a small registry of type-specific activities (`parseCycloneDX`, `parseSARIF`, `parseInTotoProvenance`, etc.). Adding support for a new pipeline never means adding a new workflow — it means that pipeline now emits to a location already being watched.

### 6.3 Idempotency via deterministic Workflow ID

Workflow ID = deterministic hash of artifact identity, e.g. `sha256(digest + docType)` or `PURL + docType`, combined with a reject-duplicate reuse policy. Re-emission or re-scanning of the same artifact is a no-op rather than requiring custom dedup logic.

### 6.4 Watch standard distribution points, not pipeline callbacks

Rather than requiring every pipeline to explicitly call an ingestion API, hook into the conventional homes these artifact types already land in. Registries don't expose a generic "new artifact" webhook, so each entry point needs a concrete trigger + fetch mechanism, not a passive "watch":

- **Cosign attestations and SBOMs pushed as OCI referrers** attach to the image manifest in the registry. The real mechanism: ECR image-push events via EventBridge (`aws.ecr` / `ECR Image Action`) trigger a pull step that queries the registry's OCI referrers API (`GET /v2/<name>/referrers/<digest>`) for cosign signatures/attestations and SBOMs attached to that digest.
- **SARIF** lands via a platform's code scanning API — for GitHub Actions specifically, the `code_scanning_alert` webhook event (or polling `GET /repos/{owner}/{repo}/code-scanning/analyses` per commit) surfaces newly uploaded SARIF results.

This makes ingestion pipeline-agnostic almost for free once these two entry points are wired up, since the underlying tools (Syft, Cosign, etc.) already publish to these same conventions regardless of which CI system invoked them.

### 6.5 Data handling and storage split

Raw documents are validated against their format's schema, normalized into the node/edge shape above, and MERGEd (never CREATEd) into Neo4j keyed on stable identity (PURL, digest, commit SHA), since the same artifact will be re-attested by multiple tools over time and duplication should converge, not multiply. Full raw JSON is not duplicated into graph node properties — nodes store a pointer back to the raw document's blob location.

Postgres is the project's sole relational store going forward (replacing v1's SQLite) and serves two roles:

- **Ingestion ledger** (source, timestamp, collector, doc hash) mirroring GUAC's collector/origin tracking, so "who told us this and when" is answerable without querying the graph.
- **Drilldown-friendly copies of parsed artifact data** — scan findings, VEX statements, build records — for read paths (dashboard/API) that are naturally tabular and don't need graph traversal.

Large binary artifacts (OCI images, blobs) are never stored in Postgres or Neo4j — both only ever hold a pointer back to the blob's actual location.

## 7. Build Completeness Correlation Workflow (Optional Layer)

### 7.1 Purpose

Individual `IngestArtifact` workflows are artifact-scoped and know nothing about siblings. This workflow answers a build-level question: did commit `abc123`'s build produce everything expected (SBOM, signature, provenance, SARIF), or is something missing, late, or failed.

This layer is additive — it consumes signals that `IngestArtifact` workflows already have a natural reason to send, and can be introduced later without touching the ingestion workflows.

### 7.2 Starting the workflow via signal-with-start

The build isn't known to exist until its first artifact arrives. Whichever `IngestArtifact` workflow completes first for a given build ID sends a signal to `BuildCompleteness-{buildId}`; if that workflow isn't already running, Temporal starts it automatically as part of delivering the signal (signal-with-start). No separate "build began" trigger is needed.

```python
# inside IngestArtifact activity, after successful ingest
await client.start_workflow(
    BuildCompletenessWorkflow.run,
    args=[build_id],
    id=f"build-completeness-{build_id}",
    task_queue="pipeline-lens",
    start_signal="artifact_ingested",
    start_signal_args=[ArtifactIngestedSignal(type="sbom", artifact_id=digest)],
)
```

### 7.3 Workflow definition

```python
@workflow.defn
class BuildCompletenessWorkflow:
    def __init__(self):
        self.received: dict[str, ArtifactIngestedSignal] = {}
        self.expected: set[str] = EXPECTED_ARTIFACT_TYPES  # e.g. {"sbom","sarif","provenance","signature"}

    @workflow.signal
    async def artifact_ingested(self, sig: ArtifactIngestedSignal):
        self.received[sig.type] = sig

    @workflow.query
    def status(self) -> dict:
        return {"received": list(self.received), "missing": list(self.expected - self.received.keys())}

    @workflow.run
    async def run(self, build_id: str):
        try:
            await workflow.wait_condition(
                lambda: self.expected.issubset(self.received.keys()),
                timeout=timedelta(minutes=30),
            )
            await workflow.execute_activity(
                mark_build_complete,
                build_id,
                start_to_close_timeout=timedelta(seconds=30),
            )
        except asyncio.TimeoutError:
            await workflow.execute_activity(
                mark_build_incomplete,
                args=[build_id, list(self.expected - self.received.keys())],
                start_to_close_timeout=timedelta(seconds=30),
            )
```

### 7.4 Key design elements

- **`expected` set** — defines what "complete" means for a build. Simplest form is a static set of required artifact types. A more realistic version looks this up from config keyed by repo/pipeline type at workflow start, since not every repo emits every artifact type (e.g. SARIF).
- **`wait_condition` with timeout** — a durable timer that survives worker restarts. Resolves early if all expected types arrive; otherwise times out to a definite "incomplete" state rather than waiting indefinitely.
- **Query handler** — allows live status lookup ("what's the current state of build X") without waiting for completion — usable by a dashboard or a TRMNL-style status display.
- **Idempotent signals** — duplicate signals for the same artifact type simply overwrite the dict entry; harmless.
- **Activity timeouts are mandatory** — the Temporal Python SDK rejects `execute_activity` calls with no timeout at schedule time, so both calls above set `start_to_close_timeout` explicitly.

### 7.5 On completion

`mark_build_complete` / `mark_build_incomplete` activities write back into Neo4j — either a `complete: true/false` property on the `Build` node, or (preferred, consistent with the attestation-as-node pattern) a `CertifyBuildComplete` node attached to `Build`, preserving *when* that determination was made rather than only the current state.

### 7.6 Why this matters

This is what enables build-level questions as first-class graph/dashboard queries — "which builds shipped without a signature," "SARIF never arrived for these 3 builds in the last day" — instead of inferring absence, which is much harder to alert on reliably.

## 8. Open Questions / Future Work

- Monorepo component-level history (Section 5.4) — schema left open, not yet implemented.
- Config source for per-repo `expected` artifact type sets (Section 7.4) — lives in Postgres per the storage model in §6.5; concrete schema not yet drafted.
- Whether/how v1's existing GitHub/ECR/K8s pipeline-run data gets remodeled into this graph, versus this being a parallel pipeline scoped to new artifact types (SBOM/SARIF/attestations) — not yet decided.
- Runtime/deployment extension via infra nodes (`Host`, `Container`, `Cluster`) — mentioned as optional scope, not detailed here.
- Concrete Cypher MERGE patterns per artifact type (SBOM ingestion, SARIF finding ingestion, etc.) — not yet drafted.
