# samepage

*Get on the same page with your AI — literally.*

[日本語版 README はこちら](README.ja.md)

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Zero runtime dependencies](https://img.shields.io/badge/runtime%20deps-none-brightgreen.svg)

![samepage demo: comment on the rendered page, export JSON, get replies and question pins](docs/images/demo.gif)

*Select text or an element, comment, press `j` — the JSON goes straight to your agent; replies
and question pins come back onto the same page.*

> The "Release notes" document in the demo is fictional sample content written for this
> repository, as are the HTML files under `docs/demo/` and `tests/fixtures/`. They describe no
> real product, project or organization.

## Why

Even when an AI produces the HTML deliverable, "review" usually still means describing the
location in chat and asking for a fix. samepage lets the human comment directly on the rendered
page instead, and hands the AI structured JSON so it fixes the *original* (the source, if the
HTML is generated) and writes replies and its own questions back onto the same page. Once there
is consensus, a clean, publishable HTML with the review layer stripped is produced.

## What it is

samepage is a removable review layer that lets a human and an AI agent look at, and negotiate
over, the same HTML document. Instead of the usual one-shot "AI writes it, human reads it" flow,
samepage turns review into a back-and-forth: the human comments directly on the rendered page,
the AI receives that feedback as structured JSON, and applies it to the *original*. If the HTML
itself is the original — hand-written, with nothing it was generated from — the AI edits that
HTML directly. If the HTML is a generated artifact (built from a Markdown file, a Marp deck, an
intent-doc IR, and so on), the AI edits the source it came from and regenerates the HTML, since a
fix made only to the HTML is lost on the next regeneration. Either way, it writes back what it
did — including, when it isn't sure how to proceed, questions of its own for the human to answer
on the same page. The loop repeats until everyone agrees, at which point the review layer is
stripped out and a clean, publishable HTML is produced.

It works on any static HTML, requires no server (everything runs from `file://`), and adds no
runtime dependencies — a human only ever needs a browser and clipboard access.

## How it works

```mermaid
flowchart LR
    A[Human: opens injected HTML,<br/>selects text / elements,<br/>writes comments] -->|comment JSON<br/>copy → j| B[AI agent]
    B -->|"fixes the original<br/>(source, if generated)"| C[Regenerate HTML]
    C -->|--responses<br/>--questions| D[Human: sees replies,<br/>answers question pins]
    D -->|more comments,<br/>or all resolved| E{Consensus?}
    E -->|not yet| A
    E -->|yes| F[--finalize:<br/>publishable HTML,<br/>review layer stripped]
```

- **Human → AI**: comments, anchored to a text range, an element, an insertion point between
  elements, a node inside an SVG diagram, or the whole document. Exported as one self-contained
  JSON, pasted straight into the agent's chat.
- **Original vs. generated**: before editing, check whether this HTML is the original or a
  generated artifact — look for a same-named source file next to it (e.g. a `.md` beside the
  `sourceHtml` path), or for a "Generated from ..." marker inside the HTML itself.
- **AI → human**: a responses JSON (what was fixed / declined / left as-is, and why) and, when the
  agent needs a decision it can't make on its own, question pins that show up directly on the
  page for the human to answer.
- **Consensus → finalize**: once every comment is resolved, `--finalize` produces a separate,
  clean HTML with the review layer and any discussion blocks removed — the one you actually ship.

## How it compares

samepage isn't trying to replace these — it fills the gap where a human needs to review a
rendered artifact and an AI agent needs to act on that review.

| | samepage | Google Docs / Notion comments | GitHub PR review | Web annotation (Hypothesis etc.) |
|---|---|---|---|---|
| What you comment on | any static HTML, as rendered | the service's own documents | a text diff | any web page |
| Server / account | none | required | required | required |
| Handing feedback to an AI | one self-contained JSON, pasted into chat | manual copy, without a dedicated integration | manual copy, without a dedicated integration | manual copy, without a dedicated integration |
| AI → human questions | question pins on the same page | comment replies | comment replies | comment replies |
| Where fixes land | the original — the source, if generated | the document itself | the document itself | — |
| Publishable output | `--finalize` strips the layer | — | — | — |

## Try it on this README

[`README.html`](README.html) is this page rendered as HTML with the samepage review layer already
injected — the tool applied to its own documentation. The Japanese page is
[`README.ja.html`](README.ja.html).

```bash
git clone https://github.com/monasu0v0/samepage.git
cd samepage
open README.html     # or: start / xdg-open. GitHub shows .html as source, so open it locally
```

Want more detail than this README gives, or a section rewritten for your situation? Comment on it
directly: select the passage, press `a`, and say what you want — *"explain this for someone who
has never used a coding agent"*, *"shorten this table"*, *"add a Windows example"*. Press `j`,
paste the JSON into a coding agent running in your clone, and it will rewrite `README.md` (and
`README.ja.md`) to answer you and rebuild the HTML. The result is your own README, shaped by the
questions you actually had.

## Quick start

```bash
git clone https://github.com/monasu0v0/samepage.git
cd samepage
python3 samepage/cli.py your-doc.html --unit-selector body --label-format "Whole"
open your-doc.html            # or: start / xdg-open
```

Then, in the browser:

1. Select text and press `a` (or click 💬) to add a comment. Press `e` to pick an element, an
   insertion point, or a diagram node instead of a text range.
2. Press `c` to open the comment panel, then `j` — or click the panel's "📋 Copy JSON" button —
   to copy the export JSON to the clipboard.
3. Paste that JSON into your coding agent's chat. It carries its own instructions, so a plain
   paste — with no extra explanation — is enough for the agent to act on it.

## Requirements

| Side | Needs |
|---|---|
| Injecting (agent / developer) | Python 3.9+ — no third-party packages |
| Reviewing (human) | A modern browser that opens `file://` HTML (Chrome, Firefox, Safari, Edge) and clipboard access. No server, extension or account |
| Optional | Playwright — for the browser tests and for regenerating the demo GIF; Pillow — only for `docs/build_demo_gif.py`; the `markdown` package — only for `docs/build_readme_html.py` and `docs/build_alignment_html.py` |

## Install as an AI Agent Skill (Antigravity / Claude Code / Other Agents)

The repository carries both a root `plugin.json` (for Google Antigravity) and a
`.claude-plugin/plugin.json` (for Claude Code), plus standard `skills/<name>/SKILL.md` definitions
and `AGENTS.md` rules. A single clone ships both skills with no marketplace and no extra install step:

```bash
# Google Antigravity (global plugin)
git clone https://github.com/monasu0v0/samepage.git ~/.gemini/config/plugins/samepage

# Google Antigravity (workspace-scoped plugin)
git clone https://github.com/monasu0v0/samepage.git .agents/plugins/samepage

# Claude Code
git clone https://github.com/monasu0v0/samepage.git ~/.claude/skills/samepage
```

For other coding agents (Codex, Cursor, etc.) that support `SKILL.md` or `AGENTS.md`, clone the
repository into your agent's skills directory or point it at `skills/samepage/SKILL.md` and
`skills/grill-on-samepage/SKILL.md`.

| Skill | Use it for |
|---|---|
| `samepage` | Injecting the review layer into an existing HTML file. Say "make this reviewable" or "let people comment on this HTML" |
| `grill-on-samepage` | Settling a design *before* code exists. It interviews you on a samepage page in rounds, and the agreed document becomes the project's source of truth. Say "let's nail down the design first" |

`skills/samepage/SKILL.md` and `skills/grill-on-samepage/SKILL.md` define the full behavior each
one follows.

## CLI reference

```
python3 samepage/cli.py <input.html> [options]
```

| Option | Description |
|---|---|
| `<input>` | Input HTML file (positional, required) |
| `--unit-selector SEL` | Selector for "unit" elements comments attach a label/index to (`tag`, `.class`, `#id`, or `tag.class`). Omit to skip unit labeling |
| `--label-format FMT` | Label template; `{n}` expands to the 1-based ordinal. Default `{n}` |
| `--doc-id ID` | Document identifier used as the JSON `doc` field and the localStorage key. Default: the input file's stem |
| `--jump {scroll,hash}` | How the comment list jumps to a unit: smooth-scroll, or set `location.hash`. Default `scroll` |
| `--out PATH` | Output path. Default: overwrite the input in place |
| `--responses PATH` | Responses JSON to embed (replies to review comments) |
| `--questions PATH` | Questions JSON to embed (question pins) |
| `--no-source-path` | Embed the injected page's `sourcePath` config value as `null` instead of an absolute path — use this for anything you distribute |
| `--finalize` | Write a publishable HTML with the review layer and discussion blocks removed, to a separate file. Cannot combine with `--unit-selector`/`--responses`/`--questions` |
| `--comments PATH` | Comments JSON checked for unresolved (`open`) items before finalizing |
| `--force` | Finalize even if `--comments` reports unresolved items |

Re-running injection on an already-injected file replaces the layer in place (idempotent). Passing
neither `--responses` nor `--questions` on a re-injection clears whichever of those layers was
previously embedded — only the most recently injected set is ever shown.

## Target kinds

Every comment or question target has a `kind`:

| kind | Points at | Key fields |
|---|---|---|
| `text-range` | A selected run of text | `selectedText`, `contextBefore`, `contextAfter` |
| `element` | An element itself | `path` (nth-of-type chain), `tag`, `nearText` |
| `insertion-point` | The gap right before/after an element | `afterPath`, `beforePath`, `nearText`, `afterTag`, `beforeTag` |
| `diagram-node` | A node inside an SVG diagram tagged with `data-sp-node` | `nodeId`, `nodeLabel`, `nearText` |
| `document` | The document as a whole | (none) |

Full field-by-field resolution rules, including fallback order when a `path` or `nodeId` no
longer matches, live in `skills/samepage/SKILL.md` §4.

## For document generators

A generator that produces HTML with an embedded SVG diagram can make individual diagram nodes
directly commentable by tagging the semantic `<g>` for each node:

```html
<g data-sp-node="spec-07" data-sp-label="Audit log is append-only">
  <rect .../>
  <text>Audit log is append-only</text>
</g>
```

- `data-sp-node` must be the **same stable id used in the source that generated the diagram**
  (an IR node id, a logical identifier — not a layout-derived `g1`, `g2`, ...), so it survives
  regeneration even when the layout changes.
- `data-sp-label` should hold the node's display name, used as a fallback and shown in the panel.
- To make an edge/arrow pickable, wrap it in its own `<g data-sp-node="...">` together with a
  transparent, wide hit-path overlaying the visible line.

A discussion block that shouldn't survive into the published output — draft notes, an options
comparison, anything meant only for the review round — is tagged with `data-sp-discussion`. Once
the review is resolved, `--finalize` removes it along with the rest of the review layer:

```html
<div data-sp-discussion>Notes under discussion. Removed by --finalize.</div>
```

See `skills/samepage/SKILL.md` §7.5 and §8 for the complete conventions.

## Privacy note

By default, the injected page embeds the absolute path to the file the layer was injected into, so
a session that only receives the exported comment JSON can still find the file. The path travels
under two different names, which are easy to mix up: in the page it is the `sourcePath` key of the
embedded config; in the exported JSON it is copied out as the `sourceHtml` field. Both exist, and
they hold the same path.

If you're distributing the HTML itself (attaching it to a README, sharing it outside your own
machine, etc.), pass `--no-source-path`: `sourcePath` is then embedded as `null` instead of a local
filesystem path, and the exported `sourceHtml` comes out `null` too.

## FAQ

**Q. How do I tell whether an HTML file is the original or a generated artifact?**
Look for a same-named source file next to it (e.g. a `.md` beside the path in `sourceHtml`), or
for a "Generated from ..." marker inside the HTML itself. If it's the original, edit the HTML
directly; if it's generated, edit the source and regenerate (skills/samepage/SKILL.md §4, rule 1).

**Q. I regenerated the HTML and a comment's `path` no longer matches — is the comment lost?**
No. `element` and `insertion-point` targets fall back automatically: `element` falls back from
`path` to a nearby match using `tag` + `nearText` (the first 60 chars of the element's text);
`insertion-point` falls back from `afterPath` to `afterTag`+`nearText`, and if that also fails,
resolves from the `beforePath`/`beforeTag` side instead. `diagram-node` falls back from `nodeId`
to `nodeLabel`, then to `nearText`. See skills/samepage/SKILL.md §4.

**Q. Where are comments stored?**
In the browser's `localStorage`, under the key `samepage:<doc>` — per browser profile, not synced
anywhere. The exported JSON is the durable record; `--doc-id` controls the `<doc>` part of that
key (default: the input file's stem).

**Q. What happens if I inject into an already-injected file?**
Re-running injection replaces the layer in place (idempotent). Omitting `--responses` and/or
`--questions` on a re-injection clears whichever of those layers was previously embedded — only
the most recently injected set is ever shown.

**Q. Why can't I comment on a node in my SVG diagram?**
Because the generator that produced the diagram hasn't tagged its nodes with `data-sp-node` — the
CLI never adds this attribute automatically; only the generator knows the semantic unit. See "For
document generators" above and `skills/samepage/SKILL.md` §7.5.

**Q. `--finalize` refuses because of unresolved comments — what now?**
Pass a `--comments` file: it reports any `open` items and aborts. Either resolve them in the
review, or pass `--force` to finalize anyway. Finalized output defaults to `<stem>.final.html`
(override with `--out`); the input HTML is left unchanged.

## Development

```bash
python3 -m pytest
```

Browser-driven tests (`tests/test_browser.py`) additionally require Playwright
(`pip install playwright && playwright install chromium`); they're skipped automatically if
Playwright isn't available. The builder tests (`tests/test_alignment_builder.py`) skip the same
way without the `markdown` package.

The generated files are rebuilt with:

```bash
pip install markdown
python3 docs/build_readme_html.py README.md README.html
python3 docs/build_readme_html.py README.ja.md README.ja.html
python3 samepage/cli.py README.html --unit-selector body \
    --label-format "Whole" --doc-id readme-en --no-source-path
python3 samepage/cli.py README.ja.html --unit-selector body \
    --label-format "全体" --doc-id readme-ja --no-source-path
for md in docs/alignment/*.md; do
    [ "$(basename "$md")" = "INDEX.md" ] && continue
    python3 docs/build_alignment_html.py "$md"
    python3 samepage/cli.py "${md%.md}.html" --finalize --out "${md%.md}.final.html"
done
python3 docs/build_alignment_html.py --index docs/alignment
```

CI runs exactly this and fails if any generated file is out of date, so `--no-source-path` is not
optional: without it your absolute path ends up committed.

## Contributing

Issues and PRs are welcome. For a bug report, attach the pre-injection HTML (or a minimal repro)
and the exported comment JSON.

Development happens on `develop`; `main` is the release branch and is merged by the maintainer
only. Open PRs against `develop`.

Run `python3 -m pytest` before opening a PR (browser tests run when Playwright is installed,
otherwise they're skipped).

Naming (the `sp-` CSS prefix, `data-sp-*` attributes, marker comments) and contracts are fixed — see
[`docs/specification.md`](docs/specification.md), [`docs/design.md`](docs/design.md), and the
Architecture Decision Records in [`docs/adr/`](docs/adr/README.md).

To rebuild the demo: `python3 docs/build_demo_gif.py`.

`README.html` / `README.ja.html` and the HTML under `docs/alignment/` are tracked, so rebuild them
after any change to the `.md` they come from. Use the command sequence in "Development" above
verbatim — it is what CI checks against, and `--no-source-path` is not optional there: without it
the absolute path of your own machine is baked into the committed HTML.

## Credits

The `grill-on-samepage` skill borrows its interview vocabulary — the design tree, the frontier,
asking in rounds, the split between facts and decisions — from the `grilling` skill in
[mattpocock/skills](https://github.com/mattpocock/skills) (MIT); the implementation here is
independent, not a fork.

## License

MIT — see `LICENSE`.
