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
