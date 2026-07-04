from sqlmodel import Field, Session, SQLModel, select

from scie.models import PipelineRun, PipelineStatus


class PipelineRunRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    service_name: str = Field(index=True)
    overall_status: str = Field(index=True)
    is_synthetic: bool = Field(index=True)
    has_vulnerabilities: bool = Field(index=True, default=False)
    last_updated: str
    payload: str


class PipelineRunStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, run: PipelineRun) -> None:
        has_vulnerabilities = bool(run.image and len(run.image.vulnerabilities) > 0)
        record = PipelineRunRecord(
            id=run.id,
            service_name=run.service_name,
            overall_status=run.overall_status.value,
            is_synthetic=run.is_synthetic,
            has_vulnerabilities=has_vulnerabilities,
            last_updated=run.last_updated.isoformat(),
            payload=run.model_dump_json(),
        )
        self.session.merge(record)
        self.session.commit()

    def get(self, run_id: str) -> PipelineRun | None:
        record = self.session.get(PipelineRunRecord, run_id)
        if record is None:
            return None
        return PipelineRun.model_validate_json(record.payload)

    def list(
        self,
        status: PipelineStatus | None = None,
        service_name: str | None = None,
        is_synthetic: bool | None = None,
        has_vulnerabilities: bool | None = None,
    ) -> list[PipelineRun]:
        query = select(PipelineRunRecord)
        if status is not None:
            query = query.where(PipelineRunRecord.overall_status == status.value)
        if service_name is not None:
            query = query.where(PipelineRunRecord.service_name == service_name)
        if is_synthetic is not None:
            query = query.where(PipelineRunRecord.is_synthetic == is_synthetic)
        if has_vulnerabilities is not None:
            query = query.where(PipelineRunRecord.has_vulnerabilities == has_vulnerabilities)
        records = self.session.exec(query).all()
        return [PipelineRun.model_validate_json(record.payload) for record in records]
