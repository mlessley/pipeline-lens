from unittest.mock import MagicMock

import scie.graph.db as graph_db


def test_get_driver_constructs_with_configured_uri_and_auth(monkeypatch):
    monkeypatch.setattr(graph_db, "_driver", None)
    fake_driver = MagicMock()
    captured = {}

    def fake_driver_factory(uri, auth):
        captured["uri"] = uri
        captured["auth"] = auth
        return fake_driver

    monkeypatch.setattr(graph_db.GraphDatabase, "driver", fake_driver_factory)

    driver = graph_db.get_driver()

    assert driver is fake_driver
    assert captured["uri"] == graph_db.NEO4J_URI
    assert captured["auth"] == (graph_db.NEO4J_USER, graph_db.NEO4J_PASSWORD)


def test_get_driver_returns_cached_instance(monkeypatch):
    monkeypatch.setattr(graph_db, "_driver", None)
    fake_driver = MagicMock()
    monkeypatch.setattr(graph_db.GraphDatabase, "driver", lambda uri, auth: fake_driver)

    first = graph_db.get_driver()
    second = graph_db.get_driver()

    assert first is second
