from datetime import datetime, timezone

import boto3
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from sqlmodel import Session
from temporalio import activity

from scie import db
from scie.models import (
    DeploymentInfo,
    ImageInfo,
    PipelineRun,
    PodStatus,
    VulnerabilityFinding,
    VulnerabilitySeverity,
)
from scie.store import PipelineRunStore


def _attribute_value(attributes: list[dict], key: str) -> str:
    return next((a["value"] for a in attributes if a["key"] == key), "unknown")


def _build_image_info(ecr_repo: str, image_tag: str) -> ImageInfo:
    ecr = boto3.client("ecr")
    scan = ecr.describe_image_scan_findings(repositoryName=ecr_repo, imageId={"imageTag": image_tag})
    if scan["imageScanStatus"]["status"] != "COMPLETE":
        raise RuntimeError("ECR scan not complete yet")

    vulnerabilities = [
        VulnerabilityFinding(
            cve_id=finding["name"],
            severity=VulnerabilitySeverity(finding["severity"]),
            package_name=_attribute_value(finding["attributes"], "package_name"),
            package_version=_attribute_value(finding["attributes"], "package_version"),
        )
        for finding in scan["imageScanFindings"]["findings"]
    ]

    images = ecr.describe_images(repositoryName=ecr_repo, imageIds=[{"imageTag": image_tag}])
    image_detail = images["imageDetails"][0]

    return ImageInfo(
        digest=image_detail["imageDigest"],
        ecr_repo=ecr_repo,
        pushed_at=image_detail["imagePushedAt"],
        vulnerabilities=vulnerabilities,
    )


@activity.defn
async def wait_for_ecr_scan_activity(ecr_repo: str, image_tag: str) -> ImageInfo:
    return _build_image_info(ecr_repo, image_tag)


def _build_deployment_info(namespace: str, deployment_name: str, cluster: str) -> DeploymentInfo:
    k8s_config.load_kube_config()
    apps_v1 = k8s_client.AppsV1Api()
    core_v1 = k8s_client.CoreV1Api()

    deployment = apps_v1.read_namespaced_deployment(deployment_name, namespace)
    pods = core_v1.list_namespaced_pod(namespace, label_selector=f"app={deployment_name}")

    pod_statuses = [
        PodStatus(
            pod_name=pod.metadata.name,
            phase=pod.status.phase,
            ready=all(c.ready for c in (pod.status.container_statuses or [])),
        )
        for pod in pods.items
    ]

    return DeploymentInfo(
        cluster=cluster,
        namespace=namespace,
        replicas_desired=deployment.spec.replicas,
        replicas_ready=deployment.status.ready_replicas or 0,
        pod_statuses=pod_statuses,
        deployed_at=datetime.now(timezone.utc),
    )


@activity.defn
async def get_k8s_deployment_state_activity(namespace: str, deployment_name: str, cluster: str) -> DeploymentInfo:
    return _build_deployment_info(namespace, deployment_name, cluster)


@activity.defn
async def write_pipeline_run_activity(run_json: str) -> None:
    run = PipelineRun.model_validate_json(run_json)
    with Session(db.engine) as session:
        PipelineRunStore(session).upsert(run)
