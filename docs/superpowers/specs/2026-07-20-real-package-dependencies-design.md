# Real Package Dependencies from uv.lock — Design

## 1. Purpose

Every `Package`/`IsDependency` node in the graph today is synthetic
(`synthetic_graph.py`). The two real repos ingested by `github_ingest.py`
(`pipeline-lens`, `dast-bench`) have real `Build`/`Commit`/`Repository`
data but zero package-level data — there's nothing to find via Package
PURL search, `package_usage`, or `vuln_blast_radius`/`vuln_origin_trace`
for either real repo. This adds real `Package` and `IsDependency` data by
parsing each repo's actual `uv.lock` and `pyproject.toml`, scoped to
direct dependencies only (not the full transitive closure).

## 2. Scope

**In scope:**
- Extends `src/scie/graph/github_ingest.py` (same file — same data
  source and `REPOS` list as the existing Build/Commit ingestion), not a
  new module.
- For each repo in `REPOS`: fetch `pyproject.toml` and `uv.lock` via
  GitHub's Contents API (not local disk, even for `pipeline-lens` itself —
  keeps the data source uniform: "the real committed file on GitHub" for
  every repo, no self-referential special case).
- Parse `pyproject.toml`'s `[project.dependencies]` with `tomllib`
  (stdlib, no new dependency) to get the repo's *direct* dependency names
  only — strip version specifiers and extras (`"uvicorn[standard]>=0.50.0"`
  → `uvicorn`).
- Parse `uv.lock`'s `[[package]]` entries with `tomllib` to resolve each
  direct dependency name to its locked version.
- One `Artifact` node per repo: `digest` = `"sha256:" + sha256(...).hexdigest()`
  of the *decoded* `uv.lock` file content (the raw file bytes, not the
  base64 string GitHub's Contents API wraps it in) — reproducible and
  verifiable, not a placeholder. `name` = `f"{repo}-dependencies"`, same
  `{digest, name}` shape `synthetic_graph.py`'s `Artifact` nodes already
  use. Linked `Build -[:PRODUCED]-> Artifact` from that repo's most
  recently ingested `Build` (`ORDER BY startTime DESC LIMIT 1`).
- One `Package` node per resolved direct dependency
  (`purl = pkg:pypi/{name}@{version}`), linked via the existing
  attestation pattern: `IsDependency {origin: 'uv.lock'}` with
  `-[:subject]-> Artifact` and `-[:dependency]-> Package`, exactly
  matching `synthetic_graph.py`'s existing Cypher shape.

**Out of scope:**
- The full transitive closure (~91 packages for `pipeline-lens`) — direct
  dependencies only (~12 for `pipeline-lens`), per the earlier decision.
- Any change to `queries.py`, the Neo4j schema/constraints, or the API —
  the new data uses the exact existing `Artifact`/`Package`/`IsDependency`
  shape, so `vuln_blast_radius`, `package_usage`, etc. pick it up with zero
  query changes.
- Real vulnerability data for these packages (no CVE/VEX status) — this is
  "what does this repo depend on," not "is it vulnerable." That's the
  separately-discussed, larger CodeQL-alerts idea.
- Any repo whose `pyproject.toml` doesn't use PEP 621's
  `[project.dependencies]` format (e.g. old-style Poetry) — if a repo's
  `pyproject.toml` doesn't have that section, it simply yields zero direct
  dependencies for that repo, not an error. Not worth handling other
  formats for two repos that both already use PEP 621 via `uv`.

## 3. Testing

Same bar as the rest of `github_ingest.py`: mocked-HTTP tests for the new
fetch/parse functions (canned `pyproject.toml`/`uv.lock` TOML content),
mocked-driver tests for the new Cypher writes, following the exact
existing test patterns in `tests/test_github_ingest.py`. No live GitHub or
Neo4j required for `pytest`.

## 4. Verification

Manual: run `python -m scie.graph.github_ingest` against the live stack,
confirm real `Package` nodes appear in Neo4j for both repos, confirm
Package PURL search in Graph Explorer now finds e.g. `fastapi` or
`streamlit` and traces back to the real `pipeline-lens` repo/build via
`package_usage`.
