from streamlit_agraph import Edge, Node

NODE_COLORS = {
    "Repository": "#4C72B0",
    "Build": "#55A868",
    "Commit": "#C44E52",
    "Artifact": "#8172B2",
    "Package": "#CCB974",
    "VulnerabilityID": "#DA3B3B",
    "Deployment": "#8C8C8C",
}

# Canvas display text only — distinct from queries.py callers' notion of a
# unique lookup key (see KEY_PROP_BY_LABEL in 1_Graph_Explorer.py, and the
# fe429d8 fix that removed Deployment.cluster from that dict for not being
# unique enough for that purpose). Display text has no uniqueness
# requirement, so it can combine fields freely.
_DISPLAY_LABEL_BUILDERS = {
    "Repository": lambda props: props.get("name") or props.get("url", ""),
    "Build": lambda props: props.get("id", ""),
    "Commit": lambda props: props.get("sha", "")[:7],
    "Artifact": lambda props: props.get("name") or props.get("digest", ""),
    "Package": lambda props: f'{props.get("name", "?")}@{props.get("version", "?")}',
    "VulnerabilityID": lambda props: props.get("id", ""),
    "Deployment": lambda props: f'{props.get("cluster", "?")}/{props.get("namespace", "?")}',
}

# Attestation nodes are always the *source* of both their edges (the GUAC
# convention this schema follows — see the "Graph Schema" section of
# docs/superpowers/specs/2026-07-16-graph-explorer-design.md). Each entry
# names which of an attestation's two outgoing edge types becomes the
# collapsed edge's source-neighbor vs target-neighbor.
_ATTESTATION_EDGE_ROLES = {
    "VexStatement": {"source_edge_type": "subject", "target_edge_type": "vulnerability"},
    "IsDependency": {"source_edge_type": "subject", "target_edge_type": "dependency"},
}


def node_display_label(node: dict) -> str:
    label = node["labels"][0]
    builder = _DISPLAY_LABEL_BUILDERS.get(label)
    if builder is None:
        return label
    return builder(node["properties"]) or label


def _attestation_edge_label(node: dict) -> str:
    label = node["labels"][0]
    if label == "VexStatement":
        return f'CertifyVuln ({node["properties"].get("status", "?")})'
    return "DependsOn"


def collapse_attestations(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse VexStatement/IsDependency attestation nodes into a single
    labeled edge between their two neighbors. Pure rendering-layer transform
    — the Neo4j data model and queries.py are untouched."""
    attestation_nodes = {
        n["element_id"]: n for n in nodes if n["labels"][0] in _ATTESTATION_EDGE_ROLES
    }
    kept_nodes = [n for n in nodes if n["element_id"] not in attestation_nodes]

    edges_by_attestation: dict[str, dict[str, str]] = {}
    kept_edges = []
    for edge in edges:
        if edge["source"] in attestation_nodes:
            edges_by_attestation.setdefault(edge["source"], {})[edge["type"]] = edge["target"]
        else:
            kept_edges.append(edge)

    for attestation_id, by_type in edges_by_attestation.items():
        attestation_node = attestation_nodes[attestation_id]
        roles = _ATTESTATION_EDGE_ROLES[attestation_node["labels"][0]]
        source_id = by_type.get(roles["source_edge_type"])
        target_id = by_type.get(roles["target_edge_type"])
        if source_id is None or target_id is None:
            continue
        kept_edges.append({
            "source": source_id,
            "target": target_id,
            "type": _attestation_edge_label(attestation_node),
        })

    return kept_nodes, kept_edges


def to_agraph_elements(nodes: list[dict], edges: list[dict]) -> tuple[list[Node], list[Edge]]:
    agraph_nodes = []
    for node in nodes:
        label = node["labels"][0]
        agraph_node = Node(
            id=node["element_id"],
            label=node_display_label(node),
            color=NODE_COLORS.get(label, "#999999"),
        )
        # streamlit_agraph defaults title to id and opens it via window.open()
        # on double-click; Node(title=...) falls back to id for any falsy
        # value, so the attribute must be cleared after construction.
        agraph_node.title = ""
        agraph_nodes.append(agraph_node)
    agraph_edges = [
        Edge(source=edge["source"], target=edge["target"], label=edge["type"])
        for edge in edges
    ]
    return agraph_nodes, agraph_edges
