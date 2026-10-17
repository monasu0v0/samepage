# samepage — design notes

> *Get on the same page with your AI — literally.*

samepage is a removable review layer for static HTML. A human opens the page,
anchors comments to text ranges / elements / insertion points / SVG diagram
nodes / the whole document, and exports structured JSON. An AI agent applies
the feedback to the **source** (not the HTML), replies with a responses JSON,
and can plant question pins for the human to answer on the same page. When
everything is resolved, `--finalize` strips the layer and produces the
publishable HTML.

For the full technical specification and architecture decision records, see:
- [Specification (English)](specification.md) / [仕様書 (日本語)](specification.ja.md)
- [Architecture Decision Records (`docs/adr/`)](adr/README.md)

## Repository layout

```text
plugin.json               manifest for Google Antigravity
.claude-plugin/
  plugin.json             manifest for Claude Code
AGENTS.md / CLAUDE.md     project rules for AI coding agents
rules/
  AGENTS.md               plugin-bundled agent rules (referenced by plugin.json)
samepage/                 Python package (also runnable as a script)
  cli.py                  entry point: python3 samepage/cli.py <html> [options]
  assets.py               builds the injected block from assets/
  assets/
    samepage.js           review layer runtime (vanilla JS, no deps)
    samepage.css          review layer styles
    panel.html            panel / popup markup injected into <body>
skills/
  samepage/SKILL.md       inject a review layer into an existing HTML file
  grill-on-samepage/SKILL.md
                          run a grilling session on an ALIGNMENT document
tests/                    pytest (+ playwright browser tests)
docs/                     design notes, specifications, ADRs, and builders
  specification.md        complete system specification (English)
  specification.ja.md     complete system specification (Japanese)
  adr/                    Architecture Decision Records (ADR 0001-0005)
  build_readme_html.py    README.md -> README.html
  build_alignment_html.py ALIGNMENT .md -> .html, and INDEX.md
  alignment/              ALIGNMENT documents: the agreed design decisions
  demo/                   demo HTML pages used for generating the demo GIF
  images/                 generated demo assets (e.g. demo.gif)
README.md / README.ja.md
```

The repository ships manifests and skill layouts that work out-of-the-box across
**Google Antigravity**, **Claude Code**, and any agent supporting `SKILL.md`:

- **Google Antigravity**: Clone into `~/.gemini/config/plugins/samepage` (global plugin) or `.agents/plugins/samepage` (workspace plugin), or copy/link `skills/*` into `.agents/skills/`. Antigravity discovers `plugin.json` and automatically loads `skills/samepage/SKILL.md` and `skills/grill-on-samepage/SKILL.md`.
- **Claude Code**: Clone into `~/.claude/skills/samepage`. The `.claude-plugin/plugin.json` manifest loads the folder as `samepage@skills-dir`.
- **Other Agents (Codex, Cursor, etc.)**: Point the agent at `skills/samepage/SKILL.md` and `skills/grill-on-samepage/SKILL.md`, which resolve `samepage/cli.py` relative to their own directory (`../../samepage/cli.py`).

## Naming (fixed — do not deviate)

| Concept | Name |
|---|---|
| Project / CLI / plugin name | `samepage` (PyPI distribution name in `pyproject.toml`: `same-page`) |
| Skill names | `samepage`, `grill-on-samepage` |
| ALIGNMENT document / its index | `docs/alignment/NNNN-slug.md`, `docs/alignment/INDEX.md` |
| HTML marker comments (idempotent block) | `<!-- samepage:begin -->` … `<!-- samepage:end -->` |
| Unit attributes (set by CLI) | `data-sp-unit`, `data-sp-label`, `data-sp-index` |
| Diagram node attributes (set by generator) | `data-sp-node`, `data-sp-label` |
| Discussion block (stripped by finalize) | `data-sp-discussion` |
| Runtime badge/action attrs | `data-sp-badge`, `data-sp-action` |
| Runtime decoration attrs (stripped by finalize) | `data-sp-q-id`, `data-sp-cmt-id`, `data-sp-resp-id` |
| Config globals | `window.SAMEPAGE_CONFIG`, `window.SAMEPAGE_RESPONSES`, `window.SAMEPAGE_QUESTIONS` |
| localStorage key | `samepage:<doc>` (config field `storageKey`) |
| CSS class / id prefix | `sp-` (e.g. `sp-panel`, `sp-mark`, `sp-qpin`, `sp-node-halo`) |
| Export JSON `_skill` | `"samepage"` |
| Export JSON `_howto` / `_rules` | English text (rules table in `skills/samepage/SKILL.md` is the source of truth) |
| Finalized output default | `<stem>.final.html` |

Keyboard shortcuts are unchanged: `a` add comment, `e` element pick,
`↑`/`↓` widen/narrow pick, `c` toggle panel, `j` copy JSON.

## JSON contracts

Defined in `skills/samepage/SKILL.md` §4 (export), §6 (responses), §7 (questions)
and formalized in `docs/specification.md` §6. Field names (`targets[].kind` =
`text-range` | `element` | `insertion-point` | `diagram-node` | `document`,
`action`, `status`, `answers`, …) are fixed.

## Non-goals

- The CLI does no Markdown → HTML conversion. It only ever injects into, or
  strips from, HTML it is handed. (The `docs/` builders do convert Markdown,
  but they are separate scripts for two specific documents — the README and
  ALIGNMENT documents — and are not part of the CLI or the skills.)
- No server. Everything runs from `file://`.
- The CLI never adds `data-sp-node` to SVG automatically (only the generator
  knows the semantic unit).
