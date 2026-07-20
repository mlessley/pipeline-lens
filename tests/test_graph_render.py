from scie.ui.graph_render import collapse_attestations, node_display_label, to_agraph_elements


def _node(element_id, label, **props):
    return {"element_id": element_id, "labels": [label], "properties": props}


def test_node_display_label_uses_identifying_property_per_label():
    assert node_display_label(_node("r1", "Repository", url="https://x/y", name="y")) == "`Repository`\ny"
    assert node_display_label(_node("b1", "Build", id="build-0001")) == "`Build`\nbuild-0001"
    assert node_display_label(_node("c1", "Commit", sha="abcdef1234567890")) == "`Commit`\nabcdef1"
    assert node_display_label(_node("a1", "Artifact", digest="sha256:x", name="svc")) == "`Artifact`\nsvc"
    assert node_display_label(_node("p1", "Package", name="openssl", version="1.0.0")) == "`Package`\nopenssl@1.0.0"
    assert node_display_label(_node("v1", "VulnerabilityID", id="CVE-2014-0160")) == "`VulnerabilityID`\nCVE-2014-0160"
    assert node_display_label(_node("d1", "Deployment", cluster="scie", namespace="prod")) == "`Deployment`\nscie/prod"


def test_node_display_label_falls_back_to_label_for_unknown_type():
    assert node_display_label(_node("x1", "SomethingElse")) == "SomethingElse"


def test_collapse_attestations_merges_vex_statement_into_edge_label():
    nodes = [
        _node("v1", "VulnerabilityID", id="CVE-2014-0160"),
        _node("vex1", "VexStatement", status="affected", origin="grype-scan"),
        _node("p1", "Package", name="openssl", version="1.0.0"),
    ]
    edges = [
        {"source": "vex1", "target": "v1", "type": "vulnerability"},
        {"source": "vex1", "target": "p1", "type": "subject"},
    ]

    kept_nodes, kept_edges = collapse_attestations(nodes, edges)

    assert {n["element_id"] for n in kept_nodes} == {"v1", "p1"}
    assert kept_edges == [{"source": "p1", "target": "v1", "type": "Certify Vuln (affected)"}]


def test_collapse_attestations_merges_is_dependency_into_edge_label():
    nodes = [
        _node("a1", "Artifact", digest="sha256:x", name="svc"),
        _node("dep1", "IsDependency", origin="synthetic-sbom"),
        _node("p1", "Package", name="openssl", version="1.0.0"),
    ]
    edges = [
        {"source": "dep1", "target": "p1", "type": "dependency"},
        {"source": "dep1", "target": "a1", "type": "subject"},
    ]

    kept_nodes, kept_edges = collapse_attestations(nodes, edges)

    assert {n["element_id"] for n in kept_nodes} == {"a1", "p1"}
    assert kept_edges == [{"source": "a1", "target": "p1", "type": "Depends On"}]


def test_collapse_attestations_preserves_non_attestation_edges():
    nodes = [_node("r1", "Repository", url="x", name="x"), _node("b1", "Build", id="build-0001")]
    edges = [{"source": "r1", "target": "b1", "type": "HAS_BUILD"}]

    kept_nodes, kept_edges = collapse_attestations(nodes, edges)

    assert kept_nodes == nodes
    assert kept_edges == edges


def test_to_agraph_elements_builds_nodes_with_empty_title_and_display_label():
    nodes = [_node("p1", "Package", name="openssl", version="1.0.0")]
    edges = [{"source": "p1", "target": "p1", "type": "self"}]

    agraph_nodes, agraph_edges = to_agraph_elements(nodes, edges)

    assert len(agraph_nodes) == 1
    assert agraph_nodes[0].id == "p1"
    assert agraph_nodes[0].label == "`Package`\nopenssl@1.0.0"
    assert agraph_nodes[0].title == ""
    assert agraph_nodes[0].color == "#CCB974"
    assert agraph_nodes[0].shape == "box"
    assert agraph_nodes[0].font == {
        "face": "monospace",
        "size": 13,
        "align": "left",
        "vadjust": 3,
        "multi": "markdown",
        "mono": {"face": "monospace", "size": 8, "color": "#000000", "vadjust": -6},
    }
    assert agraph_nodes[0].margin == 8
    assert len(agraph_edges) == 1
    assert agraph_edges[0].source == "p1"
    assert agraph_edges[0].to == "p1"
    assert agraph_edges[0].label == "self"
    assert agraph_edges[0].font == {"face": "monospace", "size": 10, "color": "#666666"}


def test_to_agraph_elements_gives_vulnerability_nodes_a_diamond_shape():
    nodes = [_node("v1", "VulnerabilityID", id="CVE-2014-0160")]

    agraph_nodes, _ = to_agraph_elements(nodes, [])

    assert agraph_nodes[0].shape == "diamond"


def test_to_agraph_elements_humanizes_underscored_edge_types():
    nodes = [_node("r1", "Repository", url="x", name="x"), _node("b1", "Build", id="build-0001")]
    edges = [{"source": "r1", "target": "b1", "type": "HAS_BUILD"}]

    _, agraph_edges = to_agraph_elements(nodes, edges)

    assert agraph_edges[0].label == "Has Build"


def test_to_agraph_elements_humanizes_single_word_uppercase_edge_types():
    nodes = [_node("b1", "Build", id="build-0001"), _node("a1", "Artifact", digest="x")]
    edges = [{"source": "b1", "target": "a1", "type": "PRODUCED"}]

    _, agraph_edges = to_agraph_elements(nodes, edges)

    assert agraph_edges[0].label == "Produced"


def test_to_agraph_elements_leaves_already_human_readable_edge_types_unchanged():
    nodes = [_node("a1", "Artifact", digest="x"), _node("p1", "Package", name="x", version="1")]
    edges = [{"source": "a1", "target": "p1", "type": "Depends On"}]

    _, agraph_edges = to_agraph_elements(nodes, edges)

    assert agraph_edges[0].label == "Depends On"


def test_to_agraph_elements_clears_edge_labels_when_show_edge_labels_is_false():
    nodes = [_node("r1", "Repository", url="x", name="x"), _node("b1", "Build", id="build-0001")]
    edges = [{"source": "r1", "target": "b1", "type": "HAS_BUILD"}]

    _, agraph_edges = to_agraph_elements(nodes, edges, show_edge_labels=False)

    assert agraph_edges[0].label == ""
