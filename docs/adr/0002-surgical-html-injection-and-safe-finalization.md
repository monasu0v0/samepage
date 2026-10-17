# ADR-0002: 文字列手術による HTML インジェクションと 5 段階の Finalize パイプライン

- **Status**: Accepted
- **Date**: 2026-10-17
- **Author**: monasu0v0 (<monasu0v0@gmail.com>)

## Context

`samepage/cli.py` は任意の既存 HTML ファイルに対して以下を行う必要がある。
1. `--unit-selector` で指定された要素への `data-sp-unit`, `data-sp-label`, `data-sp-index` 属性の追加。
2. `</body>` 直前へのレビュー層ブロック（`<!-- samepage:begin -->` … `<!-- samepage:end -->`）の冪等な注入・置換。
3. `--finalize` による、レビュー層・議論用ブロック（`data-sp-discussion`）・ランタイム装飾の完全な除去と公開用 HTML の出力。

ここで HTML 全体をパーサに通して DOM ツリーを構築し、再度文字列にシリアライズする方式を採ると、元の HTML に含まれるインライン `<script>` の生テキスト、文字参照（`&nbsp;` や数値文字参照）、属性のクォートスタイル、インデントや改行が勝手に書き換えられ、元の文書を破壊してしまう。

また、レビュアーがブラウザ上でコメントを付けた状態のライブ DOM を「名前を付けてページを保存」した場合、JS ランタイムが動的に挿入した `<mark class="sp-mark">` や質問ピン（`.sp-qpin`）が静的 HTML に焼き付くため、単にマーカーブロックだけを消しても公開用 HTML にならないという課題があった。

## Decision

1. **`html.parser.HTMLParser` はオフセット特定のみに使い、変更は文字列スライス手術（String Surgery）で行う**
   - `HTMLParser(convert_charrefs=False)` を継承したコレクタ（`_TagSpanCollector`, `_DiscussionSpanCollector`, `_RuntimeMarkSpanCollector`, `_StartTagSpanCollector`）で元の文字列上の開始位置・終了位置（オフセット）だけを記録する。
   - 実際の挿入・削除はオフセットの大きい順（末尾から先頭へ向かう逆順）に文字列スライスで行う。これにより、触っていない領域は入力 HTML と 1 バイト単位で完全一致する。
2. **インライン `<script>` への安全な JSON 埋め込み**
   - `window.SAMEPAGE_CONFIG`、`window.SAMEPAGE_RESPONSES`、`window.SAMEPAGE_QUESTIONS` を `<script>` 内にインライン展開する際、自由記述テキスト内に `</script>` が含まれていてもタグが閉じないよう、`json.dumps()` の結果に対して `.replace("</", "<\\/")` を適用する。
3. **5 段階の厳密な順序による `--finalize` パイプライン**
   - `finalize_html()` は以下の順序で除去を行う：
     1. `strip_discussion_elements`: `data-sp-discussion` を持つ要素を開始タグから終了タグまで丸ごと除去。
     2. `strip_runtime_decorations`: `.sp-qpin`, `.sp-qpin-svg`, `.sp-insert-mark`, `.sp-node-halo` を要素ごと除去し、`mark.sp-mark` / `mark.sp-mark-fixed` はタグのみを剥がして内部テキストを保持。
     3. `strip_marker_block`: `<!-- samepage:begin -->` … `<!-- samepage:end -->` を除去。
     4. `strip_sp_data_attrs`: `_StartTagSpanCollector` で収集した**開始タグの範囲内でのみ** `data-sp-*` 属性を正規表現で除去（本文やコードブロック内に書かれたリテラルの `data-sp-unit="x"` 等を絶対に破壊しない）。
     5. `strip_runtime_mark_class_token`: 開始タグ内の `sp-mark-el` クラストークンを除去。
4. **アトミック書き込みと配布用ファイル権限の保証**
   - 一時ファイル（`.sp-tmp`）へ書き出してから `os.replace` で置換する。
   - 既存ファイルの上書き時は `shutil.copymode` で元の権限を維持し、`--finalize` などで新規ファイル（`<stem>.final.html`）を作る際は `mkstemp` の `0600` のままにせず `0o666 & ~umask` を適用して他者が読める公開用権限にする。

## Alternatives Considered

- **正規表現のみでのタグ検索**: 本文や `<script>` 内の文字列、あるいは属性値内の `>` に誤反応するため却下。`HTMLParser` で開始タグスパンを正確に特定した上で、そのスパン内部にのみ正規表現を適用するハイブリッド方式を採用した。
- **マーカーブロックと `data-sp-unit` だけを削除する簡易 Finalize**: ライブ DOM 保存時や SVG ハロー・要素ハイライトが残ってしまうため、ランタイム装飾も含めた 5 段階方式を採用した。

## Consequences

- **Positive**:
  - 元の HTML のフォーマットや `<script>`、文字実体参照が一切壊れない。
  - 本文中で `samepage` 自身の属性名（`data-sp-node` 等）を解説しているドキュメント（`README.html` や仕様書自身）に対して `--finalize` をかけても、本文中のコード例が一切消えない。
  - 配布用 `.final.html` が適切なファイルパーミッションで生成される。
- **Negative / Trade-offs**:
  - `--unit-selector` で解釈できるセレクタは `tag`, `.class`, `#id`, `tag.class` の単純セレクタに限定される（実用上 `body`, `section`, `.slide` 等で十分カバーできるため許容）。
