"""Responses JSON (--responses) embedding tests."""
import json
from pathlib import Path

from samepage import cli

FIXTURE = Path(__file__).parent / "fixtures" / "sample.html"


def _inject(tmp_path, *extra_args):
    dst = tmp_path / "sample.html"
    dst.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    rc = cli.main([str(dst), "--unit-selector", "body",
                   "--label-format", "Whole", *extra_args])
    assert rc == 0
    return dst


def _write_responses(tmp_path, reply_text="Fixed as suggested"):
    p = tmp_path / "responses.json"
    p.write_text(json.dumps({
        "doc": "sample", "respondedAt": "2026-08-06T00:00:00Z",
        "responses": [{"id": "c-abc12345", "reply": reply_text,
                       "action": "fixed", "fixedText": "alpha"}],
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_responses_ok(tmp_path):
    p = _write_responses(tmp_path)
    data = cli.load_responses(str(p))
    assert data["responses"][0]["id"] == "c-abc12345"
    assert data["responses"][0]["action"] == "fixed"


def test_load_responses_defaults_action_to_fixed(tmp_path):
    p = tmp_path / "responses.json"
    p.write_text(json.dumps({"responses": [{"id": "c1", "reply": "ok"}]}), encoding="utf-8")
    data = cli.load_responses(str(p))
    assert data["responses"][0]["action"] == "fixed"


def test_load_responses_rejects_invalid_action(tmp_path):
    p = tmp_path / "responses.json"
    p.write_text(json.dumps({"responses": [{"id": "c1", "reply": "ok", "action": "bogus"}]}),
                 encoding="utf-8")
    try:
        cli.load_responses(str(p))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_responses_injected(tmp_path):
    replies = _write_responses(tmp_path)
    dst = _inject(tmp_path, "--responses", str(replies))
    out = dst.read_text(encoding="utf-8")
    assert "window.SAMEPAGE_RESPONSES=" in out


def test_responses_layer_removed_on_reinject_without_responses(tmp_path):
    replies = _write_responses(tmp_path)
    dst = _inject(tmp_path, "--responses", str(replies))
    rc = cli.main([str(dst), "--unit-selector", "body", "--label-format", "Whole"])
    assert rc == 0
    assert "window.SAMEPAGE_RESPONSES=" not in dst.read_text(encoding="utf-8")


def test_responses_with_closing_script_tag_in_reply_is_escaped(tmp_path):
    replies = _write_responses(tmp_path, reply_text="breaks the script</script> tag")
    dst = _inject(tmp_path, "--responses", str(replies))
    out = dst.read_text(encoding="utf-8")
    assert "</script> tag" not in out
    assert "<\\/script> tag" in out
