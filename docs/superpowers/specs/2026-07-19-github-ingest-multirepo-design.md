# GitHub Ingest Multi-Repo — Design

## 1. Purpose

`src/scie/graph/github_ingest.py` was deliberately scoped to a single
hardcoded repository (`mlessley/dast-bench`) in its original design, with
multi-repo support explicitly named as a later, mechanical extension. This
is that extension: add `mlessley/pipeline-lens` itself as a second real
data source — the tool ingesting its own build history.

Before shaping this, two other real-data options were checked and ruled
out for now: `pipeline-lens`'s GitHub CodeQL code-scanning alerts and
Dependabot alerts are both currently empty (zero alerts on the real repo,
confirmed via the GitHub API) — there's no real vulnerability/dependency
data to ingest yet, so this stays scoped to Build/Commit/Repository data,
same shape as the existing `dast-bench` ingestion. `pipeline-lens`'s CI
does have genuine variety worth capturing: a real mix of successful and
**failed** runs, unlike `dast-bench`'s all-success history.

## 2. Scope

**In scope:**
- A `REPOS: list[tuple[str, str]]` constant in `github_ingest.py`:
  `[("mlessley", "dast-bench"), ("mlessley", "pipeline-lens")]`.
- `main()` loops over `REPOS`, calling the existing
  `ingest_repository(driver, owner, repo, token=token)` once per entry,
  printing one summary line per repo.

**Out of scope:**
- Any change to `fetch_workflow_runs`, `_fetch_repository`, or
  `ingest_repository`'s signatures or behavior — they already generalize
  across any owner/repo; this only changes what `main()` calls them with.
- CLI arguments or a config file for the repo list — explicitly ruled out
  in favor of staying consistent with the original "no config" MVP
  philosophy; a small hardcoded list scales to a third/fourth repo without
  needing that yet.
- Real CodeQL/Dependabot vulnerability ingestion — no real alert data
  exists on `pipeline-lens` right now to ingest; worth revisiting once
  there's something real to pull.
- Any change to the ingestion/UI/read-API architecture split discussed
  separately in conversation — that's explicitly postponed, unrelated to
  this change.

## 3. Testing

No new test needed. `ingest_repository`'s per-repo behavior is already
fully covered by the existing `tests/test_github_ingest.py` suite (owner/
repo are already parameters, not hardcoded in the function itself).
`main()` has no existing test coverage — consistent with `seed.py`'s
`main()`, the established convention in this codebase is that CLI
entrypoints aren't unit tested, only the functions they call.

## 4. Verification

Manual: run `python -m scie.graph.github_ingest` against the live stack and
confirm both repos' data lands in Neo4j — same verification pattern as the
original single-repo ingestion.
