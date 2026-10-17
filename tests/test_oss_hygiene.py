"""OSS publication hygiene and privacy regression tests."""
import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _tracked_files() -> list[Path]:
    out = subprocess.check_output(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        text=True,
    )
    return [REPO_ROOT / line for line in out.splitlines() if line.strip()]


def test_no_personal_environment_paths_in_tracked_files():
    """Verify no local user home directory paths are leaked in any tracked file."""
    # Construct patterns dynamically so this file itself never contains literal matches.
    forbidden_patterns = [
        ("/" + "home/").encode("utf-8"),
        ("/" + "Users/").encode("utf-8"),
        ("C:\\" + "Users\\").encode("utf-8"),
        ("c:\\" + "Users\\").encode("utf-8"),
        ("file:///" + "home/").encode("utf-8"),
        ("file:///" + "Users/").encode("utf-8"),
    ]
    tracked = _tracked_files()
    assert len(tracked) > 0, "Expected git ls-files to return tracked repository files"

    leaks: list[str] = []
    for path in tracked:
        if not path.is_file():
            continue
        raw = path.read_bytes()
        for pat in forbidden_patterns:
            if pat in raw:
                rel = path.relative_to(REPO_ROOT)
                leaks.append(f"{rel}: matched forbidden path pattern {pat.decode('utf-8')}")

    assert not leaks, "Personal environment path leak(s) detected:\n" + "\n".join(leaks)


def test_readme_html_artifacts_have_null_source_path():
    """Verify README.html and README.ja.html embed sourcePath: null (--no-source-path)."""
    config_re = re.compile(r"window\.SAMEPAGE_CONFIG\s*=\s*(\{.*?\});")
    for filename in ("README.html", "README.ja.html"):
        html_path = REPO_ROOT / filename
        assert html_path.is_file(), f"Missing generated artifact: {filename}"
        content = html_path.read_text(encoding="utf-8")
        assert '"sourcePath": null' in content, (
            f"{filename} must be generated with --no-source-path so sourcePath is null"
        )
        match = config_re.search(content)
        assert match is not None, f"Could not find window.SAMEPAGE_CONFIG in {filename}"
        cfg = json.loads(match.group(1))
        assert cfg.get("sourcePath") is None, (
            f"Expected sourcePath to be None in {filename}, got {cfg.get('sourcePath')!r}"
        )


def test_license_and_pyproject_attribution():
    """Verify LICENSE and pyproject.toml carry the canonical monasu0v0 attribution."""
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "monasu0v0" in license_text

    pyproject_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "monasu0v0" in pyproject_text
    assert "monasu0v0@gmail.com" in pyproject_text
    assert "https://github.com/monasu0v0/samepage" in pyproject_text

