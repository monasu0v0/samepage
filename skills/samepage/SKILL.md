---
name: samepage
description: |
  Use when a human needs to be able to comment on an existing HTML document and have that
  feedback flow back to an AI agent as structured JSON. Triggers on requests like "make this
  reviewable", "let people comment on this", "add review comments to this HTML", or right after
  an AI produces an HTML deliverable that a human is expected to review.
  日本語のトリガー例:「この資料にコメントできるようにして」「レビューできる形にして」
  「samepageにして」「samepage化して」。
  Nodes inside an inline SVG diagram can also be direct comment/question targets: a generator
  that tags nodes with `data-sp-node` lets the reviewer pick them with the element-picker (`e`),
  and the stable id round-trips back to the original source via `kind:"diagram-node"`.
  Supports multi-location comments, comments on the element itself, comments on an insertion
  point between elements, whole-document comments, reverse AI-to-human question pins, and
  splitting off a review-layer-free publishable HTML with `--finalize` once everything is
  resolved. Does not do Markdown-to-HTML conversion — it only calls the existing `cli.py`.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/samepage/cli.py *)
---

# Add review comments to an existing HTML file

If asked to "samepage" a file with no other detail, target the HTML most recently produced or
discussed in this conversation. Only ask for clarification if there are multiple candidates.

## 1. Default behavior

Inject using `body` as the unit element. This works on any HTML unconditionally (`body` always
exists), and is also the right answer for HTML with no other natural unit element (the common
case).

The script is at `samepage/cli.py` in the plugin/repository root, two levels above this `SKILL.md`
(`skills/samepage/SKILL.md` → `../../samepage/cli.py`):
- **Google Antigravity / General Agents**: Resolve `../../samepage/cli.py` relative to this `SKILL.md`'s directory (e.g. `~/.gemini/config/plugins/samepage/samepage/cli.py`, `.agents/plugins/samepage/samepage/cli.py`, or `./samepage/cli.py` when working inside the repo).
- **Claude Code**: `${CLAUDE_PLUGIN_ROOT}` expands to the repository root (`${CLAUDE_PLUGIN_ROOT}/samepage/cli.py`).
- **Imported skill text only**: If only this `SKILL.md`'s text was imported without the bundled files, look for `samepage/cli.py` inside any connected workspace folder (or ask the user to connect it). Never reimplement or inline the script's logic — the injected JS/CSS assets bundled with it are the source of truth.

```bash
# Replace <SAMEPAGE_ROOT> with the directory two levels above this SKILL.md (or ${CLAUDE_PLUGIN_ROOT})
python3 <SAMEPAGE_ROOT>/samepage/cli.py \
    <HTML> --unit-selector body --label-format "Whole"
```

After injecting, open the file in a browser (`file://` works, no server needed) and walk the
human through "3. Review walkthrough" below.

## 2. Room to adjust (not a fixed rule — use judgment on the spot)

| Situation | Adjustment |
|---|---|
| Slide-shaped document (`.slide` or Marp `<section>`) | `--unit-selector .slide --jump hash` (or `section`) lets the comment list jump straight to the matching slide |
| Want a label per chapter | `--unit-selector section --label-format "Section {n}"` |
| Slide HTML advances on click | Clicking conflicts with text selection (a double-click meant to select a word instead advances the slide on the first click). Tell the reviewer to move with arrow keys, then select. **Never modify the existing HTML's click behavior to work around this** |
| Distributing the layer itself (e.g. in a README) | Add `--no-source-path` so `sourceHtml` is embedded as null instead of a local absolute path |

Never use `<h2>` as the unit element. `data-sp-unit` would land on the `<h2>` itself, leaving the
body text outside any unit and impossible to comment on. `body` as the unit is good enough in
practice even for `<h2>`-delimited reports.

## 3. Review walkthrough

1. Open the file in a browser.
2. Select text → press `a` or click the 💬 button → type a comment → Enter to submit
   (Shift+Enter for a newline).
3. To point at the element itself, or at a position to insert something, press `e` to enter
   element-pick mode. Hovering an element outlines it. Clicking within 8px of an element's
   top/bottom edge picks "the position right before/after this element" as an insertion point;
   clicking elsewhere picks the element itself. While hovering, `↑` widens the pick to the parent
   element one level at a time, `↓` narrows it back (useful for pointing at an entire section).
   Widening all the way to `body` and clicking gives a whole-document target (`document`).
   **Inside an SVG diagram, clicks snap to the nearest `data-sp-node`-tagged node**: wherever you
   click in the diagram, the nearest node (`kind:"diagram-node"`) is picked, and confirming it
   draws an amber halo around the node. There is no concept of an insertion point inside a
   diagram. Text selection inside a diagram doesn't highlight, so use the `e`-key node picker for
   feedback on a diagram.
4. To point one comment at multiple locations (e.g. "move A to where B is"), use the "+ Add
   location" button in the popup → select text or press `e` again. A verb palette (Move / Insert /
   Delete / Shorten / Good 👍 — five options) lets you state intent explicitly. Choosing "Move"
   records the 1st location as the source and the 2nd as the destination.
5. For a general remark not tied to a specific spot (structure, tone, direction, etc.), use the
   "📄 Whole-document comment" button in the panel. No mark is added to the body; it becomes a
   `kind: "document"` target.
6. `c` toggles the comment list. Comments can also be edited from the list.
7. If the AI has planted a question pin (❓) in the body, answer it by clicking a choice or
   typing free text (see section 7).
8. In the list, click "📋 Copy JSON" to copy the export JSON in one click (same as the `j` key),
   or "👁 Show JSON" → "Copy" to look it over first.
9. Paste the JSON to your AI agent (e.g. Antigravity, Claude Code).

## 4. JSON contract and how to read it (a rule set — don't apply it loosely)

A single comment can have multiple locations (the `targets` array). Each target's `kind` is one
of five forms.

```json
{
  "_howto": "Work-order text explaining that this skill should be invoked and this section followed",
  "_skill": "samepage",
  "_rules": ["A condensed string array mirroring the rules table below"],
  "doc": "the HTML file's stem",
  "sourceHtml": "absolute path of the HTML the review layer was injected into",
  "generatedAt": "ISO8601",
  "answers": [
    { "questionId": "q-xxxxxxxx", "answer": "choice text", "note": "free text (optional)", "answeredAt": "ISO8601" }
  ],
  "comments": [
    {
      "id": "c-xxxxxxxx",
      "unit": "u1",
      "unitLabel": "Whole",
      "targets": [
        {
          "kind": "text-range", "label": "1", "anchored": true,
          "selectedText": "the selected string", "contextBefore": "40 chars before", "contextAfter": "40 chars after"
        }
      ],
      "action": null,
      "comment": "comment body",
      "status": "open",
      "anchored": true,
      "selectedText": "the selected string",
      "contextBefore": "40 chars before",
      "contextAfter": "40 chars after",
      "createdAt": "ISO8601"
    }
  ]
}
```

How to read each `targets[].kind`:

| kind | fields it carries | how to resolve it |
|---|---|---|
| `text-range` | `selectedText`/`contextBefore`/`contextAfter` | Search the body text for the literal string (same as rules 2–3 below) |
| `element` | `path`/`tag`/`nearText` | Follow `path` (an id/class-independent nth-of-type chain like `body > div:nth-of-type(2) > p:nth-of-type(3)`) into the source. If the structure has changed and the path no longer resolves, fall back to a nearby match using `tag` and `nearText` (the first 60 chars of the element's text) |
| `insertion-point` | `afterPath`/`beforePath`/`nearText`/`afterTag`/`beforeTag` | The insertion point is "right after the element `afterPath` points to". `beforePath` is for cross-checking that position. If `afterPath` is broken, fall back to `afterTag`+`nearText`; if that also fails, resolve from the `beforePath`/`beforeTag` side instead |
| `diagram-node` | `nodeId`/`nodeLabel`/`nearText` | A node inside an SVG diagram. `nodeId` is the value the generator assigned to `data-sp-node` — **the same stable id as the node in the original source** (the IR / diagram definition, etc). Don't edit the SVG in the HTML directly; fix the corresponding node in the original source and regenerate the diagram. If `nodeId` can't be found, fall back to `nodeLabel` (the `data-sp-label` value), then to `nearText` (the first 60 chars of the node's text) |
| `document` | (no location fields) | A whole-document remark. Don't search for a specific spot; treat it as a structural/tone/policy-level instruction. `unit` may be `null` |

The leading `_howto` / `_skill` / `_rules` / `sourceHtml` fields are a handoff header. They exist
so that even if only the JSON — with no accompanying message — is pasted into a fresh session,
that session can still find its way to this skill, and can still do the work using `_rules` alone
in an environment without the skill installed. **`_rules` duplicates the content of the rules
table below, so when the rules change, update both `HANDOFF_RULES` in `samepage.js` and the table
below.** The table below is authoritative.

| # | Rule |
|---|---|
| 1 | Fix the original source, not this HTML. If the HTML is a generated artifact, edit the source it came from (e.g. a same-named `.md`) instead. Editing the HTML directly is lost on the next regeneration. The target HTML's location is in `sourceHtml` |
| 2 | Find the spot using `selectedText`. If it matches more than once, disambiguate using the end of `contextBefore` and the start of `contextAfter` |
| 3 | Markup syntax (e.g. Markdown `**bold**`, links) is stripped when rendering to HTML, so `selectedText` may not exist verbatim in the source. Search again with the formatting removed |
| 4 | `anchored: false` means the original text couldn't be found. Don't discard it — infer the intended fix from `unitLabel`, `comment`, or `targets[].nearText`, apply it, and clearly state that it was inferred |
| 5 | Do not modify comments with `status: "resolved"` |
| 6 | When `targets` has 2+ entries carrying a `role`, `role: "source"` → `role: "destination"` means "move the content of source to the position of destination". This always accompanies `action: "move"` |
| 7 | `action` is one of `move`/`insert`/`delete`/`shorten`/`keep`/`null`. When it has a value, it is authoritative even if `comment` reads like boilerplate. `action: "keep"` is an explicit approval of the spot as-is — never undo it, even during a fix pass or HTML regeneration |
| 8 | The top-level `selectedText`/`contextBefore`/`contextAfter`/`anchored` fields duplicate the comment's first `text-range` target (kept for backward compatibility). A comment whose only targets are `element`/`insertion-point`/`document` (no `text-range`) has `selectedText: null` at the top level |
| 9 | `answers` holds responses to question pins (section 7). Match by `questionId` against the question JSON's `id`, and treat them as additional instructions. Only entries with an `answer` (choice) or `note` (free text) are emitted |
| 10 | Report back which fix answers which comment as a responses JSON, injected via `--responses` (see section 6) |

## 5. Cases where injection is refused

| Situation | Behavior |
|---|---|
| No `</body>` | Abort with an error; never rewrite the HTML blindly |
| Selector matches 0 elements | Non-zero exit (existing `cli.py` behavior) |
| Non-UTF-8 input | Non-zero exit (existing behavior) |
| Already injected | Idempotent replace — the review layer is updated in place |

## 6. Replying to comments (injecting the responses JSON)

Once feedback has been applied to the original source and the HTML regenerated, build a responses
JSON and inject it with `--responses`. When the reviewer reopens the HTML, they see which comment
got which reply and what changed.

```json
{
  "doc": "the HTML file's stem",
  "respondedAt": "ISO8601",
  "responses": [
    {
      "id": "c-xxxxxxxx",
      "reply": "Reworded the flagged sentence to ...",
      "action": "fixed",
      "fixedText": "a string that exists verbatim in the HTML after the fix",
      "contextBefore": "text right before it (optional, for disambiguation)",
      "contextAfter": "text right after it (optional)",
      "unit": "u1"
    }
  ]
}
```

- `id`: matches the comment JSON's `id`. Required
- `reply`: the reply text. Required
- `action`: `fixed` / `declined` / `partial` / `noted`. Defaults to `fixed` when omitted
- `fixedText`: an anchor into the post-fix text. Nullable (e.g. for a `declined` reply with
  nothing to point at)
- `contextBefore` / `contextAfter` / `unit`: optional, for disambiguating multiple matches or
  narrowing the search

| # | Rule |
|---|---|
| 1 | Before injecting, confirm with grep or similar that `fixedText` exists verbatim in the regenerated HTML |
| 2 | Reply even to comments left unchanged, with `action: "declined"` or `"noted"` |
| 3 | Re-injecting without `--responses` clears the response layer (only the most recent set of fixes is ever shown) |

```bash
python3 <SAMEPAGE_ROOT>/samepage/cli.py \
    <HTML> --unit-selector body --label-format "Whole" --responses replies.json
```

After injecting, tell the reviewer: "The green highlight marks a fixed spot. Replies appear below
each comment in the 💬 panel."

## 7. Writing question pins (reverse AI-to-human confirmation)

Use this when the AI can't decide how to proceed and needs to ask the reviewer directly. This is a
separate JSON from comments (human-to-AI), injected via `--questions`.

```json
{
  "questions": [
    {
      "id": "q-xxxxxxxx",
      "question": "This paragraph repeats the earlier explanation — which one should stay?",
      "target": {
        "kind": "text-range",
        "selectedText": "target text", "contextBefore": "40 chars before", "contextAfter": "40 chars after"
      },
      "choices": ["Keep the earlier one", "Keep this one", "Keep both"]
    }
  ]
}
```

- `id` / `question`: non-empty strings, required
- `unit`: optional. Target unit ID (e.g. `"u1"`); when omitted, inferred from `target` or left unspecified
- `target`: optional. When present, a pin (❓) appears in the body. Shape matches `targets` in
  "4. JSON contract" (`text-range`/`element`/`insertion-point`/`diagram-node`). `diagram-node`
  requires `nodeId`; the pin lands on the top-right corner of that node
  (`{"kind":"diagram-node","nodeId":"spec-07"}`). Omitting `target` means no pin appears in the
  body — the question shows only in the question list panel. Pointing `text-range` at text inside
  an SVG also results in list-only (an HTML pin can't be placed inside SVG). Use `diagram-node`
  for questions about a diagram
- `choices`: optional. An array of strings renders as choice buttons; omitting it means free text
  only

```bash
python3 <SAMEPAGE_ROOT>/samepage/cli.py \
    <HTML> --unit-selector body --label-format "Whole" --questions questions.json
```

| # | Rule |
|---|---|
| 1 | `--responses` and `--questions` can be combined (pass both in the same injection call) |
| 2 | Re-injecting without `--questions` clears the pins (only the most recently injected set of questions is ever shown — same behavior as the response layer) |
| 3 | The reviewer's answers land in the export JSON's `answers` array (rule 9 in section 4). Match by `questionId` against `id`, and treat answers as work instructions |
| 4 | **Never re-inject an already-answered question.** Treat a question whose `id` appears in the export JSON's `answers` as resolved. When re-injecting `--questions` (e.g. alongside a response layer), build a fresh questions JSON containing only unanswered and new questions. If everything is answered and there's nothing new, omit `--questions` entirely. Passing the original questions JSON back unchanged would show already-answered questions as unanswered again — the answered/unanswered state doesn't live in the HTML, and injection always treats whatever JSON it's given as authoritative |

## 7.5 Convention for generators: tag SVG diagrams with `data-sp-node` (prerequisite for diagram-node comments)

Comments/questions on diagram nodes only work when **the side generating the SVG has assigned
stable ids to its nodes**. When embedding an SVG diagram in an HTML deliverable (a report,
intent-doc, logic-tree, etc.), follow this convention:

```html
<g data-sp-node="spec-07" data-sp-label="Audit log is append-only">
  <rect .../>
  <text>Audit log is append-only</text>
</g>
```

| # | Rule |
|---|---|
| 1 | The value of `data-sp-node` must be **the node id from the source data** (for intent-doc, the IR's node id; for logic-tree, the logical node's identifier) — not a layout-derived sequence number (`g1`, `g2`, ...). The point is that the id survives even when regeneration changes the layout |
| 2 | Put it on the `<g>` that represents the semantic unit (the thing a human would point at as "this node"). Never put it on a bare `<rect>` or `<text>` |
| 3 | Put the node's display name in `data-sp-label` (used for fallback resolution when the id changes, and shown in the panel) |
| 4 | To make an edge (arrow) pickable too, wrap the edge's `<path>` in `<g data-sp-node="edge-e12">` and overlay **a transparent, wide hit-path of the same shape** in that same `<g>` (`stroke="transparent" stroke-width="14"`). A thin line alone has too tight a hit target and clicks fall through to the outer element |
| 5 | An SVG with no `data-sp-node` still works as before (the element itself is picked as `kind:"element"` via an nth-of-type path). But that path is fragile across regeneration, so always tag diagrams meant for a review round-trip |

The injection script never adds this attribute to SVG automatically — only the generator knows
the semantic unit.

## 8. Discussion blocks and finalizing (splitting off the publishable HTML once consensus is reached)

When the AI writes content into the body that shouldn't survive into the final deliverable ("notes
under consideration", "comparison of options", etc.), tag that element with `data-sp-discussion`.
The attribute must be written inside the tag (the literal string `data-sp-` appearing in body text
alone does not make it a target).

```html
<div data-sp-discussion>Notes under discussion here. Removed wholesale by finalize.</div>
```

Once every comment in the list is `resolved` (consensus reached), write out a publishable HTML
with the review layer and discussion blocks stripped, to a separate file.

```bash
python3 <SAMEPAGE_ROOT>/samepage/cli.py <HTML> --finalize --comments comments.json
```

| # | Rule |
|---|---|
| 1 | Don't run this before consensus (every comment `resolved`). Passing a comments JSON with any unresolved (`open`) comment to `--comments` aborts with an error. Only pass `--force` if you must proceed anyway |
| 2 | Omitting `--comments` skips the unresolved-comment check and just prints a warning before proceeding (it is not a "safe by default" — don't run finalize without `--comments` before consensus) |
| 3 | `--finalize` cannot be combined with `--unit-selector`/`--responses`/`--questions` (doing so aborts with an error) |
| 4 | The input HTML is left unchanged. The output defaults to `<input stem>.final.html` (override with `--out`) |
| 5 | Distribute/publish the `.final.html` side. Keep the HTML that still carries discussion blocks and the review layer as the review record |
