# GitHub Ingest Multi-Repo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mlessley/pipeline-lens` as a second real ingested repository alongside `dast-bench`, per `docs/superpowers/specs/2026-07-19-github-ingest-multirepo-design.md`.

**Architecture:** A `REPOS` constant lists both repos; `main()` loops over it, calling the existing `ingest_repository` once per entry. No changes to `ingest_repository`/`fetch_workflow_runs`/`_fetch_repository` — they already take `owner`/`repo` as parameters.

**Tech Stack:** No new dependencies.

## Global Constraints

- No CLI arguments or config file for the repo list — a small hardcoded `REPOS` constant only (spec §2).
- No changes to `fetch_workflow_runs`, `_fetch_repository`, or `ingest_repository`'s signatures or behavior (spec §2).
- No vulnerability/CodeQL/Dependabot ingestion — no real alert data exists yet to ingest (spec §2).

---

### Task 1: Ingest a second repository

**Files:**
- Modify: `src/scie/graph/github_ingest.py`

**Interfaces:**
- Consumes: existing `ingest_repository(driver: Driver, owner: str, repo: str, token: str | None = None, limit: int = 20) -> None` — unchanged.
- Produces: `github_ingest.REPOS: list[tuple[str, str]]`. No other task in this plan depends on it — this is the whole feature.

- [ ] **Step 1: Add the REPOS constant and update main()**

In `src/scie/graph/github_ingest.py`, change:

```python
def main() -> None:
    driver = get_driver()
    token = os.environ.get("GITHUB_TOKEN")
    ingest_repository(driver, "mlessley", "dast-bench", token=token)
    print("Ingested GitHub Actions build history for mlessley/dast-bench.")
```

to:

```python
REPOS: list[tuple[str, str]] = [
    ("mlessley", "dast-bench"),
    ("mlessley", "pipeline-lens"),
]


def main() -> None:
    driver = get_driver()
    token = os.environ.get("GITHUB_TOKEN")
    for owner, repo in REPOS:
        ingest_repository(driver, owner, repo, token=token)
        print(f"Ingested GitHub Actions build history for {owner}/{repo}.")
```

- [ ] **Step 2: Syntax-check the file**

Run: `uv run python -c "import ast; ast.parse(open('src/scie/graph/github_ingest.py').read())"`
Expected: no output, exit code 0.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -v`
Expected: all PASS (92 pre-existing), no regressions — `ingest_repository` itself is unchanged, so its existing tests in `tests/test_github_ingest.py` continue to cover this behavior; `main()` has no test coverage, consistent with `seed.py`'s `main()` (spec §3).

- [ ] **Step 4: Commit**

```bash
git add src/scie/graph/github_ingest.py
git commit -m "feat: ingest mlessley/pipeline-lens as a second real repo"
```

---

### Task 2: Manual verification

**Files:** none — this task exercises the running stack, no code changes.

- [ ] **Step 1: Rebuild the api container**

The `src/` directory is `COPY`'d into the Docker image at build time.

Run: `docker compose -p pipeline-lens up -d --build api`
Expected: the container rebuilds and reports `Started`.

- [ ] **Step 2: Run the ingest CLI**

Run: `docker exec pipeline-lens-api-1 uv run python -m scie.graph.github_ingest`
Expected: prints two lines — `Ingested GitHub Actions build history for mlessley/dast-bench.` and `Ingested GitHub Actions build history for mlessley/pipeline-lens.` — no traceback. (No `GITHUB_TOKEN` needed — both repos are public.)

- [ ] **Step 3: Verify pipeline-lens's data landed in Neo4j**

Run:
```bash
docker exec pipeline-lens-neo4j-1 cypher-shell -u neo4j -p devpassword \
  "MATCH (r:Repository {url: 'https://github.com/mlessley/pipeline-lens'})-[:HAS_BUILD]->(b:Build) RETURN b.id, b.status, b.startTime ORDER BY b.startTime DESC LIMIT 5"
```
Expected: real build rows, including at least one with `status: "failure"` (the real CI has recent failures — confirmed via the GitHub API before writing this plan).

- [ ] **Step 4: Verify via the API**

Run: `curl -s --max-time 5 "http://172.19.0.1:18000/graph/repositories" | grep pipeline-lens`

(Use `172.19.0.1` — the `devx_default` bridge gateway — per the DooD networking note from earlier in this session.)

Expected: `{"url":"https://github.com/mlessley/pipeline-lens","name":"pipeline-lens"}` present in the list.

- [ ] **Step 5: Walk through the UI at `http://localhost:8501` → Graph Explorer**

Repository URL mode's dropdown should now include both `dast-bench` and
`pipeline-lens`. Searching `pipeline-lens` should render the build-history
table with a mix of ✅ and ❌ status rows — the first real "failed build"
data anywhere in the graph. Report back what you see.

- [ ] **Step 6: Fix forward if anything in Step 5 doesn't match**

If `pipeline-lens` doesn't show up, re-check Step 2's output for a
traceback on the second loop iteration before touching any code — Task 1's
change is a two-line loop around already-tested logic.
