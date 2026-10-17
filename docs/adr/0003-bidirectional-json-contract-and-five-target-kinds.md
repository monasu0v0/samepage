# ADR-0003: 自己記述型双方向 JSON 契約と 5 種類のターゲット表現

- **Status**: Accepted
- **Date**: 2026-10-17
- **Author**: monasu0v0 (<monasu0v0@gmail.com>)

## Context

人間が HTML 上で行ったレビューを AI エージェントに伝え、AI が修正と返信・質問を同じ HTML に戻すためには、人間と AI の双方にとって表現力が高く、かつ HTML の再生成（レイアウトや構造の微細な変化）に対して壊れにくいアンカー表現と JSON 契約が必要である。

特に以下の課題が存在した：
1. テキスト選択だけでは「この要素（表やセクション全体）を消したい」「A の段落と B の段落の間に新しい節を挿入したい」「SVG 図の中の特定ノードを直したい」「文書全体のトーンを変えたい」といった意図を表現できない。
2. Markdown 等から生成された HTML の場合、AI が HTML を直接編集してしまうと次回の再生成で修正が消えてしまう。また、HTML 再生成後に DOM 構造が変化すると、単純な XPath や CSS セレクタだけではアンカーが外れてしまう。
3. ユーザーがチャット欄に何の説明も添えず JSON だけをペーストした場合や、新しい会話セッションにペーストした場合でも、AI が対象ファイルの場所と処理ルールを即座に理解できる必要がある。

## Decision

1. **5 種類のターゲット種別（`targets[].kind`）と多段階フォールバックの採用**
   - `text-range`: `selectedText` と前後 40 文字の `contextBefore` / `contextAfter` により、同一語句が複数あっても特定可能にする。
   - `element`: ID や class に依存しない `nth-of-type` チェーン（`path`）を主キーとし、構造変化時は `tag` + `nearText`（先頭 60 文字）で近傍フォールバックする。
   - `insertion-point`: 要素の上下端 8px 以内のクリックで「要素の直前／直後」を表現し、`afterPath`（フォールバック: `afterTag` + `nearText`）および `beforePath`（フォールバック: `beforeTag` + `nearText`）の双方を記録する。
   - `diagram-node`: ドキュメント生成側が SVG の `<g>` に付与した安定 ID（`data-sp-node`）と表示名（`data-sp-label`）を拾い、`nodeId` → `nodeLabel` → `nearText` の順で解決する。これによりレイアウト座標が変わっても生成元のノードを一意に特定できる。
   - `document`: 特定箇所に紐づかない文書全体へのコメントを表現する。
2. **複数ターゲットと動詞パレット（`action`）**
   - 1 つのコメントが複数の `targets[]` を持てるようにし、`move`（1 つ目を `role: "source"`、2 つ目を `role: "destination"` として移動）、`insert`、`delete`、`shorten`、`keep`（明示的な現状維持の承認 👍）の 5 種のアクションを構造化して伝達する。
3. **自己記述型 Handoff ヘッダの同梱**
   - エクスポート JSON の先頭に `_howto`、`_skill: "samepage"`、`_rules`（10 項目の厳密な解決ルール）、および `sourceHtml`（注入対象 HTML の絶対パス。配布時は `--no-source-path` で `null` 化可能）を必ず出力する。
   - ルール 1 として「HTML が生成物である場合は HTML を直接編集せず、生成元のソース（同名の `.md` 等）を修正して再生成せよ」を明記する。
4. **双方向の Responses JSON / Questions JSON 契約**
   - AI からの返信（`--responses`）は `fixed` / `declined` / `partial` / `noted` のステータスと修正後アンカー `fixedText` を持ち、緑色のハイライトで修正箇所を示す。
   - AI から人間への逆質問（`--questions`）は任意の `target` と選択肢 `choices` を持ち、本文上の質問ピン（❓）としてレンダリングされる。回答は次回エクスポート JSON の `answers[]` に格納される。

## Alternatives Considered

- **単一ターゲットのみのコメント構造**: 「A を B の位置へ移動する」という指示を 2 つの別々のコメントに分けると AI 側で関連付けを誤るため、1 コメント内の `targets[]` 配列で表現する方式を採った（後方互換のため先頭の `text-range` フィールドはトップレベルにも複製）。
- **CLI による SVG ノードへの自動 ID 付与**: CLI はどの `<g>` が意味的なノードか（あるいは単なる装飾グループか）を知り得ないため、自動付与は行わず、生成側がソース上の安定 ID を `data-sp-node` として付与する規約とした。

## Consequences

- **Positive**:
  - テキスト・要素・隙間・SVG 図・文書全体のあらゆる粒度で人間と AI が位置を指し示して対話できる。
  - JSON を無言で AI チャットに貼り付けるだけで、対象ファイルの特定から原本修正・返信注入までが自律的に回る。
- **Negative / Trade-offs**:
  - `samepage.js` 内の `HANDOFF_RULES` と `skills/samepage/SKILL.md` §4 のルール表の 2 箇所を同期させる必要がある（仕様書と `AGENTS.md` / `SKILL.md` に同期規約を明記して担保）。
