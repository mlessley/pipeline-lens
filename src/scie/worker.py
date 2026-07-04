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
