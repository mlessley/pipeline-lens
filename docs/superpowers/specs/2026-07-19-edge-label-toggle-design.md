# Graph Explorer Edge Label Toggle — Design

## 1. Purpose

Dense or auto-laid-out sections of the graph can get crowded when every
edge draws a text label, especially now that edge labels use a real font
(monospace, sized) rather than vis-network's thin default. A sidebar
toggle lets a viewer clear all edge labels at once for a cleaner view,
without fighting vis-network's layout algorithm to make room for text.

This spec also documents a related idea that was investigated and
explicitly dropped: node-type icons via vis-network's `shape="icon"`.
`streamlit_agraph`'s frontend bundle (confirmed by inspecting its built
`index.html` and JS chunks) loads no icon font (no FontAwesome/Ionicons,
bundled or via CDN link) and runs in its own sandboxed iframe, so an icon's
Unicode codepoint has no font to render against and there's no Python-level
way to inject one. That's a real limitation of the library, not something
to work around with a hack — making icons work would mean forking and
rebuilding `streamlit_agraph`'s frontend, out of scope here.

## 2. Scope

**In scope:**
- A `st.sidebar.checkbox("Show edge labels", value=True)` in
  `src/scie/ui/pages/1_Graph_Explorer.py`.
- `graph_render.to_agraph_elements` gains a `show_edge_labels: bool = True`
  parameter. When `False`, every edge's `Edge(...)` label is `""` instead
  of `_humanize_edge_type(edge["type"])`. Default `True` preserves current
  behavior and requires no changes to existing tests that don't pass the
  new parameter.
- The page passes the checkbox's current value into every
  `to_agraph_elements` call in the graph-view branch.

**Out of scope:**
- Node-type icons (see Purpose) — explicitly dropped, not deferred to a
  follow-up in this spec; would need its own scoping conversation.
- Per-edge-type toggles (e.g. hide only `Depends On` edges) — the ask was
  a single global on/off, not fine-grained filtering.
- Persisting the toggle's state across searches/page reloads beyond what
  Streamlit's own widget state already provides — no new session-state
  key needed beyond the checkbox's own.

## 3. Testing

Same bar as the rest of `graph_render.py`: a pure-function unit test
asserting `to_agraph_elements(nodes, edges, show_edge_labels=False)`
produces edges with `label == ""`, alongside the existing default-`True`
tests (unchanged). No Streamlit runtime or live Neo4j required.

## 4. Verification

Manual — same limitation as every other visual change to this page: no
automated test can confirm the sidebar checkbox actually clears labels on
screen. Rebuild the `dashboard` container and look at it.
