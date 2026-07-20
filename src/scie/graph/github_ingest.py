import base64
import hashlib
import os
import tomllib

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


def _fetch_repository(owner: str, repo: str, token: str | None) -> dict:
    response = requests.get(
        f"{GITHUB_API_URL}/repos/{owner}/{repo}",
        headers=_github_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


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
        ingest_dependencies(driver, owner, repo, token=token)
        print(f"Ingested direct dependencies for {owner}/{repo}.")


if __name__ == "__main__":
    main()
