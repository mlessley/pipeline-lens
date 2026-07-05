# Pipeline Lens

A portfolio proof-of-concept that tracks a software service's journey from commit to running
deployment, correlating events from GitHub Actions, a container registry vulnerability scan, and a
Kubernetes cluster into a single "pipeline run" record, and exposing that fleet-wide view through an
API and a dashboard. It exists to demonstrate integration and orchestration work across a real
event-driven pipeline (webhook ingestion, a message broker, a durable workflow engine, and a
queryable API) rather than any single component in isolation.

## Architecture

The real event flow:

```
GitHub webhook (workflow_run)
  -> FastAPI webhook endpoint
  -> RedPanda topic (repo-events)
  -> bridge (Kafka consumer -> Temporal client)
  -> Temporal workflow (PipelineRunWorkflow), run by the worker
       -> wait_for_ecr_scan_activity   (ECR vulnerability scan results)
       -> get_k8s_deployment_state_activity (live Deployment/Pod status)
       -> write_pipeline_run_activity  (persists the finished run)
  -> SQLite (shared by the API and the worker)
  -> FastAPI query endpoints (/services, /pipeline-runs, /pipeline-runs/{id}/timeline)
  -> Streamlit dashboard
```

Each service in `docker-compose.yml` maps directly onto one stage of that flow:

- `api` — FastAPI app; receives GitHub webhooks, publishes to RedPanda, and serves the read API the
  dashboard consumes.
- `bridge` — consumes `repo-events` from RedPanda and starts a `PipelineRunWorkflow` in Temporal for
  each completed `workflow_run` event.
- `worker` — the Temporal worker process; registers `PipelineRunWorkflow` and its activities and
  polls the task queue so workflows the bridge starts actually execute.
- `dashboard` — Streamlit fleet overview and per-service detail/timeline view.
- `redpanda`, `postgres`, `temporal` — the messaging and workflow-engine infrastructure.

For demos (no live GitHub/AWS/Kubernetes needed), `scie.seed` populates the same database with a
synthetic fleet (`generate_synthetic_fleet`) that exercises the identical data model and API/
dashboard code paths as the real path above, just without going through RedPanda/Temporal/AWS/K8s.

## Running locally

```bash
docker compose up -d
docker compose exec api uv run python -m scie.seed
```

Then open the dashboard at `http://localhost:8501` (API at `http://localhost:8000`).

## Tests

```bash
uv run pytest -v
```
