# samepage Specification

> Version: 0.1.0  
> Author: monasu0v0 (<monasu0v0@gmail.com>)  
> [日本語版仕様書はこちら](specification.ja.md)

## 1. Overview & Scope

**samepage** is a removable, serverless review-comment layer for static HTML documents and an interactive design-alignment loop (`grill-on-samepage`) built on top of it.

It enables a bidirectional negotiation workflow between a human reviewer and an AI coding agent (such as Google Antigravity, Claude Code, Codex, Cursor, or any CLI/IDE agent):

1. **Human → AI**: The human opens an HTML document over `file://`, anchors comments to specific text ranges, DOM elements, insertion points, SVG diagram nodes, or the document as a whole, answers embedded question pins, and exports a single self-contained JSON payload to the clipboard.
2. **AI → Source**: The AI agent resolves the targets against the **original source** (editing the Markdown/IR/template and regenerating if the HTML is a generated artifact, or editing the HTML directly if hand-written).
3. **AI → Human**: The AI embeds structured replies (`--responses`) and/or reverse confirmation pins (`--questions`) back into the HTML.
4. **Consensus → Finalize**: Once all comments are resolved and all design decisions are settled, `--finalize` strips the review layer, runtime decorations, and discussion blocks (`data-sp-discussion`) to produce a clean, publishable HTML file.

---

## 2. Core Architectural Principles

1. **Zero Runtime Dependencies**: The CLI (`samepage/cli.py` and `samepage/assets.py`) uses only the Python 3.9+ standard library. The browser runtime (`samepage.js`, `samepage.css`, `panel.html`) uses vanilla ES5-compatible JavaScript (wrapped in an IIFE) and self-contained CSS with zero external assets or CDN requests.
2. **Serverless (`file://` First)**: Everything operates directly from the local filesystem (`file://`) using `localStorage` and the browser Clipboard API (with an off-screen `<textarea>` + `document.execCommand('copy')` fallback). No local HTTP server, browser extension, or cloud account is required.
3. **Byte-Preserving Surgical HTML Manipulation**: Re-serializing HTML through a DOM parser corrupts raw `<script>` contents, whitespace, and character entities. `samepage` uses `html.parser.HTMLParser` (`convert_charrefs=False`) strictly to record character offsets of start and end tags, and performs all injections and removals via reverse-order string slicing. Untouched spans remain byte-for-byte identical to the input.
4. **Self-Contained Handoff Contract**: Exported JSON includes a self-describing header (`_howto`, `_skill`, `_rules`, `sourceHtml`) so that any AI agent can execute the workflow accurately even in a fresh session without prior context.

---

## 3. CLI Specification (`samepage/cli.py` & `samepage/assets.py`)

### 3.1 Invocation & Arguments

```text
python3 samepage/cli.py <input> [options]
```

| Argument / Option | Type | Default | Description |
|---|---|---|---|
| `input` | Positional | (Required) | Path to the target HTML file. |
| `--unit-selector SEL` | String | `None` | Simple selector (`tag`, `.class`, `#id`, or `tag.class`) to label unit elements with `data-sp-unit`, `data-sp-label`, and `data-sp-index`. |
| `--label-format FMT` | String | `"{n}"` | Label template for matched units (`{n}` expands to the 1-based ordinal). |
| `--doc-id ID` | String | `<input.stem>` | Document identifier used for `doc` in JSON and `localStorage` keys (`samepage:<doc>` and `samepage-answers:<doc>`). |
| `--jump {scroll,hash}` | Enum | `"scroll"` | Navigation mode when clicking a comment item: `"scroll"` (`scrollIntoView`) or `"hash"` (`location.hash = '#' + index`). |
| `--out PATH` | Path | `<input>` (or `<stem>.final.html` for `--finalize`) | Output file path. |
| `--responses PATH` | Path | `None` | Path to a validated responses JSON file to embed as `window.SAMEPAGE_RESPONSES`. |
| `--questions PATH` | Path | `None` | Path to a validated questions JSON file to embed as `window.SAMEPAGE_QUESTIONS`. |
| `--no-source-path` | Flag | `False` | Embeds `sourcePath: null` instead of `out_html.resolve()` (mandatory for distributed/committed HTML). |
| `--finalize` | Flag | `False` | Strips the review layer, runtime decorations, and `data-sp-discussion` elements into a clean publishable HTML. Mutually exclusive with `--unit-selector`, `--responses`, and `--questions`. |
| `--comments PATH` | Path | `None` | Comments export JSON checked during `--finalize` to block finalization if any comment has `status == "open"`. |
| `--force` | Flag | `False` | Proceeds with `--finalize` even when `--comments` contains unresolved (`open`) comments. |

### 3.2 Selector Parsing & Unit Attribute Injection

`parse_selector(selector)` accepts only four simple selector forms (`tag`, `.class`, `#id`, `tag.class`) validated via two exact regular expressions:

```python
SIMPLE_SELECTOR = re.compile(r"^(?:([a-zA-Z][\w-]*))?(?:\.([\w-]+))?$")
ID_SELECTOR = re.compile(r"^#([\w-]+)$")
```

- If `ID_SELECTOR` matches, returns `(None, None, elem_id)`.
- Else if `SIMPLE_SELECTOR` matches and at least one of group 1 (`tag`) or group 2 (`cls`) is non-empty, returns `(tag, cls, None)`.
- Otherwise raises `ValueError("unsupported selector: ... (only tag / .class / #id / tag.class)")`.

`_TagSpanCollector` (subclassing `HTMLParser(convert_charrefs=False)`) computes 0-based character offsets from `(line, col)` via `self.line_offsets` and records every matching start tag as `{"start": start, "end": start + len(text), "attrs": attrd}`:
- Tag match: `tag == want_tag` (when `want_tag` is set).
- Class match: `want_cls in attrd.get("class", "").split()` (whitespace-tokenized).
- ID match: `attrd.get("id") == want_id`.

`add_unit_attrs(html, selector, label_format="{n}")` iterates over matched start tags with 1-based ordinal `n` (`enumerate(hits, start=1)`):
- **Idempotency & Ordinal Preservation**: If `"data-sp-unit"` is already present in `hit["attrs"]`, the element is skipped, **but its ordinal `n` is still consumed** so numbering stays aligned with host-side hash navigation.
- **Attribute Values**:
  - `unit = hit["attrs"].get("id") or f"u{n}"`
  - `label = label_format.replace("{n}", str(n))`
  - `index = str(n)`
  - Escaped via `_attr_escape(value)` (`&` → `&amp;`, `"` → `&quot;`, `<` → `&lt;`, `>` → `&gt;`).
- **Insertion Offset**: Inserted immediately before the closing `>` or `/>` of the start tag (`offset = hit["end"] - (2 if tag_text.endswith("/>") else 1)`), applied in reverse offset order (`sorted(inserts, reverse=True)`).

### 3.3 Input JSON Validation Contracts

```python
VALID_ACTIONS = ("fixed", "declined", "partial", "noted")
VALID_TARGET_KINDS = ("text-range", "element", "insertion-point", "diagram-node", "document")
```

- **`load_responses(path)`**:
  - Top-level value must be a `dict` containing a `"responses"` `list`.
  - Every item `r` in `"responses"` must be a `dict` where `r["id"]` and `r["reply"]` are non-empty strings (`isinstance(v, str) and v.strip()`).
  - `r.get("action")` defaults to `"fixed"` if `None`; otherwise must be in `VALID_ACTIONS`.
  - `r.get("fixedText")` must be `None` or `str`.
- **`load_questions(path)`**:
  - Top-level value must be a `dict` containing a `"questions"` `list`.
  - Every item `q` in `"questions"` must be a `dict` where `q["id"]` and `q["question"]` are non-empty strings.
  - `q.get("target")`, if not `None`, must be a `dict` with `target.get("kind") in VALID_TARGET_KINDS`. When `kind == "diagram-node"`, `target.get("nodeId")` is required and must be a non-empty string.
  - `q.get("choices")`, if not `None`, must be a `list` of `str`.
- **`collect_open_comments(path)`**:
  - Top-level value must be a `dict` containing a `"comments"` `list`.
  - Returns `[c.get("id", "?") for c in data["comments"] if isinstance(c, dict) and c.get("status") == "open"]`.

### 3.4 Exit Codes & Refusal Conditions

- **`0`**: Operation succeeded.
- **`2`**: Refusal or validation error:
  - Input HTML, `--responses`, `--questions`, or `--comments` file does not exist or fails UTF-8 decoding (`UnicodeDecodeError`).
  - No `</body>` closing tag exists in the HTML during initial injection (`html.rfind("</body>") < 0`).
  - Only one of `<!-- samepage:begin -->` or `<!-- samepage:end -->` is present (`has_begin != has_end`, indicating manual corruption).
  - `--unit-selector` is syntactically unsupported or matches `0` elements.
  - JSON validation (`load_responses`, `load_questions`, `collect_open_comments`) raises `ValueError`.
  - `--finalize` is combined with any injection option (`--unit-selector`, `--responses`, `--questions`).
  - `--finalize --comments <file>` finds one or more comments with `status == "open"` and `--force` is not set. (If `--comments` is omitted during `--finalize`, a warning is printed to `stderr` and finalization proceeds.)

### 3.5 Atomic File Writing & Permissions

All file writes use `_write_atomic(path, text)`:
1. Creates a temporary file (`suffix=".sp-tmp"`) in `path.parent` via `tempfile.mkstemp`.
2. Writes UTF-8 text to the file descriptor.
3. If `path.exists()`, copies the existing file's permissions via `shutil.copymode(str(path), tmp)`.
4. If creating a brand-new file (e.g., `<stem>.final.html`), queries the process umask (`umask = os.umask(0); os.umask(umask)`) and applies `os.chmod(tmp, 0o666 & ~umask)` so the output is readable according to standard umask rules instead of `mkstemp`'s `0600`.
5. Atomically replaces the target via `os.replace(tmp, str(path))` (unlinking `tmp` on any exception).

---

## 4. HTML Injection & DOM Contract

### 4.1 Reserved Namespaces & Attributes

| Attribute / Token | Set By | Purpose | Stripped by `--finalize`? |
|---|---|---|---|
| `<!-- samepage:begin -->` … `<!-- samepage:end -->` | CLI (`assets.py`) | Delimits the idempotent injected review-layer block right before `</body>`. | Yes (entire block + trailing `\n`) |
| `data-sp-unit`, `data-sp-label`, `data-sp-index` | CLI (`--unit-selector`) | Identifies reviewable unit containers and their 1-based ordinal. | Yes |
| `data-sp-node`, `data-sp-label` | Document Generator | Identifies semantic nodes (`<g>`) inside inline SVG diagrams. | Yes |
| `data-sp-discussion` | Author / Generator | Marks working notes, option comparisons, or 残件 blocks that must not appear in published HTML. | Yes (element + contents) |
| `data-sp-cmt-id`, `data-sp-resp-id`, `data-sp-q-id` | Runtime (`samepage.js`) | Links DOM highlights/pins/panel items to comment, response, or question IDs. | Yes |
| `data-sp-badge`, `data-sp-action` | Runtime / UI | Stores target index badges (`1`, `2`, rendered via CSS `::before`) and verb palette actions. | Yes |
| `mark.sp-mark`, `mark.sp-mark-fixed` | Runtime (`samepage.js`) | Text-range highlight wrappers (`.sp-mark-resolved` added when resolved). | Unwrapped (inner text kept) |
| `.sp-qpin`, `.sp-qpin-svg`, `.sp-insert-mark`, `.sp-node-halo` | Runtime (`samepage.js`) | Question pins, insertion-point bars, and SVG node halos (`.sp-node-halo-resolved`, `.sp-qpin-answered`). | Removed with contents |
| `.sp-mark-el` | Runtime (`samepage.js`) | Class token added to element-level targets. | Class token removed |

### 4.2 Block Assembly & Safe Inline JSON Embedding (`samepage/assets.py`)

`assets.render_block(doc_id, jump="scroll", storage_key=None, responses=None, questions=None, source_path=None)` validates `doc_id` (non-empty) and `jump in ("scroll", "hash")`, then builds the injection block in exact order:
1. `<!-- samepage:begin -->`
2. `<style>\n{samepage.css}\n</style>`
3. `{panel.html}`
4. `<script>window.SAMEPAGE_CONFIG={_embed_json(config)};</script>` where `config` is:
   ```json
   {
     "doc": "<doc_id>",
     "jump": "scroll | hash",
     "storageKey": "<storage_key or 'samepage:' + doc_id>",
     "sourcePath": "<str(source_path) or null>"
   }
   ```
5. Optional: `<script>window.SAMEPAGE_RESPONSES={_embed_json(responses)};</script>` (when `responses is not None`).
6. Optional: `<script>window.SAMEPAGE_QUESTIONS={_embed_json(questions)};</script>` (when `questions is not None`).
7. `<script>\n{samepage.js}\n</script>`
8. `<!-- samepage:end -->\n`

**Script-Tag Safety**:
- `_read_asset(name)` verifies `"</script" not in text.lower()` before inlining any asset file.
- `_embed_json(value)` serializes via `json.dumps(value, ensure_ascii=False).replace("</", "<\\/")` so free-form text containing `</script>` cannot prematurely close the inline `<script>` tag.
- `inject_block(html, block)` replaces the existing span from `MARKER_BEGIN` through `MARKER_END` (using `block.rstrip("\n")`) if both markers exist, or inserts `block` right before the last `</body>` (`html.rfind("</body>")`).

---

## 5. Browser Runtime & Target Resolution (`samepage.js`)

### 5.1 Initialization Order & `localStorage` Keys

- **Storage Keys**:
  - Comments: `STORAGE_KEY = CFG.storageKey || "samepage:default"` (CLI default: `"samepage:" + doc_id`).
  - Question Answers: `ANSWERS_KEY = "samepage-answers:" + DOC_ID`.
- **`init()` Execution Order**:
  1. Load comments from `localStorage`, normalize via `normalizeComment(c)` (converting legacy single-target comments without `targets[]` into a 1-element `targets` array with `label: "1", kind: "text-range"`), and anchor each target via `anchorTarget(c, t)`.
  2. Anchor each embedded response via `anchorResponse(r)`.
  3. Load question answers from `localStorage` and anchor each embedded question pin via `anchorQuestion(q)`. **Critical ordering constraint**: `anchorQuestion` for `text-range` targets mutates text nodes via `splitText()`, so it must run *after* comments and responses are anchored to avoid shifting `buildFlatMap` character offsets.
  4. Call `refreshQuestionPins()`, `renderQuestions()`, and `renderPanel()`.

### 5.2 Keyboard Shortcuts, IME Guard & Host Isolation

All keyboard handling runs in a document-level `keydown` capture listener (`useCapture = true`):
- **IME Composition Guard**: `isImeComposing(e)` returns `true` if `imeComposing` (tracked via capture listeners on `compositionstart` / `compositionend`), `e.isComposing === true`, or `e.keyCode === 229`.
- **Modal & Input Suppression**:
  - When `#spJsonModal` is open (`isJsonModalOpen()`), all `keydown` events call `e.stopPropagation()`, and `Escape` closes the modal.
  - When focus is inside `TEXTAREA` or `INPUT`, `e.stopPropagation()` prevents host-page shortcuts from firing. Inside `#spPopupText` or `.sp-edit-textarea` (when not IME-composing), `Enter` (without `Shift`) saves/commits and `Escape` cancels.
- **Single-Key Shortcuts** (active when not inside `TEXTAREA`/`INPUT`, modal closed, and no `ctrlKey`/`metaKey`/`altKey`):
  - `a` / `A`: If `pendingSelection` exists, adds it as a `text-range` target and opens the comment popup.
  - `e` / `E`: Starts DevTools-style element-pick mode (`startPickMode`). If the popup is already open (`popupOpen`), hides it (`visibility: 'hidden'`) while picking so another target can be added to the same comment, and restores visibility on pick or `Escape`.
  - `c` / `C`: Toggles the right-hand comment & question panel (`#spPanel.open`).
  - `j` / `J`: Copies the export JSON directly to the clipboard (`copyJsonDirect`) and flashes `"✓ Copied"` (or `"No comments yet"`) for `1500ms` on both `#spBadge` and `#spJsonCopyDirect`.
- **Host Click Guard**: A document-level `click` capture listener suppresses click propagation (`e.stopPropagation()`) whenever a non-empty text selection exists outside the samepage UI, preventing slide decks or host apps from advancing on mouseup/click after selecting text.

### 5.3 Five Target Kinds & Exact Resolution / Fallback Chains

A single comment may contain one or more targets in `targets[]` (labeled `"1"`, `"2"`, … and displayed with circled numerals `①`–`⑨` when `targets.length > 1`).

#### 1. `text-range`
- **Creation**: On `mouseup` outside samepage UI when `window.getSelection().toString().trim()` is non-empty and the selection's `startContainer` is inside a `[data-sp-unit]` element.
  - `buildFlatMap(unitEl)` walks all descendant text nodes via `document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false)` and concatenates their raw `nodeValue` (without whitespace normalization) into `{text, nodes, offsets}`.
  - `contextBefore` is `map.text.slice(Math.max(0, startFlat - 40), startFlat)` (up to 40 chars before).
  - `contextAfter` is `map.text.slice(endFlat, endFlat + 40)` (up to 40 chars after).
  - If `popupOpen` is already `true`, the selection is immediately appended to `pendingTargets` as an additional target; otherwise `#spSelectBtn` (`💬 Comment`) is shown near the selection.
- **Resolution (`locateText(root, target, contextBefore, contextAfter)`)**:
  - Builds the flat text map of `root` (`unitElement(t.unit || c.unit)` for comments; `(r.unit && unitElement(r.unit)) || document.body` for responses and questions).
  - Finds all starting indices `occ` of `target` in `map.text` (stepping by `from = p + 1`).
  - If `occ.length === 0`, returns `null` (`anchored = false`).
  - If `occ.length === 1`, chooses `occ[0]`.
  - If `occ.length > 1`, scores each occurrence `o`:
    - `before = text.slice(Math.max(0, o - 40), o)`
    - `after = text.slice(o + target.length, o + target.length + 40)`
    - `+1` if `contextBefore` is non-empty and `before.indexOf(contextBefore.slice(-20)) >= 0`.
    - `+1` if `contextAfter` is non-empty and `after.indexOf(contextAfter.slice(0, 20)) >= 0`.
    - Sorts descending by `score` (preserving document order on ties) and chooses `scored[0].o`.
  - Maps `chosen` back to the text node `node` where `start <= chosen < start + len`, with `localStart = chosen - start` and `markLen = Math.min(target.length, node.nodeValue.length - localStart)` (clamped to a single text node).
- **DOM Highlight**:
  - If `insideSvg(loc.node)` is `true` (`namespaceURI === 'http://www.w3.org/2000/svg'`), wrapping an HTML `<mark>` would break SVG rendering, so `anchorTextTarget` / `anchorResponse` returns `true` (anchored) without inserting `<mark>`, while `anchorQuestion` returns `false` (panel display only).
  - Otherwise `wrapMark` creates `<mark class="sp-mark">` (or `sp-mark-fixed` for responses) and calls `range.surroundContents(mark)`. If `surroundContents` throws (e.g., range straddles an element boundary), `wrapMark` still returns `true`.

#### 2. `element`
- **Creation**: Clicking inside an element (more than `EDGE = 8` px away from its top and bottom edges) in `e` pick mode.
  - `path`: Built by `cssPath(el)`, walking `el` up to `document.body` (exclusive) and joining `tag:nth-of-type(idx)` segments as `'body > ...'` (completely independent of `id` and `class`).
  - `tag`: `el.tagName.toLowerCase()`.
  - `nearText`: `nearTextOf(el)` — `(el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60)`.
- **Resolution (`resolveByPath(path, tag, nearText)`)**:
  1. Primary: `document.querySelector(path)` (wrapped in `try/catch`). If found, returns the element.
  2. Fallback: If `!tag || !nearText`, returns `null`. Otherwise iterates through `document.getElementsByTagName(tag)`, skipping any element inside `#spPanel, #spPopup, #spJsonModal`, and returns the first element where `nearTextOf(cand) === nearText` (exact 60-char normalized match).
- **DOM Highlight**: Adds class `sp-mark-el`, sets `data-sp-cmt-id`, and (when `c.targets.length > 1`) sets `data-sp-badge`.

#### 3. `insertion-point`
- **Creation**: Clicking within `EDGE = 8` px of an element's top edge (`where = 'before'`) or bottom edge (`where = 'after'`) at `pickLevel === 0` in `e` pick mode.
  - `prev = (where === 'before') ? el.previousElementSibling : el`
  - `next = (where === 'before') ? el : el.nextElementSibling`
  - Fields:
    - `afterPath: prev ? cssPath(prev) : null`
    - `beforePath: next ? cssPath(next) : null`
    - `afterTag: prev ? prev.tagName.toLowerCase() : null`
    - `beforeTag: next ? next.tagName.toLowerCase() : null`
    - `nearText: nearTextOf(prev || next)`
- **Resolution**:
  - **For Comments (`anchorInsertionTarget(c, t)`)**:
    1. If `t.afterPath` is set, calls `after = resolveByPath(t.afterPath, t.afterTag, t.nearText)` (using `afterPath` first, falling back to `afterTag + nearText`).
    2. Only if `after` is `null` and `t.beforePath` is set, calls `before = resolveByPath(t.beforePath, t.beforeTag, t.nearText)` (using `beforePath` first, falling back to `beforeTag + nearText`).
    3. If neither resolves, returns `false`.
    4. Creates `<span class="sp-insert-mark">` and inserts it at `after.parentNode.insertBefore(markEl, after.nextSibling)` when `after` resolved, or `before.parentNode.insertBefore(markEl, before)` when `before` resolved.
  - **For Question Pins (`anchorQuestion(q)`)**:
    1. Resolves `after = t.afterPath ? resolveByPath(t.afterPath, null, null) : null` and `before = t.beforePath ? resolveByPath(t.beforePath, null, null) : null` (strict CSS path lookup without `nearText` fallback).
    2. If `after && after.parentNode`, inserts the pin before `after.nextSibling`; else if `before && before.parentNode`, inserts the pin before `before`; else returns `false`.

#### 4. `diagram-node`
- **Creation & SVG Ancestor Snapping**:
  - In `pickTargetAt(e)`, when the hovered element `el` is an SVG element (`el.namespaceURI === 'http://www.w3.org/2000/svg'`), `diagramNodeOf(el)` calls `el.closest('[data-sp-node]')`.
  - If a `[data-sp-node]` ancestor exists, the picker snaps to that semantic node (`{el: dn || el, where: null}`); insertion points (`where`) are never created inside SVG.
  - Clicking an element with `data-sp-node` produces:
    - `kind: 'diagram-node'`
    - `nodeId: el.getAttribute('data-sp-node')`
    - `nodeLabel: el.getAttribute('data-sp-label') || null`
    - `nearText: diagramNearText(el)` — clones `el`, removes any runtime `.sp-qpin-svg` and `.sp-node-halo` descendants from the clone, and computes `(clone.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60)`.
- **Resolution (`resolveDiagramNode(nodeId, nodeLabel)`)**:
  1. Primary: Queries `document.querySelector('[data-sp-node="' + cssEsc(nodeId) + '"]')`.
  2. Fallback: If not found and `nodeLabel` is non-empty, scans `document.querySelectorAll('[data-sp-node]')` and returns the first element whose `data-sp-label` attribute equals `nodeLabel`.
  3. Returns `null` if neither matches (note: `nearText` is exported in the JSON for the AI agent's source inference when `anchored: false`, and is not used as a DOM fallback in `resolveDiagramNode`).
- **SVG Overlay Geometry (`svgHalo` & `svgQuestionPin`)**:
  - Uses `box = el.getBBox()`.
  - `appendSvgOverlay(el, node)` appends `node` directly into `el` if `el` is `<g>` or `<svg>`; otherwise appends `node` into `el.parentNode` and copies `el.getAttribute('transform')` onto `node`.
  - **Comment Halo (`svgHalo`)**: `<rect class="sp-node-halo">` with `x = box.x - 4`, `y = box.y - 4`, `width = box.width + 8`, `height = box.height + 8`, `rx = 6`, `data-sp-cmt-id = c.id`.
  - **Question Pin (`svgQuestionPin`)**: `<text class="sp-qpin-svg" font-size="16">❓</text>` with `x = box.x + box.width - 6`, `y = box.y + 4`, `data-sp-q-id = q.id`, containing a `<title>{q.question}</title>` child.

#### 5. `document`
- **Creation**: Clicking `#spDocCommentBtn` (`📄 Whole-document comment` in the panel, which prevents duplicate `document` targets in the same comment) or pressing `ArrowUp` in `e` pick mode until reaching `document.body`.
- **Fields**: `{kind: "document"}` with comment-level `unit: null` and `unitLabel: "Whole document"`. Always resolves `anchored: true` without adding any DOM mark to `document.body`.

### 5.4 Verb Palette (`action`)

Optional explicit intent selected from `#spPopupPalette`:
- `"move"`: Requires `pendingTargets.length >= 2` before saving. Automatically assigns `role: "source"` to `pendingTargets[0].target` and `role: "destination"` to `pendingTargets[1].target`. Default comment text when textarea is blank: `"[Move] ① to ②"`.
- `"insert"`: Insert content at target position. Default blank text: `"[Insert]"`.
- `"delete"`: Remove target. Default blank text: `"[Delete]"`.
- `"shorten"`: Condense target text/section. Default blank text: `"[Shorten]"`.
- `"keep"`: Explicit approval (`Keep 👍`); agents must not undo or alter approved content. Default blank text: `"[Keep 👍]"`.

### 5.5 Panel Ordering & Orphaned Response-Only Items

- **Comment Sorting**: `renderPanel()` sorts `comments` in DOM document order of their `unitElement(c.unit)` via `elA.compareDocumentPosition(elB) & Node.DOCUMENT_POSITION_FOLLOWING` (preserving creation order when two comments share the same unit or have `unit: null`).
- **Unanchored Warning**: If any target in `c.targets` has `t.anchored === false`, the panel item renders `<div class="sp-item-noanchor">⚠ Original text not found</div>`.
- **Response-Only Fallback Items (`sp-item-response-only`)**:
  - Because `window.SAMEPAGE_RESPONSES` is embedded in the HTML while `comments` live in browser-local `localStorage`, opening the HTML in a different browser or after clearing storage leaves responses without a matching local comment.
  - At the end of `renderPanel()`, every `r` in `RESPONSES` whose `r.id` is not present in `comments` is rendered as a standalone card:
    - `<div class="sp-item sp-item-response-only" data-sp-cmt-id="{r.id}">`
    - Header `<div class="sp-item-unit">(no source comment)</div>`
    - Standard `buildResponseBlock(r)` (`🤖` + action badge `Fixed` / `Partially fixed` / `Declined` / `Acknowledged` + reply text).
    - Clicking the card or response block invokes `jumpToFixed(r)`: scrolls smoothly (`block: 'center'`) to `mark.sp-mark-fixed[data-sp-resp-id="{r.id}"]` if anchored in the body, or falls back to `jumpToUnit(r.unit)`.

---

## 6. Bidirectional JSON Contracts

### 6.1 Export JSON (Human → AI)

Generated by `buildJson()` (`JSON.stringify(..., null, 2)`). `answers` includes only items where `a.answer || a.note` is truthy. Top-level `selectedText`, `contextBefore`, `contextAfter`, and `anchored` mirror the comment's first `text-range` target (`firstTextRange(c)`), or are `null` (`anchored` falling back to `c.targets[0].anchored !== false`) when the comment has no `text-range` target.

```json
{
  "_howto": "This is human review feedback exported by samepage...",
  "_skill": "samepage",
  "_rules": ["...10 authoritative resolution rules..."],
  "doc": "document-id",
  "sourceHtml": "/absolute/path/to/doc.html or null",
  "generatedAt": "2026-10-17T00:00:00.000Z",
  "answers": [
    {
      "questionId": "q-1",
      "answer": "Selected choice",
      "note": "Optional free-text note",
      "answeredAt": "2026-10-17T00:00:00.000Z"
    }
  ],
  "comments": [
    {
      "id": "c-8charid",
      "unit": "u1",
      "unitLabel": "Whole",
      "targets": [
        {
          "label": "1",
          "kind": "text-range",
          "anchored": true,
          "role": "source",
          "selectedText": "target phrase",
          "contextBefore": "preceding 40 chars",
          "contextAfter": "following 40 chars"
        }
      ],
      "action": null,
      "comment": "Please clarify this claim.",
      "status": "open",
      "anchored": true,
      "selectedText": "target phrase",
      "contextBefore": "preceding 40 chars",
      "contextAfter": "following 40 chars",
      "createdAt": "2026-10-17T00:00:00.000Z"
    }
  ]
}
```

### 6.2 Responses JSON (AI → Human, `--responses`)

```json
{
  "doc": "document-id",
  "respondedAt": "2026-10-17T00:05:00.000Z",
  "responses": [
    {
      "id": "c-8charid",
      "reply": "Updated the claim and added citation in section 2.",
      "action": "fixed",
      "fixedText": "exact substring present in the regenerated HTML",
      "contextBefore": "optional disambiguating prefix",
      "contextAfter": "optional disambiguating suffix",
      "unit": "u1"
    }
  ]
}
```
- Valid `action` values: `"fixed"` (default when omitted), `"declined"`, `"partial"`, `"noted"`.

### 6.3 Questions JSON (AI → Human, `--questions`)

```json
{
  "questions": [
    {
      "id": "q-01",
      "question": "Which retention period should we standardize on?",
      "unit": "u1",
      "target": {
        "kind": "text-range",
        "selectedText": "Retention policy",
        "contextBefore": "",
        "contextAfter": ""
      },
      "choices": ["【Recommended】 90 days", "30 days", "1 year"]
    }
  ]
}
```
- When `choices` is non-empty, clicking a choice button sets `answer` to that choice and the `<textarea>` records an optional `note`. When `choices` is omitted or empty, changing the `<textarea>` sets `answer` directly.
- Answered questions (present in `answers[]` of the export JSON) must never be re-injected in subsequent rounds.

---

## 7. Finalization Pipeline (`--finalize`)

### 7.1 Exact Stripping Regexes & Constants (`samepage/cli.py`)

```python
DATA_SP_ATTR = re.compile(r'\s+data-sp-[\w-]+(?:\s*=\s*"[^"]*"|\s*=\s*\'[^\']*\')?(?=[\s/>])')
CLASS_ATTR_RE = re.compile(r'(\sclass\s*=\s*)(["\'])(.*?)\2', re.DOTALL)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img",
             "input", "link", "meta", "source", "track", "wbr"}
```

Helper `_merge_spans(spans)` sorts `(start, end)` intervals and merges overlapping or nested intervals (`s <= merged[-1][1]`) into their outer bounds so reverse-order slicing never double-deletes nested elements.

### 7.2 Five-Stage Stripping Order (`finalize_html(html)`)

`finalize_html(html)` executes five deterministic stripping passes in strict sequence:

1. **`strip_discussion_elements(html)`**:
   - `_DiscussionSpanCollector` tracks an element stack `(tag, start_offset, is_discussion)` where `is_discussion` is `any(k == "data-sp-discussion" for k, _ in attrs)`.
   - Elements in `VOID_TAGS` or self-closing tags (`handle_startendtag`) with `data-sp-discussion` record `(start, start + len(get_starttag_text()))` immediately without pushing onto the stack.
   - Normal elements record `(start, end_tag_end)` when their matching closing tag is popped.
   - Merges spans via `_merge_spans` and slices them out in reverse order.
2. **`strip_runtime_decorations(html)`**:
   - `_RuntimeMarkSpanCollector` handles DOM state baked in if a user saved the live page via "Save Page As":
     - `REMOVE_CLASSES = ("sp-qpin", "sp-qpin-svg", "sp-insert-mark", "sp-node-halo")`: Any element carrying one of these class tokens is removed wholesale (start tag through end tag, including contents).
     - `UNWRAP_CLASSES = ("sp-mark", "sp-mark-fixed")`: Any `<mark>` element carrying one of these class tokens has only its start-tag span `(start, tag_end)` and end-tag span `(end_start, end_end)` added to `unwrap_spans`, preserving its inner text.
   - Merges `remove_spans + unwrap_spans` via `_merge_spans` and slices them out in reverse order.
3. **`strip_marker_block(html)`**:
   - Verifies `has_begin == has_end` (raising `ValueError` if only one marker is present).
   - Removes from `html.index(MARKER_BEGIN)` through `html.index(MARKER_END) + len(MARKER_END)` plus a single trailing `"\n"` if present.
4. **`strip_sp_data_attrs(html)`**:
   - `_StartTagSpanCollector` collects the `(start, end)` byte/character span of every start tag and self-closing start tag.
   - Applies `DATA_SP_ATTR.sub("", tag_text)` **only within start-tag spans** containing `"data-sp-"`, ensuring literal `data-sp-*` strings in prose or `<code>` blocks are never touched.
5. **`strip_runtime_mark_class_token(html)`**:
   - Within start-tag spans containing `"sp-mark-el"`, applies `_remove_class_token(tag_text, "sp-mark-el")` via `CLASS_ATTR_RE.sub(..., count=1)`.
   - Removes `"sp-mark-el"` from `value.split()`. If no class tokens remain, removes the entire ` class="..."` attribute (`return ""`); otherwise rejoins remaining tokens with a single space.

---

## 8. `grill-on-samepage` & Alignment Builder Specification (`docs/build_alignment_html.py`)

### 8.1 Session & Artifact Layout

```text
docs/alignment/
  INDEX.md                  # Auto-generated cross-session decision & glossary index (--index)
  NNNN-slug.md              # Single Source of Truth (SSOT) Markdown for session NNNN
  NNNN-slug.html            # HTML generated by build_alignment_html.py (review layer injected during active sessions)
  NNNN-slug.final.html      # Finalized publishable HTML extracted after consensus (--finalize)
```

### 8.2 Design Tree Notation & Parser (`parse_design_tree`)

`split_tree_section(body)` locates the heading matching `TREE_HEADING_RE` and extracts all non-blank lines until the next `^## ` heading.

```python
STATES = ("確定", "frontier", "再検討", "保留")
NODE_RE = re.compile(r"^(?P<indent> *)- \[(?P<id>[A-Za-z]+-\d+)\]\s*(?P<rest>.+?)\s*$")
DEP_RE = re.compile(r"^(?P<indent> *)- \(依存\)\s*\[(?P<id>[A-Za-z]+-\d+)\]\s*$")
TREE_HEADING_RE = re.compile(r"^##\s+.*design tree.*$", re.M)
```

Validation rules (raising `TreeError(ValueError)` with 1-based line numbers on violation):
1. **Indentation**: Leading spaces must be an even number (`len(indent) % 2 == 0`); `depth = len(indent) // 2`. Indented nodes (`depth > 0`) must have a parent at `depth - 1`.
2. **Node ID**: `[ID]` matching `[A-Za-z]+-\d+` (e.g., `[D-1]`). Must be unique across the document (`duplicate id` raises `TreeError`); withdrawn IDs are never reused.
3. **Fields**: `rest` is split on `"::"` and stripped. At least 2 fields (`title :: state`) are required, where `state in STATES`.
4. **Decision Field**: `decision = fields[2] if len(fields) > 2 else ""`.
   - A `確定` row **must** carry a non-empty `decision` field.
   - Non-`確定` rows (`frontier`, `再検討`, `保留`) **must not** carry a `decision` field.
5. **Cross-Dependencies (`DEP_RE`)**: `- (依存) [ID]` must be indented (`depth > 0`) under an owning node at `depth - 1`, and the target `ID` must exist in `seen` across the tree. Appends `(owner_id, target_id)` to `extra_edges`.

### 8.3 Design Tree SVG Layout Constants & Rendering (`layout`, `render_svg`)

#### Exact Layout Constants
```python
BOX_W, BOX_H, COL_GAP, ROW_GAP, TOP = 182, 56, 14, 74, 16
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
```

#### Grid Layout & Centering (`layout(nodes)`)
1. Groups nodes by `depth` into rows (preserving document order within each depth).
2. For each `row` at `depth`:
   - `row_span = len(row) * BOX_W + (len(row) - 1) * COL_GAP`
   - Initial `x = i * (BOX_W + COL_GAP)` for `i` in `0 .. len(row)-1`.
   - `y = TOP + depth * (BOX_H + ROW_GAP)`.
3. Total SVG `width = max(n["row_span"] for n in nodes)`.
4. Horizontally centers every row:
   - `n["x"] += (width - n["row_span"]) // 2`
   - Center coordinates: `n["cx"] = n["x"] + BOX_W // 2` (`+ 91`), `n["cy"] = n["y"] + BOX_H // 2` (`+ 28`).
5. Total SVG `height = max(n["y"] + BOX_H for n in nodes) + 40` (reserving 40px at the bottom for the state legend).

#### State Color & Symbol Palette (`STATE_STYLE`)

| State | `fill` | `stroke` | `title` | `sub` | `mark` |
|---|---|---|---|---|---|
| `確定` | `#e6f5f3` | `#0f766e` | `#0f2a28` | `#0b5750` | `✓` |
| `frontier` | `#fdf3e0` | `#b5790c` | `#5a3d05` | `#b5790c` | `❓` |
| `再検討` | `#fdecea` | `#b3261e` | `#5c1512` | `#b3261e` | `↺` |
| `保留` | `#f1f5f4` | `#8fa5a1` | `#3d4a48` | `#5b6c69` | `⏸` |

#### Text Truncation (`_fit(text, budget=170, size=12)`)
Accumulates character width `w` where characters with `ord(ch) > 0x2E80` (CJK) add `1.0 * size` and all other characters add `0.55 * size`. When `w > budget`, appends `"…"` and stops:
- Line 1 (`font-size="12"`): `_fit(f'{n["id"]} {n["title"]}', budget=170, size=12)`
- Line 2 (`font-size="11"`, `font-weight="700"`, `dy="17"`): `_fit(f'{st["mark"]} {n["decision"] or n["state"]}', budget=170, size=11)`

#### Edges, Nodes, Anchors & Legend
- **Arrow Markers**: Namespaced per document (`id="sp-ar-{doc_id}-ok"` with fill `#0f766e`, and `id="sp-ar-{doc_id}-dep"` with fill `#8fa5a1`) so multiple SVGs on a page never collide.
- **Parent Edges**: Solid line (`stroke-width="2"`, `stroke=STATE_STYLE[child["state"]]["stroke"]`, `marker-end="url(#sp-ar-{doc_id}-ok)"`) from `(parent.cx, parent.y + BOX_H)` to `(child.cx, child.y - 4)`.
- **Dependency Edges (`(依存)`)**: Dashed line (`stroke="#8fa5a1"`, `stroke-width="2"`, `stroke-dasharray="5,4"`, `marker-end="url(#sp-ar-{doc_id}-dep)"`) from `(src.cx, src.y)` to `(dst.cx, dst.y + BOX_H + 4)`.
- **Node Markup & Anchor Linking**:
  - Wrapped in `<a href="#{anchor_for(n['id'])}">` where `anchor_for(node_id)` is `node_id.replace("-", "").lower()` (e.g., `D-1` → `#d1`).
  - Both ledger table rows (`<tr><td>D-1...`) and decision headings (`<h2>D-1...` / `<h3>D-1...`) in the Markdown body automatically receive `id="d1"` via `add_row_anchors` and `add_heading_anchors`.
  - Inner `<g data-sp-node="{id}" data-sp-label="{label}">` where `label` is `"{id} {title}（{state}: {decision}）"` if `decision` is non-empty, else `"{id} {title}（{state}）"`.
- **Legend**: For each state in `STATES` present in `nodes`, renders a `14x14` rect at `(lx, height - 28)` and text `"{state}（{count}）"` at `(lx + 22, height - 17)`, advancing `lx += 40 + 13 * len(s) + 34`.

### 8.4 Outstanding Items (`build_remaining` / 残件) Calculation Logic

When `--export <export.json>` is passed to `docs/build_alignment_html.py`, `build_remaining(export_path, nodes)` computes the session's remaining work and prepends a `<div class="sp-discussion" data-sp-discussion>` block right before `<article class="sp-article">`:

1. **Input Extraction**:
   - `answers = {a.get("questionId") for a in data.get("answers", []) if a.get("questionId")}` (unique answered question IDs).
   - `comments = data.get("comments", [])`
   - `open_ids = [c.get("id") for c in comments if c.get("status") == "open"]`
   - `settled = [n for n in nodes if n["state"] == "確定"]`
   - `pending = [n for n in nodes if n["state"] in ("frontier", "再検討")]`
   - `held = [n for n in nodes if n["state"] == "保留"]`
2. **Summary Table (5 Rows)**:
   1. `回答済みの質問ピン`: count = `len(answers)`, detail = `"export JSON の answers より"`
   2. `未解決のコメント (status: "open")`: count = `len(open_ids)`, detail = `", ".join(open_ids)` if non-empty else `f"{len(comments)} 件すべて resolved"`
   3. `確定した決定`: count = `len(settled)`, detail = `", ".join(n["id"] for n in settled) or "—"`
   4. `未確定の決定 (frontier / 再検討)`: count = `len(pending)`, detail = `", ".join(n["id"] for n in pending) or "なし"`
   5. `運用へ回した保留`: count = `len(held)`, detail = `", ".join(n["id"] for n in held) or "なし"`
3. **Consensus Gate Formula (`blocked`)**:
   ```python
   blocked = len(open_ids) + len(pending)
   ```
   - Note that `保留` (`held`) nodes and answered questions do **not** increment `blocked`.
   - If `blocked == 0`: Renders `<p><strong>残件はゼロです。</strong>D-4 の合意ゲートにより、ここから先は明示的な合意が必要です。</p>`.
   - If `blocked > 0`: Renders `<p><strong>残件が {blocked} 件あります。</strong>すべて片付くまで <code>--finalize</code> しないでください（D-4）。</p>`.
4. **Automatic Stripping**: Because the wrapper carries `data-sp-discussion`, `--finalize` automatically strips the entire `残件` block when producing `<stem>.final.html`.

---

## 9. Multi-Agent Plugin & Skill Architecture

To work seamlessly across **Google Antigravity**, **Claude Code**, and other coding agents without code duplication:

| Component | Path | Target Agent(s) |
|---|---|---|
| Antigravity Plugin Manifest | `plugin.json` | Google Antigravity (`~/.gemini/config/plugins/samepage` or `.agents/plugins/samepage`) |
| Claude Plugin Manifest | `.claude-plugin/plugin.json` | Claude Code (`~/.claude/skills/samepage`) |
| Workspace / Plugin Rules | `AGENTS.md`, `CLAUDE.md` | Antigravity, Claude Code, Codex, Cursor |
| Skills | `skills/samepage/SKILL.md`, `skills/grill-on-samepage/SKILL.md` | All agents supporting `SKILL.md` progressive disclosure |

Skills resolve `samepage/cli.py` and `docs/build_alignment_html.py` relative to the skill directory (`../../samepage/cli.py`) or via `${CLAUDE_PLUGIN_ROOT}` when expanded by Claude Code, ensuring identical execution in any agent environment.
