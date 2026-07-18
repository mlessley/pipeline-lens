# Real GitHub Ingestion (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull `mlessley/dast-bench`'s real GitHub Actions workflow-run history into the existing Neo4j graph, using the same schema the synthetic generator already produces, per `docs/superpowers/specs/2026-07-18-github-ingest-design.md`.

**Architecture:** One new module, `src/scie/graph/github_ingest.py`, with two importable functions (`fetch_workflow_runs`, `ingest_repository`) and a `main()` CLI entrypoint mirroring `seed.py`. No changes anywhere else — the existing query layer, API routes, and Graph Explorer UI consume this data with zero modification because it lands in the identical `Repository`/`Build`/`Commit` shape the synthetic data already uses.

**Tech Stack:** `requests` (already an installed transitive dependency, used elsewhere in this codebase — see `src/scie/ui/streamlit_app.py`), `neo4j` Python driver, pytest with the existing `FakeDriver`/`FakeSession` doubles in `tests/graph_fakes.py`.

## Global Constraints

- Hardcode `owner="mlessley"`, `repo="dast-bench"` — no config file, no CLI args, no other repos in this increment (spec §2).
- Only ingest `Repository`, `Build`, `Commit` nodes and `HAS_BUILD`/`FOR_COMMIT` edges — no `Package`/`Artifact`/`VulnerabilityID`/`VexStatement`/`Deployment`/`IsDependency` data for this repo (spec §2).
- Only ingest workflow runs where `status == "completed"` — skip in-progress/queued runs (spec §3).
- `Build.status` is GitHub's raw `conclusion` string, not normalized — `build_history_rows` already treats anything but exactly `"success"` as ❌ (spec §3).
- No `PRODUCED`/`Artifact` edges — `repo_build_history`'s `OPTIONAL MATCH` already tolerates builds with no artifacts, confirmed against the existing Cypher (spec §3).
- No changes to `queries.py`, the Neo4j schema, or the Graph Explorer UI (spec §2).
- Same PoC-grade error handling bar as the rest of the graph slice: `response.raise_for_status()` surfaces GitHub API errors as an uncaught exception, no retry logic (spec §5).

---

### Task 1: GitHub workflow-run ingestion module

**Files:**
- Create: `src/scie/graph/github_ingest.py`
- Test: `tests/test_github_ingest.py`

**Interfaces:**
- Consumes: `scie.graph.db.get_driver() -> Driver` (existing, used by `main()` only — the same import `seed.py` already uses).
- Produces: `github_ingest.fetch_workflow_runs(owner: str, repo: str, token: str | None) -> list[dict]` (returns the raw `workflow_runs` list from GitHub's API response, unfiltered); `github_ingest.ingest_repository(driver: Driver, owner: str, repo: str, token: str | None = None, limit: int = 20) -> None`; `github_ingest.main() -> None`. No other task in this plan depends on these — this is the whole feature.

- [ ] **Step 1: Write the failing tests for `fetch_workflow_runs`**

Create `tests/test_github_ingest.py`:

```python
from graph_fakes import FakeDriver

from scie.graph import github_ingest


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_workflow_runs_sends_correct_url_and_no_auth_header_without_token(monkeypatch):
    captured = {}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResponse({"workflow_runs": [{"id": 1}]})

    monkeypatch.setattr(github_ingest.requests, "get", fake_get)

    result = github_ingest.fetch_workflow_runs("mlessley", "dast-bench", None)

    assert captured["url"] == "https://api.github.com/repos/mlessley/dast-bench/actions/runs"
    assert "Authorization" not in captured["headers"]
    assert result == [{"id": 1}]


def test_fetch_workflow_runs_sends_bearer_token_when_provided(monkeypatch):
    captured = {}

    def fake_get(url, headers, timeout):
        captured["headers"] = headers
        return FakeResponse({"workflow_runs": []})

    monkeypatch.setattr(github_ingest.requests, "get", fake_get)

    github_ingest.fetch_workflow_runs("mlessley", "dast-bench", "secret-token")

    assert captured["headers"]["Authorization"] == "Bearer secret-token"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_github_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.graph.github_ingest'`.

- [ ] **Step 3: Implement `fetch_workflow_runs`**

Create `src/scie/graph/github_ingest.py` with this initial content:

```python
import os

import requests
from neo4j import Driver

from scie.graph.db import get_driver

GITHUB_API_URL = "https://api.github.com"


def _github_headers(token: str | None) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_workflow_runs(owner: str, repo: str, token: str | None) -> list[dict]:
    response = requests.get(
        f"{GITHUB_API_URL}/repos/{owner}/{repo}/actions/runs",
        headers=_github_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["workflow_runs"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_github_ingest.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Write the failing tests for `ingest_repository`**

Append to `tests/test_github_ingest.py`:

```python
def test_ingest_repository_merges_repository_build_and_commit(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        github_ingest, "_fetch_repository",
        lambda owner, repo, token: {
            "html_url": "https://github.com/mlessley/dast-bench", "name": "dast-bench",
        },
    )
    monkeypatch.setattr(
        github_ingest, "fetch_workflow_runs",
        lambda owner, repo, token: [
            {
                "id": 29206742457,
                "status": "completed",
                "conclusion": "success",
                "head_sha": "08f3e3fedf4607c8c31a95c0e9f06b5f1252323b",
                "run_started_at": "2026-07-12T19:55:52Z",
                "head_commit": {
                    "author": {"name": "Mark"},
                    "timestamp": "2026-07-12T19:55:49Z",
                },
            },
        ],
    )

    github_ingest.ingest_repository(driver, "mlessley", "dast-bench")

    calls = driver.fake_session.calls
    repo_call = next(c for c in calls if c[0].strip().startswith("MERGE (r:Repository"))
    assert repo_call[1] == {
        "url": "https://github.com/mlessley/dast-bench", "name": "dast-bench",
    }

    build_call = next(c for c in calls if "MERGE (b:Build" in c[0])
    assert build_call[1] == {
        "repo_url": "https://github.com/mlessley/dast-bench",
        "build_id": "29206742457",
        "start_time": "2026-07-12T19:55:52Z",
        "status": "success",
    }

    commit_call = next(c for c in calls if "MERGE (c:Commit" in c[0])
    assert commit_call[1] == {
        "build_id": "29206742457",
        "sha": "08f3e3fedf4607c8c31a95c0e9f06b5f1252323b",
        "author": "Mark",
        "timestamp": "2026-07-12T19:55:49Z",
    }


def test_ingest_repository_skips_non_completed_runs(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        github_ingest, "_fetch_repository",
        lambda owner, repo, token: {
            "html_url": "https://github.com/mlessley/dast-bench", "name": "dast-bench",
        },
    )
    monkeypatch.setattr(
        github_ingest, "fetch_workflow_runs",
        lambda owner, repo, token: [
            {
                "id": 1, "status": "in_progress", "conclusion": None,
                "head_sha": "abc", "run_started_at": "2026-07-12T00:00:00Z",
            },
        ],
    )

    github_ingest.ingest_repository(driver, "mlessley", "dast-bench")

    build_calls = [c for c in driver.fake_session.calls if "MERGE (b:Build" in c[0]]
    assert build_calls == []


def test_ingest_repository_falls_back_to_actor_login_when_head_commit_absent(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        github_ingest, "_fetch_repository",
        lambda owner, repo, token: {
            "html_url": "https://github.com/mlessley/dast-bench", "name": "dast-bench",
        },
    )
    monkeypatch.setattr(
        github_ingest, "fetch_workflow_runs",
        lambda owner, repo, token: [
            {
                "id": 2,
                "status": "completed",
                "conclusion": "failure",
                "head_sha": "def456",
                "run_started_at": "2026-07-12T01:00:00Z",
                "head_commit": None,
                "actor": {"login": "mlessley"},
            },
        ],
    )

    github_ingest.ingest_repository(driver, "mlessley", "dast-bench")

    commit_call = next(c for c in driver.fake_session.calls if "MERGE (c:Commit" in c[0])
    assert commit_call[1]["author"] == "mlessley"
    assert commit_call[1]["timestamp"] == "2026-07-12T01:00:00Z"


def test_ingest_repository_respects_limit(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        github_ingest, "_fetch_repository",
        lambda owner, repo, token: {
            "html_url": "https://github.com/mlessley/dast-bench", "name": "dast-bench",
        },
    )
    monkeypatch.setattr(
        github_ingest, "fetch_workflow_runs",
        lambda owner, repo, token: [
            {
                "id": i, "status": "completed", "conclusion": "success",
                "head_sha": f"sha{i}", "run_started_at": "2026-07-12T00:00:00Z",
                "head_commit": {"author": {"name": "Mark"}, "timestamp": "2026-07-12T00:00:00Z"},
            }
            for i in range(5)
        ],
    )

    github_ingest.ingest_repository(driver, "mlessley", "dast-bench", limit=2)

    build_calls = [c for c in driver.fake_session.calls if "MERGE (b:Build" in c[0]]
    assert len(build_calls) == 2
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/test_github_ingest.py -v -k ingest_repository`
Expected: FAIL with `AttributeError: module 'scie.graph.github_ingest' has no attribute '_fetch_repository'` (or similar — `ingest_repository` doesn't exist yet either).

- [ ] **Step 7: Implement `_fetch_repository`, `ingest_repository`, and `main`**

Append to `src/scie/graph/github_ingest.py`:

```python
def _fetch_repository(owner: str, repo: str, token: str | None) -> dict:
    response = requests.get(
        f"{GITHUB_API_URL}/repos/{owner}/{repo}",
        headers=_github_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _commit_author_and_timestamp(run: dict) -> tuple[str, str]:
    head_commit = run.get("head_commit")
    if head_commit:
        return head_commit["author"]["name"], head_commit["timestamp"]
    actor = run.get("actor")
    author = actor["login"] if actor else "unknown"
    return author, run["run_started_at"]


def _ingest_run(session, repo_url: str, run: dict) -> None:
    author, timestamp = _commit_author_and_timestamp(run)
    build_id = str(run["id"])

    session.run(
        """
        MATCH (r:Repository {url: $repo_url})
        MERGE (b:Build {id: $build_id})
        SET b.startTime = $start_time, b.ciSystem = 'github-actions', b.status = $status
        MERGE (r)-[:HAS_BUILD]->(b)
        """,
        repo_url=repo_url,
        build_id=build_id,
        start_time=run["run_started_at"],
        status=run["conclusion"],
    )
    session.run(
        """
        MATCH (b:Build {id: $build_id})
        MERGE (c:Commit {sha: $sha})
        SET c.author = $author, c.timestamp = $timestamp
        MERGE (b)-[:FOR_COMMIT]->(c)
        """,
        build_id=build_id,
        sha=run["head_sha"],
        author=author,
        timestamp=timestamp,
    )


def ingest_repository(
    driver: Driver, owner: str, repo: str, token: str | None = None, limit: int = 20,
) -> None:
    repo_data = _fetch_repository(owner, repo, token)
    runs = fetch_workflow_runs(owner, repo, token)
    completed_runs = [run for run in runs if run["status"] == "completed"][:limit]

    with driver.session() as session:
        session.run(
            "MERGE (r:Repository {url: $url}) SET r.name = $name",
            url=repo_data["html_url"],
            name=repo_data["name"],
        )
        for run in completed_runs:
            _ingest_run(session, repo_data["html_url"], run)


def main() -> None:
    driver = get_driver()
    token = os.environ.get("GITHUB_TOKEN")
    ingest_repository(driver, "mlessley", "dast-bench", token=token)
    print("Ingested GitHub Actions build history for mlessley/dast-bench.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_github_ingest.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 9: Run the full test suite**

Run: `uv run pytest -v`
Expected: all PASS (81 pre-existing + 6 new = 87), no regressions.

- [ ] **Step 10: Commit**

```bash
git add src/scie/graph/github_ingest.py tests/test_github_ingest.py
git commit -m "feat: add real GitHub Actions ingestion for mlessley/dast-bench"
```

---

### Task 2: Manual end-to-end verification

**Files:** none — this task exercises the running stack against the real GitHub API and live Neo4j, no code changes.

This is the step that confirms real data actually reaches the graph and renders correctly in Graph Explorer — nothing in Task 1's tests hits a live GitHub or Neo4j, by design.

- [ ] **Step 1: Rebuild the api container so the new module is present**

The `src/` directory is `COPY`'d into the Docker image at build time — a plain restart won't pick up `github_ingest.py`.

Run: `docker compose -p pipeline-lens up -d --build api`
Expected: the container rebuilds and reports `Started`.

- [ ] **Step 2: Run the ingest CLI against the live stack**

Run: `docker exec pipeline-lens-api-1 uv run python -m scie.graph.github_ingest`
Expected: prints `Ingested GitHub Actions build history for mlessley/dast-bench.` with no traceback. (No `GITHUB_TOKEN` needed — the repo is public; if GitHub's unauthenticated rate limit is hit, set `GITHUB_TOKEN` in the container's environment and re-run.)

- [ ] **Step 3: Verify the data landed in Neo4j**

Run:
```bash
docker exec pipeline-lens-neo4j-1 cypher-shell -u neo4j -p devpassword \
  "MATCH (r:Repository {url: 'https://github.com/mlessley/dast-bench'})-[:HAS_BUILD]->(b:Build) RETURN b.id, b.status, b.startTime ORDER BY b.startTime DESC LIMIT 5"
```
Expected: real build rows with real `startTime` values from 2026-07-12 and real `status` values (`success`/`failure`/etc, not the synthetic generator's fixed `"success"`).

- [ ] **Step 4: Verify via the API**

Run: `curl -s --max-time 5 "http://172.19.0.1:18000/graph/repositories" | grep dast-bench`

(Use `172.19.0.1` — the `devx_default` bridge gateway — per the DooD networking note from this session; `localhost` won't reach the Docker host's published ports from inside this sandbox container.)

Expected: `{"url":"https://github.com/mlessley/dast-bench","name":"dast-bench"}` present in the list.

- [ ] **Step 5: Walk through the UI at `http://localhost:8501` → Graph Explorer**

Report back:
- Repository URL mode's dropdown includes `dast-bench` alongside the synthetic `example-org/*` repos.
- Searching it renders the build-history table with real dates/CI status — not the synthetic generator's data.
- The build history table's Artifacts column is empty for these rows (expected — no Artifact data was ingested in this increment).

- [ ] **Step 6: Fix forward if anything in Step 5 doesn't match**

If a specific check fails, note which one — e.g. wrong author/timestamp fallback means revisiting Task 1's `_commit_author_and_timestamp`, not a one-off tweak.
