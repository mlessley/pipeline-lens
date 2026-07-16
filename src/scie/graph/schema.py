CONSTRAINTS = [
    "CREATE CONSTRAINT repository_url IF NOT EXISTS FOR (r:Repository) REQUIRE r.url IS UNIQUE",
    "CREATE CONSTRAINT build_id IF NOT EXISTS FOR (b:Build) REQUIRE b.id IS UNIQUE",
    "CREATE CONSTRAINT commit_sha IF NOT EXISTS FOR (c:Commit) REQUIRE c.sha IS UNIQUE",
    "CREATE CONSTRAINT artifact_digest IF NOT EXISTS FOR (a:Artifact) REQUIRE a.digest IS UNIQUE",
    "CREATE CONSTRAINT package_purl IF NOT EXISTS FOR (p:Package) REQUIRE p.purl IS UNIQUE",
    "CREATE CONSTRAINT vulnerability_id IF NOT EXISTS FOR (v:VulnerabilityID) REQUIRE v.id IS UNIQUE",
    "CREATE INDEX build_start_time IF NOT EXISTS FOR (b:Build) ON (b.startTime)",
]


def apply_constraints(driver) -> None:
    with driver.session() as session:
        for statement in CONSTRAINTS:
            session.run(statement)
