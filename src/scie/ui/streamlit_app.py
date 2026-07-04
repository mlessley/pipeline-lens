import os

import requests
import streamlit as st

API_URL = os.environ.get("SCIE_API_URL", "http://localhost:8000")

STATUS_COLORS = {
    "Deployed": "🟢",
    "DeployedWithFindings": "🟡",
    "Failed": "🔴",
    "InProgress": "🔵",
    "Stalled": "🟠",
    "Abandoned": "⚫",
}

st.set_page_config(page_title="Supply Chain Insights Engine", layout="wide")
st.title("Supply Chain Insights Engine")

services = requests.get(f"{API_URL}/services", timeout=10).json()

st.header("Fleet overview")
for service in services:
    badge = STATUS_COLORS.get(service["overall_status"], "⚪")
    demo_tag = " `[demo]`" if service["is_synthetic"] else ""
    st.write(f"{badge} **{service['service_name']}**{demo_tag} — {service['overall_status']}")

st.header("Service detail")
selected_service = st.selectbox(
    "Select a service", options=[s["service_name"] for s in services]
)

if selected_service:
    runs = requests.get(
        f"{API_URL}/pipeline-runs", params={"service_name": selected_service}, timeout=10
    ).json()
    for run in runs:
        st.subheader(f"Commit {run['id']}")
        st.json(run)
        timeline = requests.get(f"{API_URL}/pipeline-runs/{run['id']}/timeline", timeout=10).json()
        st.write(timeline["stages"])
