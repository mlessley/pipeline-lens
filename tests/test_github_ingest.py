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
