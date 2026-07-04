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
