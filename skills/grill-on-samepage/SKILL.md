---
name: grill-on-samepage
description: |
  Use when a plan, design, or decision needs to be stress-tested with the human before any code
  is written, and the agreement itself should survive as a document rather than as chat history.
  Runs a round-based interview on a samepage HTML page: the agent writes an ALIGNMENT document,
  plants question pins on it, the human answers in the browser, and the loop repeats until every
  branch of the design tree is settled. The agreed document then becomes the project's SSOT, and
  the same page is reopened whenever implementation starts drifting from it.
  Triggers on requests like "let's nail down the design first", "grill me on this",
  "stress-test this plan", "I want the agreement written down".
  日本語のトリガー例:「設計を詰めたい」「詰めてほしい」「合意ドキュメントを作って」
  「samepage で詰めよう」「grill して」。
  Do not use for reviewing an existing HTML deliverable — that is the `samepage` skill.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/samepage/cli.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/docs/build_alignment_html.py *)
---

# Reach agreement on a samepage document, then treat it as the SSOT

The interview technique here — the design tree, the frontier, asking in rounds, and the split
between facts and decisions — is taken from the `grilling` skill in
[mattpocock/skills](https://github.com/mattpocock/skills) (MIT). This skill is an independent
implementation, not a fork: the wording and the mechanism are its own, because the questions are
delivered as pins on an HTML page rather than as a numbered list in a terminal.

## 1. The shape of a session

One session produces exactly one **ALIGNMENT document**: `docs/alignment/NNNN-slug.md`. It is the
source; the HTML beside it is generated. Fix the `.md`, never the `.html`.

```
docs/alignment/
  INDEX.md                  generated — the index across sessions
  0001-slug.md              the source of truth for one session
  0001-slug.html            generated, then injected with the review layer
  0001-slug.final.html      written by --finalize once consensus is reached
```

A session runs in **rounds**. A round asks the whole **frontier** — every decision whose
prerequisites are already settled — and then waits. Two questions never share a round if one
depends on the other; a question that hinges on an answer still open belongs to a later round.

## 2. The design tree notation

The `## design tree` section of the `.md` is the machine-readable spine of the document. The
builder parses it and renders the SVG; it will refuse to build on a violation.

```markdown
## design tree

- [D-1] 合意ドキュメントの種類 :: 確定 :: 単一 ALIGNMENT.md
  - [D-5] 実装スコープ :: 確定 :: ビルダーを作る
    - [D-13] 記法の具体 :: frontier
- [D-2] grilling との関係 :: 確定 :: 独立
  - [D-14] スクロール挙動 :: 保留
    - (依存) [D-4]
```

| # | Rule |
|---|---|
| 1 | Indent is **two spaces per level**; indentation is the parent/child relation |
| 2 | `[ID]` is unique within the document, numbered in order of appearance. **A retired id is never reused** — a decision that gets withdrawn and re-decided keeps its id, so the history stays followable |
| 3 | Fields are separated by `::` — title, state, decision |
| 4 | State is one of `確定` / `frontier` / `再検討` / `保留`. **Only a `確定` row carries the third field**, and a `確定` row must carry it |
| 5 | A node with more than one parent goes under its main parent, with a `- (依存) [ID]` child line for the extra edge. That line renders as a dashed edge, not as a node |

## 3. Running a round

1. **Find the facts yourself.** When a frontier question needs something the environment can
   settle — a licence, a library's behaviour, what the CI actually runs — dispatch a subagent or
   run the command. Never ask the human for something you could look up. Do not block the round on
   it: only the questions downstream of a running exploration wait. **The decisions are the
   human's; put each one to them and wait.**
2. **Write the material into the document body**, not into the pin. Each frontier decision gets a
   section with an options table carrying real pros and cons, and a recommendation with its
   reason. This is what survives into the SSOT — "why we decided that" has to be readable a month
   later.
3. **Build the HTML.** (Where `<SAMEPAGE_ROOT>` is the plugin/repository root two directories above this `SKILL.md`, i.e. `../..`, or `${CLAUDE_PLUGIN_ROOT}` in Claude Code.)
   ```bash
   python3 <SAMEPAGE_ROOT>/docs/build_alignment_html.py docs/alignment/NNNN-slug.md \
       --export export.json
   ```
   `--export` takes the human's most recent export JSON and prepends the 残件 block. Omit it on
   the first round.
4. **Write the questions JSON and inject the review layer.** Point each question at the section
   that holds the material, using a `text-range` target on the section heading — **not** at the
   design tree. The panel scrolls to the pin, so the pin's position is the jump destination.
   ```bash
   python3 <SAMEPAGE_ROOT>/samepage/cli.py docs/alignment/NNNN-slug.html \
       --unit-selector body --label-format "全体" --doc-id "alignment-NNNN" \
       --no-source-path --questions round-N.json --responses replies.json
   ```
   Keep `--doc-id` **stable for the whole session**: the human's comments and answers live in
   `localStorage` under that key, so changing it (or renaming the file without pinning it) throws
   the session's history away.
5. **Hand over the `file://` URL** and say what is being asked. Then wait.
6. **On the pasted export JSON**: apply the answers to the `.md`, move the settled nodes to
   `確定`, add the newly-unblocked nodes as `frontier`, reply to every comment via `--responses`,
   and start the next round. Follow the `samepage` skill's rules for reading the export.

| # | Rule |
|---|---|
| 1 | Put a recommendation on every question, with the reason. A question with no recommendation makes the human do your thinking |
| 2 | Say plainly when you cannot judge something. "You are the only one who knows how many existing users there are" is a useful sentence; a confident guess is not |
| 3 | 4–6 questions per round is the working range. More than that and the round stops being answerable in one sitting |
| 4 | **Never re-inject an answered question.** Build a fresh questions JSON each round holding only the unanswered and the new ones (`samepage` SKILL.md §7 rule 4) |
| 5 | Offer an option the human may actually want even when you disagree with it, and label your own pick `【推奨】` |

## 4. Withdrawing a settled decision

A settled decision whose premise turns out to be wrong **must be reopened, not quietly worked
around**. This happens: a fact arrives late, or the recommendation you wrote was mistaken.

1. Set the node's state to `再検討` and say in the section, in plain words, **which of your own
   claims was wrong and what the new evidence is**.
2. Reopen every node downstream of it — a decision made on a withdrawn premise is not settled.
3. Ask it again in the next round with the corrected material.
4. Keep the id. Rule 2 of §2 exists for exactly this case.

A comment on a `確定` node is a withdrawal request. Treat it as one.

## 5. Drift, once implementation starts

Two failure modes, each needing its own guard.

- **You notice.** Stop at that point, plant a question pin on the SSOT, and ask. Do not decide it
  yourself and do not carry on. The initial bar is deliberately loose: stop when the work would
  **explicitly break a settled decision**, not on every small divergence. Tighten it with
  experience.
- **You don't notice.** At milestones — before a PR, when a task completes — walk the settled
  decisions against what was actually built, and report the diff.

## 6. The consensus gate

An empty frontier is **not** the end of the session. The end is the human saying the
understanding is shared.

1. Regenerate with `--export` so the 残件 block is current. It counts answered pins, `open`
   comments, and unsettled nodes.
2. If anything is outstanding, say so and keep going.
3. If nothing is, present the remaining count **and the implementation order you intend to
   follow**, mapped to the decisions that justify each step, and ask for agreement. The human
   should know what they are agreeing to, not just that you ran out of questions.
4. Only after an explicit yes:
   ```bash
   python3 <SAMEPAGE_ROOT>/samepage/cli.py docs/alignment/NNNN-slug.html \
       --finalize --comments comments.json
   python3 <SAMEPAGE_ROOT>/docs/build_alignment_html.py --index docs/alignment
   ```
   `--finalize` refuses to run while any comment is `open`. Regenerating `INDEX.md` is what makes
   the new session visible to the next one.

| # | Rule |
|---|---|
| 1 | Never run `--finalize` before an explicit agreement, even with the frontier empty and zero 残件 |
| 2 | `--finalize` strips every `data-sp-*` attribute, including `data-sp-node` on the diagram. That is intended: re-injection always targets the generated HTML, never the finalized one |
| 3 | Keep the pre-finalize HTML. It is the review record — the questions, the replies, the discussion blocks |
| 4 | `INDEX.md` is generated. Never hand-edit it; put notes in the ALIGNMENT document instead |

## 7. What goes in the document, and what does not

| Content | Where |
|---|---|
| A decision, its rationale, and why the alternatives were rejected | The decision table. This is the point of the document |
| Terms this project uses in its own way | The glossary section, as `- **term** — definition`. `--index` merges these across sessions |
| Facts you looked up, with how you verified them | The facts section. Include the command and its output when you ran one |
| Options still under consideration, working notes, per-round measurements | A block tagged `data-sp-discussion`, so `--finalize` drops it |
| The interview transcript | Nowhere. The document records what was decided, not the conversation |

## 8. When not to use this

- The task is small enough that the plan fits in a sentence. A session has real cost; a
  three-line change does not earn one.
- The question cannot be settled by talking ("how should this feel?"). Build the throwaway
  version, look at it, then come back.
- There is an HTML deliverable that needs review comments. That is the `samepage` skill.
