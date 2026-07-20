import os

import requests
import streamlit as st
from streamlit_agraph import Config, agraph

from scie.ui.build_history_view import build_history_rows
from scie.ui.graph_render import collapse_attestations, to_agraph_elements

API_URL = os.environ.get("SCIE_API_URL", "http://localhost:8000")

KEY_PROP_BY_LABEL = {
    "Repository": "url",
    "Build": "id",
    "Commit": "sha",
    "Artifact": "digest",
    "Package": "purl",
    "VulnerabilityID": "id",
}

st.set_page_config(page_title="Graph Explorer", layout="wide")
st.title("Graph Explorer")

if "graph_nodes" not in st.session_state:
    st.session_state.graph_nodes = {}
    st.session_state.graph_edges = {}
    st.session_state.view_kind = "graph"


def _replace(result: dict, view_kind: str) -> None:
    st.session_state.graph_nodes = {node["element_id"]: node for node in result["nodes"]}
    st.session_state.graph_edges = {
        (edge["source"], edge["target"], edge["type"]): edge for edge in result["edges"]
    }
    st.session_state.view_kind = view_kind


def _merge(result: dict) -> None:
    for node in result["nodes"]:
        st.session_state.graph_nodes[node["element_id"]] = node
    for edge in result["edges"]:
        key = (edge["source"], edge["target"], edge["type"])
        st.session_state.graph_edges[key] = edge


def _fetch(path: str) -> dict | list:
    response = requests.get(f"{API_URL}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


def _run_query_and_rerun(path: str, view_kind: str) -> None:
    _replace(_fetch(path), view_kind)
    st.rerun()


show_edge_labels = st.sidebar.checkbox("Show edge labels", value=True)

mode = st.selectbox("Search by", ["Vulnerability ID", "Package PURL", "Repository URL"])

if mode == "Vulnerability ID":
    options = _fetch("/graph/vulnerabilities")
    option_labels = [opt["id"] for opt in options]
elif mode == "Package PURL":
    options = _fetch("/graph/packages")
    option_labels = [f'{opt["name"]}@{opt["version"]}' for opt in options]
else:
    options = _fetch("/graph/repositories")
    option_labels = [opt["name"] or opt["url"] for opt in options]

selected_index = None
if option_labels:
    selected_index = st.selectbox(
        "Value", options=range(len(option_labels)), format_func=lambda i: option_labels[i],
    )
else:
    st.info("No data seeded yet for this search mode.")

if st.button("Search") and selected_index is not None:
    selected = options[selected_index]
    if mode == "Vulnerability ID":
        _run_query_and_rerun(f"/graph/vulnerabilities/{selected['id']}/blast-radius", "graph")
    elif mode == "Package PURL":
        _run_query_and_rerun(f"/graph/packages/{selected['purl']}/usage", "graph")
    else:
        _run_query_and_rerun(f"/graph/repositories/{selected['url']}/history", "table")

if st.session_state.graph_nodes:
    if st.session_state.view_kind == "table":
        rows = build_history_rows(
            list(st.session_state.graph_nodes.values()),
            list(st.session_state.graph_edges.values()),
        )
        st.dataframe(rows, use_container_width=True)
        if st.button("Show as graph"):
            st.session_state.view_kind = "graph"
            st.rerun()
    else:
        nodes, edges = collapse_attestations(
            list(st.session_state.graph_nodes.values()),
            list(st.session_state.graph_edges.values()),
        )
        agraph_nodes, agraph_edges = to_agraph_elements(nodes, edges, show_edge_labels)
        config = Config(
            width=1000, height=800, directed=True,
            hierarchical=True, direction="LR", physics=False,
        )
        # Config's constructor always appends "px" to width/height, so a
        # percentage has to be set directly on the attribute afterward,
        # bypassing that formatting (same pattern as the Node.title override
        # elsewhere in this file). vis-network itself accepts any valid CSS
        # size string here — confirmed by inspecting the frontend bundle,
        # which parses our config JSON and hands it to vis-network as-is
        # with no validation.
        config.width = "100%"
        clicked_id = agraph(nodes=agraph_nodes, edges=agraph_edges, config=config)

        if clicked_id and clicked_id in st.session_state.graph_nodes:
            clicked_node = st.session_state.graph_nodes[clicked_id]
            label = clicked_node["labels"][0]
            props = clicked_node["properties"]
            st.subheader(label)
            for key, value in props.items():
                st.write(f"**{key}:** {value}")

            if label == "Package" and "purl" in props:
                if st.button("Show usage"):
                    _run_query_and_rerun(f"/graph/packages/{props['purl']}/usage", "graph")
            elif label == "VulnerabilityID" and "id" in props:
                lens_col1, lens_col2 = st.columns(2)
                with lens_col1:
                    if st.button("Blast radius"):
                        _run_query_and_rerun(
                            f"/graph/vulnerabilities/{props['id']}/blast-radius", "graph"
                        )
                with lens_col2:
                    if st.button("Origin trace"):
                        _run_query_and_rerun(
                            f"/graph/vulnerabilities/{props['id']}/origin", "graph"
                        )
            elif label == "Repository" and "url" in props:
                if st.button("Build history"):
                    _run_query_and_rerun(f"/graph/repositories/{props['url']}/history", "table")

            key_prop = KEY_PROP_BY_LABEL.get(label)
            if key_prop and key_prop in props:
                if st.button(f"Expand {label}"):
                    result = _fetch(f"/graph/expand/{label}/{key_prop}/{props[key_prop]}")
                    _merge(result)
                    st.rerun()
else:
    st.info("No graph data loaded yet — run a search above.")
