# Supply Chain Insights Engine — V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1 vertical slice of the Supply Chain Insights Engine: a real, event-driven pipeline that correlates GitHub commit/CI data, ECR image/scan data, and K8s deployment data into a unified `PipelineRun` record, served via FastAPI and displayed in Streamlit, with a synthetic-fleet generator for scale.

**Architecture:** GitHub webhooks and a bounded ECR-scan-wait publish events onto RedPanda topics; a Temporal workflow per commit SHA consumes those events (via a small bridge process), calls activities to enrich with ECR scan results and K8s deployment state, and persists the correlated `PipelineRun` to SQLite via a thin store. FastAPI exposes query endpoints over that store; Streamlit renders them. Real AWS (ECR, IAM, EKS) is provisioned via Terraform and treated as a bounded dependency, not application-managed infrastructure.

**Tech Stack:** Python 3.12, uv, FastAPI, pydantic v2, SQLModel + SQLite, confluent-kafka (against RedPanda), temporalio, boto3, kubernetes (python client), Streamlit, pytest.

## Global Constraints

- Package/project management: `uv` exclusively — no pip/poetry/conda commands anywhere in this plan.
- Core stack: FastAPI, pydantic v2, Streamlit, Temporal.io (per the original hard constraints).
- Deployment: containerized; local pieces run via Docker Compose.
- Phase: PoC — mock/skip production-grade hardening explicitly called out as stretch in the spec; do not add retry/validation/error-handling beyond what each task specifies.
- Vulnerability data comes only from ECR's scan-on-push; Trivy in CI is a pass/fail gate only (per spec's Data Model section) — do not build a second vulnerability schema for Trivy findings.
- `overall_status` semantics are fixed by the spec: `Failed` is set immediately on explicit failure (never via timeout), `Deployed` vs `DeployedWithFindings` is decided solely by whether `image.vulnerabilities` is non-empty. `Stalled`/`Abandoned` are out of scope for v1 (spec defers the reconciliation sweep that produces them to stretch) — do not add half-built timeout/stall logic in this plan.

**Out of scope for this plan** (spec's stretch items — a separate follow-up plan once v1 ships): the full kube-state-metrics + Prometheus + AlertManager pipeline, the `ReconciliationWorkflow` + Temporal Schedule, the manual retry endpoint/UI action, and the Streamlit "how this works" tab.

---

## File Structure

```
scie/
├── pyproject.toml
├── docker-compose.yml
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── ecr.tf
│   ├── iam.tf
│   └── eks.tf
├── .github/workflows/ci.yml
├── src/scie/
│   ├── __init__.py
│   ├── models.py              # pydantic v2 domain models (RepoEvent, ImageEvent, K8sEvent, PipelineRun, ...)
│   ├── status.py               # compute_overall_status()
│   ├── synthetic.py            # generate_synthetic_fleet()
│   ├── db.py                   # SQLModel engine + get_session() + init_db()
│   ├── store.py                # PipelineRunStore (get/list/upsert)
│   ├── events.py                # RedPanda publisher: publish_event()
│   ├── webhooks/
│   │   ├── __init__.py
│   │   └── github.py           # verify_github_signature(), parse_github_push_payload()
│   ├── api/
│   │   ├── __init__.py
│   │   └── app.py              # FastAPI app: healthz, pipeline-runs, services, webhooks/github
│   ├── workflows/
│   │   ├── __init__.py
│   │   ├── activities.py       # wait_for_ecr_scan_activity, get_k8s_deployment_state_activity, write_pipeline_run_activity
│   │   └── pipeline_run_workflow.py  # PipelineRunWorkflow
│   ├── bridge.py                # RedPanda consumer -> Temporal signal-with-start bridge
│   └── ui/
│       └── streamlit_app.py     # Streamlit dashboard
└── tests/
    ├── test_models.py
    ├── test_status.py
    ├── test_synthetic.py
    ├── test_store.py
    ├── test_github_webhook_parsing.py
    ├── test_events.py
    ├── test_api.py
    ├── test_activities.py
    ├── test_pipeline_run_workflow.py
    └── test_bridge.py
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml` (via `uv init`)
- Create: `src/scie/__init__.py`

**Interfaces:**
- Produces: an importable `scie` package and a `uv run pytest` command every later task relies on.

- [ ] **Step 1: Initialize the uv package**

Run:
```bash
cd /devx/repos/scie
uv init --package scie --python 3.12
```
Expected: creates `pyproject.toml`, `src/scie/__init__.py`, `README.md`.

- [ ] **Step 2: Add runtime dependencies**

Run:
```bash
uv add fastapi "uvicorn[standard]" pydantic sqlmodel confluent-kafka temporalio boto3 kubernetes streamlit httpx
```

- [ ] **Step 3: Add dev/test dependencies**

Run:
```bash
uv add --dev pytest pytest-asyncio
```

- [ ] **Step 4: Verify the environment resolves and imports work**

Run:
```bash
uv run python -c "import fastapi, pydantic, sqlmodel, confluent_kafka, temporalio, boto3, kubernetes, streamlit; print('ok')"
```
Expected: prints `ok` with no import errors.

- [ ] **Step 5: Verify pytest runs (no tests yet)**

Run: `uv run pytest`
Expected: `no tests ran` (exit code 0 or 5, no collection errors).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/scie/__init__.py README.md
git commit -m "chore: scaffold uv package"
```

---

### Task 2: Core domain models

**Files:**
- Create: `src/scie/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `PipelineStatus`, `VulnerabilitySeverity`, `VulnerabilityFinding`, `PodStatus`, `RepoEvent`, `ImageEvent`, `K8sEvent`, `CommitInfo`, `BuildInfo`, `ImageInfo` (with `.vulnerability_summary` property), `DeploymentInfo`, `PipelineRun` — all pydantic v2 `BaseModel`s, used by every later task.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from datetime import datetime, timezone

from scie.models import (
    PipelineRun,
    PipelineStatus,
    CommitInfo,
    ImageInfo,
    VulnerabilityFinding,
    VulnerabilitySeverity,
)


def test_pipeline_run_defaults_to_in_progress_with_no_stages():
    run = PipelineRun(
        id="abc123",
        service_name="billing-api",
        last_updated=datetime.now(timezone.utc),
    )
    assert run.overall_status == PipelineStatus.IN_PROGRESS
    assert run.commit is None
    assert run.is_synthetic is False


def test_image_info_vulnerability_summary_counts_by_severity():
    image = ImageInfo(
        digest="sha256:abc",
        ecr_repo="billing-api",
        pushed_at=datetime.now(timezone.utc),
        vulnerabilities=[
            VulnerabilityFinding(
                cve_id="CVE-2025-1111",
                severity=VulnerabilitySeverity.HIGH,
                package_name="openssl",
                package_version="1.0.0",
            ),
            VulnerabilityFinding(
                cve_id="CVE-2025-2222",
                severity=VulnerabilitySeverity.HIGH,
                package_name="requests",
                package_version="2.0.0",
            ),
        ],
    )
    assert image.vulnerability_summary["HIGH"] == 2
    assert image.vulnerability_summary["CRITICAL"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.models'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/models.py
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PipelineStatus(str, Enum):
    IN_PROGRESS = "InProgress"
    DEPLOYED = "Deployed"
    DEPLOYED_WITH_FINDINGS = "DeployedWithFindings"
    FAILED = "Failed"
    STALLED = "Stalled"
    ABANDONED = "Abandoned"


class VulnerabilitySeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class VulnerabilityFinding(BaseModel):
    cve_id: str
    severity: VulnerabilitySeverity
    package_name: str
    package_version: str


class PodStatus(BaseModel):
    pod_name: str
    phase: str
    ready: bool


class RepoEvent(BaseModel):
    commit_sha: str
    repo: str
    branch: str
    author: str
    message: str
    pr_number: int | None = None
    event_type: str
    workflow_run_id: str | None = None
    workflow_conclusion: str | None = None
    timestamp: datetime


class ImageEvent(BaseModel):
    image_digest: str
    image_tag: str
    ecr_repo: str
    pushed_at: datetime
    vulnerabilities: list[VulnerabilityFinding] = Field(default_factory=list)
    scan_completed_at: datetime | None = None


class K8sEvent(BaseModel):
    deployment_name: str
    namespace: str
    cluster: str
    running_image_ref: str
    replicas_desired: int
    replicas_ready: int
    pod_statuses: list[PodStatus] = Field(default_factory=list)
    reason: str | None = None
    observed_at: datetime


class CommitInfo(BaseModel):
    author: str
    message: str
    branch: str
    pr_number: int | None = None
    timestamp: datetime


class BuildInfo(BaseModel):
    workflow_run_id: str | None = None
    trivy_gate_status: str
    started_at: datetime
    completed_at: datetime | None = None
    conclusion: str | None = None


class ImageInfo(BaseModel):
    digest: str
    ecr_repo: str
    pushed_at: datetime
    vulnerabilities: list[VulnerabilityFinding] = Field(default_factory=list)

    @property
    def vulnerability_summary(self) -> dict[str, int]:
        summary = {severity.value: 0 for severity in VulnerabilitySeverity}
        for finding in self.vulnerabilities:
            summary[finding.severity.value] += 1
        return summary


class DeploymentInfo(BaseModel):
    cluster: str
    namespace: str
    replicas_desired: int
    replicas_ready: int
    pod_statuses: list[PodStatus] = Field(default_factory=list)
    deployed_at: datetime


class PipelineRun(BaseModel):
    id: str
    service_name: str
    is_synthetic: bool = False
    commit: CommitInfo | None = None
    build: BuildInfo | None = None
    image: ImageInfo | None = None
    deployment: DeploymentInfo | None = None
    overall_status: PipelineStatus = PipelineStatus.IN_PROGRESS
    last_updated: datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/models.py tests/test_models.py
git commit -m "feat: add core pydantic v2 domain models"
```

---

### Task 3: Status computation logic

**Files:**
- Create: `src/scie/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: `PipelineRun`, `PipelineStatus`, `BuildInfo`, `ImageInfo`, `VulnerabilityFinding`, `VulnerabilitySeverity` from `scie.models` (Task 2).
- Produces: `compute_overall_status(run: PipelineRun) -> PipelineStatus`, used by Task 4 (synthetic) and Task 11 (workflow).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_status.py
from datetime import datetime, timezone

from scie.models import (
    PipelineRun,
    PipelineStatus,
    BuildInfo,
    ImageInfo,
    DeploymentInfo,
    VulnerabilityFinding,
    VulnerabilitySeverity,
)
from scie.status import compute_overall_status

NOW = datetime.now(timezone.utc)


def _base_run(**overrides) -> PipelineRun:
    defaults = dict(id="abc123", service_name="billing-api", last_updated=NOW)
    defaults.update(overrides)
    return PipelineRun(**defaults)


def test_no_build_or_deployment_is_in_progress():
    run = _base_run()
    assert compute_overall_status(run) == PipelineStatus.IN_PROGRESS


def test_build_conclusion_failure_is_failed_immediately():
    run = _base_run(
        build=BuildInfo(trivy_gate_status="Pass", started_at=NOW, conclusion="failure")
    )
    assert compute_overall_status(run) == PipelineStatus.FAILED


def test_trivy_gate_failure_is_failed():
    run = _base_run(
        build=BuildInfo(trivy_gate_status="Fail", started_at=NOW, conclusion="success")
    )
    assert compute_overall_status(run) == PipelineStatus.FAILED


def test_deployed_with_no_vulnerabilities_is_deployed():
    run = _base_run(
        build=BuildInfo(trivy_gate_status="Pass", started_at=NOW, conclusion="success"),
        image=ImageInfo(digest="sha256:x", ecr_repo="billing-api", pushed_at=NOW),
        deployment=DeploymentInfo(
            cluster="scie-poc",
            namespace="default",
            replicas_desired=2,
            replicas_ready=2,
            deployed_at=NOW,
        ),
    )
    assert compute_overall_status(run) == PipelineStatus.DEPLOYED


def test_deployed_with_vulnerabilities_is_deployed_with_findings():
    run = _base_run(
        build=BuildInfo(trivy_gate_status="Pass", started_at=NOW, conclusion="success"),
        image=ImageInfo(
            digest="sha256:x",
            ecr_repo="billing-api",
            pushed_at=NOW,
            vulnerabilities=[
                VulnerabilityFinding(
                    cve_id="CVE-2025-1111",
                    severity=VulnerabilitySeverity.HIGH,
                    package_name="openssl",
                    package_version="1.0.0",
                )
            ],
        ),
        deployment=DeploymentInfo(
            cluster="scie-poc",
            namespace="default",
            replicas_desired=2,
            replicas_ready=2,
            deployed_at=NOW,
        ),
    )
    assert compute_overall_status(run) == PipelineStatus.DEPLOYED_WITH_FINDINGS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.status'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/status.py
from scie.models import PipelineRun, PipelineStatus


def compute_overall_status(run: PipelineRun) -> PipelineStatus:
    if run.build is not None and run.build.conclusion == "failure":
        return PipelineStatus.FAILED
    if run.build is not None and run.build.trivy_gate_status == "Fail":
        return PipelineStatus.FAILED
    if run.deployment is not None:
        if run.image is not None and len(run.image.vulnerabilities) > 0:
            return PipelineStatus.DEPLOYED_WITH_FINDINGS
        return PipelineStatus.DEPLOYED
    return PipelineStatus.IN_PROGRESS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_status.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/status.py tests/test_status.py
git commit -m "feat: add overall_status computation"
```

---

### Task 4: Synthetic fleet generator

**Files:**
- Create: `src/scie/synthetic.py`
- Test: `tests/test_synthetic.py`

**Interfaces:**
- Consumes: `PipelineRun`, `CommitInfo`, `BuildInfo`, `ImageInfo`, `DeploymentInfo`, `PodStatus`, `VulnerabilityFinding`, `VulnerabilitySeverity` (Task 2); `compute_overall_status` (Task 3).
- Produces: `generate_synthetic_fleet(count: int = 20, seed: int | None = None) -> list[PipelineRun]`, used by Task 5's tests and the app's seed step.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_synthetic.py
from scie.models import PipelineStatus
from scie.synthetic import generate_synthetic_fleet


def test_generates_requested_count():
    fleet = generate_synthetic_fleet(count=10, seed=42)
    assert len(fleet) == 10


def test_all_generated_runs_are_flagged_synthetic():
    fleet = generate_synthetic_fleet(count=5, seed=42)
    assert all(run.is_synthetic for run in fleet)


def test_generated_runs_have_a_valid_terminal_status():
    fleet = generate_synthetic_fleet(count=20, seed=42)
    assert all(
        run.overall_status in (PipelineStatus.DEPLOYED, PipelineStatus.DEPLOYED_WITH_FINDINGS)
        for run in fleet
    )


def test_same_seed_is_deterministic():
    first = generate_synthetic_fleet(count=5, seed=7)
    second = generate_synthetic_fleet(count=5, seed=7)
    assert [run.id for run in first] == [run.id for run in second]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synthetic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.synthetic'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/synthetic.py
import random
from datetime import datetime, timedelta, timezone

from scie.models import (
    CommitInfo,
    BuildInfo,
    ImageInfo,
    DeploymentInfo,
    PipelineRun,
    PodStatus,
    VulnerabilityFinding,
    VulnerabilitySeverity,
)
from scie.status import compute_overall_status

SERVICE_NAMES = [
    "billing-api",
    "auth-service",
    "notification-worker",
    "inventory-sync",
    "payments-gateway",
    "user-profile",
    "search-indexer",
    "audit-logger",
]

AUTHORS = ["alice", "bob", "carol"]
MESSAGES = ["fix bug", "add feature", "update deps", "improve logging"]
PACKAGES = ["openssl", "requests", "urllib3", "jinja2"]


def generate_synthetic_fleet(count: int = 20, seed: int | None = None) -> list[PipelineRun]:
    rng = random.Random(seed)
    runs: list[PipelineRun] = []
    for i in range(count):
        service_name = f"{rng.choice(SERVICE_NAMES)}-{i}"
        commit_sha = f"synthetic{i:04d}"
        base_time = datetime.now(timezone.utc) - timedelta(hours=rng.randint(0, 72))

        commit = CommitInfo(
            author=rng.choice(AUTHORS),
            message=rng.choice(MESSAGES),
            branch="main",
            pr_number=rng.randint(1, 500),
            timestamp=base_time,
        )
        build = BuildInfo(
            workflow_run_id=f"run-{i}",
            trivy_gate_status="Pass",
            started_at=base_time,
            completed_at=base_time + timedelta(minutes=5),
            conclusion="success",
        )
        vuln_count = rng.choice([0, 0, 0, 1, 2])
        vulnerabilities = [
            VulnerabilityFinding(
                cve_id=f"CVE-2025-{rng.randint(1000, 9999)}",
                severity=rng.choice(list(VulnerabilitySeverity)),
                package_name=rng.choice(PACKAGES),
                package_version="1.0.0",
            )
            for _ in range(vuln_count)
        ]
        image = ImageInfo(
            digest=f"sha256:{commit_sha}",
            ecr_repo=service_name,
            pushed_at=base_time + timedelta(minutes=6),
            vulnerabilities=vulnerabilities,
        )
        deployment = DeploymentInfo(
            cluster="scie",
            namespace="default",
            replicas_desired=2,
            replicas_ready=2,
            pod_statuses=[
                PodStatus(pod_name=f"{service_name}-{j}", phase="Running", ready=True)
                for j in range(2)
            ],
            deployed_at=base_time + timedelta(minutes=8),
        )
        run = PipelineRun(
            id=commit_sha,
            service_name=service_name,
            is_synthetic=True,
            commit=commit,
            build=build,
            image=image,
            deployment=deployment,
            last_updated=base_time + timedelta(minutes=8),
        )
        run.overall_status = compute_overall_status(run)
        runs.append(run)
    return runs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synthetic.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/synthetic.py tests/test_synthetic.py
git commit -m "feat: add synthetic fleet generator"
```

---

### Task 5: Persistence layer

**Files:**
- Create: `src/scie/db.py`
- Create: `src/scie/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `PipelineRun`, `PipelineStatus` (Task 2); `generate_synthetic_fleet` (Task 4, tests only).
- Produces: `engine`, `init_db()`, `get_session()` from `scie.db`; `PipelineRunStore` with `.upsert(run: PipelineRun) -> None`, `.get(run_id: str) -> PipelineRun | None`, `.list(status=None, service_name=None, is_synthetic=None, has_vulnerabilities=None) -> list[PipelineRun]` from `scie.store` — used by Task 6 (API), Task 10 (activities).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store.py
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from scie.models import PipelineRun, PipelineStatus, ImageInfo, VulnerabilityFinding, VulnerabilitySeverity
from scie.store import PipelineRunStore

NOW = datetime.now(timezone.utc)


def _make_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    return engine


def test_upsert_then_get_round_trips(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        run = PipelineRun(id="abc123", service_name="billing-api", last_updated=NOW)
        store.upsert(run)

        fetched = store.get("abc123")
        assert fetched is not None
        assert fetched.id == "abc123"
        assert fetched.service_name == "billing-api"


def test_get_missing_returns_none(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        assert store.get("does-not-exist") is None


def test_upsert_overwrites_existing_record(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        run = PipelineRun(id="abc123", service_name="billing-api", last_updated=NOW)
        store.upsert(run)

        run.overall_status = PipelineStatus.FAILED
        store.upsert(run)

        fetched = store.get("abc123")
        assert fetched.overall_status == PipelineStatus.FAILED


def test_list_filters_by_service_name_and_synthetic(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        store.upsert(PipelineRun(id="1", service_name="billing-api", is_synthetic=True, last_updated=NOW))
        store.upsert(PipelineRun(id="2", service_name="auth-service", is_synthetic=False, last_updated=NOW))

        results = store.list(service_name="billing-api")
        assert [r.id for r in results] == ["1"]

        results = store.list(is_synthetic=False)
        assert [r.id for r in results] == ["2"]


def test_list_filters_by_has_vulnerabilities(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        vulnerable = PipelineRun(
            id="1",
            service_name="billing-api",
            last_updated=NOW,
            image=ImageInfo(
                digest="sha256:x",
                ecr_repo="billing-api",
                pushed_at=NOW,
                vulnerabilities=[
                    VulnerabilityFinding(
                        cve_id="CVE-2025-1111",
                        severity=VulnerabilitySeverity.HIGH,
                        package_name="openssl",
                        package_version="1.0.0",
                    )
                ],
            ),
        )
        clean = PipelineRun(id="2", service_name="auth-service", last_updated=NOW)
        store.upsert(vulnerable)
        store.upsert(clean)

        results = store.list(has_vulnerabilities=True)
        assert [r.id for r in results] == ["1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.store'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/db.py
import os

from sqlmodel import SQLModel, Session, create_engine

DATABASE_URL = os.environ.get("SCIE_DATABASE_URL", "sqlite:///./scie.db")
engine = create_engine(DATABASE_URL, echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
```

```python
# src/scie/store.py
from sqlmodel import Field, Session, SQLModel, select

from scie.models import PipelineRun, PipelineStatus


class PipelineRunRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    service_name: str = Field(index=True)
    overall_status: str = Field(index=True)
    is_synthetic: bool = Field(index=True)
    has_vulnerabilities: bool = Field(index=True, default=False)
    last_updated: str
    payload: str


class PipelineRunStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, run: PipelineRun) -> None:
        has_vulnerabilities = bool(run.image and len(run.image.vulnerabilities) > 0)
        record = PipelineRunRecord(
            id=run.id,
            service_name=run.service_name,
            overall_status=run.overall_status.value,
            is_synthetic=run.is_synthetic,
            has_vulnerabilities=has_vulnerabilities,
            last_updated=run.last_updated.isoformat(),
            payload=run.model_dump_json(),
        )
        self.session.merge(record)
        self.session.commit()

    def get(self, run_id: str) -> PipelineRun | None:
        record = self.session.get(PipelineRunRecord, run_id)
        if record is None:
            return None
        return PipelineRun.model_validate_json(record.payload)

    def list(
        self,
        status: PipelineStatus | None = None,
        service_name: str | None = None,
        is_synthetic: bool | None = None,
        has_vulnerabilities: bool | None = None,
    ) -> list[PipelineRun]:
        query = select(PipelineRunRecord)
        if status is not None:
            query = query.where(PipelineRunRecord.overall_status == status.value)
        if service_name is not None:
            query = query.where(PipelineRunRecord.service_name == service_name)
        if is_synthetic is not None:
            query = query.where(PipelineRunRecord.is_synthetic == is_synthetic)
        if has_vulnerabilities is not None:
            query = query.where(PipelineRunRecord.has_vulnerabilities == has_vulnerabilities)
        records = self.session.exec(query).all()
        return [PipelineRun.model_validate_json(record.payload) for record in records]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/db.py src/scie/store.py tests/test_store.py
git commit -m "feat: add SQLite-backed PipelineRunStore"
```

---

### Task 6: FastAPI query API

**Files:**
- Create: `src/scie/api/__init__.py`
- Create: `src/scie/api/app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `PipelineRun`, `PipelineStatus` (Task 2); `engine`, `init_db`, `get_session` (Task 5's `scie.db`); `PipelineRunStore` (Task 5's `scie.store`).
- Produces: FastAPI `app` object with routes `GET /healthz`, `GET /pipeline-runs`, `GET /pipeline-runs/{run_id}`, `GET /pipeline-runs/{run_id}/timeline`, `GET /services` — extended by Task 9 with the webhook route.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.api'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/api/__init__.py
```

```python
# src/scie/api/app.py
from fastapi import Depends, FastAPI, HTTPException
from sqlmodel import Session

from scie.db import get_session, init_db
from scie.models import PipelineRun, PipelineStatus
from scie.store import PipelineRunStore

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/api/__init__.py src/scie/api/app.py tests/test_api.py
git commit -m "feat: add FastAPI query endpoints for pipeline runs"
```

---

### Task 7: GitHub webhook signature verification and payload parsing

**Files:**
- Create: `src/scie/webhooks/__init__.py`
- Create: `src/scie/webhooks/github.py`
- Test: `tests/test_github_webhook_parsing.py`

**Interfaces:**
- Consumes: `RepoEvent` (Task 2).
- Produces: `InvalidSignatureError`, `verify_github_signature(payload_body: bytes, signature_header: str | None, secret: str) -> None`, `parse_github_push_payload(payload: dict) -> RepoEvent` — used by Task 9.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_github_webhook_parsing.py
import hashlib
import hmac

import pytest

from scie.webhooks.github import (
    InvalidSignatureError,
    parse_github_push_payload,
    verify_github_signature,
)

SECRET = "test-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_valid_signature():
    body = b'{"hello": "world"}'
    verify_github_signature(body, _sign(body), SECRET)  # should not raise


def test_verify_signature_rejects_missing_header():
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(b"{}", None, SECRET)


def test_verify_signature_rejects_wrong_signature():
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(b"{}", "sha256=deadbeef", SECRET)


def test_parse_github_push_payload_extracts_repo_event():
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "mlessley/scie"},
        "head_commit": {
            "id": "abc123",
            "author": {"username": "mlessley"},
            "message": "add feature",
            "timestamp": "2026-07-04T12:00:00+00:00",
        },
    }
    event = parse_github_push_payload(payload)
    assert event.commit_sha == "abc123"
    assert event.repo == "mlessley/scie"
    assert event.branch == "main"
    assert event.author == "mlessley"
    assert event.event_type == "push"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_github_webhook_parsing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.webhooks'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/webhooks/__init__.py
```

```python
# src/scie/webhooks/github.py
import hashlib
import hmac
from datetime import datetime

from scie.models import RepoEvent


class InvalidSignatureError(Exception):
    pass


def verify_github_signature(payload_body: bytes, signature_header: str | None, secret: str) -> None:
    if signature_header is None:
        raise InvalidSignatureError("missing X-Hub-Signature-256 header")
    expected = "sha256=" + hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise InvalidSignatureError("signature mismatch")


def parse_github_push_payload(payload: dict) -> RepoEvent:
    head_commit = payload["head_commit"]
    return RepoEvent(
        commit_sha=head_commit["id"],
        repo=payload["repository"]["full_name"],
        branch=payload["ref"].removeprefix("refs/heads/"),
        author=head_commit["author"]["username"],
        message=head_commit["message"],
        pr_number=None,
        event_type="push",
        workflow_run_id=None,
        workflow_conclusion=None,
        timestamp=datetime.fromisoformat(head_commit["timestamp"]),
    )


def parse_github_workflow_run_payload(payload: dict) -> RepoEvent:
    workflow_run = payload["workflow_run"]
    head_commit = workflow_run["head_commit"]
    return RepoEvent(
        commit_sha=workflow_run["head_sha"],
        repo=payload["repository"]["full_name"],
        branch=workflow_run["head_branch"],
        author=head_commit["author"]["name"],
        message=head_commit["message"],
        pr_number=None,
        event_type="workflow_run",
        workflow_run_id=str(workflow_run["id"]),
        workflow_conclusion=workflow_run["conclusion"],
        timestamp=datetime.fromisoformat(workflow_run["updated_at"]),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_github_webhook_parsing.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/webhooks/__init__.py src/scie/webhooks/github.py tests/test_github_webhook_parsing.py
git commit -m "feat: add GitHub webhook signature verification and payload parsing"
```

---

### Task 8: RedPanda event publisher

**Files:**
- Create: `src/scie/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: `RepoEvent`, `ImageEvent`, `K8sEvent` (Task 2).
- Produces: `publish_event(topic: str, key: str, event, producer=None) -> None`, used by Task 9.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events.py
from datetime import datetime, timezone

from scie.events import publish_event
from scie.models import RepoEvent


class FakeProducer:
    def __init__(self):
        self.produced = []
        self.flushed = False

    def produce(self, topic, key=None, value=None):
        self.produced.append((topic, key, value))

    def flush(self):
        self.flushed = True


def test_publish_event_produces_and_flushes():
    producer = FakeProducer()
    event = RepoEvent(
        commit_sha="abc123",
        repo="mlessley/scie",
        branch="main",
        author="mlessley",
        message="add feature",
        event_type="push",
        timestamp=datetime.now(timezone.utc),
    )

    publish_event("repo-events", key="abc123", event=event, producer=producer)

    assert producer.flushed is True
    assert len(producer.produced) == 1
    topic, key, value = producer.produced[0]
    assert topic == "repo-events"
    assert key == b"abc123"
    assert b"abc123" in value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.events'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/events.py
import os

from confluent_kafka import Producer

from scie.models import ImageEvent, K8sEvent, RepoEvent

_producer: Producer | None = None


def get_producer() -> Producer:
    global _producer
    if _producer is None:
        _producer = Producer(
            {"bootstrap.servers": os.environ.get("REDPANDA_BROKERS", "localhost:19092")}
        )
    return _producer


def publish_event(
    topic: str,
    key: str,
    event: RepoEvent | ImageEvent | K8sEvent,
    producer: Producer | None = None,
) -> None:
    producer = producer or get_producer()
    producer.produce(topic, key=key.encode(), value=event.model_dump_json().encode())
    producer.flush()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_events.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/events.py tests/test_events.py
git commit -m "feat: add RedPanda event publisher"
```

---

### Task 9: GitHub webhook route

**Files:**
- Modify: `src/scie/api/app.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `verify_github_signature`, `InvalidSignatureError`, `parse_github_push_payload`, `parse_github_workflow_run_payload` (Task 7); `publish_event` (Task 8).
- Produces: `POST /webhooks/github` route on the existing `app`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
import hashlib
import hmac
import json

from scie.api import app as app_module

WEBHOOK_SECRET = "test-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_github_webhook_rejects_invalid_signature(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    client = TestClient(app)

    response = client.post(
        "/webhooks/github",
        content=b'{"ref": "refs/heads/main"}',
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )
    assert response.status_code == 401


def test_github_webhook_accepts_valid_push_payload_and_publishes(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)

    published = []
    monkeypatch.setattr(
        app_module,
        "publish_event",
        lambda topic, key, event: published.append((topic, key, event)),
    )

    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "mlessley/scie"},
        "head_commit": {
            "id": "abc123",
            "author": {"username": "mlessley"},
            "message": "add feature",
            "timestamp": "2026-07-04T12:00:00+00:00",
        },
    }
    body = json.dumps(payload).encode()

    client = TestClient(app)
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "push"},
    )

    assert response.status_code == 200
    assert len(published) == 1
    topic, key, event = published[0]
    assert topic == "repo-events"
    assert key == "abc123"
    assert event.commit_sha == "abc123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -v -k github_webhook`
Expected: FAIL with 404 (no such route) on both new tests

- [ ] **Step 3: Extend the implementation**

Add to the top of `src/scie/api/app.py` (after existing imports):

```python
import json
import os

from fastapi import Header, HTTPException, Request

from scie.events import publish_event
from scie.webhooks.github import (
    InvalidSignatureError,
    parse_github_push_payload,
    parse_github_workflow_run_payload,
    verify_github_signature,
)

GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "dev-secret")
```

Add this route at the end of `src/scie/api/app.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/api/app.py tests/test_api.py
git commit -m "feat: add GitHub webhook route"
```

---

### Task 10: Temporal activities

**Files:**
- Create: `src/scie/workflows/__init__.py`
- Create: `src/scie/workflows/activities.py`
- Test: `tests/test_activities.py`

**Interfaces:**
- Consumes: `ImageInfo`, `DeploymentInfo`, `PodStatus`, `VulnerabilityFinding`, `VulnerabilitySeverity`, `PipelineRun` (Task 2); `PipelineRunStore` (Task 5).
- Produces: `wait_for_ecr_scan_activity(ecr_repo: str, image_tag: str) -> ImageInfo`, `get_k8s_deployment_state_activity(namespace: str, deployment_name: str, cluster: str) -> DeploymentInfo`, `write_pipeline_run_activity(run_json: str) -> None` — used by Task 11.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_activities.py
from datetime import datetime, timezone
from unittest.mock import MagicMock

from sqlmodel import SQLModel, create_engine

import scie.db as db
from scie.models import PipelineRun
from scie.workflows import activities

NOW = datetime.now(timezone.utc)


def test_wait_for_ecr_scan_activity_builds_image_info(monkeypatch):
    fake_ecr = MagicMock()
    fake_ecr.describe_image_scan_findings.return_value = {
        "imageScanStatus": {"status": "COMPLETE"},
        "imageScanFindings": {
            "findings": [
                {
                    "name": "CVE-2025-1111",
                    "severity": "HIGH",
                    "attributes": [
                        {"key": "package_name", "value": "openssl"},
                        {"key": "package_version", "value": "1.0.0"},
                    ],
                }
            ]
        },
    }
    fake_ecr.describe_images.return_value = {
        "imageDetails": [{"imageDigest": "sha256:abc", "imagePushedAt": NOW}]
    }
    monkeypatch.setattr(activities.boto3, "client", lambda service: fake_ecr)

    image_info = activities._build_image_info("billing-api", "abc123")

    assert image_info.digest == "sha256:abc"
    assert len(image_info.vulnerabilities) == 1
    assert image_info.vulnerabilities[0].cve_id == "CVE-2025-1111"


def test_write_pipeline_run_activity_persists_via_store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)

    run = PipelineRun(id="abc123", service_name="billing-api", last_updated=NOW)

    import asyncio

    asyncio.run(activities.write_pipeline_run_activity(run.model_dump_json()))

    from sqlmodel import Session

    from scie.store import PipelineRunStore

    with Session(engine) as session:
        fetched = PipelineRunStore(session).get("abc123")
    assert fetched is not None
    assert fetched.service_name == "billing-api"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_activities.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.workflows'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/workflows/__init__.py
```

```python
# src/scie/workflows/activities.py
from datetime import datetime, timezone

import boto3
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from sqlmodel import Session
from temporalio import activity

from scie.db import engine
from scie.models import (
    DeploymentInfo,
    ImageInfo,
    PipelineRun,
    PodStatus,
    VulnerabilityFinding,
    VulnerabilitySeverity,
)
from scie.store import PipelineRunStore


def _attribute_value(attributes: list[dict], key: str) -> str:
    return next((a["value"] for a in attributes if a["key"] == key), "unknown")


def _build_image_info(ecr_repo: str, image_tag: str) -> ImageInfo:
    ecr = boto3.client("ecr")
    scan = ecr.describe_image_scan_findings(repositoryName=ecr_repo, imageId={"imageTag": image_tag})
    if scan["imageScanStatus"]["status"] != "COMPLETE":
        raise RuntimeError("ECR scan not complete yet")

    vulnerabilities = [
        VulnerabilityFinding(
            cve_id=finding["name"],
            severity=VulnerabilitySeverity(finding["severity"]),
            package_name=_attribute_value(finding["attributes"], "package_name"),
            package_version=_attribute_value(finding["attributes"], "package_version"),
        )
        for finding in scan["imageScanFindings"]["findings"]
    ]

    images = ecr.describe_images(repositoryName=ecr_repo, imageIds=[{"imageTag": image_tag}])
    image_detail = images["imageDetails"][0]

    return ImageInfo(
        digest=image_detail["imageDigest"],
        ecr_repo=ecr_repo,
        pushed_at=image_detail["imagePushedAt"],
        vulnerabilities=vulnerabilities,
    )


@activity.defn
async def wait_for_ecr_scan_activity(ecr_repo: str, image_tag: str) -> ImageInfo:
    return _build_image_info(ecr_repo, image_tag)


def _build_deployment_info(namespace: str, deployment_name: str, cluster: str) -> DeploymentInfo:
    k8s_config.load_kube_config()
    apps_v1 = k8s_client.AppsV1Api()
    core_v1 = k8s_client.CoreV1Api()

    deployment = apps_v1.read_namespaced_deployment(deployment_name, namespace)
    pods = core_v1.list_namespaced_pod(namespace, label_selector=f"app={deployment_name}")

    pod_statuses = [
        PodStatus(
            pod_name=pod.metadata.name,
            phase=pod.status.phase,
            ready=all(c.ready for c in (pod.status.container_statuses or [])),
        )
        for pod in pods.items
    ]

    return DeploymentInfo(
        cluster=cluster,
        namespace=namespace,
        replicas_desired=deployment.spec.replicas,
        replicas_ready=deployment.status.ready_replicas or 0,
        pod_statuses=pod_statuses,
        deployed_at=datetime.now(timezone.utc),
    )


@activity.defn
async def get_k8s_deployment_state_activity(namespace: str, deployment_name: str, cluster: str) -> DeploymentInfo:
    return _build_deployment_info(namespace, deployment_name, cluster)


@activity.defn
async def write_pipeline_run_activity(run_json: str) -> None:
    run = PipelineRun.model_validate_json(run_json)
    with Session(engine) as session:
        PipelineRunStore(session).upsert(run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_activities.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/workflows/__init__.py src/scie/workflows/activities.py tests/test_activities.py
git commit -m "feat: add Temporal activities for ECR scan and K8s enrichment"
```

---

### Task 11: Temporal correlation workflow

**Files:**
- Create: `src/scie/workflows/pipeline_run_workflow.py`
- Test: `tests/test_pipeline_run_workflow.py`

**Interfaces:**
- Consumes: `RepoEvent`, `PipelineRun`, `PipelineStatus`, `CommitInfo`, `BuildInfo` (Task 2); `compute_overall_status` (Task 3); `wait_for_ecr_scan_activity`, `get_k8s_deployment_state_activity`, `write_pipeline_run_activity` (Task 10).
- Produces: `PipelineRunWorkflow` (a `@workflow.defn` class with `.run(initial_event: RepoEvent) -> PipelineRun`), used by Task 12 (bridge).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_run_workflow.py
import uuid
from datetime import datetime, timezone

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from scie.models import (
    DeploymentInfo,
    ImageInfo,
    PipelineStatus,
    PodStatus,
    RepoEvent,
    VulnerabilityFinding,
    VulnerabilitySeverity,
)
from scie.workflows.pipeline_run_workflow import PipelineRunWorkflow

NOW = datetime.now(timezone.utc)


# Fakes are registered under the SAME activity type name as the real
# activities (via `@activity.defn(name=...)`) so the workflow — which
# schedules activities by name — invokes these instead of the real,
# boto3/kubernetes-backed implementations. Temporal's test Worker resolves
# activities by registered name, not by the Python object the workflow
# imported, so this is the correct way to substitute fakes; there is no
# `.fn` attribute on a `@activity.defn`-decorated function to reassign.
@activity.defn(name="wait_for_ecr_scan_activity")
async def fake_wait_for_ecr_scan_activity(ecr_repo: str, image_tag: str) -> ImageInfo:
    return ImageInfo(
        digest="sha256:abc",
        ecr_repo=ecr_repo,
        pushed_at=NOW,
        vulnerabilities=[
            VulnerabilityFinding(
                cve_id="CVE-2025-1111",
                severity=VulnerabilitySeverity.HIGH,
                package_name="openssl",
                package_version="1.0.0",
            )
        ],
    )


@activity.defn(name="get_k8s_deployment_state_activity")
async def fake_get_k8s_deployment_state_activity(namespace: str, deployment_name: str, cluster: str) -> DeploymentInfo:
    return DeploymentInfo(
        cluster=cluster,
        namespace=namespace,
        replicas_desired=2,
        replicas_ready=2,
        pod_statuses=[PodStatus(pod_name="pod-1", phase="Running", ready=True)],
        deployed_at=NOW,
    )


written_runs = []


@activity.defn(name="write_pipeline_run_activity")
async def fake_write_pipeline_run_activity(run_json: str) -> None:
    written_runs.append(run_json)


@pytest.mark.asyncio
async def test_successful_build_produces_deployed_with_findings():
    written_runs.clear()
    task_queue = f"test-queue-{uuid.uuid4()}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[PipelineRunWorkflow],
            activities=[
                fake_wait_for_ecr_scan_activity,
                fake_get_k8s_deployment_state_activity,
                fake_write_pipeline_run_activity,
            ],
        ):
            event = RepoEvent(
                commit_sha="abc123",
                repo="mlessley/scie",
                branch="main",
                author="mlessley",
                message="add feature",
                event_type="workflow_run",
                workflow_run_id="run-1",
                workflow_conclusion="success",
                timestamp=NOW,
            )
            result = await env.client.execute_workflow(
                PipelineRunWorkflow.run,
                event,
                id=f"pipeline-run-{uuid.uuid4()}",
                task_queue=task_queue,
            )

    assert result.overall_status == PipelineStatus.DEPLOYED_WITH_FINDINGS
    assert result.image.digest == "sha256:abc"
    assert result.deployment.replicas_ready == 2


@pytest.mark.asyncio
async def test_failed_build_short_circuits_to_failed():
    written_runs.clear()
    task_queue = f"test-queue-{uuid.uuid4()}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[PipelineRunWorkflow],
            activities=[
                fake_wait_for_ecr_scan_activity,
                fake_get_k8s_deployment_state_activity,
                fake_write_pipeline_run_activity,
            ],
        ):
            event = RepoEvent(
                commit_sha="def456",
                repo="mlessley/scie",
                branch="main",
                author="mlessley",
                message="broken build",
                event_type="workflow_run",
                workflow_run_id="run-2",
                workflow_conclusion="failure",
                timestamp=NOW,
            )
            result = await env.client.execute_workflow(
                PipelineRunWorkflow.run,
                event,
                id=f"pipeline-run-{uuid.uuid4()}",
                task_queue=task_queue,
            )

    assert result.overall_status == PipelineStatus.FAILED
    assert result.image is None
    assert result.deployment is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_run_workflow.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.workflows.pipeline_run_workflow'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/workflows/pipeline_run_workflow.py
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from scie.models import BuildInfo, CommitInfo, PipelineRun, PipelineStatus, RepoEvent
    from scie.status import compute_overall_status
    from scie.workflows.activities import (
        get_k8s_deployment_state_activity,
        wait_for_ecr_scan_activity,
        write_pipeline_run_activity,
    )


async def _persist(run: PipelineRun) -> None:
    await workflow.execute_activity(
        write_pipeline_run_activity,
        args=[run.model_dump_json()],
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=RetryPolicy(maximum_attempts=5),
    )


@workflow.defn
class PipelineRunWorkflow:
    @workflow.run
    async def run(self, initial_event: RepoEvent) -> PipelineRun:
        service_name = initial_event.repo.split("/")[-1]

        run = PipelineRun(
            id=initial_event.commit_sha,
            service_name=service_name,
            commit=CommitInfo(
                author=initial_event.author,
                message=initial_event.message,
                branch=initial_event.branch,
                pr_number=initial_event.pr_number,
                timestamp=initial_event.timestamp,
            ),
            build=BuildInfo(
                workflow_run_id=initial_event.workflow_run_id,
                trivy_gate_status="Pass" if initial_event.workflow_conclusion == "success" else "Fail",
                started_at=initial_event.timestamp,
                completed_at=workflow.now(),
                conclusion=initial_event.workflow_conclusion,
            ),
            last_updated=workflow.now(),
        )
        run.overall_status = compute_overall_status(run)
        await _persist(run)

        if run.overall_status == PipelineStatus.FAILED:
            return run

        run.image = await workflow.execute_activity(
            wait_for_ecr_scan_activity,
            args=[service_name, initial_event.commit_sha],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=10, backoff_coefficient=2.0),
        )
        run.overall_status = compute_overall_status(run)
        run.last_updated = workflow.now()
        await _persist(run)

        run.deployment = await workflow.execute_activity(
            get_k8s_deployment_state_activity,
            args=["default", service_name, service_name],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=5, backoff_coefficient=2.0),
        )
        run.overall_status = compute_overall_status(run)
        run.last_updated = workflow.now()
        await _persist(run)

        return run
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_run_workflow.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/workflows/pipeline_run_workflow.py tests/test_pipeline_run_workflow.py
git commit -m "feat: add PipelineRunWorkflow correlating repo, image, and deployment data"
```

---

### Task 12: RedPanda-to-Temporal bridge

**Files:**
- Create: `src/scie/bridge.py`
- Test: `tests/test_bridge.py`

**Interfaces:**
- Consumes: `RepoEvent` (Task 2); `PipelineRunWorkflow` (Task 11).
- Produces: `handle_repo_event(client, event: RepoEvent) -> None`, `run_bridge(consumer, client) -> None` — this is the process entrypoint that starts workflows from RedPanda messages; no downstream task depends on it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bridge.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from scie.bridge import handle_repo_event
from scie.models import RepoEvent
from scie.workflows.pipeline_run_workflow import PipelineRunWorkflow

NOW = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_workflow_run_event_with_conclusion_starts_workflow():
    client = AsyncMock()
    event = RepoEvent(
        commit_sha="abc123",
        repo="mlessley/scie",
        branch="main",
        author="mlessley",
        message="add feature",
        event_type="workflow_run",
        workflow_run_id="run-1",
        workflow_conclusion="success",
        timestamp=NOW,
    )

    await handle_repo_event(client, event)

    client.start_workflow.assert_awaited_once()
    args, kwargs = client.start_workflow.call_args
    assert args[0] is PipelineRunWorkflow.run
    assert args[1] is event
    assert kwargs["id"] == "pipeline-run-abc123"


@pytest.mark.asyncio
async def test_push_event_without_conclusion_does_not_start_workflow():
    client = AsyncMock()
    event = RepoEvent(
        commit_sha="abc123",
        repo="mlessley/scie",
        branch="main",
        author="mlessley",
        message="add feature",
        event_type="push",
        timestamp=NOW,
    )

    await handle_repo_event(client, event)

    client.start_workflow.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bridge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scie.bridge'`

- [ ] **Step 3: Write the implementation**

```python
# src/scie/bridge.py
import asyncio
import os

from confluent_kafka import Consumer
from temporalio.client import Client

from scie.models import RepoEvent
from scie.workflows.pipeline_run_workflow import PipelineRunWorkflow

TOPICS = ["repo-events"]


def build_consumer() -> Consumer:
    consumer = Consumer(
        {
            "bootstrap.servers": os.environ.get("REDPANDA_BROKERS", "localhost:19092"),
            "group.id": "scie-bridge",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe(TOPICS)
    return consumer


async def handle_repo_event(client: Client, event: RepoEvent) -> None:
    if event.event_type != "workflow_run" or event.workflow_conclusion is None:
        return
    await client.start_workflow(
        PipelineRunWorkflow.run,
        event,
        id=f"pipeline-run-{event.commit_sha}",
        task_queue="scie-task-queue",
    )


async def run_bridge(consumer: Consumer, client: Client) -> None:
    loop = asyncio.get_event_loop()
    while True:
        message = await loop.run_in_executor(None, consumer.poll, 1.0)
        if message is None or message.error():
            continue
        event = RepoEvent.model_validate_json(message.value())
        await handle_repo_event(client, event)
        consumer.commit(message)


async def main() -> None:
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    consumer = build_consumer()
    await run_bridge(consumer, client)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bridge.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/scie/bridge.py tests/test_bridge.py
git commit -m "feat: add RedPanda-to-Temporal bridge"
```

---

### Task 13: Docker Compose for the local stack

**Files:**
- Create: `docker-compose.yml`
- Create: `Dockerfile`

**Interfaces:**
- Consumes: the `scie` package as a whole (Tasks 1-12).
- Produces: a runnable local stack (`docker compose up`) exposing the FastAPI service on `:8000` and Streamlit on `:8501`.

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev
COPY src ./src
ENV PYTHONPATH=/app/src
CMD ["uv", "run", "uvicorn", "scie.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write docker-compose.yml**

```yaml
# docker-compose.yml
services:
  redpanda:
    image: redpandadata/redpanda:latest
    command:
      - redpanda
      - start
      - --smp=1
      - --overprovisioned
      - --kafka-addr=PLAINTEXT://0.0.0.0:9092,OUTSIDE://0.0.0.0:19092
      - --advertise-kafka-addr=PLAINTEXT://redpanda:9092,OUTSIDE://localhost:19092
    ports:
      - "19092:19092"

  temporal:
    image: temporalio/auto-setup:latest
    ports:
      - "7233:7233"
    environment:
      - DB=sqlite

  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - REDPANDA_BROKERS=redpanda:9092
      - TEMPORAL_ADDRESS=temporal:7233
      - SCIE_DATABASE_URL=sqlite:////data/scie.db
    volumes:
      - scie-data:/data
    depends_on:
      - redpanda
      - temporal

  dashboard:
    build: .
    command: ["uv", "run", "streamlit", "run", "src/scie/ui/streamlit_app.py", "--server.address=0.0.0.0"]
    ports:
      - "8501:8501"
    environment:
      - SCIE_API_URL=http://api:8000
    depends_on:
      - api

volumes:
  scie-data:
```

- [ ] **Step 3: Verify the stack builds and the API responds**

Run:
```bash
docker compose build api
docker compose up -d redpanda temporal api
sleep 5
curl -s http://localhost:8000/healthz
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Tear down**

Run: `docker compose down`

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "chore: add Docker Compose local stack"
```

---

### Task 14: Streamlit dashboard

**Files:**
- Create: `src/scie/ui/__init__.py`
- Create: `src/scie/ui/streamlit_app.py`

**Interfaces:**
- Consumes: the FastAPI endpoints from Task 6/9 (`GET /services`, `GET /pipeline-runs/{run_id}`, `GET /pipeline-runs/{run_id}/timeline`) over HTTP.
- Produces: a runnable Streamlit app with no downstream code dependents.

- [ ] **Step 1: Write the implementation**

```python
# src/scie/ui/__init__.py
```

```python
# src/scie/ui/streamlit_app.py
import os

import requests
import streamlit as st

API_URL = os.environ.get("SCIE_API_URL", "http://localhost:8000")

STATUS_COLORS = {
    "Deployed": "🟢",
    "DeployedWithFindings": "🟡",
    "Failed": "🔴",
    "InProgress": "🔵",
    "Stalled": "🟠",
    "Abandoned": "⚫",
}

st.set_page_config(page_title="Supply Chain Insights Engine", layout="wide")
st.title("Supply Chain Insights Engine")

services = requests.get(f"{API_URL}/services", timeout=10).json()

st.header("Fleet overview")
for service in services:
    badge = STATUS_COLORS.get(service["overall_status"], "⚪")
    demo_tag = " `[demo]`" if service["is_synthetic"] else ""
    st.write(f"{badge} **{service['service_name']}**{demo_tag} — {service['overall_status']}")

st.header("Service detail")
selected_service = st.selectbox(
    "Select a service", options=[s["service_name"] for s in services]
)

if selected_service:
    runs = requests.get(
        f"{API_URL}/pipeline-runs", params={"service_name": selected_service}, timeout=10
    ).json()
    for run in runs:
        st.subheader(f"Commit {run['id']}")
        st.json(run)
        timeline = requests.get(f"{API_URL}/pipeline-runs/{run['id']}/timeline", timeout=10).json()
        st.write(timeline["stages"])
```

- [ ] **Step 2: Verify it runs against a live API**

With the Task 13 stack running (`docker compose up -d`), run:
```bash
uv run streamlit run src/scie/ui/streamlit_app.py
```
Expected: Streamlit starts and prints a local URL; opening it in a browser shows "Supply Chain Insights Engine" with an empty fleet overview (no data seeded yet — seeding happens when the synthetic generator is invoked, e.g. via a short `uv run python -c "..."` script calling `generate_synthetic_fleet` and `PipelineRunStore.upsert` for each run against the same database the API uses).

- [ ] **Step 3: Commit**

```bash
git add src/scie/ui/__init__.py src/scie/ui/streamlit_app.py
git commit -m "feat: add Streamlit dashboard"
```

---

### Task 15: Terraform for AWS (ECR, IAM OIDC role, EKS, initial K8s Deployment)

**Files:**
- Create: `terraform/main.tf`
- Create: `terraform/variables.tf`
- Create: `terraform/ecr.tf`
- Create: `terraform/iam.tf`
- Create: `terraform/eks.tf`
- Create: `terraform/k8s.tf`

**Interfaces:**
- Produces: an ECR repository, an IAM role assumable by GitHub Actions via OIDC, an EKS cluster, and an initial `kubernetes_deployment` named `var.project_name` (default `scie`) in the `default` namespace with a container of the same name — consumed by Task 16's CI workflow (which pushes to the ECR repo, assumes the IAM role, and runs `kubectl set image` against this Deployment) and by the K8s activity in Task 10 (`get_k8s_deployment_state_activity`, which reads this Deployment's status). The Deployment must exist before the first CI run, since `kubectl set image` only updates an existing Deployment — it does not create one.
- **Naming constraint carried from the spec's correlation design:** the ECR repository name, the K8s Deployment name, and the container name must all equal `var.project_name`, and `var.project_name` must equal the actual GitHub repository's short name — Task 11's workflow derives its ECR/K8s lookup key as `RepoEvent.repo.split("/")[-1]`, so any mismatch here breaks the real (non-synthetic) correlation path at runtime, not just at review time.

- [ ] **Step 1: Write the provider and variables**

```hcl
# terraform/main.tf
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
```

```hcl
# terraform/variables.tf
variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  description = "Also used as the ECR repo name and K8s Deployment/container name — must equal the GitHub repo's short name, since the correlation workflow (Task 11) derives its ECR/K8s lookup key from RepoEvent.repo.split('/')[-1]."
  type        = string
  default     = "scie"
}

variable "github_repo" {
  description = "GitHub repo in 'owner/name' form, for OIDC trust"
  type        = string
}
```

- [ ] **Step 2: Write the ECR repository**

```hcl
# terraform/ecr.tf
resource "aws_ecr_repository" "scie" {
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}
```

- [ ] **Step 3: Write the GitHub Actions OIDC IAM role**

```hcl
# terraform/iam.tf
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project_name}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

resource "aws_iam_role_policy_attachment" "github_actions_ecr" {
  role       = aws_iam_role.github_actions.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser"
}

resource "aws_iam_role_policy_attachment" "github_actions_eks" {
  role       = aws_iam_role.github_actions.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}
```

- [ ] **Step 4: Write the EKS cluster**

```hcl
# terraform/eks.tf
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.project_name
  cluster_version = "1.30"

  vpc_id     = data.aws_vpc.default.id
  subnet_ids = data.aws_subnets.default.ids

  eks_managed_node_groups = {
    default = {
      instance_types = ["t3.small"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
```

- [ ] **Step 5: Write the initial K8s Deployment**

The GitHub Actions CI workflow (Task 16) only runs `kubectl set image` to update an *existing* Deployment's image on each push — it does not create the Deployment. This step creates it once, via the same `terraform apply` that creates the cluster, so there's nothing to run/administer afterward.

```hcl
# terraform/k8s.tf
data "aws_eks_cluster_auth" "this" {
  name = module.eks.cluster_name
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

resource "kubernetes_deployment" "scie" {
  metadata {
    name      = var.project_name
    namespace = "default"
    labels = {
      app = var.project_name
    }
  }

  spec {
    replicas = 2

    selector {
      match_labels = {
        app = var.project_name
      }
    }

    template {
      metadata {
        labels = {
          app = var.project_name
        }
      }

      spec {
        container {
          name = var.project_name
          # Bootstrap placeholder so the Deployment exists before the first
          # real CI push. ci.yml (Task 16) replaces this via `kubectl set
          # image` on every push to main — this value is never read again
          # after the first successful CI run.
          image = "public.ecr.aws/docker/library/nginx:stable"
        }
      }
    }
  }

  depends_on = [module.eks]
}
```

- [ ] **Step 6: Validate**

Run:
```bash
cd terraform
terraform init
terraform validate
terraform plan -var="github_repo=mlessley/scie"
```
Expected: `terraform validate` reports `Success!`; `terraform plan` shows the resources to be created (ECR repo, IAM role, EKS cluster, Deployment) with no errors (review the plan before running `terraform apply` manually — this is a real-money step, not part of automated CI).

- [ ] **Step 7: Commit**

```bash
cd ..
git add terraform/
git commit -m "chore: add Terraform for ECR, GitHub OIDC role, EKS, and initial Deployment"
```

---

### Task 16: GitHub Actions CI pipeline

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the ECR repository and IAM role from Task 15; produces the `workflow_run` webhook event consumed by Task 7/9's parser and Task 12's bridge.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]

permissions:
  id-token: write
  contents: read

jobs:
  build-scan-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build image
        run: docker build -t scie:${{ github.sha }} .

      - name: Trivy scan gate
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: scie:${{ github.sha }}
          exit-code: "1"
          severity: "CRITICAL,HIGH"

      - name: Configure AWS credentials via OIDC
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::${{ secrets.AWS_ACCOUNT_ID }}:role/scie-github-actions
          aws-region: us-east-1

      - name: Login to ECR
        id: ecr-login
        uses: aws-actions/amazon-ecr-login@v2

      - name: Tag and push image
        run: |
          docker tag scie:${{ github.sha }} ${{ steps.ecr-login.outputs.registry }}/scie:${{ github.sha }}
          docker push ${{ steps.ecr-login.outputs.registry }}/scie:${{ github.sha }}

      - name: Deploy to EKS
        run: |
          aws eks update-kubeconfig --name scie --region us-east-1
          kubectl set image deployment/scie scie=${{ steps.ecr-login.outputs.registry }}/scie:${{ github.sha }} --record
```

Note: the ECR repository name, IAM role name, EKS cluster name, and K8s Deployment/container name here (`scie`) must all equal `var.project_name` from Task 15's Terraform and the actual GitHub repository's short name — this is the same naming constraint recorded in Task 15's Interfaces block, not a new decision.

- [ ] **Step 2: Verify locally as far as possible without pushing**

Run: `docker build -t scie:local .`
Expected: image builds successfully (validates the Dockerfile from Task 13 independent of the GH Actions runner).

- [ ] **Step 3: Push to a real branch and verify in GitHub's Actions tab**

Run:
```bash
git push origin main
```
Then check the repository's Actions tab: the `CI` workflow should run, and (once `AWS_ACCOUNT_ID` is set as a repo secret and the Terraform from Task 15 has been applied) reach a green checkmark through the ECR push and EKS deploy steps.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "chore: add GitHub Actions CI pipeline"
```

---

### Task 17: Worker entrypoint, Compose wiring, synthetic seed script, and README

**Added 2026-07-04 after the final whole-branch review of Tasks 1-16.** That review found a real, plan-level gap no per-task review could catch: Task 12's bridge calls `client.start_workflow(...)`, which enqueues a workflow task, but nothing in `src/` ever runs a Temporal `Worker` that registers `PipelineRunWorkflow` and its three activities and polls `scie-task-queue` — so in a live run, workflows would sit pending forever. Combined with Docker Compose never running the bridge either, the whole RedPanda→Temporal path is dormant in the shipped stack, and there's no committed way to populate the dashboard with synthetic data for a demo. This task closes all four gaps.

**Files:**
- Create: `src/scie/worker.py`
- Test: `tests/test_worker.py`
- Create: `src/scie/seed.py`
- Modify: `docker-compose.yml`
- Modify (from empty): `README.md`

**Interfaces:**
- Consumes: `PipelineRunWorkflow` (Task 11); `wait_for_ecr_scan_activity`, `get_k8s_deployment_state_activity`, `write_pipeline_run_activity` (Task 10); `pydantic_data_converter` (already used in Task 12's `bridge.py`, same pattern applies here); `generate_synthetic_fleet` (Task 4); `PipelineRunStore`, `engine`, `init_db` (Task 5).
- Produces: `build_worker(client) -> Worker` and `main()` in `src/scie/worker.py` (mirrors `bridge.py`'s `build_consumer()`/`main()` split so the registration logic is unit-testable without running the worker's blocking poll loop); a `main()` in `src/scie/seed.py` that seeds the fleet against the same DB the API uses; `bridge` and `worker` services in `docker-compose.yml`; a real `README.md`.

- [ ] **Step 1: Write the worker entrypoint**

Follow `src/scie/bridge.py`'s existing shape exactly (it already solves the "real client, testable helper, blocking main loop" problem once — reuse the pattern, don't reinvent it):

```python
# src/scie/worker.py
import asyncio
import os

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from scie.workflows.activities import (
    get_k8s_deployment_state_activity,
    wait_for_ecr_scan_activity,
    write_pipeline_run_activity,
)
from scie.workflows.pipeline_run_workflow import PipelineRunWorkflow

TASK_QUEUE = "scie-task-queue"


def build_worker(client: Client) -> Worker:
    return Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[PipelineRunWorkflow],
        activities=[
            wait_for_ecr_scan_activity,
            get_k8s_deployment_state_activity,
            write_pipeline_run_activity,
        ],
    )


async def main() -> None:
    # See bridge.py's main() for why pydantic_data_converter is required here.
    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        data_converter=pydantic_data_converter,
    )
    worker = build_worker(client)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
```

Write `tests/test_worker.py` to verify `build_worker` registers the right task queue, workflow, and activities. A plain `unittest.mock.MagicMock()` client will NOT work here — `Worker.__init__` validates the client's internal service-client shape and raises `TypeError` on a bare mock. Use the same real-test-client pattern Task 11's `tests/test_pipeline_run_workflow.py` already uses (`temporalio.testing.WorkflowEnvironment.start_time_skipping()`, which gives a real `env.client`), construct the worker against `env.client`, and assert on whatever the installed `temporalio` version's `Worker` actually exposes for inspection (at last check: `.task_queue`, and a `.config` dict — confirm the exact keys/shape for this installed version rather than assuming, the way Task 11 confirmed the data-converter behavior empirically instead of guessing). If no clean public introspection point exists, a passing construction (no exception) plus `.task_queue == TASK_QUEUE` is an acceptable minimum bar — don't reach for private attributes beyond `.config` to force a deeper assertion.

- [ ] **Step 2: Write the seed script**

```python
# src/scie/seed.py
from sqlmodel import Session

from scie.db import engine, init_db
from scie.store import PipelineRunStore
from scie.synthetic import generate_synthetic_fleet


def main(count: int = 20) -> None:
    init_db()
    fleet = generate_synthetic_fleet(count=count)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        for run in fleet:
            store.upsert(run)
    print(f"Seeded {len(fleet)} synthetic pipeline runs.")


if __name__ == "__main__":
    main()
```

No dedicated test file is required for this script (it's a thin composition of already-tested `generate_synthetic_fleet` and `PipelineRunStore.upsert` — Tasks 4 and 5 already cover their correctness). Verify it for real instead: run it against a temp `SCIE_DATABASE_URL`, then query the same DB directly (or via the API, as Task 14's implementer already did) to confirm rows landed.

- [ ] **Step 3: Wire `bridge` and `worker` into Docker Compose**

Add two services to `docker-compose.yml`, alongside the existing `api`/`dashboard`. They must share `api`'s `scie-data` volume and `SCIE_DATABASE_URL` — the worker's `write_pipeline_run_activity` and the API's query endpoints must read/write the *same* SQLite file, not two different ones:

```yaml
  bridge:
    build: .
    command: ["uv", "run", "python", "-m", "scie.bridge"]
    environment:
      - REDPANDA_BROKERS=redpanda:9092
      - TEMPORAL_ADDRESS=temporal:7233
    depends_on:
      - redpanda
      - temporal

  worker:
    build: .
    command: ["uv", "run", "python", "-m", "scie.worker"]
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
      - SCIE_DATABASE_URL=sqlite:////data/scie.db
    volumes:
      - scie-data:/data
    depends_on:
      - temporal
```

Verify for real (Docker is available in this environment): `docker compose build`, then `docker compose up -d redpanda postgres temporal api worker bridge`, confirm via `docker compose ps`/`docker compose logs` that `worker` and `bridge` both reach a running (non-crash-looping) state — same verification bar Task 13 already established. Tear down cleanly afterward.

- [ ] **Step 4: Write the README**

Replace the empty `README.md` with real content covering: what this project is and why it exists (one paragraph); the architecture (the real event flow: GitHub webhook → RedPanda → bridge → Temporal workflow → activities (ECR scan, K8s state) → SQLite → FastAPI → Streamlit — plus the synthetic-fleet path for demo purposes); and how to run it locally (`docker compose up -d`, then seed via `uv run python -m scie.seed`, then open the dashboard). Keep it concise — this is a portfolio README, not a full user manual.

- [ ] **Step 5: Run the full suite and commit**

Run: `uv run pytest -v` — expect the existing 36 plus the new worker test(s), all passing, no regressions.

```bash
git add src/scie/worker.py tests/test_worker.py src/scie/seed.py docker-compose.yml README.md
git commit -m "feat: add Temporal worker entrypoint, seed script, and wire the full stack together"
```

---

## Self-Review Notes

- **Spec coverage:** every v1 item from the spec's "Scope: v1 vs. stretch" section has a task — GitHub Actions/Trivy/OIDC/ECR (Tasks 15-16), Terraform EKS+IAM (Task 15), targeted K8s observation (Task 10), RedPanda+Temporal correlation (Tasks 8, 10-12), FastAPI webhook+query API (Tasks 6, 9), Streamlit fleet+detail view (Task 14), synthetic fleet generator (Task 4), Docker Compose (Task 13). Stretch items are explicitly excluded per the Global Constraints section rather than half-built.
- **Type consistency checked:** `PipelineRun`/`CommitInfo`/`BuildInfo`/`ImageInfo`/`DeploymentInfo` field names are identical across Tasks 2, 4, 5, 9, 10, 11, 14. `compute_overall_status` (Task 3) is the single source of truth for status transitions and is reused (not reimplemented) in Task 4's synthetic generator and Task 11's workflow.
- **No placeholders:** every step has complete, runnable code; the one previously-considered stall-detection stub was removed by restructuring the workflow (Task 11) to derive `build` info directly from the triggering `workflow_run` event instead of waiting on a signal that v1 doesn't implement.
- **Pre-flight fixes made during the SDD scan (2026-07-04), before Task 1 was dispatched:** (1) Task 11's test originally monkeypatched a nonexistent `.fn` attribute on `@activity.defn`-decorated functions to fake them out — fixed to register fakes under the real activity type names via `@activity.defn(name=...)`, which is how Temporal's test `Worker` actually substitutes activity implementations. (2) The real (non-synthetic) path had no task provisioning the K8s Deployment resource that Task 16's `kubectl set image` and Task 10's `get_k8s_deployment_state_activity` both require to already exist — added to Task 15 as a Terraform-managed `kubernetes_deployment`. (3) `var.project_name` (ECR repo / EKS cluster / IAM role name), the K8s Deployment/container name, and the literal `scie-poc` strings previously hardcoded in Task 11's workflow and Task 16's `ci.yml` were inconsistent with each other and with `service_name` (derived at runtime from the GitHub repo's short name) — standardized to `scie` everywhere in the real path, with the constraint recorded in Task 15 and Task 16 so it isn't silently reintroduced. Task 3's and Task 4's fixture/synthetic-data uses of similar strings are unaffected (they're arbitrary test/demo values, not tied to real infrastructure) except Task 4's cosmetic `cluster` label, which was aligned to `scie` for dashboard visual consistency with the one real entry.
