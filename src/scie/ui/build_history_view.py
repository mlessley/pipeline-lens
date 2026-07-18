def build_history_rows(nodes: list[dict], edges: list[dict]) -> list[dict]:
    nodes_by_id = {node["element_id"]: node for node in nodes}
    builds = [node for node in nodes if node["labels"][0] == "Build"]

    artifact_names_by_build: dict[str, list[str]] = {}
    for edge in edges:
        if edge["type"] != "PRODUCED":
            continue
        artifact = nodes_by_id.get(edge["target"])
        if artifact is None:
            continue
        name = artifact["properties"].get("name") or artifact["properties"].get("digest", "")
        artifact_names_by_build.setdefault(edge["source"], []).append(name)

    rows = []
    for build in builds:
        props = build["properties"]
        rows.append({
            "Start Time": props.get("startTime", ""),
            "CI System": props.get("ciSystem", ""),
            "Status": "✅" if props.get("status") == "success" else "❌",
            "Artifacts": ", ".join(artifact_names_by_build.get(build["element_id"], [])),
        })

    rows.sort(key=lambda row: row["Start Time"], reverse=True)
    return rows
