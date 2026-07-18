# Real GitHub Ingestion (MVP) — Design

## 1. Purpose

The Graph Explorer redesign (`docs/superpowers/specs/2026-07-17-graph-explorer-ux-design.md`)
made the presentation layer credible, but the underlying data is still 100%
synthetic — every `Repository` is a fictional `example-org/*` name. This spec
adds the first slice of real data: a pull-based script that ingests one real
repository's GitHub Actions build history into the same Neo4j graph, so
Graph Explorer's Repository URL search can show something true.

This is deliberately a small, standalone precursor — not an attempt at the
full ingestion architecture in `docs/phase2-graph-model.md` §6 (the generic
`IngestArtifact` Temporal workflow, OCI-referrers/code-scanning-API watchers,
Postgres ingestion ledger). That architecture is designed for continuous,
event-driven ingestion of SBOM/SARIF/provenance across many repos; this spec
answers a narrower question — "show one real repo's real build history" —
using the smallest mechanism that does that. Real artifact/vulnerability
ingestion (the "add a pipeline scan" step) is an explicit, separate future
increment, not built here.

## 2. Scope

**In scope:**
- A single new module, `src/scie/graph/github_ingest.py`, that calls the
  GitHub REST API for one hardcoded repository's Actions workflow runs and
  MERGEs `Repository`/`Build`/`Commit` nodes and `HAS_BUILD`/`FOR_COMMIT`
  edges into Neo4j, using the same property names and shapes
  `synthetic_graph.py` already produces
- A CLI entrypoint (`python -m scie.graph.github_ingest`), run on demand,
  mirroring `seed.py`'s existing CLI pattern
- Mocked-driver and mocked-HTTP unit tests, no live GitHub or Neo4j required
  for `pytest` — same bar as the rest of the graph slice

**Out of scope (deferred):**
- Any repo other than `mlessley/dast-bench` — no config file, no repo list,
  no CLI argument for owner/repo. Multi-repo support is a mechanical
  extension of this same module later, not designed here.
- `Package`, `IsDependency`, `VexStatement`, `VulnerabilityID`, `Artifact`,
  `Deployment` data for this repo — no SBOM, no SARIF, no scan results. This
  repo will show up in Graph Explorer's build-history table only; the
  vulnerability-search modes won't find anything for it yet.
- Webhooks, live/event-driven ingestion, Temporal, OCI referrers, GitHub's
  code-scanning API — all of `docs/phase2-graph-model.md` §6. A live webhook
  receiver isn't practical from this sandbox right now (the DooD networking
  situation from this session means a webhook would need public exposure);
  pull-on-demand sidesteps that entirely.
- The Postgres ingestion ledger (§6.5) — no ledger to write yet, same
  reasoning the original Graph Explorer slice used to defer it.
- Any change to `queries.py`, the Neo4j schema, or the Graph Explorer UI —
  this spec produces data in the existing shape; nothing downstream needs to
  change to consume it.

## 3. Data Mapping

GitHub's `GET /repos/{owner}/{repo}/actions/runs` returns workflow runs. Only
**completed** runs are ingested (`status == "completed"`) — in-progress/queued
runs are skipped, since they have no `conclusion` yet and MERGE-based
idempotency means a later pull will pick them up once they finish.

| Graph entity | Source | Notes |
|---|---|---|
| `Repository {url, name}` | `GET /repos/{owner}/{repo}` | MERGEd once per ingest run, keyed on `url` (existing uniqueness constraint) |
| `Build {id, startTime, ciSystem, status}` | one per completed workflow run | `id` = run id (string); `startTime` = `run_started_at`; `ciSystem` = literal `"github-actions"`; `status` = the run's `conclusion` verbatim (`"success"`, `"failure"`, `"cancelled"`, ...) |
| `Commit {sha, author, timestamp}` | run's `head_sha` + `head_commit` | If `head_commit` is present: `author` = `head_commit.author.name`, `timestamp` = `head_commit.timestamp`. GitHub omits `head_commit` on some runs — if absent, `author` falls back to the run's `actor.login` (or `"unknown"` if that's also absent) and `timestamp` falls back to the run's `run_started_at` |
| `Repository -[:HAS_BUILD]-> Build` | | |
| `Build -[:FOR_COMMIT]-> Commit` | | |

`status` is passed through as GitHub's raw `conclusion` string rather than
normalized to `"success"`/`"failed"`. This is intentional: `build_history_rows`
(from the Graph Explorer redesign) already treats anything other than exactly
`"success"` as ❌, so GitHub's own vocabulary (`"failure"`, `"cancelled"`,
`"timed_out"`, etc.) renders correctly without a translation table, and the
real value is preserved for anyone inspecting the node directly.

No `Build -[:PRODUCED]-> Artifact` edges are written. `repo_build_history`'s
`OPTIONAL MATCH (b)-[:PRODUCED]->(a:Artifact)` already tolerates builds with
no artifacts (`collect(a)` yields an empty list) — confirmed against the
existing Cypher, no query change needed.

## 4. Components

```
src/scie/graph/github_ingest.py
  fetch_workflow_runs(owner: str, repo: str, token: str | None) -> list[dict]
    GET https://api.github.com/repos/{owner}/{repo}/actions/runs
    Sends `Authorization: Bearer {token}` header only if token is not None.
    Returns the raw `workflow_runs` list from the JSON response.

  ingest_repository(driver: Driver, owner: str, repo: str,
                     token: str | None = None, limit: int = 20) -> None
    Fetches repo metadata (GET /repos/{owner}/{repo}) and workflow runs,
    filters to completed runs, MERGEs per the mapping in §3. `limit` caps how
    many most-recent runs are considered (GitHub returns newest-first).

  main() -> None
    Hardcodes owner="mlessley", repo="dast-bench". Reads GITHUB_TOKEN from
    the environment (optional — the repo is public, so unauthenticated calls
    work; a token just raises the rate limit from 60/hr to 5000/hr). Calls
    get_driver() + ingest_repository(), prints a summary line, mirroring
    seed.py's existing CLI shape.

if __name__ == "__main__": main()
```

Run via `docker compose exec api uv run python -m scie.graph.github_ingest`,
the same invocation pattern as `python -m scie.graph.seed`.

## 5. Error Handling & Testing

Same PoC-grade bar as the rest of the graph slice: no retry logic, no
pagination beyond `limit`. `requests.raise_for_status()` surfaces GitHub API
errors (rate limit, 404) as an uncaught exception — acceptable for an
on-demand CLI script that a person is watching run, unlike the FastAPI routes
which need the 503-on-`ServiceUnavailable` handling for a live request path.

Tests:
- `fetch_workflow_runs`: mock `requests.get` (monkeypatch, following the
  existing test style in this codebase), assert the correct URL and headers
  (with and without a token) and that the JSON response's `workflow_runs`
  list is returned unchanged.
- `ingest_repository`: use the existing `FakeDriver`/`FakeSession` doubles
  from `tests/graph_fakes.py`, with `fetch_workflow_runs` monkeypatched to
  return canned run data (including at least one non-`completed` run, to
  verify it's filtered out). Assert the right `MERGE` statements and
  parameters reach the fake session, following the same assertion style as
  `tests/test_graph_synthetic.py`.
- No live GitHub or Neo4j connection in the test suite — `pytest` stays
  fully offline, same as every other test in this codebase.

## 6. Relation to Prior Work

This is additive to, not a replacement for,
`docs/superpowers/specs/2026-07-16-graph-explorer-design.md` (schema, query
layer) and `docs/superpowers/specs/2026-07-17-graph-explorer-ux-design.md`
(presentation layer) — neither changes here. The full ingestion architecture
in `docs/phase2-graph-model.md` §6-7 (generic `IngestArtifact` workflow,
`BuildCompletenessWorkflow`, Postgres ledger) remains undesigned-in-detail
and unbuilt; this script is not a step toward that architecture's specific
mechanisms (it doesn't use Temporal, doesn't watch OCI referrers), it's a
narrower, separate answer to "show one real repo" that happens to share the
same target schema.
