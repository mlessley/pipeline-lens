from neo4j import Driver

VULN_BLAST_RADIUS_QUERY = """
MATCH (v:VulnerabilityID {id: $vuln_id})<-[:vulnerability]-(vex:VexStatement {status: 'affected'})-[:subject]->(p:Package)
MATCH (dep:IsDependency)-[:dependency]->(p)
MATCH (dep)-[:subject]->(a:Artifact)-[:DEPLOYED_TO]->(d:Deployment)
RETURN v, vex, p, dep, a, d
"""

VULN_ORIGIN_TRACE_QUERY = """
MATCH (v:VulnerabilityID {id: $vuln_id})<-[:vulnerability]-(vex:VexStatement {status: 'affected'})-[:subject]->(p:Package)
MATCH (dep:IsDependency)-[:dependency]->(p)
MATCH (dep)-[:subject]->(a:Artifact)
MATCH (b:Build)-[:PRODUCED]->(a)
MATCH (b)-[:FOR_COMMIT]->(c:Commit)
MATCH (r:Repository)-[:HAS_BUILD]->(b)
RETURN v, vex, p, dep, a, b, c, r
"""

REPO_BUILD_HISTORY_QUERY = """
MATCH (r:Repository {url: $repo_url})-[:HAS_BUILD]->(b:Build)
OPTIONAL MATCH (b)-[:PRODUCED]->(a:Artifact)
RETURN r, b, collect(a) AS artifacts
ORDER BY b.startTime DESC
"""

PACKAGE_USAGE_QUERY = """
MATCH (p:Package {purl: $purl})<-[:dependency]-(dep:IsDependency)-[:subject]->(a:Artifact)
MATCH (b:Build)-[:PRODUCED]->(a)
MATCH (r:Repository)-[:HAS_BUILD]->(b)
RETURN r, b, a, p, dep
"""

EXPAND_NEIGHBORS_QUERY = """
MATCH (n) WHERE $node_label IN labels(n) AND n[$key_prop] = $key_value
MATCH (n)-[rel]-(neighbor)
RETURN n, type(rel) AS rel_type, neighbor, startNode(rel) = n AS rel_from_n
"""

LIST_PACKAGES_QUERY = """
MATCH (p:Package)
RETURN p.purl AS purl, p.name AS name, p.version AS version
ORDER BY p.name
"""

LIST_VULNERABILITIES_QUERY = """
MATCH (v:VulnerabilityID)
RETURN v.id AS id
ORDER BY v.id
"""

LIST_REPOSITORIES_QUERY = """
MATCH (r:Repository)
RETURN r.url AS url, r.name AS name
ORDER BY r.name
"""


def _serialize_value(value):
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if hasattr(value, "labels") and hasattr(value, "items"):
        return {
            "element_id": value.element_id,
            "labels": list(value.labels),
            "properties": dict(value),
        }
    return value


def _run(driver: Driver, query: str, **params) -> list[dict]:
    with driver.session() as session:
        result = session.run(query, **params)
        return [
            {key: _serialize_value(value) for key, value in record.items()}
            for record in result
        ]


def vuln_blast_radius(driver: Driver, vuln_id: str) -> dict:
    records = _run(driver, VULN_BLAST_RADIUS_QUERY, vuln_id=vuln_id)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        v, vex, p, dep, a, d = (
            record["v"], record["vex"], record["p"],
            record["dep"], record["a"], record["d"],
        )
        for node in (v, vex, p, dep, a, d):
            nodes[node["element_id"]] = node
        edges.append({"source": vex["element_id"], "target": v["element_id"], "type": "vulnerability"})
        edges.append({"source": vex["element_id"], "target": p["element_id"], "type": "subject"})
        edges.append({"source": dep["element_id"], "target": p["element_id"], "type": "dependency"})
        edges.append({"source": dep["element_id"], "target": a["element_id"], "type": "subject"})
        edges.append({"source": a["element_id"], "target": d["element_id"], "type": "DEPLOYED_TO"})
    return {"nodes": list(nodes.values()), "edges": edges}


def vuln_origin_trace(driver: Driver, vuln_id: str) -> dict:
    records = _run(driver, VULN_ORIGIN_TRACE_QUERY, vuln_id=vuln_id)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        v, vex, p, dep, a, b, c, r = (
            record["v"], record["vex"], record["p"], record["dep"],
            record["a"], record["b"], record["c"], record["r"],
        )
        for node in (v, vex, p, dep, a, b, c, r):
            nodes[node["element_id"]] = node
        edges.append({"source": vex["element_id"], "target": v["element_id"], "type": "vulnerability"})
        edges.append({"source": vex["element_id"], "target": p["element_id"], "type": "subject"})
        edges.append({"source": dep["element_id"], "target": p["element_id"], "type": "dependency"})
        edges.append({"source": dep["element_id"], "target": a["element_id"], "type": "subject"})
        edges.append({"source": b["element_id"], "target": a["element_id"], "type": "PRODUCED"})
        edges.append({"source": b["element_id"], "target": c["element_id"], "type": "FOR_COMMIT"})
        edges.append({"source": r["element_id"], "target": b["element_id"], "type": "HAS_BUILD"})
    return {"nodes": list(nodes.values()), "edges": edges}


def repo_build_history(driver: Driver, repo_url: str) -> dict:
    records = _run(driver, REPO_BUILD_HISTORY_QUERY, repo_url=repo_url)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        r, b, artifacts = record["r"], record["b"], record["artifacts"]
        nodes[r["element_id"]] = r
        nodes[b["element_id"]] = b
        edges.append({"source": r["element_id"], "target": b["element_id"], "type": "HAS_BUILD"})
        for artifact in artifacts:
            nodes[artifact["element_id"]] = artifact
            edges.append({"source": b["element_id"], "target": artifact["element_id"], "type": "PRODUCED"})
    return {"nodes": list(nodes.values()), "edges": edges}


def package_usage(driver: Driver, purl: str) -> dict:
    records = _run(driver, PACKAGE_USAGE_QUERY, purl=purl)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        r, b, a, p, dep = record["r"], record["b"], record["a"], record["p"], record["dep"]
        for node in (r, b, a, p, dep):
            nodes[node["element_id"]] = node
        edges.append({"source": r["element_id"], "target": b["element_id"], "type": "HAS_BUILD"})
        edges.append({"source": b["element_id"], "target": a["element_id"], "type": "PRODUCED"})
        edges.append({"source": dep["element_id"], "target": a["element_id"], "type": "subject"})
        edges.append({"source": dep["element_id"], "target": p["element_id"], "type": "dependency"})
    return {"nodes": list(nodes.values()), "edges": edges}


def expand_neighbors(driver: Driver, node_label: str, key_prop: str, key_value: str) -> dict:
    records = _run(
        driver, EXPAND_NEIGHBORS_QUERY,
        node_label=node_label, key_prop=key_prop, key_value=key_value,
    )
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for record in records:
        n, neighbor = record["n"], record["neighbor"]
        nodes[n["element_id"]] = n
        nodes[neighbor["element_id"]] = neighbor
        source, target = (n, neighbor) if record["rel_from_n"] else (neighbor, n)
        edges.append({
            "source": source["element_id"],
            "target": target["element_id"],
            "type": record["rel_type"],
        })
    return {"nodes": list(nodes.values()), "edges": edges}


def list_packages(driver: Driver) -> list[dict]:
    return _run(driver, LIST_PACKAGES_QUERY)


def list_vulnerabilities(driver: Driver) -> list[dict]:
    return _run(driver, LIST_VULNERABILITIES_QUERY)


def list_repositories(driver: Driver) -> list[dict]:
    return _run(driver, LIST_REPOSITORIES_QUERY)
