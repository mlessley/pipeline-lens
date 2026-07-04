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
