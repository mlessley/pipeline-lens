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

# vis-network node shapes (streamlit_agraph passes this straight through with
# no validation — confirmed by inspecting the built frontend bundle). Every
# type is a rectangle sized to its label text except VulnerabilityID, which
# gets a diamond so CVEs visually stand out as the "risk" node type rather
# than blending in as just another colored box.
SHAPE_BY_LABEL = {
    "Repository": "box",
    "Build": "box",
    "Commit": "box",
    "Artifact": "box",
    "Package": "box",
    "VulnerabilityID": "diamond",
    "Deployment": "box",
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


# vis-network markdown multi-font: font.multi="markdown" lets a label mix a
# default-styled segment with a `backtick-wrapped` segment rendered using
# font.mono. Used to make the type-badge line subtler (smaller, black) than
# the identifying-value line beneath it, both in the same monospace face.
# Black (not gray) for the mono segment — gray had too little contrast
# against our darker node colors (e.g. Commit's #C44E52, Repository's
# #4C72B0). align: "left" (vis-network default is "center") applies to the
# whole label block, not per-line — vis-network has no way to pin one
# segment to a corner independent of the rest of the label — but since the
# type badge is line 1, left-aligning the block reads as the badge sitting
# in the top-left rather than dead-center. vadjust (px, positive = down)
# nudges each segment vertically within the block: the mono/type segment
# shifts up toward the box's top border, the base/value segment shifts down
# slightly off dead-center.
NODE_FONT = {
    "face": "monospace",
    "size": 13,
    "align": "left",
    "vadjust": 3,
    "multi": "markdown",
    "mono": {"face": "monospace", "size": 8, "color": "#000000", "vadjust": -6},
}

# margin: default is 5px — bumped up so label text doesn't crowd the box
# walls. Only applies to box/circle/database/icon/text shapes per vis-network
# docs; our VulnerabilityID diamonds don't get it, which is fine since that's
# a single-line label with less crowding risk to begin with.
NODE_MARGIN = 8

EDGE_FONT = {"face": "monospace", "size": 10, "color": "#666666"}


def node_display_label(node: dict) -> str:
    label = node["labels"][0]
    builder = _DISPLAY_LABEL_BUILDERS.get(label)
    identifying_value = builder(node["properties"]) if builder else None
    if not identifying_value:
        return label
    return f"`{label}`\n{identifying_value}"


def _attestation_edge_label(node: dict) -> str:
    label = node["labels"][0]
    if label == "VexStatement":
        return f'Certify Vuln ({node["properties"].get("status", "?")})'
    return "Depends On"


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


def _humanize_edge_type(raw_type: str) -> str:
    """Convert a SCREAMING_SNAKE_CASE Neo4j relationship type (HAS_BUILD,
    PRODUCED) into Title Case with spaces for display. Strings that already
    read as human-readable text — the labels _attestation_edge_label
    produces — pass through unchanged."""
    if "_" not in raw_type and not raw_type.isupper():
        return raw_type
    return raw_type.replace("_", " ").title()


def to_agraph_elements(
    nodes: list[dict], edges: list[dict], show_edge_labels: bool = True,
) -> tuple[list[Node], list[Edge]]:
    agraph_nodes = []
    for node in nodes:
        label = node["labels"][0]
        agraph_node = Node(
            id=node["element_id"],
            label=node_display_label(node),
            color=NODE_COLORS.get(label, "#999999"),
            shape=SHAPE_BY_LABEL.get(label, "box"),
            font=NODE_FONT,
            margin=NODE_MARGIN,
        )
        # streamlit_agraph defaults title to id and opens it via window.open()
        # on double-click; Node(title=...) falls back to id for any falsy
        # value, so the attribute must be cleared after construction.
        agraph_node.title = ""
        agraph_nodes.append(agraph_node)
    agraph_edges = [
        Edge(
            source=edge["source"],
            target=edge["target"],
            label=_humanize_edge_type(edge["type"]) if show_edge_labels else "",
            font=EDGE_FONT,
        )
        for edge in edges
    ]
    return agraph_nodes, agraph_edges
