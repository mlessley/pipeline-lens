from scie.models import PipelineRun, PipelineStatus


def compute_overall_status(run: PipelineRun) -> PipelineStatus:
    if run.build is not None and run.build.conclusion == "failure":
        return PipelineStatus.FAILED
    if run.build is not None and run.build.trivy_gate_status == "Fail":
        return PipelineStatus.FAILED
    if run.deployment is not None:
        if run.image is not None and len(run.image.vulnerabilities) > 0:
            return PipelineStatus.DEPLOYED_WITH_FINDINGS
        return PipelineStatus.DEPLOYED
    return PipelineStatus.IN_PROGRESS
