import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from scie.worker import TASK_QUEUE, build_worker
from scie.workflows.activities import (
    get_k8s_deployment_state_activity,
    wait_for_ecr_scan_activity,
    write_pipeline_run_activity,
)
from scie.workflows.pipeline_run_workflow import PipelineRunWorkflow


@pytest.mark.asyncio
async def test_build_worker_registers_task_queue_workflow_and_activities():
    # A bare unittest.mock.MagicMock() client raises TypeError inside
    # Worker.__init__ (it validates the client's internal service-client
    # shape), so a real test client is required here, same as Task 11's
    # tests/test_pipeline_run_workflow.py.
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        worker = build_worker(env.client)

        assert worker.task_queue == TASK_QUEUE

        config = worker.config()
        assert config["task_queue"] == TASK_QUEUE
        assert PipelineRunWorkflow in config["workflows"]
        assert set(config["activities"]) == {
            wait_for_ecr_scan_activity,
            get_k8s_deployment_state_activity,
            write_pipeline_run_activity,
        }
