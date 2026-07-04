import json
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from sqlmodel import Session

from scie.db import get_session, init_db
from scie.events import publish_event
from scie.models import PipelineRun, PipelineStatus
from scie.store import PipelineRunStore
from scie.webhooks.github import (
    InvalidSignatureError,
    parse_github_push_payload,
    parse_github_workflow_run_payload,
    verify_github_signature,
)

GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "dev-secret")

app = FastAPI(title="Supply Chain Insights Engine")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/pipeline-runs", response_model=list[PipelineRun])
def list_pipeline_runs(
    status: PipelineStatus | None = None,
    service_name: str | None = None,
    is_synthetic: bool | None = None,
    has_vulnerabilities: bool | None = None,
    session: Session = Depends(get_session),
) -> list[PipelineRun]:
    store = PipelineRunStore(session)
    return store.list(
        status=status,
        service_name=service_name,
        is_synthetic=is_synthetic,
        has_vulnerabilities=has_vulnerabilities,
    )


@app.get("/pipeline-runs/{run_id}", response_model=PipelineRun)
def get_pipeline_run(run_id: str, session: Session = Depends(get_session)) -> PipelineRun:
    store = PipelineRunStore(session)
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="pipeline run not found")
    return run


@app.get("/pipeline-runs/{run_id}/timeline")
def get_pipeline_run_timeline(run_id: str, session: Session = Depends(get_session)) -> dict:
    store = PipelineRunStore(session)
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="pipeline run not found")
    stages = []
    if run.commit is not None:
        stages.append({"stage": "commit", "timestamp": run.commit.timestamp.isoformat()})
    if run.build is not None and run.build.completed_at is not None:
        stages.append({"stage": "build", "timestamp": run.build.completed_at.isoformat()})
    if run.image is not None:
        stages.append({"stage": "image", "timestamp": run.image.pushed_at.isoformat()})
    if run.deployment is not None:
        stages.append({"stage": "deployment", "timestamp": run.deployment.deployed_at.isoformat()})
    stages.sort(key=lambda stage: stage["timestamp"])
    return {"run_id": run_id, "stages": stages}


@app.get("/services")
def list_services(session: Session = Depends(get_session)) -> list[dict]:
    store = PipelineRunStore(session)
    latest: dict[str, PipelineRun] = {}
    for run in store.list():
        current = latest.get(run.service_name)
        if current is None or run.last_updated > current.last_updated:
            latest[run.service_name] = run
    return [
        {
            "service_name": name,
            "overall_status": run.overall_status,
            "last_updated": run.last_updated,
            "is_synthetic": run.is_synthetic,
        }
        for name, run in latest.items()
    ]


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    try:
        verify_github_signature(body, x_hub_signature_256, GITHUB_WEBHOOK_SECRET)
    except InvalidSignatureError:
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(body)
    if x_github_event == "workflow_run":
        event = parse_github_workflow_run_payload(payload)
    else:
        event = parse_github_push_payload(payload)

    publish_event("repo-events", key=event.commit_sha, event=event)
    return {"status": "accepted"}
