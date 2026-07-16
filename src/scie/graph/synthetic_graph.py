import random
from datetime import datetime, timedelta, timezone

from neo4j import Driver

SERVICE_NAMES = [
    "billing-api",
    "auth-service",
    "notification-worker",
    "inventory-sync",
    "payments-gateway",
    "user-profile",
    "search-indexer",
    "audit-logger",
]

PACKAGE_CATALOG = [
    ("pkg:pypi/openssl@1.0.0", "openssl", "1.0.0"),
    ("pkg:pypi/requests@2.25.0", "requests", "2.25.0"),
    ("pkg:pypi/urllib3@1.26.0", "urllib3", "1.26.0"),
    ("pkg:pypi/jinja2@2.11.0", "jinja2", "2.11.0"),
    ("pkg:pypi/pyyaml@5.3.1", "pyyaml", "5.3.1"),
]

VULNERABILITY_CATALOG = [
    ("CVE-2025-1111", "pkg:pypi/openssl@1.0.0"),
    ("CVE-2025-2222", "pkg:pypi/requests@2.25.0"),
    ("CVE-2025-3333", "pkg:pypi/urllib3@1.26.0"),
]

VEX_ORIGINS = ["grype-scan", "vendor-vex-feed"]
VEX_STATUSES = ["affected", "affected", "not_affected", "fixed"]
ENVIRONMENTS = ["prod", "staging", "dev"]


def generate_synthetic_graph(driver: Driver, count: int = 10, seed: int | None = None) -> None:
    rng = random.Random(seed)
    with driver.session() as session:
        for i in range(count):
            _write_chain(session, rng, i)
        for vuln_id, purl in VULNERABILITY_CATALOG:
            _write_vex_statements(session, rng, vuln_id, purl)


def _write_chain(session, rng: random.Random, i: int) -> None:
    service_name = f"{rng.choice(SERVICE_NAMES)}-{i}"
    repo_url = f"https://github.com/example-org/{service_name}"
    commit_sha = f"synthetic{i:04d}"
    build_id = f"build-{i:04d}"
    digest = f"sha256:artifact{i:04d}"
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc) - timedelta(hours=rng.randint(0, 72))

    session.run(
        "MERGE (r:Repository {url: $url}) SET r.name = $name",
        url=repo_url,
        name=service_name,
    )
    session.run(
        """
        MATCH (r:Repository {url: $repo_url})
        MERGE (b:Build {id: $build_id})
        SET b.startTime = $start_time, b.ciSystem = 'github-actions', b.status = 'success'
        MERGE (r)-[:HAS_BUILD]->(b)
        """,
        repo_url=repo_url,
        build_id=build_id,
        start_time=base_time.isoformat(),
    )
    session.run(
        """
        MATCH (b:Build {id: $build_id})
        MERGE (c:Commit {sha: $sha})
        SET c.author = $author, c.timestamp = $timestamp
        MERGE (b)-[:FOR_COMMIT]->(c)
        """,
        build_id=build_id,
        sha=commit_sha,
        author=rng.choice(["alice", "bob", "carol"]),
        timestamp=base_time.isoformat(),
    )
    session.run(
        """
        MATCH (b:Build {id: $build_id})
        MERGE (a:Artifact {digest: $digest})
        SET a.name = $name
        MERGE (b)-[:PRODUCED]->(a)
        """,
        build_id=build_id,
        digest=digest,
        name=service_name,
    )

    package_count = rng.choice([1, 1, 2, 3])
    for purl, name, version in rng.sample(PACKAGE_CATALOG, package_count):
        session.run(
            """
            MATCH (a:Artifact {digest: $digest})
            MERGE (p:Package {purl: $purl})
            SET p.name = $name, p.version = $version
            CREATE (dep:IsDependency {origin: 'synthetic-sbom'})
            CREATE (dep)-[:subject]->(a)
            CREATE (dep)-[:dependency]->(p)
            """,
            digest=digest,
            purl=purl,
            name=name,
            version=version,
        )

    if rng.random() < 0.7:
        environment = rng.choice(ENVIRONMENTS)
        session.run(
            """
            MATCH (a:Artifact {digest: $digest})
            CREATE (d:Deployment {
                cluster: 'scie', namespace: $environment, environment: $environment,
                deployed_at: $deployed_at
            })
            CREATE (a)-[:DEPLOYED_TO]->(d)
            """,
            digest=digest,
            environment=environment,
            deployed_at=(base_time + timedelta(minutes=8)).isoformat(),
        )


def _write_vex_statements(session, rng: random.Random, vuln_id: str, purl: str) -> None:
    session.run("MERGE (v:VulnerabilityID {id: $id})", id=vuln_id)

    statement_count = rng.choice([1, 1, 2])
    for _ in range(statement_count):
        session.run(
            """
            MATCH (p:Package {purl: $purl})
            MATCH (v:VulnerabilityID {id: $vuln_id})
            CREATE (vex:VexStatement {status: $status, origin: $origin})
            CREATE (vex)-[:subject]->(p)
            CREATE (vex)-[:vulnerability]->(v)
            """,
            purl=purl,
            vuln_id=vuln_id,
            status=rng.choice(VEX_STATUSES),
            origin=rng.choice(VEX_ORIGINS),
        )
