#!/usr/bin/env python3
"""Build a reviewable HTML page from an ALIGNMENT document.

Usage:
    python3 docs/build_alignment_html.py docs/alignment/0001-slug.md
    python3 docs/build_alignment_html.py docs/alignment/0001-slug.md --out out.html
    python3 docs/build_alignment_html.py docs/alignment/0001-slug.md --export export.json
    python3 docs/build_alignment_html.py --index docs/alignment

An ALIGNMENT document is the source of truth for one grilling session
(see docs/alignment/0001-grill-on-samepage.md, decision D-1). This script
turns it into the HTML that samepage's review layer is injected into; it
never injects the layer itself, which stays samepage/cli.py's job.

Three things are generated rather than written by hand:

* the ``## design tree`` section becomes an inline SVG whose nodes carry
  ``data-sp-node`` (decision D-5, D-10, D-13),
* ``--export`` reads a samepage export JSON and prepends a "残件" block
  listing what is still unanswered or unresolved (decision D-15),
* ``--index`` scans a directory of ALIGNMENT documents and writes
  ``INDEX.md`` (decision D-11).

Requires the third-party `markdown` package. If it isn't installed, this
script stops with an explanation instead of silently degrading.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:
    sys.stderr.write(
        "error: the 'markdown' package is required but is not installed.\n"
        "Install it with:  pip install markdown\n"
    )
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# design tree notation (decision D-13)
# --------------------------------------------------------------------------
# - [D-1] title :: 確定 :: decision
#   - [D-5] title :: frontier
#     - (依存) [D-4]
#
# Indent is two spaces per level. Fields are separated by "::". Only a 確定
# row carries the third field. A "(依存) [ID]" child is an extra edge, not a
# node.

STATES = ("確定", "frontier", "再検討", "保留")

STATE_STYLE = {
    "確定":     {"fill": "#e6f5f3", "stroke": "#0f766e", "title": "#0f2a28",
                 "sub": "#0b5750", "mark": "✓"},
    "frontier": {"fill": "#fdf3e0", "stroke": "#b5790c", "title": "#5a3d05",
                 "sub": "#b5790c", "mark": "❓"},
    "再検討":   {"fill": "#fdecea", "stroke": "#b3261e", "title": "#5c1512",
                 "sub": "#b3261e", "mark": "↺"},
    "保留":     {"fill": "#f1f5f4", "stroke": "#8fa5a1", "title": "#3d4a48",
                 "sub": "#5b6c69", "mark": "⏸"},
}

NODE_RE = re.compile(r"^(?P<indent> *)- \[(?P<id>[A-Za-z]+-\d+)\]\s*(?P<rest>.+?)\s*$")
DEP_RE = re.compile(r"^(?P<indent> *)- \(依存\)\s*\[(?P<id>[A-Za-z]+-\d+)\]\s*$")
TREE_HEADING_RE = re.compile(r"^##\s+.*design tree.*$", re.M)


class TreeError(ValueError):
    """Raised when the design tree does not follow the D-13 notation."""


def parse_design_tree(lines):
    """Parse D-13 notation into (nodes, extra_edges).

    nodes is a list of dicts with id/title/state/decision/depth/parent, in
    document order. extra_edges is a list of (child_id, parent_id) pairs
    coming from "(依存) [ID]" rows.
    """
    nodes, edges, stack, seen = [], [], [], set()
    for lineno, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        dep = DEP_RE.match(raw)
        if dep:
            depth = len(dep.group("indent")) // 2
            if depth == 0 or not stack:
                raise TreeError(f"line {lineno}: (依存) must hang off a node")
            owner = next((nid for d, nid in reversed(stack) if d == depth - 1), None)
            if owner is None:
                raise TreeError(f"line {lineno}: (依存) has no owning node")
            edges.append((owner, dep.group("id")))
            continue
        m = NODE_RE.match(raw)
        if not m:
            raise TreeError(f"line {lineno}: not a design-tree row: {raw.strip()!r}")
        if len(m.group("indent")) % 2:
            raise TreeError(f"line {lineno}: indent must be a multiple of two spaces")
        depth = len(m.group("indent")) // 2
        fields = [f.strip() for f in m.group("rest").split("::")]
        if len(fields) < 2:
            raise TreeError(f"line {lineno}: expected 'title :: state' at minimum")
        nid, title, state = m.group("id"), fields[0], fields[1]
        if state not in STATES:
            raise TreeError(f"line {lineno}: state must be one of {'/'.join(STATES)}, got {state!r}")
        decision = fields[2] if len(fields) > 2 else ""
        if state == "確定" and not decision:
            raise TreeError(f"line {lineno}: a 確定 row must carry a decision field")
        if state != "確定" and decision:
            raise TreeError(f"line {lineno}: only a 確定 row may carry a decision field")
        if nid in seen:
            raise TreeError(f"line {lineno}: duplicate id {nid} (ids are never reused)")
        seen.add(nid)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if depth and not stack:
            raise TreeError(f"line {lineno}: {nid} is indented but has no parent")
        parent = stack[-1][1] if depth else None
        stack.append((depth, nid))
        nodes.append({"id": nid, "title": title, "state": state,
                      "decision": decision, "depth": depth, "parent": parent})
    for _, target in edges:
        if target not in seen:
            raise TreeError(f"(依存) points at unknown id {target}")
    return nodes, edges


def split_tree_section(body):
    """Return (before, tree_lines, after) around the design tree list."""
    m = TREE_HEADING_RE.search(body)
    if not m:
        return body, [], ""
    after_heading = m.end()
    rest = body[after_heading:]
    nxt = re.search(r"^## ", rest, re.M)
    section_end = after_heading + (nxt.start() if nxt else len(rest))
    section = body[after_heading:section_end]
    tree_lines = [ln for ln in section.splitlines() if ln.strip()]
    return body[:after_heading], tree_lines, body[section_end:]


# --------------------------------------------------------------------------
# SVG rendering
# --------------------------------------------------------------------------

BOX_W, BOX_H, COL_GAP, ROW_GAP, TOP = 182, 56, 14, 74, 16
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def _esc(s):
    return html.escape(s, quote=True)


def anchor_for(node_id):
    """#d1 for D-1 — matches the id the ledger table rows get."""
    return node_id.replace("-", "").lower()


def _fit(text, budget=170, size=12):
    """Truncate to roughly `budget` px at `size` px, counting CJK as full width."""
    out, w = [], 0.0
    for ch in text:
        w += size * (1.0 if ord(ch) > 0x2E80 else 0.55)
        if w > budget:
            out.append("…")
            break
        out.append(ch)
    return "".join(out)


def layout(nodes):
    """Grid layout: row = depth, column = order within that depth."""
    rows = {}
    for n in nodes:
        rows.setdefault(n["depth"], []).append(n)
    for depth, row in rows.items():
        span = len(row) * BOX_W + (len(row) - 1) * COL_GAP
        for i, n in enumerate(row):
            n["x"] = i * (BOX_W + COL_GAP)
            n["y"] = TOP + depth * (BOX_H + ROW_GAP)
            n["row_span"] = span
    width = max(n["row_span"] for n in nodes)
    for n in nodes:                                  # centre each row
        n["x"] += (width - n["row_span"]) // 2
        n["cx"], n["cy"] = n["x"] + BOX_W // 2, n["y"] + BOX_H // 2
    height = max(n["y"] + BOX_H for n in nodes) + 40
    return width, height


def render_svg(nodes, edges, doc_id):
    """Inline SVG for the design tree. Marker ids are namespaced per document
    so two diagrams on one page cannot collide."""
    if not nodes:
        return ""
    width, height = layout(nodes)
    by_id = {n["id"]: n for n in nodes}
    out = [f'<svg class="sp-tree-svg" viewBox="0 0 {width} {height}" role="img"'
           f' aria-label="design tree">', '  <defs>']
    for key, col in (("ok", "#0f766e"), ("dep", "#8fa5a1")):
        out.append(f'    <marker id="sp-ar-{doc_id}-{key}" viewBox="0 0 10 10" refX="9" refY="5"'
                   f' markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                   f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{col}"/></marker>')
    out.append("  </defs>")

    for n in nodes:                                  # parent edges
        if not n["parent"]:
            continue
        p = by_id[n["parent"]]
        col = STATE_STYLE[n["state"]]["stroke"]
        out.append(f'  <line x1="{p["cx"]}" y1="{p["y"] + BOX_H}" x2="{n["cx"]}" y2="{n["y"] - 4}"'
                   f' stroke="{col}" stroke-width="2" marker-end="url(#sp-ar-{doc_id}-ok)"/>')
    for src, dst in edges:                           # (依存) edges, dashed
        a, b = by_id[src], by_id[dst]
        out.append(f'  <line x1="{a["cx"]}" y1="{a["y"]}" x2="{b["cx"]}" y2="{b["y"] + BOX_H + 4}"'
                   f' stroke="#8fa5a1" stroke-width="2" stroke-dasharray="5,4"'
                   f' marker-end="url(#sp-ar-{doc_id}-dep)"/>')

    for n in nodes:
        st = STATE_STYLE[n["state"]]
        label = f'{n["id"]} {n["title"]}' + (f'（{n["state"]}: {n["decision"]}）'
                                             if n["decision"] else f'（{n["state"]}）')
        line1 = _fit(f'{n["id"]} {n["title"]}')
        line2 = _fit(f'{st["mark"]} {n["decision"] or n["state"]}', size=11)
        out.append(
            f'  <a href="#{anchor_for(n["id"])}">'
            f'<g data-sp-node="{_esc(n["id"])}" data-sp-label="{_esc(label)}">'
            f'<rect x="{n["x"]}" y="{n["y"]}" width="{BOX_W}" height="{BOX_H}" rx="10" ry="10"'
            f' fill="{st["fill"]}" stroke="{st["stroke"]}" stroke-width="2"/>'
            f'<text text-anchor="middle" font-family="{FONT}" y="{n["y"] + 24}">'
            f'<tspan x="{n["cx"]}" font-size="12" fill="{st["title"]}">{_esc(line1)}</tspan>'
            f'<tspan x="{n["cx"]}" dy="17" font-size="11" fill="{st["sub"]}"'
            f' font-weight="700">{_esc(line2)}</tspan></text></g></a>')

    seen_states = [s for s in STATES if any(n["state"] == s for n in nodes)]
    lx = 0
    for s in seen_states:
        st = STATE_STYLE[s]
        n = sum(1 for x in nodes if x["state"] == s)
        out.append(f'  <g><rect x="{lx}" y="{height - 28}" width="14" height="14" rx="3"'
                   f' fill="{st["fill"]}" stroke="{st["stroke"]}" stroke-width="2"/>'
                   f'<text x="{lx + 22}" y="{height - 17}" font-size="12" fill="#5b6c69"'
                   f' font-family="{FONT}">{_esc(s)}（{n}）</text></g>')
        lx += 40 + 13 * len(s) + 34
    out.append("</svg>")
    return '<div class="sp-tree-wrap">' + "\n".join(out) + "</div>"


# --------------------------------------------------------------------------
# 残件 block (decision D-15)
# --------------------------------------------------------------------------

def build_remaining(export_path, nodes):
    """Render the outstanding-items block from a samepage export JSON."""
    data = json.loads(Path(export_path).read_text(encoding="utf-8"))
    answers = {a.get("questionId") for a in data.get("answers", []) if a.get("questionId")}
    comments = data.get("comments", [])
    open_ids = [c.get("id") for c in comments if c.get("status") == "open"]
    settled = [n for n in nodes if n["state"] == "確定"]
    pending = [n for n in nodes if n["state"] in ("frontier", "再検討")]
    held = [n for n in nodes if n["state"] == "保留"]
    rows = [
        ("回答済みの質問ピン", len(answers), "export JSON の answers より"),
        ("未解決のコメント (<code>status: &quot;open&quot;</code>)", len(open_ids),
         ", ".join(open_ids) if open_ids else f"{len(comments)} 件すべて resolved"),
        ("確定した決定", len(settled), ", ".join(n["id"] for n in settled) or "—"),
        ("未確定の決定 (frontier / 再検討)", len(pending),
         ", ".join(n["id"] for n in pending) or "なし"),
        ("運用へ回した保留", len(held), ", ".join(n["id"] for n in held) or "なし"),
    ]
    body = "".join(
        f'<tr><td>{label}</td><td class="sp-v">{count}</td><td>{detail}</td></tr>'
        for label, count, detail in rows)
    blocked = len(open_ids) + len(pending)
    verdict = ("<p><strong>残件はゼロです。</strong>D-4 の合意ゲートにより、"
               "ここから先は明示的な合意が必要です。</p>" if blocked == 0 else
               f"<p><strong>残件が {blocked} 件あります。</strong>"
               "すべて片付くまで <code>--finalize</code> しないでください（D-4）。</p>")
    return (
        '<div class="sp-discussion" data-sp-discussion>\n'
        '<h3 id="remaining">残件</h3>\n'
        f'<p><small>{_esc(str(data.get("generatedAt", "")))} のエクスポートから算出。'
        'この節はビルダーが生成します（D-15）。<code>data-sp-discussion</code> 付きなので '
        'finalize で消えます。</small></p>\n'
        '<div class="table-wrap"><table><thead><tr><th>項目</th><th>件数</th><th>内訳</th>'
        f'</tr></thead><tbody>{body}</tbody></table></div>\n{verdict}\n</div>\n')


# --------------------------------------------------------------------------
# page assembly
# --------------------------------------------------------------------------

PAGE_CSS = """
:root{
  --sp-bg:#fbfdfc; --sp-fg:#1c2624; --sp-muted:#5b6c69;
  --sp-accent:#0f766e; --sp-accent-dark:#0b5750; --sp-border:#d7e6e3;
  --sp-kbd-bg:#eef2f1; --sp-kbd-border:#c3d3d0; --sp-banner-bg:#eef7f5;
  --sp-banner-fg:#0b5750; --sp-amber:#b5790c; --sp-red:#b3261e;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{background:var(--sp-bg); color:var(--sp-fg); line-height:1.7; font-size:16px;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;}
a{color:var(--sp-accent-dark);}
.sp-banner{background:var(--sp-banner-bg); color:var(--sp-banner-fg); text-align:center;
  padding:.6rem 1rem; font-size:.85rem; border-bottom:1px solid var(--sp-border);}
.sp-shell{max-width:920px; margin:0 auto; padding:0 1.25rem 5rem;}
.sp-hero{padding:2.6rem 0 1rem; border-bottom:1px solid var(--sp-border);}
.sp-hero .sp-eyebrow{font-size:.78rem; text-transform:uppercase; letter-spacing:.09em;
  color:var(--sp-muted); margin:0 0 .5rem;}
.sp-hero h1{font-size:2rem; margin:0 0 .5rem; letter-spacing:-.01em;}
.sp-hero p{margin:.35rem 0; color:var(--sp-muted);}
.sp-meta{font-size:.85rem; color:var(--sp-muted); margin-top:1rem;}
.sp-meta span{margin-right:1.2rem;}
h2{font-size:1.4rem; margin:3rem 0 1rem; padding-top:.6rem;
   border-top:1px solid var(--sp-border); scroll-margin-top:1rem;}
h3{font-size:1.12rem; margin:2.2rem 0 .6rem; color:var(--sp-accent-dark); scroll-margin-top:1rem;}
p{margin:.8rem 0;} ul,ol{margin:.6rem 0; padding-left:1.4rem;} li{margin:.35rem 0;}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--sp-kbd-bg); border:1px solid var(--sp-kbd-border);
  border-radius:4px; padding:.1rem .35rem; font-size:.88em;}
pre{background:#1e293b; color:#e2e8f0; border-radius:8px; padding:1rem 1.1rem;
  overflow-x:auto; font-size:.86rem; line-height:1.55;}
pre code{background:transparent; border:none; padding:0; color:inherit;}
.table-wrap{overflow-x:auto; margin:1rem 0; border:1px solid var(--sp-border); border-radius:8px;}
table{border-collapse:collapse; width:100%; font-size:.9rem;}
th,td{padding:.6rem .8rem; border-bottom:1px solid var(--sp-border);
  text-align:left; vertical-align:top;}
thead th{background:#f1f8f6; color:var(--sp-accent-dark); font-weight:600;}
tbody tr:last-child td{border-bottom:none;}
tbody td:first-child{font-weight:600; color:var(--sp-accent-dark); white-space:nowrap;}
td.sp-v{font-weight:700; color:#0b5750; white-space:nowrap;}
.sp-discussion{background:#f6f4fb; border:1px dashed #9b8fc4; padding:1rem 1.15rem;
  margin:1.4rem 0; border-radius:8px; font-size:.93rem;}
.sp-discussion h3{margin-top:0; color:#5b4b96;}
.sp-tree-wrap{margin:1.4rem 0 .6rem;}
.sp-tree-svg{display:block; max-width:100%; height:auto;}
.sp-tree-svg a [data-sp-node]{cursor:pointer;}
"""

PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="sp-banner">{banner}</div>
<div class="sp-shell">
<header class="sp-hero">
  <p class="sp-eyebrow">Alignment {doc_id}</p>
  <h1>{h1}</h1>
  <p>{lede}</p>
  <p class="sp-meta">{meta}</p>
</header>
{remaining}<article class="sp-article">{body}</article>
</div>
</body>
</html>
"""

TABLE_RE = re.compile(r"<table>.*?</table>", re.S)
LEDGER_ROW_RE = re.compile(r'<tr>\s*<td>([A-Za-z]+-\d+)', re.M)
HEADING_ID_RE = re.compile(r'<(h[23])(?![^>]*\bid=)[^>]*>\s*([A-Za-z]+-\d+)(?=[.\s])')
HEADING_TOC_ID_RE = re.compile(r'<(h[23]) id="[^"]*">\s*([A-Za-z]+-\d+)(?=[.\s])')


def wrap_tables(html_text):
    return TABLE_RE.sub(lambda m: f'<div class="table-wrap">{m.group(0)}</div>', html_text)


def add_row_anchors(html_text):
    """Give every table row whose first cell starts with an id (D-1, …) an
    HTML id, so the design tree's node links and question pins can target it."""
    def rep(m):
        return f'<tr id="{anchor_for(m.group(1))}">\n<td>{m.group(1)}'
    return LEDGER_ROW_RE.sub(rep, html_text)


def add_heading_anchors(html_text):
    """Same, for a decision written as its own section rather than as a ledger
    row: an <h2>/<h3> starting with an id gets that id, overriding the slug the
    toc extension derived from the heading text. Both spellings of a decision
    therefore end up reachable at the anchor the design tree links to."""
    def rep(m):
        return f'<{m.group(1)} id="{anchor_for(m.group(2))}">{m.group(2)}'
    html_text = HEADING_TOC_ID_RE.sub(
        lambda m: f'<{m.group(1)} id="{anchor_for(m.group(2))}">{m.group(2)}', html_text)
    return HEADING_ID_RE.sub(rep, html_text)


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[end + 5:]


def build(md_path, out_path, export_path=None):
    text = Path(md_path).read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    doc_id = meta.get("id") or Path(md_path).stem.split("-")[0]

    before, tree_lines, after = split_tree_section(body)
    nodes, edges = parse_design_tree(tree_lines) if tree_lines else ([], [])
    svg = render_svg(nodes, edges, doc_id)

    # h1 + lede come out of the body so the hero can own them
    m = re.match(r"\s*#\s+(.+?)\n+(.*?)\n\n", before, re.S)
    h1 = m.group(1).strip() if m else meta.get("title", Path(md_path).stem)
    lede = m.group(2).strip() if m else ""
    if m:
        before = before[m.end():]

    md_body = before + "\n\n@@TREE@@\n\n" + after
    html_body = markdown.markdown(md_body, extensions=["fenced_code", "tables", "toc"])
    html_body = html_body.replace("<p>@@TREE@@</p>", svg)
    html_body = add_heading_anchors(add_row_anchors(wrap_tables(html_body)))

    meta_bits = []
    for key, label in (("status", "状態"), ("agreed-at", "合意日"), ("branch", "ブランチ")):
        if meta.get(key):
            meta_bits.append(f'<span>{_esc(label)} {_esc(meta[key])}</span>')
    meta_bits.append(f'<span>決定 {len(nodes)} 件</span>')

    page = PAGE.format(
        title=_esc(h1), css=PAGE_CSS, doc_id=_esc(str(doc_id)), h1=_esc(h1),
        lede=_esc(lede), meta="".join(meta_bits),
        banner=_esc(f"{Path(md_path).name} から生成 — 編集は .md 側に対して行い、再生成してください。"),
        remaining=build_remaining(export_path, nodes) if export_path else "",
        body=html_body)
    Path(out_path).write_text(page, encoding="utf-8")
    return nodes


def build_index(dirpath):
    """Write INDEX.md: one row per ALIGNMENT document plus a merged glossary
    (decision D-11). Body text stays in the documents; this file is generated."""
    d = Path(dirpath)
    docs, glossary = [], {}
    for md in sorted(d.glob("*.md")):
        if md.name == "INDEX.md":
            continue
        meta, body = parse_frontmatter(md.read_text(encoding="utf-8"))
        _, tree_lines, _ = split_tree_section(body)
        nodes, _ = parse_design_tree(tree_lines) if tree_lines else ([], [])
        docs.append({"file": md.name, "meta": meta, "nodes": nodes,
                     "title": meta.get("title", md.stem)})
        for line in body.splitlines():
            g = re.match(r"^- \*\*(.+?)\*\* — (.+)$", line.strip())
            if g:
                glossary.setdefault(g.group(1), (g.group(2), md.name))

    out = ["<!-- Generated by docs/build_alignment_html.py --index. Do not edit by hand. -->",
           "", "# ALIGNMENT 文書の索引", "",
           "各文書が 1 回の grilling セッションに対応します（D-1）。本文はここには置かず、",
           "各文書側にあります（D-11）。", "", "## 文書", "",
           "| 文書 | タイトル | 状態 | 合意日 | 決定 |", "|---|---|---|---|---|"]
    for doc in docs:
        settled = sum(1 for n in doc["nodes"] if n["state"] == "確定")
        out.append(f'| [`{doc["file"]}`]({doc["file"]}) | {doc["title"]} '
                   f'| {doc["meta"].get("status", "—")} | {doc["meta"].get("agreed-at", "—")} '
                   f'| {settled}/{len(doc["nodes"])} 確定 |')
    out += ["", "## 決定", "", "| ID | タイトル | 状態 | 決定 | 出典 |", "|---|---|---|---|---|"]
    for doc in docs:
        for n in doc["nodes"]:
            out.append(f'| {n["id"]} | {n["title"]} | {n["state"]} | {n["decision"] or "—"} '
                       f'| [`{doc["file"]}`]({doc["file"]}) |')
    if glossary:
        out += ["", "## 用語", "", "| 語 | 定義 | 出典 |", "|---|---|---|"]
        for term, (defn, src) in sorted(glossary.items()):
            out.append(f'| {term} | {defn} | [`{src}`]({src}) |')
    (d / "INDEX.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return docs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", nargs="?", help="ALIGNMENT markdown file")
    ap.add_argument("--out", help="output HTML (default: <input stem>.html)")
    ap.add_argument("--export", help="samepage export JSON, for the 残件 block")
    ap.add_argument("--index", metavar="DIR", help="write INDEX.md for a directory instead")
    args = ap.parse_args(argv)

    if args.index:
        docs = build_index(args.index)
        print(f"wrote {Path(args.index) / 'INDEX.md'} ({len(docs)} documents)")
        return 0
    if not args.input:
        ap.error("an input file is required unless --index is given")
    out = args.out or str(Path(args.input).with_suffix(".html"))
    try:
        nodes = build(args.input, out, args.export)
    except TreeError as e:
        sys.stderr.write(f"error: design tree: {e}\n")
        return 1
    states = {}
    for n in nodes:
        states[n["state"]] = states.get(n["state"], 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in states.items()) or "no tree"
    print(f"wrote {out} (nodes={len(nodes)}, {summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
