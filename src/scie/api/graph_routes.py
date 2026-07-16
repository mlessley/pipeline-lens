from fastapi import APIRouter, HTTPException
from neo4j.exceptions import ServiceUnavailable

from scie.graph import queries
from scie.graph.db import get_driver

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/vulnerabilities/{vuln_id}/blast-radius")
def get_vuln_blast_radius(vuln_id: str) -> dict:
    try:
        return queries.vuln_blast_radius(get_driver(), vuln_id)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/vulnerabilities/{vuln_id}/origin")
def get_vuln_origin_trace(vuln_id: str) -> dict:
    try:
        return queries.vuln_origin_trace(get_driver(), vuln_id)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/repositories/{repo_url:path}/history")
def get_repo_build_history(repo_url: str) -> dict:
    try:
        return queries.repo_build_history(get_driver(), repo_url)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/packages/{purl:path}/usage")
def get_package_usage(purl: str) -> dict:
    try:
        return queries.package_usage(get_driver(), purl)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")


@router.get("/expand/{node_label}/{key_prop}/{key_value:path}")
def get_expand_neighbors(node_label: str, key_prop: str, key_value: str) -> dict:
    try:
        return queries.expand_neighbors(get_driver(), node_label, key_prop, key_value)
    except ServiceUnavailable:
        raise HTTPException(status_code=503, detail="graph database unavailable")
