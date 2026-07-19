# Graph Explorer Label Polish — Design

## 1. Purpose

Two rendering-layer inconsistencies surfaced while researching whether
Graph Explorer's edge names should align with GUAC's internal naming, SLSA/
in-toto provenance vocabulary, or something else entirely (see the
conversation preceding this spec for the full research trail — GUAC's Go
type names aren't a real industry standard developers recognize; the actual
recognizable vocabulary is scattered across three separate standards
depending on what part of the graph you're looking at: SLSA/in-toto for
build provenance, CycloneDX for SBOM dependencies, VEX for exploitability
status).

The conclusion of that research: chasing a "perfect standards-sourced verb"
for every edge isn't worth it. Most of this graph's edges connect two node
types that can only ever mean one thing (`Build` → `Artifact` has exactly
one possible relationship), so the edge label is redundant once the node
types are visible — labels only earn their keep when they resolve real
ambiguity (the same two node types could mean different things, or the data
is dynamic per-instance, like a VEX status). What's left to fix isn't
vocabulary — it's two concrete, unforced inconsistencies:

1. **Casing**: raw Neo4j relationship types are `SCREAMING_SNAKE_CASE`/
   lowercase (`HAS_BUILD`, `subject`); the hand-authored attestation-edge
   labels added in the earlier UX redesign are `PascalCase`/spaced
   (`"DependsOn"`, `"CertifyVuln (affected)"`). Two conventions, same graph,
   no documented reason.
2. **Node type visibility**: a node's type is currently conveyed only by
   color and shape (from the earlier redesign and the node-shapes work).
   Without memorizing the color/shape legend, there's no way to tell a
   `Package` node from a `Repository` node at a glance.

## 2. Scope

**In scope — both changes live entirely in `src/scie/ui/graph_render.py`,
no schema/query changes:**

- A `_humanize_edge_type` function converting the four raw backbone Cypher
  relationship types (`HAS_BUILD`, `FOR_COMMIT`, `PRODUCED`, `DEPLOYED_TO`
  — the only raw types that ever reach a rendered edge; `subject`/
  `dependency`/`vulnerability` only exist adjacent to attestation nodes,
  which `collapse_attestations` always removes before rendering) into
  Title Case with spaces (`"Has Build"`, `"For Commit"`, `"Produced"`,
  `"Deployed To"`). Already-human-readable labels produced by
  `collapse_attestations` (`"Depends On"`, the VEX-status label) pass
  through unchanged.
- `node_display_label` returning a two-line label (`"{type}\n{identifying
  value}"`) instead of just the identifying value, so every node shows its
  type regardless of whether the viewer has the color/shape mapping
  memorized. Falls back to just the type name if no identifying value is
  available, same as today.

**Out of scope:**
- Any rename of the raw Neo4j relationship types themselves (`HAS_BUILD`
  etc. stay exactly as they are in `queries.py`/`synthetic_graph.py`/
  `github_ingest.py`) — this is a display-only change.
- Adopting SLSA/in-toto/CycloneDX vocabulary as literal relationship type
  names, or adding a `Builder` node — explicitly decided against per the
  research conversation; may be worth revisiting once real metadata (real
  SBOM/SARIF ingestion) makes the graph's provenance story richer, but not
  now.
- Any change to `NODE_COLORS` or `SHAPE_BY_LABEL` — this adds a third,
  independent signal (a text label) on top of the two that already exist,
  it doesn't touch them.

## 3. Verification

Same bar as the rest of `graph_render.py`: pure-function unit tests, no
Streamlit runtime or live Neo4j required. Final visual confirmation
(does the two-line label actually render as two lines, sized correctly,
inside a `box`/`diamond`) is manual — same limitation noted in every prior
visual-change spec for this page.
