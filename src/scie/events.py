import os

from confluent_kafka import Producer

from scie.models import ImageEvent, K8sEvent, RepoEvent

_producer: Producer | None = None


def get_producer() -> Producer:
    global _producer
    if _producer is None:
        _producer = Producer(
            {"bootstrap.servers": os.environ.get("REDPANDA_BROKERS", "localhost:19092")}
        )
    return _producer


def publish_event(
    topic: str,
    key: str,
    event: RepoEvent | ImageEvent | K8sEvent,
    producer: Producer | None = None,
) -> None:
    producer = producer or get_producer()
    producer.produce(topic, key=key.encode(), value=event.model_dump_json().encode())
    producer.flush()
