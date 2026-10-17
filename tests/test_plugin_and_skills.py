"""Multi-agent plugin and skill contract verification tests (ADR-0005)."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. Dual Manifests (plugin.json & .claude-plugin/plugin.json)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rel_path",
    [
        "plugin.json",
        ".claude-plugin/plugin.json",
    ],
)
def test_plugin_manifests_valid_and_metadata_matches(rel_path: str):
    manifest_path = REPO_ROOT / rel_path
    assert manifest_path.is_file(), f"Missing manifest: {rel_path}"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["name"] == "samepage"
    assert isinstance(data.get("version"), str) and data["version"]
    assert isinstance(data.get("description"), str) and data["description"]
    assert data["author"] == {
        "name": "monasu0v0",
        "email": "monasu0v0@gmail.com",
    }
    assert data["repository"] == "https://github.com/monasu0v0/samepage"
    assert data["homepage"] == "https://github.com/monasu0v0/samepage"
    assert data["license"] == "MIT"


# ---------------------------------------------------------------------------
# 2. Agent Rule Files (AGENTS.md, rules/AGENTS.md, CLAUDE.md)
# ---------------------------------------------------------------------------

def test_agent_rule_files_exist():
    for rel_path in ("AGENTS.md", "rules/AGENTS.md", "CLAUDE.md"):
        p = REPO_ROOT / rel_path
        assert p.is_file(), f"Missing agent rule file: {rel_path}"
        assert p.read_text(encoding="utf-8").strip(), f"Empty rule file: {rel_path}"


@pytest.mark.parametrize("rel_path", ["AGENTS.md", "CLAUDE.md"])
def test_root_agent_docs_reference_ssot_and_adr(rel_path: str):
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert "docs/specification.md" in text
    assert "docs/adr/" in text


def test_plugin_rules_agents_md_enforces_relative_script_and_no_source_path():
    text = (REPO_ROOT / "rules/AGENTS.md").read_text(encoding="utf-8")
    assert "samepage/cli.py" in text
    assert "docs/build_alignment_html.py" in text
    assert "--no-source-path" in text


# ---------------------------------------------------------------------------
# 3. Skills (skills/samepage/SKILL.md & skills/grill-on-samepage/SKILL.md)
# ---------------------------------------------------------------------------

def _parse_frontmatter(md_text: str) -> dict[str, str]:
    """Minimal zero-dependency YAML frontmatter parser for SKILL.md."""
    assert md_text.startswith("---\n"), "SKILL.md must begin with YAML frontmatter delimiter '---'"
    end_idx = md_text.find("\n---\n", 4)
    assert end_idx != -1, "SKILL.md must have closing YAML frontmatter delimiter '---'"
    raw_fm = md_text[4:end_idx]

    result: dict[str, str] = {}
    current_key: str | None = None
    multiline_lines: list[str] = []

    for line in raw_fm.splitlines():
        if current_key is not None:
            if line.startswith("  ") or line == "":
                multiline_lines.append(line[2:] if line.startswith("  ") else "")
                continue
            else:
                result[current_key] = "\n".join(multiline_lines).strip()
                current_key = None
                multiline_lines = []

        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val in ("|", ">"):
                current_key = key
                multiline_lines = []
            else:
                result[key] = val

    if current_key is not None:
        result[current_key] = "\n".join(multiline_lines).strip()

    return result


@pytest.mark.parametrize(
    "skill_name,expected_scripts",
    [
        ("samepage", ["../../samepage/cli.py"]),
        ("grill-on-samepage", ["../../samepage/cli.py", "../../docs/build_alignment_html.py"]),
    ],
)
def test_skill_frontmatter_and_relative_script_resolution(
    skill_name: str, expected_scripts: list[str]
):
    skill_dir = REPO_ROOT / "skills" / skill_name
    skill_md = skill_dir / "SKILL.md"
    assert skill_md.is_file(), f"Missing SKILL.md for {skill_name}"

    text = skill_md.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    assert fm.get("name") == skill_name
    assert fm.get("description"), f"Empty description in {skill_md}"

    for rel_script in expected_scripts:
        resolved = (skill_dir / rel_script).resolve()
        assert resolved.is_file(), f"Relative script {rel_script} from {skill_dir} did not resolve"
        # Confirm it is an executable Python script via `python3 <script> --help`
        proc = subprocess.run(
            [sys.executable, str(resolved), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, (
            f"Script {resolved} failed `--help` with exit code {proc.returncode}: {proc.stderr}"
        )


def test_skills_document_universal_relative_path_and_claude_plugin_root():
    samepage_md = (REPO_ROOT / "skills/samepage/SKILL.md").read_text(encoding="utf-8")
    grill_md = (REPO_ROOT / "skills/grill-on-samepage/SKILL.md").read_text(encoding="utf-8")

    assert "../../samepage/cli.py" in samepage_md
    assert "${CLAUDE_PLUGIN_ROOT}" in samepage_md
    assert "<SAMEPAGE_ROOT>/samepage/cli.py" in samepage_md

    assert "<SAMEPAGE_ROOT>/docs/build_alignment_html.py" in grill_md
    assert "<SAMEPAGE_ROOT>/samepage/cli.py" in grill_md
    assert "${CLAUDE_PLUGIN_ROOT}" in grill_md


# ---------------------------------------------------------------------------
# 4. HANDOFF_RULES in samepage.js vs. skills/samepage/SKILL.md §4
# ---------------------------------------------------------------------------

def _extract_js_handoff_rules(js_text: str) -> list[str]:
    """Extract the string array assigned to `var HANDOFF_RULES = [...]` in samepage.js."""
    m = re.search(r"var\s+HANDOFF_RULES\s*=\s*\[(.*?)\];", js_text, re.DOTALL)
    assert m, "Could not find `var HANDOFF_RULES = [...];` in samepage.js"
    body = m.group(1)

    # Split top-level array elements separated by `,\n` after a single-quoted literal
    raw_items = re.split(r"(?<='),\s*\n", body.strip())
    rules: list[str] = []
    for item in raw_items:
        # Concatenate adjacent `'...' + '...'` JS string fragments
        fragments = re.findall(r"'((?:\\'|[^'])*)'", item)
        joined = "".join(f.replace("\\'", "'") for f in fragments)
        if joined:
            rules.append(joined)
    return rules


def _extract_skill_section4_rules(skill_md_text: str) -> list[tuple[int, str]]:
    """Extract the 10-row numbered rules table in `skills/samepage/SKILL.md` §4."""
    sec4_match = re.search(
        r"^## 4\. JSON contract.*?(?=^## 5\.)",
        skill_md_text,
        re.DOTALL | re.MULTILINE,
    )
    assert sec4_match, "Could not locate section 4 in skills/samepage/SKILL.md"
    sec4 = sec4_match.group(0)

    rows: list[tuple[int, str]] = []
    for line in sec4.splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|$", line.strip())
        if m:
            rows.append((int(m.group(1)), m.group(2)))
    return rows


def test_handoff_rules_in_samepage_js_matches_skill_md_section_4():
    js_text = (REPO_ROOT / "samepage/assets/samepage.js").read_text(encoding="utf-8")
    skill_text = (REPO_ROOT / "skills/samepage/SKILL.md").read_text(encoding="utf-8")

    js_rules = _extract_js_handoff_rules(js_text)
    md_rows = _extract_skill_section4_rules(skill_text)

    assert len(js_rules) == 10, f"Expected 10 HANDOFF_RULES in samepage.js, got {len(js_rules)}"
    assert len(md_rows) == 10, f"Expected 10 rules in SKILL.md §4 table, got {len(md_rows)}"
    assert [num for num, _ in md_rows] == list(range(1, 11))

    md_rules_combined = "\n".join(text for _, text in md_rows)
    js_rules_combined = "\n".join(js_rules)

    # Key contract terms that must appear in both HANDOFF_RULES and SKILL.md §4
    shared_contract_terms = [
        "sourceHtml",
        "selectedText",
        "contextBefore",
        "contextAfter",
        "anchored",
        "resolved",
        "role",
        "source",
        "destination",
        "move",
        "insert",
        "delete",
        "shorten",
        "keep",
        "text-range",
        "answers",
        "questionId",
        "--responses",
    ]
    for term in shared_contract_terms:
        assert term in js_rules_combined, f"Missing contract term {term!r} in samepage.js HANDOFF_RULES"
        assert term in md_rules_combined, f"Missing contract term {term!r} in SKILL.md §4 rules table"
