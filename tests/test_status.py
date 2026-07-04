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
