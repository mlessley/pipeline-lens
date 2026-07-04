from datetime import datetime, timezone
from unittest.mock import MagicMock

from sqlmodel import SQLModel, create_engine

import scie.db as db
from scie.models import PipelineRun
from scie.workflows import activities

NOW = datetime.now(timezone.utc)


def test_wait_for_ecr_scan_activity_builds_image_info(monkeypatch):
    fake_ecr = MagicMock()
    fake_ecr.describe_image_scan_findings.return_value = {
        "imageScanStatus": {"status": "COMPLETE"},
        "imageScanFindings": {
            "findings": [
                {
                    "name": "CVE-2025-1111",
                    "severity": "HIGH",
                    "attributes": [
                        {"key": "package_name", "value": "openssl"},
                        {"key": "package_version", "value": "1.0.0"},
                    ],
                }
            ]
        },
    }
    fake_ecr.describe_images.return_value = {
        "imageDetails": [{"imageDigest": "sha256:abc", "imagePushedAt": NOW}]
    }
    monkeypatch.setattr(activities.boto3, "client", lambda service: fake_ecr)

    image_info = activities._build_image_info("billing-api", "abc123")

    assert image_info.digest == "sha256:abc"
    assert len(image_info.vulnerabilities) == 1
    assert image_info.vulnerabilities[0].cve_id == "CVE-2025-1111"


def test_write_pipeline_run_activity_persists_via_store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)

    run = PipelineRun(id="abc123", service_name="billing-api", last_updated=NOW)

    import asyncio

    asyncio.run(activities.write_pipeline_run_activity(run.model_dump_json()))

    from sqlmodel import Session

    from scie.store import PipelineRunStore

    with Session(engine) as session:
        fetched = PipelineRunStore(session).get("abc123")
    assert fetched is not None
    assert fetched.service_name == "billing-api"
