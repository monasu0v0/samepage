"""Baseline injection behavior regression tests."""
from pathlib import Path

from samepage import assets, cli

FIXTURE = Path(__file__).parent / "fixtures" / "sample.html"


def _inject(tmp_path, *extra_args):
    dst = tmp_path / "sample.html"
    dst.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    rc = cli.main([str(dst), "--unit-selector", "body",
                   "--label-format", "Whole", *extra_args])
    assert rc == 0
    return dst


def test_inject_adds_marker_and_unit(tmp_path):
    dst = _inject(tmp_path)
    out = dst.read_text(encoding="utf-8")
    assert assets.MARKER_BEGIN in out and assets.MARKER_END in out
    assert "data-sp-unit=" in out
    assert "window.SAMEPAGE_CONFIG" in out


def test_inject_idempotent(tmp_path):
    dst = _inject(tmp_path)
    first = dst.read_text(encoding="utf-8")
    rc = cli.main([str(dst), "--unit-selector", "body", "--label-format", "Whole"])
    assert rc == 0
    second = dst.read_text(encoding="utf-8")
    assert second == first
    assert second.count(assets.MARKER_BEGIN) == 1
    assert second.count(assets.MARKER_END) == 1


def test_inject_idempotent_running_three_times(tmp_path):
    """Repeated re-injection never accumulates more than one marker block."""
    dst = _inject(tmp_path)
    for _ in range(2):
        rc = cli.main([str(dst), "--unit-selector", "body", "--label-format", "Whole"])
        assert rc == 0
    out = dst.read_text(encoding="utf-8")
    assert out.count("<!-- samepage:begin -->") == 1
    assert out.count("<!-- samepage:end -->") == 1


def test_no_source_path(tmp_path):
    dst = _inject(tmp_path, "--no-source-path")
    out = dst.read_text(encoding="utf-8")
    assert '"sourcePath": null' in out
    # Default: the injected-into file's absolute path is embedded.
    dst2 = _inject(tmp_path)
    assert '"sourcePath": null' not in dst2.read_text(encoding="utf-8")
    assert str(dst2.resolve()) in dst2.read_text(encoding="utf-8")


def test_unit_selector_matching_zero_elements_fails(tmp_path):
    dst = tmp_path / "sample.html"
    dst.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    rc = cli.main([str(dst), "--unit-selector", ".does-not-exist"])
    assert rc != 0


def test_missing_body_tag_aborts_and_leaves_input_unchanged(tmp_path):
    dst = tmp_path / "no-body.html"
    original = "<html><head></head><p>no body closing tag here</p></html>"
    dst.write_text(original, encoding="utf-8")
    rc = cli.main([str(dst)])
    assert rc != 0
    # Input must be byte-for-byte unchanged: injection failed before any write.
    assert dst.read_text(encoding="utf-8") == original


def test_missing_body_tag_with_out_leaves_both_files_unaffected(tmp_path):
    dst = tmp_path / "no-body.html"
    original = "<html><head></head><p>no body closing tag here</p></html>"
    dst.write_text(original, encoding="utf-8")
    out_path = tmp_path / "out.html"
    rc = cli.main([str(dst), "--out", str(out_path)])
    assert rc != 0
    assert dst.read_text(encoding="utf-8") == original
    assert not out_path.exists()


def test_out_writes_to_separate_file_leaving_input_unchanged(tmp_path):
    dst = tmp_path / "sample.html"
    dst.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    original = dst.read_text(encoding="utf-8")
    out_path = tmp_path / "out.html"
    rc = cli.main([str(dst), "--unit-selector", "body", "--out", str(out_path)])
    assert rc == 0
    assert dst.read_text(encoding="utf-8") == original
    assert assets.MARKER_BEGIN in out_path.read_text(encoding="utf-8")
