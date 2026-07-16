from graph_fakes import FakeDriver, FakeNode

from scie.graph import queries


def test_vuln_blast_radius_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.VULN_BLAST_RADIUS_QUERY, [])

    queries.vuln_blast_radius(driver, "CVE-2025-1111")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.VULN_BLAST_RADIUS_QUERY
    assert params == {"vuln_id": "CVE-2025-1111"}


def test_vuln_blast_radius_builds_nodes_and_edges_from_records():
    driver = FakeDriver()
    v = FakeNode("v1", ["VulnerabilityID"], {"id": "CVE-2025-1111"})
    vex = FakeNode("vex1", ["VexStatement"], {"status": "affected", "origin": "grype-scan"})
    p = FakeNode("p1", ["Package"], {"purl": "pkg:pypi/openssl@1.0.0"})
    dep = FakeNode("dep1", ["IsDependency"], {"origin": "synthetic-sbom"})
    a = FakeNode("a1", ["Artifact"], {"digest": "sha256:artifact0001"})
    d = FakeNode("d1", ["Deployment"], {"cluster": "scie", "environment": "prod"})
    driver.fake_session.set_result(
        queries.VULN_BLAST_RADIUS_QUERY,
        [{"v": v, "vex": vex, "p": p, "dep": dep, "a": a, "d": d}],
    )

    result = queries.vuln_blast_radius(driver, "CVE-2025-1111")

    node_ids = {node["element_id"] for node in result["nodes"]}
    assert node_ids == {"v1", "vex1", "p1", "dep1", "a1", "d1"}
    assert {"source": "vex1", "target": "v1", "type": "vulnerability"} in result["edges"]
    assert {"source": "vex1", "target": "p1", "type": "subject"} in result["edges"]
    assert {"source": "dep1", "target": "p1", "type": "dependency"} in result["edges"]
    assert {"source": "dep1", "target": "a1", "type": "subject"} in result["edges"]
    assert {"source": "a1", "target": "d1", "type": "DEPLOYED_TO"} in result["edges"]


def test_vuln_origin_trace_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.VULN_ORIGIN_TRACE_QUERY, [])

    queries.vuln_origin_trace(driver, "CVE-2025-1111")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.VULN_ORIGIN_TRACE_QUERY
    assert params == {"vuln_id": "CVE-2025-1111"}


def test_vuln_origin_trace_builds_nodes_and_edges_from_records():
    driver = FakeDriver()
    v = FakeNode("v1", ["VulnerabilityID"], {"id": "CVE-2025-1111"})
    vex = FakeNode("vex1", ["VexStatement"], {"status": "affected"})
    p = FakeNode("p1", ["Package"], {"purl": "pkg:pypi/openssl@1.0.0"})
    dep = FakeNode("dep1", ["IsDependency"], {"origin": "synthetic-sbom"})
    a = FakeNode("a1", ["Artifact"], {"digest": "sha256:artifact0001"})
    b = FakeNode("b1", ["Build"], {"id": "build-0001"})
    c = FakeNode("c1", ["Commit"], {"sha": "synthetic0001"})
    r = FakeNode("r1", ["Repository"], {"url": "https://github.com/example-org/billing-api-1"})
    driver.fake_session.set_result(
        queries.VULN_ORIGIN_TRACE_QUERY,
        [{"v": v, "vex": vex, "p": p, "dep": dep, "a": a, "b": b, "c": c, "r": r}],
    )

    result = queries.vuln_origin_trace(driver, "CVE-2025-1111")

    node_ids = {node["element_id"] for node in result["nodes"]}
    assert node_ids == {"v1", "vex1", "p1", "dep1", "a1", "b1", "c1", "r1"}
    assert {"source": "b1", "target": "a1", "type": "PRODUCED"} in result["edges"]
    assert {"source": "b1", "target": "c1", "type": "FOR_COMMIT"} in result["edges"]
    assert {"source": "r1", "target": "b1", "type": "HAS_BUILD"} in result["edges"]


def test_repo_build_history_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.REPO_BUILD_HISTORY_QUERY, [])

    queries.repo_build_history(driver, "https://github.com/example-org/billing-api-1")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.REPO_BUILD_HISTORY_QUERY
    assert params == {"repo_url": "https://github.com/example-org/billing-api-1"}


def test_repo_build_history_builds_nodes_and_edges_including_artifact_list():
    driver = FakeDriver()
    r = FakeNode("r1", ["Repository"], {"url": "https://github.com/example-org/billing-api-1"})
    b = FakeNode("b1", ["Build"], {"id": "build-0001"})
    a = FakeNode("a1", ["Artifact"], {"digest": "sha256:artifact0001"})
    driver.fake_session.set_result(
        queries.REPO_BUILD_HISTORY_QUERY,
        [{"r": r, "b": b, "artifacts": [a]}],
    )

    result = queries.repo_build_history(driver, "https://github.com/example-org/billing-api-1")

    node_ids = {node["element_id"] for node in result["nodes"]}
    assert node_ids == {"r1", "b1", "a1"}
    assert {"source": "r1", "target": "b1", "type": "HAS_BUILD"} in result["edges"]
    assert {"source": "b1", "target": "a1", "type": "PRODUCED"} in result["edges"]


def test_package_usage_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.PACKAGE_USAGE_QUERY, [])

    queries.package_usage(driver, "pkg:pypi/openssl@1.0.0")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.PACKAGE_USAGE_QUERY
    assert params == {"purl": "pkg:pypi/openssl@1.0.0"}


def test_package_usage_builds_nodes_and_edges_from_records():
    driver = FakeDriver()
    r = FakeNode("r1", ["Repository"], {"url": "https://github.com/example-org/billing-api-1"})
    b = FakeNode("b1", ["Build"], {"id": "build-0001"})
    a = FakeNode("a1", ["Artifact"], {"digest": "sha256:artifact0001"})
    p = FakeNode("p1", ["Package"], {"purl": "pkg:pypi/openssl@1.0.0"})
    dep = FakeNode("dep1", ["IsDependency"], {"origin": "synthetic-sbom"})
    driver.fake_session.set_result(
        queries.PACKAGE_USAGE_QUERY,
        [{"r": r, "b": b, "a": a, "p": p, "dep": dep}],
    )

    result = queries.package_usage(driver, "pkg:pypi/openssl@1.0.0")

    node_ids = {node["element_id"] for node in result["nodes"]}
    assert node_ids == {"r1", "b1", "a1", "p1", "dep1"}
    assert {"source": "r1", "target": "b1", "type": "HAS_BUILD"} in result["edges"]
    assert {"source": "b1", "target": "a1", "type": "PRODUCED"} in result["edges"]
    assert {"source": "dep1", "target": "a1", "type": "subject"} in result["edges"]
    assert {"source": "dep1", "target": "p1", "type": "dependency"} in result["edges"]


def test_expand_neighbors_sends_expected_query_and_params():
    driver = FakeDriver()
    driver.fake_session.set_result(queries.EXPAND_NEIGHBORS_QUERY, [])

    queries.expand_neighbors(driver, "Package", "purl", "pkg:pypi/openssl@1.0.0")

    statement, params = driver.fake_session.calls[0]
    assert statement == queries.EXPAND_NEIGHBORS_QUERY
    assert params == {
        "node_label": "Package",
        "key_prop": "purl",
        "key_value": "pkg:pypi/openssl@1.0.0",
    }


def test_expand_neighbors_respects_relationship_direction():
    driver = FakeDriver()
    n = FakeNode("p1", ["Package"], {"purl": "pkg:pypi/openssl@1.0.0"})
    neighbor = FakeNode("dep1", ["IsDependency"], {"origin": "synthetic-sbom"})
    driver.fake_session.set_result(
        queries.EXPAND_NEIGHBORS_QUERY,
        [{"n": n, "rel_type": "dependency", "neighbor": neighbor, "rel_from_n": False}],
    )

    result = queries.expand_neighbors(driver, "Package", "purl", "pkg:pypi/openssl@1.0.0")

    assert {"source": "dep1", "target": "p1", "type": "dependency"} in result["edges"]
