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
