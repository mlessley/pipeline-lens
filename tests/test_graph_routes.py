from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from scie.api import graph_routes
from scie.api.app import app


def test_vuln_blast_radius_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "vuln_blast_radius",
        lambda driver, vuln_id: {"nodes": [{"element_id": vuln_id}], "edges": []},
    )
    client = TestClient(app)

    response = client.get("/graph/vulnerabilities/CVE-2025-1111/blast-radius")

    assert response.status_code == 200
    assert response.json() == {"nodes": [{"element_id": "CVE-2025-1111"}], "edges": []}


def test_vuln_origin_trace_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "vuln_origin_trace",
        lambda driver, vuln_id: {"nodes": [], "edges": []},
    )
    client = TestClient(app)

    response = client.get("/graph/vulnerabilities/CVE-2025-1111/origin")

    assert response.status_code == 200
    assert response.json() == {"nodes": [], "edges": []}


def test_repo_build_history_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "repo_build_history",
        lambda driver, repo_url: {"nodes": [], "edges": [], "repo_url": repo_url},
    )
    client = TestClient(app)

    response = client.get(
        "/graph/repositories/https://github.com/example-org/billing-api-1/history"
    )

    assert response.status_code == 200
    assert response.json()["repo_url"] == "https://github.com/example-org/billing-api-1"


def test_package_usage_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "package_usage",
        lambda driver, purl: {"nodes": [], "edges": [], "purl": purl},
    )
    client = TestClient(app)

    response = client.get("/graph/packages/pkg:pypi/openssl@1.0.0/usage")

    assert response.status_code == 200
    assert response.json()["purl"] == "pkg:pypi/openssl@1.0.0"


def test_expand_neighbors_route_returns_query_results(monkeypatch):
    monkeypatch.setattr(
        graph_routes.queries, "expand_neighbors",
        lambda driver, node_label, key_prop, key_value: {
            "nodes": [], "edges": [], "args": [node_label, key_prop, key_value],
        },
    )
    client = TestClient(app)

    response = client.get("/graph/expand/Package/purl/pkg:pypi/openssl@1.0.0")

    assert response.status_code == 200
    assert response.json()["args"] == ["Package", "purl", "pkg:pypi/openssl@1.0.0"]


def test_vuln_blast_radius_route_returns_503_when_graph_db_unavailable(monkeypatch):
    def raise_unavailable(driver, vuln_id):
        raise ServiceUnavailable("down")

    monkeypatch.setattr(graph_routes.queries, "vuln_blast_radius", raise_unavailable)
    client = TestClient(app)

    response = client.get("/graph/vulnerabilities/CVE-2025-1111/blast-radius")

    assert response.status_code == 503
