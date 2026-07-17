from scie.ui.build_history_view import build_history_rows


def _node(element_id, label, **props):
    return {"element_id": element_id, "labels": [label], "properties": props}


def test_build_history_rows_includes_artifact_names_and_status_glyph():
    nodes = [
        _node(
            "b1", "Build", id="build-0001",
            startTime="2026-01-01T00:00:00+00:00", ciSystem="github-actions", status="success",
        ),
        _node("a1", "Artifact", digest="sha256:x", name="svc-a"),
    ]
    edges = [{"source": "b1", "target": "a1", "type": "PRODUCED"}]

    rows = build_history_rows(nodes, edges)

    assert rows == [{
        "Start Time": "2026-01-01T00:00:00+00:00",
        "CI System": "github-actions",
        "Status": "✅",
        "Artifacts": "svc-a",
    }]


def test_build_history_rows_uses_failure_glyph_for_non_success_status():
    nodes = [
        _node(
            "b1", "Build", id="build-0001",
            startTime="2026-01-01T00:00:00+00:00", ciSystem="github-actions", status="failed",
        ),
    ]

    rows = build_history_rows(nodes, [])

    assert rows[0]["Status"] == "❌"


def test_build_history_rows_sorted_by_start_time_descending():
    nodes = [
        _node(
            "b1", "Build", id="build-0001",
            startTime="2026-01-01T00:00:00+00:00", ciSystem="x", status="success",
        ),
        _node(
            "b2", "Build", id="build-0002",
            startTime="2026-01-02T00:00:00+00:00", ciSystem="x", status="success",
        ),
    ]

    rows = build_history_rows(nodes, [])

    assert [row["Start Time"] for row in rows] == [
        "2026-01-02T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
    ]


def test_build_history_rows_handles_build_with_no_artifacts():
    nodes = [
        _node(
            "b1", "Build", id="build-0001",
            startTime="2026-01-01T00:00:00+00:00", ciSystem="x", status="success",
        ),
    ]

    rows = build_history_rows(nodes, [])

    assert rows[0]["Artifacts"] == ""
