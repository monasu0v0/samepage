"""Question pin (--questions) tests."""
import json
from pathlib import Path

import pytest

from samepage import cli

FIXTURE = Path(__file__).parent / "fixtures" / "sample.html"


def _q(**over):
    q = {"id": "q-abc12345", "question": "Is this figure's data still current?",
         "target": {"kind": "element", "path": "body > section:nth-of-type(2) > figure:nth-of-type(1)",
                    "tag": "figure", "nearText": "Figure 1: bar chart for verification"},
         "choices": ["yes", "no"], "unit": "u1"}
    q.update(over)
    return q


def _write_questions(tmp_path, questions):
    p = tmp_path / "questions.json"
    p.write_text(json.dumps({"doc": "sample", "askedAt": "2026-08-06T00:00:00Z",
                             "questions": questions}, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_questions_ok(tmp_path):
    p = _write_questions(tmp_path, [_q()])
    data = cli.load_questions(str(p))
    assert data["questions"][0]["id"] == "q-abc12345"


@pytest.mark.parametrize("bad", [
    {"id": ""},
    {"question": None},
    {"target": {"kind": "unknown"}},
    {"choices": ["yes", 1]},
    {"target": {"kind": "diagram-node"}},
    {"target": {"kind": "diagram-node", "nodeId": " "}},
])
def test_load_questions_rejects(tmp_path, bad):
    p = _write_questions(tmp_path, [_q(**bad)])
    with pytest.raises(ValueError):
        cli.load_questions(str(p))


def test_load_questions_diagram_node_ok(tmp_path):
    q = _q(target={"kind": "diagram-node", "nodeId": "spec-07",
                   "nodeLabel": "audit log is append-only"})
    p = _write_questions(tmp_path, [q])
    data = cli.load_questions(str(p))
    assert data["questions"][0]["target"]["nodeId"] == "spec-07"


def test_questions_injected_and_idempotent(tmp_path):
    dst = tmp_path / "sample.html"
    dst.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    qp = _write_questions(tmp_path, [_q(question="breaks the script</script> tag")])
    rc = cli.main([str(dst), "--unit-selector", "body",
                   "--label-format", "Whole", "--questions", str(qp)])
    assert rc == 0
    out = dst.read_text(encoding="utf-8")
    assert "window.SAMEPAGE_QUESTIONS=" in out
    assert "</script> tag" not in out
    assert "<\\/script> tag" in out
    # Re-injecting without --questions drops the question layer.
    rc = cli.main([str(dst), "--unit-selector", "body", "--label-format", "Whole"])
    assert rc == 0
    assert "window.SAMEPAGE_QUESTIONS=" not in dst.read_text(encoding="utf-8")


def test_responses_and_questions_injected_together(tmp_path):
    dst = tmp_path / "sample.html"
    dst.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    rp = tmp_path / "responses.json"
    rp.write_text(json.dumps({
        "doc": "sample", "respondedAt": "2026-08-06T00:00:00Z",
        "responses": [{"id": "c-abc12345", "reply": "Fixed as suggested",
                       "action": "fixed", "fixedText": "alpha"}],
    }, ensure_ascii=False), encoding="utf-8")
    qp = _write_questions(tmp_path, [_q()])
    rc = cli.main([str(dst), "--unit-selector", "body", "--label-format", "Whole",
                   "--responses", str(rp), "--questions", str(qp)])
    assert rc == 0
    out = dst.read_text(encoding="utf-8")
    assert "window.SAMEPAGE_RESPONSES=" in out
    assert "window.SAMEPAGE_QUESTIONS=" in out
