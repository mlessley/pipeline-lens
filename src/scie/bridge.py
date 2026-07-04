import asyncio
import os

from confluent_kafka import Consumer
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

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
    # NOTE: data_converter=pydantic_data_converter is required here. Temporal's
    # default data converter is not pydantic-v2-aware; without this it falls
    # back to deprecated pydantic v1-compat shims (`.dict()`/`.parse_obj()`),
    # which emit PydanticDeprecatedSince20 warnings and will break when those
    # shims are removed. This mirrors the fix already applied to the test
    # client in tests/test_pipeline_run_workflow.py (WorkflowEnvironment).
    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        data_converter=pydantic_data_converter,
    )
    consumer = build_consumer()
    await run_bridge(consumer, client)


if __name__ == "__main__":
    asyncio.run(main())
