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


if __name__ == "__main__":
    main()
