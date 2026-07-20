# Real Package Dependencies (uv.lock) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest each real repo's direct dependencies from its `uv.lock` into real `Package`/`IsDependency`/`Artifact` nodes, per `docs/superpowers/specs/2026-07-20-real-package-dependencies-design.md`.

**Architecture:** Two additions to `src/scie/graph/github_ingest.py`: a fetch+parse layer (Task 1, pure functions) that turns a repo's `uv.lock` bytes into `(name, version)` pairs, and a Cypher-writing layer (Task 2) that attaches those as `Package`/`IsDependency` nodes off a new per-repo `Artifact`, wired into `main()`'s existing loop.

**Tech Stack:** `tomllib` (Python stdlib since 3.11, no new dependency), `hashlib` (stdlib), `base64` (stdlib).

## Global Constraints

- Only `uv.lock` is fetched — no `pyproject.toml` — confirmed sufficient on both real repos (spec §1, §2).
- Direct dependencies only, identified via the `[[package]]` entry with `source.editable == "."` — not the full transitive closure (spec §2).
- No changes to `queries.py`, the Neo4j schema/constraints, or the API (spec §2).
- `Artifact.digest` = `"sha256:" + sha256(...).hexdigest()` of the decoded `uv.lock` file bytes (not the base64 string) — a real, reproducible digest, not a placeholder (spec §2).
- `IsDependency`/`Package` Cypher must match `synthetic_graph.py`'s existing shape exactly: `IsDependency {origin}` with `-[:subject]-> Artifact` and `-[:dependency]-> Package` (spec §2).

---

### Task 1: Fetch and parse uv.lock's direct dependencies

**Files:**
- Modify: `src/scie/graph/github_ingest.py`
- Test: `tests/test_github_ingest.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `github_ingest.fetch_file_content(owner: str, repo: str, path: str, token: str | None) -> bytes` (decoded raw file bytes, base64 handled internally); `github_ingest.parse_direct_dependencies(uv_lock_content: bytes) -> list[tuple[str, str]]` (`[(name, version), ...]`, empty list if no `source.editable == "."` entry is found). Task 2 calls both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_github_ingest.py`:

```python
def test_fetch_file_content_decodes_base64_response(monkeypatch):
    captured = {}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResponse({"content": "aGVsbG8="})  # base64 for "hello"

    monkeypatch.setattr(github_ingest.requests, "get", fake_get)

    result = github_ingest.fetch_file_content("mlessley", "pipeline-lens", "uv.lock", None)

    assert captured["url"] == "https://api.github.com/repos/mlessley/pipeline-lens/contents/uv.lock"
    assert "Authorization" not in captured["headers"]
    assert result == b"hello"


def test_parse_direct_dependencies_resolves_names_to_versions():
    uv_lock_content = b"""
[[package]]
name = "scie"
version = "0.1.0"
source = { editable = "." }
dependencies = [
    { name = "fastapi" },
    { name = "streamlit" },
]

[[package]]
name = "fastapi"
version = "0.139.0"

[[package]]
name = "streamlit"
version = "1.58.0"
"""

    result = github_ingest.parse_direct_dependencies(uv_lock_content)

    assert set(result) == {("fastapi", "0.139.0"), ("streamlit", "1.58.0")}


def test_parse_direct_dependencies_returns_empty_list_without_editable_entry():
    uv_lock_content = b"""
[[package]]
name = "fastapi"
version = "0.139.0"
"""

    result = github_ingest.parse_direct_dependencies(uv_lock_content)

    assert result == []


def test_parse_direct_dependencies_skips_names_with_no_resolved_version():
    uv_lock_content = b"""
[[package]]
name = "scie"
version = "0.1.0"
source = { editable = "." }
dependencies = [
    { name = "fastapi" },
    { name = "missing-package" },
]

[[package]]
name = "fastapi"
version = "0.139.0"
"""

    result = github_ingest.parse_direct_dependencies(uv_lock_content)

    assert result == [("fastapi", "0.139.0")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_github_ingest.py -v -k "fetch_file_content or parse_direct_dependencies"`
Expected: FAIL with `AttributeError: module 'scie.graph.github_ingest' has no attribute 'fetch_file_content'` (and similarly for `parse_direct_dependencies`).

- [ ] **Step 3: Implement `fetch_file_content` and `parse_direct_dependencies`**

In `src/scie/graph/github_ingest.py`, add `import base64` and `import tomllib` to the top imports (alongside the existing `import os`), and add these two functions after `_fetch_repository`:

```python
def fetch_file_content(owner: str, repo: str, path: str, token: str | None) -> bytes:
    response = requests.get(
        f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{path}",
        headers=_github_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return base64.b64decode(response.json()["content"])


def parse_direct_dependencies(uv_lock_content: bytes) -> list[tuple[str, str]]:
    data = tomllib.loads(uv_lock_content.decode("utf-8"))
    packages = data.get("package", [])
    versions_by_name = {pkg["name"]: pkg["version"] for pkg in packages}
    own_entry = next(
        (pkg for pkg in packages if pkg.get("source", {}).get("editable") == "."),
        None,
    )
    if own_entry is None:
        return []
    direct_names = [dep["name"] for dep in own_entry.get("dependencies", [])]
    return [
        (name, versions_by_name[name]) for name in direct_names if name in versions_by_name
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_github_ingest.py -v`
Expected: all tests PASS (6 pre-existing + 4 new = 10).

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all PASS (92 pre-existing + 4 net-new = 96), no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/scie/graph/github_ingest.py tests/test_github_ingest.py
git commit -m "feat: fetch and parse uv.lock direct dependencies"
```

---

### Task 2: Write dependencies into Neo4j

**Files:**
- Modify: `src/scie/graph/github_ingest.py`
- Test: `tests/test_github_ingest.py`

**Interfaces:**
- Consumes: `fetch_file_content`, `parse_direct_dependencies` from Task 1.
- Produces: `github_ingest.ingest_dependencies(driver: Driver, owner: str, repo: str, token: str | None = None) -> None`. Called from `main()`'s loop; no other task depends on it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_github_ingest.py`:

```python
def test_ingest_dependencies_writes_artifact_and_packages(monkeypatch):
    driver = FakeDriver()
    driver.fake_session.set_result(
        """
        MATCH (r:Repository {url: $repo_url})-[:HAS_BUILD]->(b:Build)
        RETURN b.id AS id
        ORDER BY b.startTime DESC
        LIMIT 1
        """,
        [{"id": "29694298639"}],
    )
    monkeypatch.setattr(
        github_ingest, "fetch_file_content", lambda owner, repo, path, token: b"fake-uv-lock-bytes",
    )
    monkeypatch.setattr(
        github_ingest, "parse_direct_dependencies",
        lambda content: [("fastapi", "0.139.0"), ("streamlit", "1.58.0")],
    )

    github_ingest.ingest_dependencies(driver, "mlessley", "pipeline-lens")

    calls = driver.fake_session.calls
    expected_digest = "sha256:" + hashlib.sha256(b"fake-uv-lock-bytes").hexdigest()

    artifact_call = next(c for c in calls if "MERGE (a:Artifact" in c[0])
    assert artifact_call[1] == {
        "build_id": "29694298639",
        "digest": expected_digest,
        "name": "pipeline-lens-dependencies",
    }

    package_calls = [c for c in calls if "MERGE (p:Package" in c[0]]
    assert len(package_calls) == 2
    assert {c[1]["purl"] for c in package_calls} == {
        "pkg:pypi/fastapi@0.139.0", "pkg:pypi/streamlit@1.58.0",
    }


def test_ingest_dependencies_does_nothing_when_no_dependencies_found(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        github_ingest, "fetch_file_content", lambda owner, repo, path, token: b"fake-uv-lock-bytes",
    )
    monkeypatch.setattr(github_ingest, "parse_direct_dependencies", lambda content: [])

    github_ingest.ingest_dependencies(driver, "mlessley", "pipeline-lens")

    assert driver.fake_session.calls == []


def test_ingest_dependencies_does_nothing_when_repo_has_no_build(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        github_ingest, "fetch_file_content", lambda owner, repo, path, token: b"fake-uv-lock-bytes",
    )
    monkeypatch.setattr(
        github_ingest, "parse_direct_dependencies", lambda content: [("fastapi", "0.139.0")],
    )
    # No set_result() call for the build-lookup query -> FakeSession.run
    # returns [] for it by default, simulating "no Build found yet".

    github_ingest.ingest_dependencies(driver, "mlessley", "pipeline-lens")

    artifact_calls = [c for c in driver.fake_session.calls if "MERGE (a:Artifact" in c[0]]
    assert artifact_calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_github_ingest.py -v -k ingest_dependencies`
Expected: FAIL with `AttributeError: module 'scie.graph.github_ingest' has no attribute 'ingest_dependencies'`.

- [ ] **Step 3: Implement `ingest_dependencies` and wire it into `main()`**

In `src/scie/graph/github_ingest.py`, add `import hashlib` to the top imports. Add this function after `ingest_repository`:

```python
def _write_dependencies(
    session, build_id: str, repo_name: str, uv_lock_content: bytes, dependencies: list[tuple[str, str]],
) -> None:
    digest = "sha256:" + hashlib.sha256(uv_lock_content).hexdigest()

    session.run(
        """
        MATCH (b:Build {id: $build_id})
        MERGE (a:Artifact {digest: $digest})
        SET a.name = $name
        MERGE (b)-[:PRODUCED]->(a)
        """,
        build_id=build_id,
        digest=digest,
        name=f"{repo_name}-dependencies",
    )
    for name, version in dependencies:
        session.run(
            """
            MATCH (a:Artifact {digest: $digest})
            MERGE (p:Package {purl: $purl})
            SET p.name = $name, p.version = $version
            CREATE (dep:IsDependency {origin: 'uv.lock'})
            CREATE (dep)-[:subject]->(a)
            CREATE (dep)-[:dependency]->(p)
            """,
            digest=digest,
            purl=f"pkg:pypi/{name}@{version}",
            name=name,
            version=version,
        )


def ingest_dependencies(
    driver: Driver, owner: str, repo: str, token: str | None = None,
) -> None:
    uv_lock_content = fetch_file_content(owner, repo, "uv.lock", token)
    dependencies = parse_direct_dependencies(uv_lock_content)
    if not dependencies:
        return

    repo_url = f"https://github.com/{owner}/{repo}"
    with driver.session() as session:
        records = list(session.run(
            """
            MATCH (r:Repository {url: $repo_url})-[:HAS_BUILD]->(b:Build)
            RETURN b.id AS id
            ORDER BY b.startTime DESC
            LIMIT 1
            """,
            repo_url=repo_url,
        ))
        if not records:
            return
        _write_dependencies(session, records[0]["id"], repo, uv_lock_content, dependencies)
```

Then change `main()` from:

```python
def main() -> None:
    driver = get_driver()
    token = os.environ.get("GITHUB_TOKEN")
    for owner, repo in REPOS:
        ingest_repository(driver, owner, repo, token=token)
        print(f"Ingested GitHub Actions build history for {owner}/{repo}.")
```

to:

```python
def main() -> None:
    driver = get_driver()
    token = os.environ.get("GITHUB_TOKEN")
    for owner, repo in REPOS:
        ingest_repository(driver, owner, repo, token=token)
        print(f"Ingested GitHub Actions build history for {owner}/{repo}.")
        ingest_dependencies(driver, owner, repo, token=token)
        print(f"Ingested direct dependencies for {owner}/{repo}.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_github_ingest.py -v`
Expected: all tests PASS (10 pre-existing after Task 1 + 3 new = 13). Note: `hashlib` must be imported at the top of `tests/test_github_ingest.py` too, for the expected-digest computation in the first new test — add `import hashlib` there, it isn't currently imported.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all PASS (96 pre-existing + 3 net-new = 99), no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/scie/graph/github_ingest.py tests/test_github_ingest.py
git commit -m "feat: ingest real package dependencies from uv.lock into Neo4j"
```

---

### Task 3: Manual verification

**Files:** none — this task exercises the running stack, no code changes.

- [ ] **Step 1: Rebuild the api container**

Run: `docker compose -p pipeline-lens up -d --build api`
Expected: the container rebuilds and reports `Started`.

- [ ] **Step 2: Run the ingest CLI**

Run: `docker exec pipeline-lens-api-1 uv run python -m scie.graph.github_ingest`
Expected: prints two lines per repo — the existing build-history line, then a
new `Ingested direct dependencies for {owner}/{repo}.` line — no traceback.

- [ ] **Step 3: Verify real Package nodes landed in Neo4j**

Run:
```bash
docker exec pipeline-lens-neo4j-1 cypher-shell -u neo4j -p devpassword \
  "MATCH (a:Artifact {name: 'pipeline-lens-dependencies'})<-[:PRODUCED]-(b:Build) MATCH (a)<-[:subject]-(dep:IsDependency)-[:dependency]->(p:Package) RETURN p.purl ORDER BY p.purl"
```
Expected: 12 rows, one per `pipeline-lens` direct dependency (`pkg:pypi/boto3@...`, `pkg:pypi/fastapi@...`, `pkg:pypi/streamlit@...`, etc.).

- [ ] **Step 4: Verify via the API and UI**

Run: `curl -s --max-time 5 "http://172.19.0.1:18000/graph/packages" | grep fastapi`
Expected: a real `fastapi` entry present.

Open `http://localhost:8501` → Graph Explorer → Package PURL mode.
Confirm the dropdown now includes real packages like `fastapi@0.139.0` or
`streamlit@1.58.0` alongside the synthetic ones (`openssl@1.0.0` etc.).
Search one — confirm `package_usage` traces it back to the real
`pipeline-lens` repository/build via the existing graph view, with no
query-layer changes needed. Report back what you see.

- [ ] **Step 5: Fix forward if anything in Step 4 doesn't match**

If a real package doesn't trace back to its repo correctly, check
`_write_dependencies`'s `MATCH (a:Artifact {digest: $digest})` in the
per-package loop — it depends on the `MERGE (a:Artifact ...)` in the same
function having already run in the same session, which it does since both
are called from `ingest_dependencies` in sequence.
