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
