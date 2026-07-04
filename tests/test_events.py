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
