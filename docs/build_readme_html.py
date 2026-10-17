#!/usr/bin/env python3
"""Build a rich, self-contained HTML page from README.md / README.ja.md.

Usage:
    python3 docs/build_readme_html.py README.ja.md README.ja.html
    python3 docs/build_readme_html.py README.md README.html

All body text is taken from the Markdown source and converted with the
`markdown` package (extensions: fenced_code, tables, toc). Nothing in this
script hardcodes prose from the README — only UI chrome (banner text, TOC
heading, etc.) and the inline SVG flow diagram that replaces the ```mermaid
fenced block are defined here.

Requires the third-party `markdown` package. If it isn't installed, this
script stops with an explanation instead of silently degrading.
"""
import html
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


# --------------------------------------------------------------------------
# UI strings per language
# --------------------------------------------------------------------------

UI = {
    "ja": {
        "html_lang": "ja",
        "banner": "この HTML は README.ja.md から自動生成されています — "
                   "編集は元の .md に対して行い、再生成してください。",
        "toc_heading": "目次",
        "toc_summary": "目次を開く",
        "generated_note": "samepage のレビュー層を注入して確認できます。",
    },
    "en": {
        "html_lang": "en",
        "banner": "Generated from README.md — this file is derived; "
                   "edit the .md and rebuild.",
        "toc_heading": "Contents",
        "toc_summary": "Show contents",
        "generated_note": "Inject the samepage review layer to comment on it.",
    },
}


# --------------------------------------------------------------------------
# Inline SVG flow diagram (replaces the ```mermaid fenced block)
# --------------------------------------------------------------------------

FLOW_LABELS = {
    "ja": {
        "flow-human-comment": ["人がコメント"],
        "flow-agent": ["AIエージェント"],
        "flow-fix-source": ["原本を直す", "（生成物なら生成元）"],
        "flow-regenerate": ["HTML再生成"],
        "flow-human-review": ["人が返信・", "質問ピンを見る"],
        "flow-agree": ["合意できたか？"],
        "flow-finalize": ["--finalize で", "公開用HTML"],
        "edge-comment-to-agent": "コメントJSON → j",
        "edge-agent-to-fix": "反映",
        "edge-fix-to-regen": "再生成",
        "edge-regen-to-review": "--responses / --questions",
        "edge-review-to-agree": "解決 or 追加コメント",
        "edge-agree-to-finalize": "できた",
        "edge-agree-loop-back": "まだ",
    },
    "en": {
        "flow-human-comment": ["Human comments"],
        "flow-agent": ["AI agent"],
        "flow-fix-source": ["Fix the original", "(source, if generated)"],
        "flow-regenerate": ["Regenerate HTML"],
        "flow-human-review": ["Human reviews replies", "& question pins"],
        "flow-agree": ["Consensus?"],
        "flow-finalize": ["--finalize:", "publishable HTML"],
        "edge-comment-to-agent": "comment JSON → j",
        "edge-agent-to-fix": "applies the fix",
        "edge-fix-to-regen": "regenerate",
        "edge-regen-to-review": "--responses / --questions",
        "edge-review-to-agree": "more comments, or resolved",
        "edge-agree-to-finalize": "yes",
        "edge-agree-loop-back": "not yet",
    },
}

# Fixed node geometry, shared across languages. (x, y, w, h)
NODE_BOX = {
    "flow-human-comment": (15, 40, 150, 70),
    "flow-agent": (275, 40, 150, 70),
    "flow-fix-source": (535, 40, 150, 70),
    "flow-regenerate": (795, 40, 150, 70),
    "flow-human-review": (795, 300, 150, 70),
    "flow-finalize": (15, 300, 150, 70),
}
# diamond: center x/y, half-width, half-height
AGREE_DIAMOND = (350, 335, 95, 55)


def _esc(s):
    return html.escape(s, quote=True)


def _text_block(lines, cx, cy, font_size=13, fill="#0f2a28"):
    """Render 1-3 lines of text centered at (cx, cy) using tspans."""
    n = len(lines)
    line_h = font_size + 5
    first_dy = -((n - 1) * line_h) / 2.0
    tspans = []
    for i, line in enumerate(lines):
        dy = first_dy if i == 0 else line_h
        tspans.append(f'<tspan x="{cx}" dy="{dy}">{_esc(line)}</tspan>')
    return (
        f'<text text-anchor="middle" font-size="{font_size}" fill="{fill}" '
        f'font-family="-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif" '
        f'y="{cy}">{"".join(tspans)}</text>'
    )


def _rect_node(node_id, label_lines, box):
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    label = " / ".join(label_lines)
    return (
        f'<g data-sp-node="{_esc(node_id)}" data-sp-label="{_esc(label)}">'
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" ry="10" '
        f'fill="#e6f5f3" stroke="#0f766e" stroke-width="2"/>'
        f'{_text_block(label_lines, cx, cy)}'
        f'</g>'
    )


def _diamond_node(node_id, label_lines, diamond):
    cx, cy, hw, hh = diamond
    pts = f"{cx},{cy-hh} {cx+hw},{cy} {cx},{cy+hh} {cx-hw},{cy}"
    label = " / ".join(label_lines)
    return (
        f'<g data-sp-node="{_esc(node_id)}" data-sp-label="{_esc(label)}">'
        f'<polygon points="{pts}" fill="#fdf3e0" stroke="#b5790c" stroke-width="2"/>'
        f'{_text_block(label_lines, cx, cy, font_size=12, fill="#5a3d05")}'
        f'</g>'
    )


def _halo_text(label_x, label_y, label, text_anchor="middle", font_size=11,
               fill="#3a5a57"):
    """A text label with a white halo (paint-order: stroke) so it stays
    readable when it sits on top of a line or a node edge."""
    ff = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
    return (
        f'<text x="{label_x}" y="{label_y}" text-anchor="{text_anchor}" '
        f'font-size="{font_size}" fill="{fill}" font-family="{ff}" '
        f'paint-order="stroke" stroke="#fbfdfc" stroke-width="4" '
        f'stroke-linejoin="round">{_esc(label)}</text>'
    )


def _straight_edge(edge_id, label, x1, y1, x2, y2, label_x=None, label_y=None,
                    label_anchor="middle", label_above=True):
    if label_x is None:
        label_x = (x1 + x2) / 2
    if label_y is None:
        # Default: place the label just above the line (not on top of it),
        # so it never gets clipped behind a short edge's node boxes.
        base_y = (y1 + y2) / 2
        label_y = base_y - 16 if label_above else base_y - 8
    return (
        f'<g data-sp-node="{_esc(edge_id)}" data-sp-label="{_esc(label)}">'
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="transparent" stroke-width="14"/>'
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="#0f766e" stroke-width="2" marker-end="url(#sp-arrow)"/>'
        f'{_halo_text(label_x, label_y, label, text_anchor=label_anchor)}'
        f'</g>'
    )


def _curve_edge(edge_id, label, path_d, label_x, label_y, color="#b5790c"):
    return (
        f'<g data-sp-node="{_esc(edge_id)}" data-sp-label="{_esc(label)}">'
        f'<path d="{path_d}" fill="none" stroke="transparent" stroke-width="16"/>'
        f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="2" '
        f'marker-end="url(#sp-arrow-amber)" stroke-dasharray="6,4"/>'
        f'{_halo_text(label_x, label_y, label, fill=color)}'
        f'</g>'
    )


def build_flow_svg(lang):
    L = FLOW_LABELS[lang]
    hc = NODE_BOX["flow-human-comment"]
    ag = NODE_BOX["flow-agent"]
    fx = NODE_BOX["flow-fix-source"]
    rg = NODE_BOX["flow-regenerate"]
    hr = NODE_BOX["flow-human-review"]
    fin = NODE_BOX["flow-finalize"]
    dia = AGREE_DIAMOND

    nodes = [
        _rect_node("flow-human-comment", L["flow-human-comment"], hc),
        _rect_node("flow-agent", L["flow-agent"], ag),
        _rect_node("flow-fix-source", L["flow-fix-source"], fx),
        _rect_node("flow-regenerate", L["flow-regenerate"], rg),
        _rect_node("flow-human-review", L["flow-human-review"], hr),
        _diamond_node("flow-agree", L["flow-agree"], dia),
        _rect_node("flow-finalize", L["flow-finalize"], fin),
    ]

    row1_y = hc[1] + hc[3] / 2  # center-y of row 1
    row2_y = hr[1] + hr[3] / 2  # center-y of row 2

    edges = [
        _straight_edge(
            "edge-comment-to-agent", L["edge-comment-to-agent"],
            hc[0] + hc[2], row1_y, ag[0], row1_y,
        ),
        _straight_edge(
            "edge-agent-to-fix", L["edge-agent-to-fix"],
            ag[0] + ag[2], row1_y, fx[0], row1_y,
        ),
        _straight_edge(
            "edge-fix-to-regen", L["edge-fix-to-regen"],
            fx[0] + fx[2], row1_y, rg[0], row1_y,
        ),
        _straight_edge(
            "edge-regen-to-review", L["edge-regen-to-review"],
            rg[0] + rg[2] / 2, rg[1] + rg[3], hr[0] + hr[2] / 2, hr[1],
            label_x=rg[0] + rg[2] / 2 - 8, label_y=(rg[1] + rg[3] + hr[1]) / 2,
            label_anchor="end",
        ),
        _straight_edge(
            "edge-review-to-agree", L["edge-review-to-agree"],
            hr[0], row2_y, dia[0] + dia[2], dia[1],
        ),
        _straight_edge(
            "edge-agree-to-finalize", L["edge-agree-to-finalize"],
            dia[0] - dia[2], dia[1], fin[0] + fin[2], row2_y,
        ),
        _curve_edge(
            "edge-agree-loop-back", L["edge-agree-loop-back"],
            f"M {dia[0]} {dia[1] - dia[3]} "
            f"C {dia[0] - 60} {dia[1] - 140}, "
            f"{hc[0] + hc[2] / 2 - 20} {hc[1] + hc[3] + 90}, "
            f"{hc[0] + hc[2] / 2} {hc[1] + hc[3]}",
            (dia[0] + hc[0] + hc[2] / 2) / 2 - 40, (dia[1] + hc[1] + hc[3]) / 2 - 40,
        ),
    ]

    width, height = 980, 400
    svg = f'''<svg class="sp-flow-svg" viewBox="0 0 {width} {height}" width="100%"
     xmlns="http://www.w3.org/2000/svg" role="img" aria-label="flow diagram">
  <defs>
    <marker id="sp-arrow" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#0f766e"/>
    </marker>
    <marker id="sp-arrow-amber" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#b5790c"/>
    </marker>
  </defs>
  {"".join(edges)}
  {"".join(nodes)}
</svg>'''
    return svg


# --------------------------------------------------------------------------
# Markdown -> HTML pipeline
# --------------------------------------------------------------------------

MERMAID_BLOCK_RE = re.compile(
    r"<pre><code class=\"language-mermaid\">.*?</code></pre>", re.DOTALL
)
CODE_KBD_RE = re.compile(r"<code>([a-zA-Z])</code>")
H2_RE = re.compile(r'<h2 id="([^"]+)">(.*?)</h2>', re.DOTALL)
STRIP_TAGS_RE = re.compile(r"<[^>]+>")


def convert_markdown(md_text):
    return markdown.markdown(
        md_text, extensions=["fenced_code", "tables", "toc"]
    )


def replace_mermaid_with_svg(body_html, lang):
    svg = build_flow_svg(lang)
    return MERMAID_BLOCK_RE.sub(svg, body_html)


def kbdify(body_html):
    return CODE_KBD_RE.sub(r"<kbd>\1</kbd>", body_html)


def wrap_tables(body_html):
    body_html = body_html.replace("<table>", '<div class="table-wrap"><table>')
    body_html = body_html.replace("</table>", "</table></div>")
    return body_html


def split_hero_and_body(full_html):
    """Split into (hero_html, body_html) at the first <h2 ...> tag."""
    m = re.search(r"<h2", full_html)
    if not m:
        return full_html, ""
    return full_html[: m.start()], full_html[m.start():]


def build_toc(body_html):
    items = []
    for m in H2_RE.finditer(body_html):
        anchor_id, inner = m.group(1), m.group(2)
        text = STRIP_TAGS_RE.sub("", inner).strip()
        items.append((anchor_id, text))
    return items


def toc_html(items, heading, list_class="sp-toc-list"):
    lis = "".join(
        f'<li><a href="#{_esc(i)}">{_esc(t)}</a></li>' for i, t in items
    )
    return f'<p class="sp-toc-heading">{_esc(heading)}</p><ul class="{list_class}">{lis}</ul>'


def extract_h1_text(hero_html):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", hero_html, re.DOTALL)
    if not m:
        return "samepage"
    return STRIP_TAGS_RE.sub("", m.group(1)).strip()


# --------------------------------------------------------------------------
# Page template
# --------------------------------------------------------------------------

PAGE_CSS = """
:root{
  --sp-bg:#fbfdfc; --sp-fg:#1c2624; --sp-muted:#5b6c69;
  --sp-accent:#0f766e; --sp-accent-dark:#0b5750; --sp-border:#d7e6e3;
  --sp-card:#ffffff; --sp-code-bg:#1e293b; --sp-code-fg:#e2e8f0;
  --sp-kbd-bg:#eef2f1; --sp-kbd-border:#c3d3d0; --sp-banner-bg:#eef7f5;
  --sp-banner-fg:#0b5750;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{
  background:var(--sp-bg); color:var(--sp-fg);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  line-height:1.65; font-size:16px;
}
a{color:var(--sp-accent-dark);}
a:hover{color:var(--sp-accent);}
.sp-banner{
  background:var(--sp-banner-bg); color:var(--sp-banner-fg);
  text-align:center; padding:.6rem 1rem; font-size:.85rem;
  border-bottom:1px solid var(--sp-border);
}
.sp-shell{
  max-width:1180px; margin:0 auto; padding:0 1.25rem 4rem;
  display:flex; gap:2.5rem; align-items:flex-start;
}
.sp-main{ min-width:0; flex:1 1 auto; max-width:920px; }
.sp-hero{ padding:2.5rem 0 1rem; }
.sp-hero h1{ font-size:2.1rem; margin:0 0 .4rem; letter-spacing:-.01em; }
.sp-hero p{ margin:.3rem 0; color:var(--sp-muted); }
.sp-hero em{ font-style:italic; color:var(--sp-muted); }
.sp-toc-desktop{
  flex:0 0 240px; position:sticky; top:1.5rem;
  align-self:flex-start; padding-top:2.5rem;
}
.sp-toc-mobile{ display:none; }
.sp-toc-heading{
  font-size:.8rem; text-transform:uppercase; letter-spacing:.06em;
  color:var(--sp-muted); margin:0 0 .6rem; border:none;
}
.sp-toc-list{ list-style:none; margin:0; padding:0; }
.sp-toc-list li{ margin:0; }
.sp-toc-list a{
  display:block; padding:.3rem 0; font-size:.9rem; text-decoration:none;
  color:var(--sp-muted); border-left:2px solid transparent; padding-left:.6rem;
}
.sp-toc-list a:hover{ color:var(--sp-accent-dark); border-left-color:var(--sp-border); }
.sp-article h2{
  font-size:1.45rem; margin:3rem 0 1rem; padding-top:.5rem;
  border-top:1px solid var(--sp-border);
}
.sp-article h1 + h2, .sp-article > h2:first-child{ border-top:none; }
.sp-article h3{ font-size:1.15rem; margin:1.6rem 0 .6rem; }
.sp-article p{ margin:.75rem 0; }
.sp-article ul, .sp-article ol{ margin:.6rem 0; padding-left:1.4rem; }
.sp-article li{ margin:.3rem 0; }
.sp-article code{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--sp-kbd-bg); border:1px solid var(--sp-kbd-border);
  border-radius:4px; padding:.1rem .35rem; font-size:.88em;
}
.sp-article pre{
  background:var(--sp-code-bg); color:var(--sp-code-fg);
  border-radius:8px; padding:1rem 1.1rem; overflow-x:auto;
  font-size:.88rem; line-height:1.55;
}
.sp-article pre code{
  background:transparent; border:none; padding:0; color:inherit;
  font-size:1em;
}
kbd{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--sp-kbd-bg); border:1px solid var(--sp-kbd-border);
  border-bottom-width:2px; border-radius:5px; padding:.05rem .4rem;
  font-size:.85em; box-shadow:0 1px 0 rgba(0,0,0,.04);
}
.table-wrap{ overflow-x:auto; margin:1rem 0; border:1px solid var(--sp-border);
  border-radius:8px; }
table{ border-collapse:collapse; width:100%; font-size:.92rem; }
th,td{ padding:.55rem .8rem; border-bottom:1px solid var(--sp-border);
  text-align:left; vertical-align:top; white-space:normal; }
thead th{ background:#f1f8f6; color:var(--sp-accent-dark); font-weight:600; }
td:first-child code, th:first-child code{
  font-weight:600; color:var(--sp-accent-dark); background:transparent;
  border:none; padding:0;
}
.sp-flow-wrap{ margin:1.2rem 0 1.6rem; }
.sp-flow-svg{ display:block; max-width:100%; height:auto; }
.sp-flow-svg [data-sp-node]{ cursor:default; }
@media (max-width: 860px){
  .sp-shell{ flex-direction:column; padding:0 1rem 3rem; }
  .sp-toc-desktop{ display:none; }
  .sp-toc-mobile{ display:block; margin:1.2rem 0 0; }
  .sp-toc-mobile summary{
    cursor:pointer; font-weight:600; color:var(--sp-accent-dark);
    padding:.5rem 0;
  }
  .sp-toc-mobile .sp-toc-heading{ display:none; }
  .sp-main{ max-width:100%; }
}
"""


def build_page(lang, title_text, hero_html, body_html, toc_items, ui):
    toc_desktop = f'<aside class="sp-toc-desktop">{toc_html(toc_items, ui["toc_heading"])}</aside>'
    toc_mobile = (
        f'<details class="sp-toc-mobile"><summary>{_esc(ui["toc_summary"])}</summary>'
        f'{toc_html(toc_items, ui["toc_heading"], list_class="sp-toc-list sp-toc-list-mobile")}'
        f'</details>'
    )
    return f"""<!DOCTYPE html>
<html lang="{ui['html_lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title_text)}</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="sp-banner">{_esc(ui['banner'])}</div>
<div class="sp-shell">
  {toc_desktop}
  <main class="sp-main">
    <header class="sp-hero">{hero_html}</header>
    {toc_mobile}
    <article class="sp-article">{body_html}</article>
  </main>
</div>
</body>
</html>"""


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def detect_lang(input_path):
    name = Path(input_path).name
    return "ja" if ".ja." in name else "en"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        sys.stderr.write(
            "usage: python3 docs/build_readme_html.py <input.md> <output.html>\n"
        )
        return 2
    in_path, out_path = argv
    lang = detect_lang(in_path)
    ui = UI[lang]

    md_text = Path(in_path).read_text(encoding="utf-8")
    full_html = convert_markdown(md_text)

    hero_html, body_html = split_hero_and_body(full_html)
    body_html = replace_mermaid_with_svg(body_html, lang)
    body_html = kbdify(body_html)
    hero_html = kbdify(hero_html)
    body_html = wrap_tables(body_html)

    # Wrap the flow-diagram SVG (now sitting bare in body_html) in a div for
    # spacing; it was inserted verbatim by replace_mermaid_with_svg above.
    body_html = re.sub(
        r'(<svg class="sp-flow-svg".*?</svg>)',
        r'<div class="sp-flow-wrap">\1</div>',
        body_html,
        flags=re.DOTALL,
    )

    toc_items = build_toc(body_html)
    title_text = extract_h1_text(hero_html)

    page = build_page(lang, title_text, hero_html, body_html, toc_items, ui)
    Path(out_path).write_text(page, encoding="utf-8")
    print(f"wrote {out_path} (lang={lang}, sections={len(toc_items)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
