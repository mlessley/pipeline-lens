import os

import requests
import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

API_URL = os.environ.get("SCIE_API_URL", "http://localhost:8000")

NODE_COLORS = {
    "Repository": "#4C72B0",
    "Build": "#55A868",
    "Commit": "#C44E52",
    "Artifact": "#8172B2",
    "Package": "#CCB974",
    "VulnerabilityID": "#DA3B3B",
    "VexStatement": "#64B5CD",
    "IsDependency": "#B0B0B0",
    "Deployment": "#8C8C8C",
}

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


def _absorb(result: dict) -> None:
    for node in result["nodes"]:
        st.session_state.graph_nodes[node["element_id"]] = node
    for edge in result["edges"]:
        key = (edge["source"], edge["target"], edge["type"])
        st.session_state.graph_edges[key] = edge


mode = st.selectbox("Search by", ["Vulnerability ID", "Package PURL", "Repository URL"])
query_value = st.text_input("Value")

if st.button("Search") and query_value:
    if mode == "Vulnerability ID":
        response = requests.get(
            f"{API_URL}/graph/vulnerabilities/{query_value}/blast-radius", timeout=10
        )
    elif mode == "Package PURL":
        response = requests.get(f"{API_URL}/graph/packages/{query_value}/usage", timeout=10)
    else:
        response = requests.get(
            f"{API_URL}/graph/repositories/{query_value}/history", timeout=10
        )
    response.raise_for_status()
    _absorb(response.json())

if st.session_state.graph_nodes:
    nodes = [
        Node(
            id=element_id,
            label=node["labels"][0],
            color=NODE_COLORS.get(node["labels"][0], "#999999"),
        )
        for element_id, node in st.session_state.graph_nodes.items()
    ]
    edges = [
        Edge(source=edge["source"], target=edge["target"], label=edge["type"])
        for edge in st.session_state.graph_edges.values()
    ]
    config = Config(width=1000, height=600, directed=True, physics=True)
    clicked_id = agraph(nodes=nodes, edges=edges, config=config)

    if clicked_id and clicked_id in st.session_state.graph_nodes:
        clicked_node = st.session_state.graph_nodes[clicked_id]
        label = clicked_node["labels"][0]
        st.subheader(label)
        st.json(clicked_node["properties"])

        key_prop = KEY_PROP_BY_LABEL.get(label)
        if key_prop and key_prop in clicked_node["properties"]:
            if st.button(f"Expand {label}"):
                key_value = clicked_node["properties"][key_prop]
                response = requests.get(
                    f"{API_URL}/graph/expand/{label}/{key_prop}/{key_value}", timeout=10
                )
                response.raise_for_status()
                _absorb(response.json())
                st.rerun()
else:
    st.info("No graph data loaded yet — run a search above.")
