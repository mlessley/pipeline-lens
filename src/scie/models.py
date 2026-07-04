from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PipelineStatus(str, Enum):
    IN_PROGRESS = "InProgress"
    DEPLOYED = "Deployed"
    DEPLOYED_WITH_FINDINGS = "DeployedWithFindings"
    FAILED = "Failed"
    STALLED = "Stalled"
    ABANDONED = "Abandoned"


class VulnerabilitySeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class VulnerabilityFinding(BaseModel):
    cve_id: str
    severity: VulnerabilitySeverity
    package_name: str
    package_version: str


class PodStatus(BaseModel):
    pod_name: str
    phase: str
    ready: bool


class RepoEvent(BaseModel):
    commit_sha: str
    repo: str
    branch: str
    author: str
    message: str
    pr_number: int | None = None
    event_type: str
    workflow_run_id: str | None = None
    workflow_conclusion: str | None = None
    timestamp: datetime


class ImageEvent(BaseModel):
    image_digest: str
    image_tag: str
    ecr_repo: str
    pushed_at: datetime
    vulnerabilities: list[VulnerabilityFinding] = Field(default_factory=list)
    scan_completed_at: datetime | None = None


class K8sEvent(BaseModel):
    deployment_name: str
    namespace: str
    cluster: str
    running_image_ref: str
    replicas_desired: int
    replicas_ready: int
    pod_statuses: list[PodStatus] = Field(default_factory=list)
    reason: str | None = None
    observed_at: datetime


class CommitInfo(BaseModel):
    author: str
    message: str
    branch: str
    pr_number: int | None = None
    timestamp: datetime


class BuildInfo(BaseModel):
    workflow_run_id: str | None = None
    trivy_gate_status: str
    started_at: datetime
    completed_at: datetime | None = None
    conclusion: str | None = None


class ImageInfo(BaseModel):
    digest: str
    ecr_repo: str
    pushed_at: datetime
    vulnerabilities: list[VulnerabilityFinding] = Field(default_factory=list)

    @property
    def vulnerability_summary(self) -> dict[str, int]:
        summary = {severity.value: 0 for severity in VulnerabilitySeverity}
        for finding in self.vulnerabilities:
            summary[finding.severity.value] += 1
        return summary


class DeploymentInfo(BaseModel):
    cluster: str
    namespace: str
    replicas_desired: int
    replicas_ready: int
    pod_statuses: list[PodStatus] = Field(default_factory=list)
    deployed_at: datetime


class PipelineRun(BaseModel):
    id: str
    service_name: str
    is_synthetic: bool = False
    commit: CommitInfo | None = None
    build: BuildInfo | None = None
    image: ImageInfo | None = None
    deployment: DeploymentInfo | None = None
    overall_status: PipelineStatus = PipelineStatus.IN_PROGRESS
    last_updated: datetime
