from graph_fakes import FakeDriver

import scie.graph.seed as seed


def test_main_applies_constraints_and_generates_graph(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(seed, "get_driver", lambda: driver)

    seed.main(count=3)

    ran_statements = [call[0] for call in driver.fake_session.calls]
    assert any(
        stmt.startswith("CREATE CONSTRAINT repository_url") for stmt in ran_statements
    )
    repo_merges = [s for s in ran_statements if s.strip().startswith("MERGE (r:Repository")]
    assert len(repo_merges) == 3
