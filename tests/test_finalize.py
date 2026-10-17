"""--finalize (publishable clean HTML output) tests."""
import json
import os
import stat
from pathlib import Path

import pytest

from samepage import cli

FIXTURE = Path(__file__).parent / "fixtures" / "sample.html"


def _injected(tmp_path):
    dst = tmp_path / "sample.html"
    dst.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main([str(dst), "--unit-selector", "body", "--label-format", "Whole"]) == 0
    return dst


def _comments_json(tmp_path, statuses):
    p = tmp_path / "comments.json"
    p.write_text(json.dumps({
        "doc": "sample", "generatedAt": "2026-08-06T00:00:00Z",
        "comments": [{"id": f"c-{i:08d}", "status": s} for i, s in enumerate(statuses)],
    }), encoding="utf-8")
    return p


def test_finalize_removes_everything(tmp_path):
    dst = _injected(tmp_path)
    rc = cli.main([str(dst), "--finalize"])
    assert rc == 0
    final = tmp_path / "sample.final.html"
    assert final.is_file()
    out = final.read_text(encoding="utf-8")
    assert "samepage" not in out          # marker, embedded CSS/JS/config all gone
    assert "data-sp-" not in out          # unit attrs and discussion attrs gone
    assert "Discussion notes" not in out  # discussion block removed with its contents
    assert "Nested discussion span" not in out
    assert "keystone-alpha" in out and "keystone-gamma" in out  # body text kept
    assert "Figure 1: bar chart for verification" in out
    # Input (with the review layer) is left untouched.
    assert "samepage:begin" in dst.read_text(encoding="utf-8")


def test_finalize_output_contains_none_of_the_forbidden_substrings(tmp_path):
    dst = _injected(tmp_path)
    rc = cli.main([str(dst), "--finalize"])
    assert rc == 0
    out = (tmp_path / "sample.final.html").read_text(encoding="utf-8")
    for forbidden in ("data-sp-", "samepage:", "sp-mark"):
        assert forbidden not in out


def test_finalize_blocks_on_open_comments(tmp_path):
    dst = _injected(tmp_path)
    cj = _comments_json(tmp_path, ["open", "resolved"])
    rc = cli.main([str(dst), "--finalize", "--comments", str(cj)])
    assert rc == 2
    assert not (tmp_path / "sample.final.html").exists()


def test_finalize_force_overrides(tmp_path):
    dst = _injected(tmp_path)
    cj = _comments_json(tmp_path, ["open"])
    rc = cli.main([str(dst), "--finalize", "--comments", str(cj), "--force"])
    assert rc == 0
    assert (tmp_path / "sample.final.html").is_file()


def test_finalize_resolved_comments_pass(tmp_path):
    dst = _injected(tmp_path)
    cj = _comments_json(tmp_path, ["resolved", "resolved"])
    rc = cli.main([str(dst), "--finalize", "--comments", str(cj)])
    assert rc == 0


@pytest.mark.parametrize("extra", [
    ["--unit-selector", "body"],
    ["--responses", "dummy.json"],
    ["--questions", "dummy.json"],
])
def test_finalize_rejects_other_flags(tmp_path, extra):
    dst = _injected(tmp_path)
    rc = cli.main([str(dst), "--finalize", *extra])
    assert rc == 2


def test_finalize_plain_html_passthrough(tmp_path):
    """HTML with neither an injected layer nor discussion blocks passes through unchanged."""
    dst = tmp_path / "plain.html"
    dst.write_text("<html><body><p>body text</p></body></html>", encoding="utf-8")
    rc = cli.main([str(dst), "--finalize"])
    assert rc == 0
    assert (tmp_path / "plain.final.html").read_text(encoding="utf-8") == \
        "<html><body><p>body text</p></body></html>"


def test_finalize_comments_file_missing(tmp_path, capsys):
    dst = _injected(tmp_path)
    rc = cli.main([str(dst), "--finalize", "--comments", str(tmp_path / "no-such.json")])
    assert rc == 2
    assert not (tmp_path / "sample.final.html").exists()
    assert "Error" in capsys.readouterr().err


def test_finalize_comments_broken_json(tmp_path, capsys):
    dst = _injected(tmp_path)
    cj = tmp_path / "broken.json"
    cj.write_text("{not valid json", encoding="utf-8")
    rc = cli.main([str(dst), "--finalize", "--comments", str(cj)])
    assert rc == 2
    assert not (tmp_path / "sample.final.html").exists()
    assert "Error" in capsys.readouterr().err


@pytest.mark.parametrize("bad_json", [
    "[]",
    json.dumps({"comments": "x"}),
])
def test_collect_open_comments_rejects_bad_structure(tmp_path, bad_json):
    cj = tmp_path / "bad.json"
    cj.write_text(bad_json, encoding="utf-8")
    with pytest.raises(ValueError):
        cli.collect_open_comments(str(cj))


# --- data-sp-* stripping must be scoped to tag attributes, never body text ---

def test_finalize_preserves_body_text_matching_attr_pattern():
    html = ('<html><body><p>the literal text data-sp-unit="x" appears here in prose</p>'
            '<div data-sp-unit="u1" data-sp-label="Whole">content</div></body></html>')
    out = cli.finalize_html(html)
    assert 'data-sp-unit="x" appears here in prose' in out
    assert 'data-sp-unit="u1"' not in out
    assert "data-sp-label=" not in out


def test_finalize_removes_discussion_void_tag_with_gt_in_attr():
    html = ('<html><body><p>before</p>'
            '<img data-sp-discussion alt="a > b" src="x.png">'
            '<p>after</p></body></html>')
    out = cli.finalize_html(html)
    assert "data-sp-discussion" not in out
    assert "x.png" not in out
    assert "alt=" not in out
    assert "<p>before</p>" in out
    assert "<p>after</p>" in out


# --- runtime decorations that a browser "Save As" of the live DOM would bake in ---

_SAVED_DOM_HTML = (
    '<html><body>'
    '<p>Before <mark class="sp-mark" data-sp-cmt-id="c-000001">selected text</mark> after.</p>'
    '<p><mark class="sp-mark-fixed" data-sp-resp-id="r-000001">fixed text</mark></p>'
    '<p>question<span class="sp-qpin" data-sp-q-id="q-000001">?</span>pin</p>'
    '<div class="sp-insert-mark" data-sp-cmt-id="c-000002"></div>'
    '<div class="sp-mark-el foo" data-sp-cmt-id="c-000003">kept content</div>'
    '<svg viewBox="0 0 100 50">'
    '<g data-sp-node="spec-07" data-sp-label="Node A"><rect x="0" y="0" width="40" height="20"></rect>'
    '<rect class="sp-node-halo" data-sp-cmt-id="c-000004" x="-4" y="-4" width="48" height="28"></rect>'
    '<text class="sp-qpin-svg" data-sp-q-id="q-000002" x="30" y="4">?</text></g>'
    '</svg>'
    '</body></html>'
)


def test_finalize_unwraps_mark_elements_keeping_text():
    out = cli.finalize_html(_SAVED_DOM_HTML)
    assert "<mark" not in out
    assert "</mark>" not in out
    assert "selected text" in out
    assert "fixed text" in out


def test_finalize_removes_qpin_and_insert_mark_with_content():
    out = cli.finalize_html(_SAVED_DOM_HTML)
    assert "sp-qpin" not in out
    assert "sp-insert-mark" not in out
    assert "question" in out and "pin" in out
    assert "question?pin" not in out


def test_finalize_removes_svg_runtime_decorations_keeping_node():
    out = cli.finalize_html(_SAVED_DOM_HTML)
    assert "sp-node-halo" not in out
    assert "sp-qpin-svg" not in out
    assert '<rect x="0" y="0" width="40" height="20">' in out
    assert "data-sp-node" not in out
    assert "data-sp-label" not in out


def test_finalize_strips_runtime_decoration_attrs_and_class_token():
    out = cli.finalize_html(_SAVED_DOM_HTML)
    assert "data-sp-q-id" not in out
    assert "data-sp-cmt-id" not in out
    assert "data-sp-resp-id" not in out
    assert "sp-mark-el" not in out
    assert "kept content" in out
    assert 'class="foo"' in out


def test_finalize_strips_badge_and_action_attrs():
    html = ('<html><body>'
            '<button data-sp-badge="3">badge</button>'
            '<button data-sp-action="move">move</button>'
            '</body></html>')
    out = cli.finalize_html(html)
    assert "data-sp-badge" not in out
    assert "data-sp-action" not in out
    assert "badge" in out and "move" in out


def test_finalize_plain_injected_html_unchanged_by_runtime_mark_stripping(tmp_path):
    dst = _injected(tmp_path)
    rc = cli.main([str(dst), "--finalize"])
    assert rc == 0
    out = (tmp_path / "sample.final.html").read_text(encoding="utf-8")
    assert "samepage" not in out
    assert "data-sp-" not in out
    assert "keystone-alpha" in out and "keystone-gamma" in out
    assert "Figure 1: bar chart for verification" in out


def test_finalize_out_writes_to_custom_path(tmp_path):
    dst = _injected(tmp_path)
    custom = tmp_path / "custom" / "published.html"
    custom.parent.mkdir(parents=True, exist_ok=True)
    rc = cli.main([str(dst), "--finalize", "--out", str(custom)])
    assert rc == 0
    assert custom.is_file()
    assert not (tmp_path / "sample.final.html").exists()
    out = custom.read_text(encoding="utf-8")
    assert "samepage" not in out


def _umask_mode():
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def test_finalize_output_is_readable_by_others(tmp_path):
    """--finalize writes the copy meant to be distributed (SKILL.md section 8,
    rule 5), so a brand-new output file must follow the umask instead of
    staying at the 0600 mkstemp gives it."""
    dst = _injected(tmp_path)
    out = tmp_path / "sample.final.html"
    assert not out.exists()
    assert cli.main([str(dst), "--finalize"]) == 0
    assert stat.S_IMODE(out.stat().st_mode) == _umask_mode()


def test_finalize_preserves_the_mode_of_an_existing_output(tmp_path):
    dst = _injected(tmp_path)
    out = tmp_path / "custom.final.html"
    out.write_text("placeholder", encoding="utf-8")
    os.chmod(str(out), 0o640)
    assert cli.main([str(dst), "--finalize", "--out", str(out)]) == 0
    assert stat.S_IMODE(out.stat().st_mode) == 0o640
