from graph_fakes import FakeDriver

from scie.graph.synthetic_graph import VULNERABILITY_CATALOG, generate_synthetic_graph


def test_generates_one_repository_merge_per_count():
    driver = FakeDriver()

    generate_synthetic_graph(driver, count=5, seed=42)

    repo_merges = [
        call for call in driver.fake_session.calls
        if call[0].strip().startswith("MERGE (r:Repository")
    ]
    assert len(repo_merges) == 5


def test_same_seed_is_deterministic():
    first_driver = FakeDriver()
    generate_synthetic_graph(first_driver, count=5, seed=7)

    second_driver = FakeDriver()
    generate_synthetic_graph(second_driver, count=5, seed=7)

    assert first_driver.fake_session.calls == second_driver.fake_session.calls


def test_writes_a_vex_statement_for_every_catalog_vulnerability():
    driver = FakeDriver()

    generate_synthetic_graph(driver, count=5, seed=42)

    vuln_merges = [
        call for call in driver.fake_session.calls
        if call[0].strip().startswith("MERGE (v:VulnerabilityID")
    ]
    seen_vuln_ids = {call[1]["id"] for call in vuln_merges}
    expected_vuln_ids = {vuln_id for vuln_id, _purl in VULNERABILITY_CATALOG}
    assert seen_vuln_ids == expected_vuln_ids


def test_writes_at_least_one_vex_statement_create_per_vulnerability():
    driver = FakeDriver()

    generate_synthetic_graph(driver, count=5, seed=42)

    vex_creates = [
        call for call in driver.fake_session.calls
        if "CREATE (vex:VexStatement" in call[0]
    ]
    assert len(vex_creates) >= len(VULNERABILITY_CATALOG)
