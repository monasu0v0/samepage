"""Tests for docs/build_alignment_html.py.

The builder needs the third-party `markdown` package, which the unit CI job
deliberately does not install (decision D-12: the dependency stays undeclared
and the dedicated `docs` job is what exercises it). Skip the whole module when
it is missing, the same way tests/test_browser.py skips without Playwright.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "docs"))

try:
    # The builder calls sys.exit(1) when `markdown` is missing, so importing it
    # raises SystemExit rather than ImportError. Catch both.
    import build_alignment_html as bah
    HAVE_MARKDOWN = True
except (ImportError, SystemExit):
    HAVE_MARKDOWN = False

pytestmark = pytest.mark.skipif(
    not HAVE_MARKDOWN, reason="the 'markdown' package is not installed")


def _tree(*lines):
    return list(lines)


# --------------------------------------------------------------------------
# design tree notation (decision D-13)
# --------------------------------------------------------------------------

def test_parses_a_flat_tree():
    nodes, edges = bah.parse_design_tree(_tree(
        "- [D-1] first :: 確定 :: chose A",
        "- [D-2] second :: frontier",
    ))
    assert [n["id"] for n in nodes] == ["D-1", "D-2"]
    assert nodes[0]["decision"] == "chose A"
    assert nodes[0]["parent"] is None and nodes[1]["parent"] is None
    assert edges == []


def test_indentation_is_the_parent_relation():
    nodes, _ = bah.parse_design_tree(_tree(
        "- [D-1] root :: 確定 :: x",
        "  - [D-2] child :: 確定 :: y",
        "    - [D-3] grandchild :: frontier",
        "  - [D-4] second child :: 保留",
        "- [D-5] other root :: frontier",
    ))
    by_id = {n["id"]: n for n in nodes}
    assert by_id["D-2"]["parent"] == "D-1"
    assert by_id["D-3"]["parent"] == "D-2"
    assert by_id["D-4"]["parent"] == "D-1"
    assert by_id["D-5"]["parent"] is None
    assert [by_id[k]["depth"] for k in ("D-1", "D-2", "D-3", "D-4", "D-5")] == [0, 1, 2, 1, 0]


def test_dependency_row_is_an_edge_not_a_node():
    nodes, edges = bah.parse_design_tree(_tree(
        "- [D-1] root :: 確定 :: x",
        "  - [D-2] child :: frontier",
        "    - (依存) [D-1]",
    ))
    assert [n["id"] for n in nodes] == ["D-1", "D-2"]
    assert edges == [("D-2", "D-1")]


@pytest.mark.parametrize("lines, message", [
    (["- [D-1] t :: nonsense"], "state must be one of"),
    (["- [D-1] t :: 確定"], "must carry a decision"),
    (["- [D-1] t :: frontier :: oops"], "only a 確定 row"),
    (["- [D-1] a :: 確定 :: x", "- [D-1] b :: 確定 :: y"], "duplicate id"),
    (["- [D-1] a :: 確定 :: x", "   - [D-2] b :: 確定 :: y"], "multiple of two spaces"),
    (["  - [D-1] a :: 確定 :: x"], "no parent"),
    (["- [D-1] a :: 確定 :: x", "  - (依存) [D-9]"], "unknown id"),
    (["- [D-1] just a title"], "expected 'title :: state'"),
    (["a stray line"], "not a design-tree row"),
])
def test_rejects_notation_violations(lines, message):
    with pytest.raises(bah.TreeError) as excinfo:
        bah.parse_design_tree(lines)
    assert message in str(excinfo.value)


def test_a_retired_id_is_never_reused():
    """D-13 rule 2: ids are unique for the life of the document, so a
    withdrawn decision keeps its number and the history stays followable."""
    with pytest.raises(bah.TreeError, match="ids are never reused"):
        bah.parse_design_tree(_tree(
            "- [D-1] withdrawn :: 再検討",
            "- [D-1] re-decided :: 確定 :: y",
        ))


# --------------------------------------------------------------------------
# layout and SVG
# --------------------------------------------------------------------------

def test_layout_puts_each_depth_on_its_own_row():
    nodes, _ = bah.parse_design_tree(_tree(
        "- [D-1] a :: frontier",
        "  - [D-2] b :: frontier",
        "- [D-3] c :: frontier",
    ))
    bah.layout(nodes)
    by_id = {n["id"]: n for n in nodes}
    assert by_id["D-1"]["y"] == by_id["D-3"]["y"]
    assert by_id["D-2"]["y"] > by_id["D-1"]["y"]
    assert by_id["D-1"]["x"] != by_id["D-3"]["x"]


def test_svg_tags_nodes_and_links_them_to_their_section():
    nodes, edges = bah.parse_design_tree(_tree(
        "- [D-1] a :: 確定 :: x",
        "  - [D-2] b :: frontier",
    ))
    svg = bah.render_svg(nodes, edges, "0001")
    assert 'data-sp-node="D-1"' in svg and 'data-sp-node="D-2"' in svg
    assert 'href="#d1"' in svg and 'href="#d2"' in svg
    assert 'data-sp-label="D-1 a（確定: x）"' in svg


def test_marker_ids_are_namespaced_per_document():
    """Two diagrams on one page must not collide on marker ids."""
    nodes, edges = bah.parse_design_tree(_tree("- [D-1] a :: frontier"))
    assert "sp-ar-0001-ok" in bah.render_svg(nodes, edges, "0001")
    assert "sp-ar-0007-ok" in bah.render_svg(nodes, edges, "0007")


def test_a_decision_written_as_a_section_gets_the_same_anchor():
    """A decision can be a ledger row or its own section; the design tree links
    to one anchor either way, so the heading id must override the toc slug."""
    html = bah.add_heading_anchors(
        '<h3 id="w-1-title">W-1. title</h3><h2 id="s">1. context</h2>')
    assert '<h3 id="w1">W-1. title</h3>' in html
    assert '<h2 id="s">1. context</h2>' in html          # untouched


def test_anchor_matches_the_ledger_row_id():
    assert bah.anchor_for("D-13") == "d13"
    html = bah.add_row_anchors("<tr>\n<td>D-13</td><td>x</td></tr>")
    assert '<tr id="d13">' in html


# --------------------------------------------------------------------------
# the 残件 block (decision D-15)
# --------------------------------------------------------------------------

def _export(tmp_path, answers, comments):
    p = tmp_path / "export.json"
    p.write_text(json.dumps({
        "generatedAt": "2026-08-30T00:00:00Z",
        "answers": [{"questionId": a} for a in answers],
        "comments": comments}), encoding="utf-8")
    return p


def test_remaining_block_reports_zero_when_everything_is_settled(tmp_path):
    nodes, _ = bah.parse_design_tree(_tree("- [D-1] a :: 確定 :: x"))
    export = _export(tmp_path, ["q1"], [{"id": "c1", "status": "resolved"}])
    block = bah.build_remaining(str(export), nodes)
    assert "残件はゼロです" in block
    assert "data-sp-discussion" in block


def test_remaining_block_counts_open_comments_and_unsettled_nodes(tmp_path):
    nodes, _ = bah.parse_design_tree(_tree(
        "- [D-1] a :: 確定 :: x",
        "- [D-2] b :: frontier",
        "- [D-3] c :: 再検討",
        "- [D-4] d :: 保留",
    ))
    export = _export(tmp_path, ["q1"], [
        {"id": "c-open", "status": "open"}, {"id": "c-done", "status": "resolved"}])
    block = bah.build_remaining(str(export), nodes)
    assert "残件が 3 件あります" in block      # 1 open comment + D-2 + D-3
    assert "c-open" in block
    assert "--finalize</code> しないでください" in block


def test_a_held_node_is_not_counted_as_outstanding(tmp_path):
    """保留 is an explicit decision to defer, not an unanswered question."""
    nodes, _ = bah.parse_design_tree(_tree(
        "- [D-1] a :: 確定 :: x", "- [D-2] b :: 保留"))
    export = _export(tmp_path, ["q1"], [])
    assert "残件はゼロです" in bah.build_remaining(str(export), nodes)


# --------------------------------------------------------------------------
# end-to-end
# --------------------------------------------------------------------------

ALIGNMENT_MD = """---
id: 0042
title: sample
status: 合意済み
agreed-at: 2026-01-01
---

# Sample alignment

One line of lede.

## design tree

- [D-1] first :: 確定 :: chose A
  - [D-2] second :: frontier

## 決定

| 決定 | 結論 | 根拠 |
|---|---|---|
| D-1 | chose A | because |
| D-2 | — | pending |

## 用語

- **frontier** — decisions whose prerequisites are settled.
"""


def test_build_produces_a_page_with_the_tree_inlined(tmp_path):
    md = tmp_path / "0042-sample.md"
    md.write_text(ALIGNMENT_MD, encoding="utf-8")
    out = tmp_path / "0042-sample.html"
    nodes = bah.build(str(md), str(out))
    html = out.read_text(encoding="utf-8")
    assert len(nodes) == 2
    assert "@@TREE@@" not in html
    assert '<svg class="sp-tree-svg"' in html
    assert '<tr id="d1">' in html and '<tr id="d2">' in html
    assert "<h1>Sample alignment</h1>" in html
    assert "One line of lede." in html
    assert '<div class="table-wrap">' in html
    assert "決定 2 件" in html


def test_build_is_deterministic(tmp_path):
    md = tmp_path / "0042-sample.md"
    md.write_text(ALIGNMENT_MD, encoding="utf-8")
    first, second = tmp_path / "a.html", tmp_path / "b.html"
    bah.build(str(md), str(first))
    bah.build(str(md), str(second))
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_index_lists_documents_decisions_and_glossary(tmp_path):
    (tmp_path / "0042-sample.md").write_text(ALIGNMENT_MD, encoding="utf-8")
    docs = bah.build_index(str(tmp_path))
    index = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
    assert len(docs) == 1
    assert "Do not edit by hand" in index
    assert "0042-sample.md" in index
    assert "| D-1 | first | 確定 | chose A |" in index
    assert "1/2 確定" in index
    assert "frontier" in index and "prerequisites are settled" in index


def test_index_skips_itself_on_a_rebuild(tmp_path):
    (tmp_path / "0042-sample.md").write_text(ALIGNMENT_MD, encoding="utf-8")
    bah.build_index(str(tmp_path))
    assert len(bah.build_index(str(tmp_path))) == 1


def test_main_reports_a_notation_error_without_traceback(tmp_path, capsys):
    md = tmp_path / "0001-bad.md"
    md.write_text("# t\n\nlede\n\n## design tree\n\n- [D-1] t :: bogus\n", encoding="utf-8")
    assert bah.main([str(md), "--out", str(tmp_path / "o.html")]) == 1
    assert "state must be one of" in capsys.readouterr().err
