from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from scie.models import PipelineRun, PipelineStatus, ImageInfo, VulnerabilityFinding, VulnerabilitySeverity
from scie.store import PipelineRunStore

NOW = datetime.now(timezone.utc)


def _make_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    return engine


def test_upsert_then_get_round_trips(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        run = PipelineRun(id="abc123", service_name="billing-api", last_updated=NOW)
        store.upsert(run)

        fetched = store.get("abc123")
        assert fetched is not None
        assert fetched.id == "abc123"
        assert fetched.service_name == "billing-api"


def test_get_missing_returns_none(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        assert store.get("does-not-exist") is None


def test_upsert_overwrites_existing_record(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        run = PipelineRun(id="abc123", service_name="billing-api", last_updated=NOW)
        store.upsert(run)

        run.overall_status = PipelineStatus.FAILED
        store.upsert(run)

        fetched = store.get("abc123")
        assert fetched.overall_status == PipelineStatus.FAILED


def test_list_filters_by_service_name_and_synthetic(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        store.upsert(PipelineRun(id="1", service_name="billing-api", is_synthetic=True, last_updated=NOW))
        store.upsert(PipelineRun(id="2", service_name="auth-service", is_synthetic=False, last_updated=NOW))

        results = store.list(service_name="billing-api")
        assert [r.id for r in results] == ["1"]

        results = store.list(is_synthetic=False)
        assert [r.id for r in results] == ["2"]


def test_list_filters_by_has_vulnerabilities(tmp_path):
    engine = _make_engine(tmp_path)
    with Session(engine) as session:
        store = PipelineRunStore(session)
        vulnerable = PipelineRun(
            id="1",
            service_name="billing-api",
            last_updated=NOW,
            image=ImageInfo(
                digest="sha256:x",
                ecr_repo="billing-api",
                pushed_at=NOW,
                vulnerabilities=[
                    VulnerabilityFinding(
                        cve_id="CVE-2025-1111",
                        severity=VulnerabilitySeverity.HIGH,
                        package_name="openssl",
                        package_version="1.0.0",
                    )
                ],
            ),
        )
        clean = PipelineRun(id="2", service_name="auth-service", last_updated=NOW)
        store.upsert(vulnerable)
        store.upsert(clean)

        results = store.list(has_vulnerabilities=True)
        assert [r.id for r in results] == ["1"]
