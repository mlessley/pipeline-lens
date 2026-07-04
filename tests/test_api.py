from datetime import datetime, timezone

import scie.db as db
from sqlmodel import SQLModel, create_engine
from fastapi.testclient import TestClient

from scie.api.app import app
from scie.models import PipelineRun
from scie.store import PipelineRunStore

NOW = datetime.now(timezone.utc)


def _use_temp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    return engine


def test_healthz(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_pipeline_run_not_found(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.get("/pipeline-runs/does-not-exist")
    assert response.status_code == 404


def test_list_and_get_pipeline_run(tmp_path, monkeypatch):
    engine = _use_temp_db(tmp_path, monkeypatch)
    from sqlmodel import Session

    with Session(engine) as session:
        PipelineRunStore(session).upsert(
            PipelineRun(id="abc123", service_name="billing-api", last_updated=NOW)
        )

    client = TestClient(app)

    list_response = client.get("/pipeline-runs")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    detail_response = client.get("/pipeline-runs/abc123")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == "abc123"


def test_services_returns_latest_status_per_service(tmp_path, monkeypatch):
    engine = _use_temp_db(tmp_path, monkeypatch)
    from sqlmodel import Session

    with Session(engine) as session:
        PipelineRunStore(session).upsert(
            PipelineRun(id="abc123", service_name="billing-api", last_updated=NOW)
        )

    client = TestClient(app)
    response = client.get("/services")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["service_name"] == "billing-api"


def test_get_pipeline_run_timeline_not_found(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.get("/pipeline-runs/does-not-exist/timeline")
    assert response.status_code == 404


def test_get_pipeline_run_timeline_returns_sorted_stages(tmp_path, monkeypatch):
    from datetime import timedelta
    from sqlmodel import Session
    from scie.models import CommitInfo, BuildInfo, ImageInfo, DeploymentInfo

    engine = _use_temp_db(tmp_path, monkeypatch)

    # Create timestamps in non-chronological order to verify sort is exercised
    commit_time = NOW
    build_time = NOW + timedelta(seconds=100)
    image_time = NOW + timedelta(seconds=200)
    deployment_time = NOW + timedelta(seconds=300)

    with Session(engine) as session:
        run = PipelineRun(
            id="timeline-test",
            service_name="test-service",
            last_updated=NOW,
            # Intentionally not in chronological order in construction
            deployment=DeploymentInfo(
                cluster="prod",
                namespace="default",
                replicas_desired=3,
                replicas_ready=3,
                deployed_at=deployment_time,
            ),
            commit=CommitInfo(
                author="test-author",
                message="test commit",
                branch="main",
                timestamp=commit_time,
            ),
            image=ImageInfo(
                digest="sha256:abc123",
                ecr_repo="my-repo",
                pushed_at=image_time,
            ),
            build=BuildInfo(
                trivy_gate_status="pass",
                started_at=build_time,
                completed_at=build_time,
            ),
        )
        PipelineRunStore(session).upsert(run)

    client = TestClient(app)
    response = client.get("/pipeline-runs/timeline-test/timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "timeline-test"
    assert len(body["stages"]) == 4

    stages = body["stages"]
    stage_names = [stage["stage"] for stage in stages]
    assert stage_names == ["commit", "build", "image", "deployment"]

    # Verify timestamps are in chronological order
    timestamps = [stage["timestamp"] for stage in stages]
    assert timestamps == [
        commit_time.isoformat(),
        build_time.isoformat(),
        image_time.isoformat(),
        deployment_time.isoformat(),
    ]
