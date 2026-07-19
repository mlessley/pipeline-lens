# Graph Explorer Node Shapes — Design

## 1. Purpose

Graph Explorer's nodes are currently distinguished only by color
(`NODE_COLORS` in `src/scie/ui/graph_render.py`) and identifying label text —
all rendered as `streamlit_agraph`'s default `dot` shape. This adds a second,
independent visual signal (shape) so node type reads at a glance without
relying on color alone, and gives `VulnerabilityID` nodes a distinct shape
so CVEs visually stand out as the risk/alert type in the graph rather than
blending in as just another colored circle.

This was chosen over switching graph libraries (cytoscape.js/neovis.js) or
adding a tabular debug view — see the conversation preceding this spec for
the full options comparison. It's the cheapest of the three options and was
picked specifically because `streamlit_agraph`'s frontend was confirmed
(by inspecting the built JS bundle) to pass the `shape` field straight
through to vis-network with no validation, so this requires no library
changes and no new component.

## 2. Scope

**In scope:**
- A `SHAPE_BY_LABEL` dict in `src/scie/ui/graph_render.py`, structured like
  the existing `NODE_COLORS` dict: `"box"` (a rectangle sized to its label
  text) for every current node type (`Repository`, `Build`, `Commit`,
  `Artifact`, `Package`, `Deployment`), `"diamond"` for `VulnerabilityID`.
- Wiring `shape=SHAPE_BY_LABEL.get(label, "box")` into the `Node(...)`
  construction in `to_agraph_elements`, alongside the existing `color=`
  argument.
- A test asserting the shape on a constructed node, following the existing
  `test_to_agraph_elements_builds_nodes_with_empty_title_and_display_label`
  test's pattern in `tests/test_graph_render.py`.

**Out of scope:**
- Any change to `queries.py`, the Neo4j schema, the API, or the Neo4j data
  model — this is a pure rendering-layer change, same category as the
  existing attestation-to-edge-label collapsing in `graph_render.py`.
- Icons, images, or any shape requiring an asset (`image`/`circularImage`)
  — `box` and `diamond` are both native vis-network vector shapes with no
  asset dependency, keeping this change self-contained.
- Per-status styling (e.g. a different shape/border for a `Build` that
  failed vs. succeeded) — that's a separate, unrelated visual dimension not
  raised in this design.

## 3. Testing

Same bar as the rest of `graph_render.py`: pure-function unit tests with no
Streamlit runtime or live Neo4j required, following the existing
`tests/test_graph_render.py` pattern (`FakeDriver`-free, plain dict
fixtures via the file's existing `_node()` helper).

## 4. Verification

No automated test can confirm a shape actually *looks* like a rectangle vs.
a diamond in a real browser — same limitation noted in the Graph Explorer
UX redesign spec. Final verification is manual: rebuild the `dashboard`
container and look at it in the browser.
