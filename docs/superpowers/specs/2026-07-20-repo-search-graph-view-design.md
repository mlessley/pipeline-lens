# Repository Search "Show as Graph" — Design

## 1. Purpose

Repository URL search always renders as a table (`build_history_rows`) with
no click/expand interaction — unlike Package PURL and Vulnerability ID
search, which land in a graph with clickable nodes, an "Expand" button, and
lens buttons. This makes Repository URL search a dead end for exploration:
there's currently no way to start at a repo and walk outward to its builds,
commits, artifacts, or (for the synthetic fleet) packages and
vulnerabilities.

## 2. Scope

**In scope:**
- A "Show as graph" button rendered under the table in the table-view
  branch of `src/scie/ui/pages/1_Graph_Explorer.py`. Clicking it sets
  `st.session_state.view_kind = "graph"` and reruns — no new query, no new
  API call. The `Repository`/`Build`/`Commit`/`Artifact` nodes and edges
  `repo_build_history` already returned are already sitting in
  `st.session_state.graph_nodes`/`graph_edges`; this only changes how
  they're rendered.
- Once switched to graph view, node click, the "Expand" button, and every
  existing lens button work unchanged — same code path as any other graph
  result, no special-casing needed.

**Out of scope:**
- Any change to `repo_build_history`, `queries.py`, or the Neo4j schema.
- Any change to what data exists — this doesn't add Package/dependency data
  for `pipeline-lens`/`dast-bench` (that's the separately-discussed, larger
  "real SBOM data" idea, not part of this change). Expanding those two
  repos' nodes will still only reveal `Build`→`Commit` chains, the same
  information the table already showed, just rendered as a graph.
- An always-visible Table/Graph toggle applied to every search mode —
  explicitly decided against in favor of a one-way "Show as graph" button,
  mirroring the existing "Build history" lens button (which already does
  the reverse: graph→table, via a real API re-fetch).
- A reverse "Show as table" button from graph view back to table — not
  requested; the existing "Build history" lens button already covers
  getting back to a table for a `Repository` node reached via Expand.

## 3. Testing

No automated test needed — this is a Streamlit page interaction with no
new pure-function logic (no changes to `graph_render.py` or
`build_history_view.py`). Same established convention as every other
change to `1_Graph_Explorer.py` in this project: no dedicated test
coverage for the page file itself, verified manually.

## 4. Verification

Manual: search a Repository URL, confirm the table renders with a "Show as
graph" button beneath it, click it, confirm the same repo's data now
renders as a graph with working node click/Expand.
