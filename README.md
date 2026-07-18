# Pipeline Lens

## The Problem

Modern software delivery is fragmented across tools that don't talk to each
other. A commit lands in GitHub, a pipeline builds and scans it, a container
gets deployed to Kubernetes — and today, answering a simple question like
"what's actually running in production, and is it safe?" means manually
checking three or four different systems with no shared context between them.

## What Pipeline Lens Does

Pipeline Lens is a working prototype that solves this by correlating events
across the software delivery lifecycle into a single, queryable "pipeline run"
record — from commit, through build and vulnerability scanning, to what's
actually deployed and running. It's a fleet-wide view of software delivery
health, built the way I'd approach it in production: event-driven ingestion,
durable workflow orchestration, and a normalized data model that new sources
can be added to without re-architecting the system.

This isn't a dashboard bolted onto one tool's output — it's an independent
correlation layer that pulls from multiple heterogeneous sources (CI/CD events,
container scan results, live cluster state) and gives you one place to ask
questions none of those tools can answer alone.

## Why This Architecture

The design choices reflect how I'd build this for a real organization, not
just a demo:

- **Event-driven, not polling-based** — GitHub webhooks trigger the pipeline
  in real time rather than periodic scraping
- **Durable workflows (Temporal)** — a pipeline run might wait on a slow scan
  or a deployment that takes minutes; Temporal makes that reliable without
  custom retry/state logic
- **Normalized schema** — GitHub, ECR scan results, and Kubernetes state all
  land in one unified `pipeline_run` record, decoupled from any single
  source's format
- **Read/write separation** — the worker and bridge handle ingestion, the API
  is a clean read layer the dashboard (or anything else) can consume

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

* `api` — FastAPI app; receives GitHub webhooks, publishes to RedPanda, and serves the read API the dashboard consumes.
* `bridge` — consumes `repo-events` from RedPanda and starts a `PipelineRunWorkflow` in Temporal for each completed `workflow_run` event.
* `worker` — the Temporal worker process; registers `PipelineRunWorkflow` and its activities and polls the task queue so workflows the bridge starts actually execute.
* `dashboard` — Streamlit fleet overview and per-service detail/timeline view.
* `redpanda`, `temporal` — the messaging and workflow-engine infrastructure; `postgres` is Temporal's own history store, not the app's data.

For demos (no live GitHub/AWS/Kubernetes needed), `scie.seed` populates the same database with a synthetic fleet (`generate_synthetic_fleet`) that exercises the identical data model and API/dashboard code paths as the real path above, just without going through RedPanda/Temporal/AWS/K8s.

## The Graph Layer (In Progress)

The flat `pipeline_run` record above is good enough to answer "what's
running and is it healthy," but not deeper lineage questions like "if this
vulnerability shows up in a scan, which commit introduced it, which services
deploy that image, and is it exposed anywhere right now." That's a graph
problem more than a relational one — the relationships between commits,
images, deployments, and findings matter as much as the records themselves.

This is a separate, incremental layer being added alongside v1, not a
rewrite of it: Neo4j, a hand-written Cypher query layer, and a "Graph
Explorer" page in the dashboard that renders results as a graph you can
click through — identifying labels instead of raw node types, attestation
relationships shown as edge labels instead of extra clutter on the canvas.
Most of the data behind it is still a synthetic fleet, same as v1's — one
real repository (`mlessley/dast-bench`) has its actual GitHub Actions build
history ingested too, as a first, small step toward confirming the schema
holds up against real data and not just a generator.

What's not built yet: real SBOM/SARIF/provenance ingestion, a
build-completeness correlation workflow, and moving the relational store
off SQLite to Postgres as an ingestion ledger. That fuller design — node/edge
modeling adapting GUAC's attestation-as-node pattern, the ingestion
architecture, the completeness workflow — is written up in
[`docs/phase2-graph-model.md`](docs/phase2-graph-model.md), but design
docs are cheap and this part of the project is genuinely still evolving.
To be clear, this whole repo is a personal project built to learn this
architecture hands-on, not something running in production — this graph
layer especially is the newest and roughest part of it.

## Running Locally

```
docker compose up -d
docker compose exec api uv run python -m scie.seed
docker compose exec api uv run python -m scie.graph.seed
```

Then open the dashboard at `http://localhost:8501` (API at `http://localhost:8000`) — the
"Graph Explorer" page is in the sidebar. Neo4j Browser is available directly at
`http://localhost:7474` (user `neo4j`, password `devpassword`) for sanity-checking the
seeded graph.

## Tests

```
uv run pytest -v
```
