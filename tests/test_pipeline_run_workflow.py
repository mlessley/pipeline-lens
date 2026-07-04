import uuid
from datetime import datetime, timezone

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
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

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
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

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
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
