# samepage 仕様書 (Specification)

> バージョン: 0.1.0  
> 作者: monasu0v0 (<monasu0v0@gmail.com>)  
> [English Specification](specification.md)

## 1. 概要とスコープ

**samepage** は、静的 HTML ドキュメントに対して着脱可能なサーバーレスのレビューコメント層を注入するツール、およびその上で動作する対話型設計合意ループ（`grill-on-samepage`）です。

人間のレビュアーと AI コーディングエージェント（Google Antigravity、Claude Code、Codex、Cursor などの各種エージェント）の間で、以下の双方向ネゴシエーションを実現します。

1. **人間 → AI**: 人間は `file://` で HTML をブラウザで開き、テキスト範囲・DOM 要素・要素間の挿入位置・SVG 図のノード・文書全体の 5 種類のターゲットに対してコメントや質問ピンへの回答を入力し、自己記述型の単一 JSON をクリップボードにコピーして AI に渡します。
2. **AI → 原本（Source）**: AI エージェントは HTML そのものではなく**生成元の原本**（Markdown や IR 等から生成された HTML ならそのソース、手書き HTML なら HTML 自身）を修正して再生成します。
3. **AI → 人間**: AI は修正内容の返信（`--responses`）や、判断を仰ぐための逆質問ピン（`--questions`）を同じ HTML に再注入します。
4. **合意 → Finalize**: 全コメントが解決（`resolved`）し合意に達したら、`--finalize` によってレビュー層・ランタイム装飾・検討用ブロック（`data-sp-discussion`）を完全に除去した公開用 HTML（`<stem>.final.html`）を切り出します。

---

## 2. コア設計原則

1. **ランタイム外部依存ゼロ (Zero Runtime Dependencies)**: CLI（`samepage/cli.py` および `samepage/assets.py`）は Python 3.9+ 標準ライブラリのみで動作します。ブラウザ側ランタイム（`samepage.js`, `samepage.css`, `panel.html`）も外部ライブラリや CDN を一切使わない ES5 互換 Vanilla JS（IIFE 構造）/ CSS で完結します。
2. **サーバーレス (`file://` 完結)**: ローカルの `file://` プロトコル、`localStorage`、およびブラウザの Clipboard API（未対応環境向けの画面外 `<textarea>` + `document.execCommand('copy')` フォールバック付き）のみで動作し、ローカル Web サーバー・ブラウザ拡張・外部アカウントを一切必要としません。
3. **バイト保持型の文字列手術による HTML 操作**: HTML パーサで DOM ツリーを再シリアライズすると、`<script>` 内の生テキストや文字参照・空白が破壊されます。`samepage` は `html.parser.HTMLParser`（`convert_charrefs=False`）を開始タグ・終了タグの文字オフセット特定のみに使用し、実際の属性付与・削除は末尾からの逆順文字列スライス置換で行うため、対象外の領域は 1 バイトたりとも変化しません。
4. **自己記述型ハンドオフ契約 (Self-Contained Handoff)**: エクスポート JSON には `_howto`, `_skill`, `_rules`, `sourceHtml` が同梱されており、スキル未導入の環境や新規セッションに JSON だけを貼り付けても AI が迷わず処理できます。

---

## 3. CLI 仕様 (`samepage/cli.py` & `samepage/assets.py`)

### 3.1 コマンド体系とオプション

```text
python3 samepage/cli.py <input> [options]
```

| 引数 / オプション | 型 | 既定値 | 説明 |
|---|---|---|---|
| `input` | 位置引数 | （必須） | 対象の HTML ファイルパス。 |
| `--unit-selector SEL` | 文字列 | `None` | 単位要素の簡易セレクタ（`tag`, `.class`, `#id`, `tag.class`）。一致した要素に `data-sp-unit`, `data-sp-label`, `data-sp-index` を付与する。 |
| `--label-format FMT` | 文字列 | `"{n}"` | 単位ラベルのフォーマット（`{n}` が 1 始まりの連番に展開される）。 |
| `--doc-id ID` | 文字列 | `<input.stem>` | JSON の `doc` フィールドおよび `localStorage` キー（`samepage:<doc>`, `samepage-answers:<doc>`）に使われる識別子。 |
| `--jump {scroll,hash}` | 列挙値 | `"scroll"` | パネルから単位要素へジャンプする方式（`scroll`: `scrollIntoView` / `hash`: `location.hash = '#' + index`）。 |
| `--out PATH` | パス | `<input>`（`--finalize` 時は `<stem>.final.html`） | 出力先ファイルパス。 |
| `--responses PATH` | パス | `None` | 返信 JSON を検証し `window.SAMEPAGE_RESPONSES` として埋め込む。 |
| `--questions PATH` | パス | `None` | 質問ピン JSON を検証し `window.SAMEPAGE_QUESTIONS` として埋め込む。 |
| `--no-source-path` | フラグ | `False` | `sourcePath` に `out_html.resolve()` の絶対パスではなく `null` を埋め込む（配布・Git コミット用 HTML では必須）。 |
| `--finalize` | フラグ | `False` | レビュー層・ランタイム装飾・`data-sp-discussion` 要素を除去した公開用 HTML を別ファイルに出力する。注入オプションとの併用不可。 |
| `--comments PATH` | パス | `None` | `--finalize` 実行前に未解決（`status == "open"`）のコメントが残っていないか検査するコメント JSON。 |
| `--force` | フラグ | `False` | `--comments` に未解決コメントがあっても `--finalize` を強行する。 |

### 3.2 セレクタ解析と単位属性（Unit Attributes）の注入仕様

`parse_selector(selector)` は以下の 2 つの正規表現を用いて 4 種類の簡易セレクタ（`tag`, `.class`, `#id`, `tag.class`）のみを受理します。

```python
SIMPLE_SELECTOR = re.compile(r"^(?:([a-zA-Z][\w-]*))?(?:\.([\w-]+))?$")
ID_SELECTOR = re.compile(r"^#([\w-]+)$")
```

- `ID_SELECTOR` に一致した場合は `(None, None, elem_id)` を返します。
- `SIMPLE_SELECTOR` に一致し、かつグループ 1（`tag`）またはグループ 2（`cls`）の少なくとも一方が非空であれば `(tag, cls, None)` を返します。
- いずれにも該当しない場合は `ValueError("unsupported selector: ... (only tag / .class / #id / tag.class)")` を送出します。

`_TagSpanCollector`（`HTMLParser(convert_charrefs=False)` のサブクラス）は、改行位置から計算した `self.line_offsets` を用いて `(line, col)` を 0 始まりの文字オフセットへ変換し、条件に一致する開始タグを `{"start": start, "end": start + len(text), "attrs": attrd}` として収集します。
- タグ判定: `want_tag` 指定時は `tag == want_tag`。
- クラス判定: `want_cls` 指定時は空白分割したトークン配列 `attrd.get("class", "").split()` に含まれること。
- ID 判定: `want_id` 指定時は `attrd.get("id") == want_id`。

`add_unit_attrs(html, selector, label_format="{n}")` は一致した要素を 1 始まりの連番 `n`（`enumerate(hits, start=1)`）で走査します。
- **冪等性と連番の維持**: すでに `"data-sp-unit"` が `hit["attrs"]` に存在する要素は属性挿入をスキップしますが、**連番 `n` は消費**し、ホストページ側のハッシュジャンプ番号との整合性を維持します。
- **付与される属性値**:
  - `unit = hit["attrs"].get("id") or f"u{n}"`
  - `label = label_format.replace("{n}", str(n))`
  - `index = str(n)`
  - 属性値は `_attr_escape(value)`（`&` → `&amp;`, `"` → `&quot;`, `<` → `&lt;`, `>` → `&gt;`）でエスケープされます。
- **挿入位置**: 開始タグの終端が `/>` なら末尾 2 文字手前、通常の `>` なら末尾 1 文字手前（`offset = hit["end"] - (2 if tag_text.endswith("/>") else 1)`）を挿入位置とし、前方オフセットがずれないよう逆順（`sorted(inserts, reverse=True)`）で文字列挿入します。

### 3.3 入力 JSON バリデーション契約

```python
VALID_ACTIONS = ("fixed", "declined", "partial", "noted")
VALID_TARGET_KINDS = ("text-range", "element", "insertion-point", "diagram-node", "document")
```

- **`load_responses(path)`**:
  - トップレベルが `"responses"` リストを持つ `dict` であること。
  - 各要素 `r` が `dict` であり、`r["id"]` と `r["reply"]` が空白のみでない文字列（`isinstance(v, str) and v.strip()`）であること。
  - `r.get("action")` が省略（`None`）された場合は `"fixed"` を補完し、指定されている場合は `VALID_ACTIONS` のいずれかであること。
  - `r.get("fixedText")` は `None` または `str` であること。
- **`load_questions(path)`**:
  - トップレベルが `"questions"` リストを持つ `dict` であること。
  - 各要素 `q` が `dict` であり、`q["id"]` と `q["question"]` が空白のみでない文字列であること。
  - `q.get("target")` が `None` でない場合、`dict` かつ `target.get("kind") in VALID_TARGET_KINDS` であること。特に `kind == "diagram-node"` の場合は `target.get("nodeId")` が非空文字列として必須。
  - `q.get("choices")` が `None` でない場合、すべての要素が `str` の `list` であること。
- **`collect_open_comments(path)`**:
  - トップレベルが `"comments"` リストを持つ `dict` であること。
  - `[c.get("id", "?") for c in data["comments"] if isinstance(c, dict) and c.get("status") == "open"]` を返します。

### 3.4 終了コードと拒否条件

- **`0`**: 正常終了。
- **`2`**: バリデーションエラーまたは安全のための処理拒否:
  - 入力ファイルまたは指定された JSON ファイルが存在しない、あるいは UTF-8 デコードに失敗（`UnicodeDecodeError`）した場合。
  - 初回注入対象の HTML に `</body>` タグが存在しない場合（`html.rfind("</body>") < 0`）。
  - `<!-- samepage:begin -->` と `<!-- samepage:end -->` の片方だけが存在する場合（`has_begin != has_end`、手動編集による破損検知）。
  - `--unit-selector` が未対応の構文、または一致する要素が `0` 件の場合。
  - `--responses`, `--questions`, `--comments` の JSON スキーマ検証（`ValueError`）に失敗した場合。
  - `--finalize` と注入用オプション（`--unit-selector`, `--responses`, `--questions`）を同時に指定した場合。
  - `--finalize --comments <file>` で `status == "open"` のコメントが存在し、`--force` がない場合（なお `--finalize` 時に `--comments` が未指定の場合は `stderr` に警告を出して続行します）。

### 3.5 アトミック書き込みとパーミッション管理

`_write_atomic(path, text)` により、書き込み途中のクラッシュによるファイル破損を防ぎます。
1. `tempfile.mkstemp(dir=str(path.parent), suffix=".sp-tmp")` で出力先と同じディレクトリに一時ファイルを作成。
2. UTF-8 でテキストを書き込み。
3. 既存ファイルの上書き時（`path.exists()`）は `shutil.copymode(str(path), tmp)` で元のファイル権限を維持。
4. 新規ファイル作成時（`<stem>.final.html` など）は、`mkstemp` 固有の `0600` のままにせず、プロセスの `umask`（`umask = os.umask(0); os.umask(umask)`）に従った `os.chmod(tmp, 0o666 & ~umask)` を適用して配布可能な読み取り権限を確保。
5. `os.replace(tmp, str(path))` でアトミックに置換（例外発生時は `tmp` を確実に `unlink`）。

---

## 4. HTML インジェクションと DOM 契約

### 4.1 予約プレフィックス・属性一覧

| 属性 / トークン | 付与主体 | 用途 | `--finalize` での扱い |
|---|---|---|---|
| `<!-- samepage:begin -->` … `<!-- samepage:end -->` | CLI (`assets.py`) | `</body>` 直前に注入される冪等ブロックの境界マーカー。 | ブロックごと削除（直後の `\n` 含む） |
| `data-sp-unit`, `data-sp-label`, `data-sp-index` | CLI (`--unit-selector`) | 単位要素の識別子・表示ラベル・1 始まり連番。 | 属性のみ削除 |
| `data-sp-node`, `data-sp-label` | ドキュメント生成側 | インライン SVG 図内の意味単位ノード（`<g>`）の安定 ID と表示名。 | 属性のみ削除 |
| `data-sp-discussion` | 作成者 / 生成スクリプト | 検討中のメモ、選択肢比較、残件ブロックなど、合意後の公開物に残すべきでない要素。 | 要素と中身ごと削除 |
| `data-sp-cmt-id`, `data-sp-resp-id`, `data-sp-q-id` | ランタイム (`samepage.js`) | ハイライト・ピン・パネル項目と各 ID の紐付け。 | 属性のみ削除 |
| `data-sp-badge`, `data-sp-action` | ランタイム / UI | 複数ターゲット番号バッジ（`"1"`, `"2"`、CSS `::before` で描画）およびアクション指定。 | 属性のみ削除 |
| `mark.sp-mark`, `mark.sp-mark-fixed` | ランタイム (`samepage.js`) | テキスト選択範囲のハイライト要素（解決時は `.sp-mark-resolved` 付与）。 | タグを剥がし内部テキストを保持 |
| `.sp-qpin`, `.sp-qpin-svg`, `.sp-insert-mark`, `.sp-node-halo` | ランタイム (`samepage.js`) | 質問ピン・挿入位置バー・SVG ノードの後光装飾（`.sp-node-halo-resolved`, `.sp-qpin-answered`）。 | 要素と中身ごと削除 |
| `.sp-mark-el` | ランタイム (`samepage.js`) | 要素ターゲットに付与されるハイライト用クラス。 | クラストークンのみ削除 |

### 4.2 注入ブロックの組み立てとインライン JSON の安全埋め込み (`samepage/assets.py`)

`assets.render_block(doc_id, jump="scroll", storage_key=None, responses=None, questions=None, source_path=None)` は `doc_id`（非空必須）と `jump in ("scroll", "hash")` を検証した上で、厳密に以下の順序で注入ブロック文字列を組み立てます。
1. `<!-- samepage:begin -->`
2. `<style>\n{samepage.css}\n</style>`
3. `{panel.html}`
4. `<script>window.SAMEPAGE_CONFIG={_embed_json(config)};</script>`（`config` は `{"doc": doc_id, "jump": jump, "storageKey": storage_key or f"samepage:{doc_id}", "sourcePath": str(source_path) if source_path else None}`）
5. `responses is not None` の場合: `<script>window.SAMEPAGE_RESPONSES={_embed_json(responses)};</script>`
6. `questions is not None` の場合: `<script>window.SAMEPAGE_QUESTIONS={_embed_json(questions)};</script>`
7. `<script>\n{samepage.js}\n</script>`
8. `<!-- samepage:end -->\n`

**`<script>` タグ早期終了の防止**:
- `_read_asset(name)` はアセットファイル内に `"</script"`（小文字化して検査）が含まれていないことを事前に検証します。
- `_embed_json(value)` は `json.dumps(value, ensure_ascii=False).replace("</", "<\\/")` により、すべての `</` を `<\/` にエスケープします。これにより、自由記述の返信文や質問文に `</script>` が含まれていても `<script>` タグが早期終了しないことを保証します。
- `inject_block(html, block)` は、既存マーカーがあれば `MARKER_BEGIN` から `MARKER_END` までを `block.rstrip("\n")` でインプレース置換し、なければ最後の `</body>`（`html.rfind("</body>")`）の直前に挿入します。

---

## 5. ブラウザランタイムとターゲット解決仕様 (`samepage.js`)

### 5.1 初期化順序と `localStorage` キー

- **ストレージキー**:
  - コメント一覧: `STORAGE_KEY = CFG.storageKey || "samepage:default"`（CLI 既定値: `"samepage:" + doc_id`）。
  - 質問ピンへの回答: `ANSWERS_KEY = "samepage-answers:" + DOC_ID`。
- **`init()` の厳密な実行順序**:
  1. `localStorage` からコメントを読み込み、`normalizeComment(c)` で正規化（`targets[]` を持たない旧形式のコメントを `label: "1", kind: "text-range"` の 1 要素配列へ変換）した上で、各ターゲットに対して `anchorTarget(c, t)` を実行。
  2. 埋め込まれた `RESPONSES` の各要素に対して `anchorResponse(r)` を実行。
  3. `localStorage` から回答を読み込み、`QUESTIONS` の各要素に対して `anchorQuestion(q)` を実行。**順序上の重要制約**: `anchorQuestion` の `text-range` アンカーは `splitText()` によって DOM のテキストノードを分割するため、`buildFlatMap` のオフセットがずれないよう、必ずコメントとレスポンスのアンカー完了後に実行しなければなりません。
  4. `refreshQuestionPins()`, `renderQuestions()`, `renderPanel()` を呼び出して描画を完了。

### 5.2 キーボードショートカット・IME 保護・ホストページ隔離

すべてのキー操作は `document` のキャプチャフェーズ（`useCapture = true`）で処理されます。
- **IME 変換保護**: `isImeComposing(e)` は、`compositionstart` / `compositionend` キャプチャリスナが管理するフラグ `imeComposing`、`e.isComposing === true`、または `e.keyCode === 229` のいずれかが真のときに `true` を返し、変換確定の Enter やキャンセルの Escape を誤って奪わないようにします。
- **モーダルおよび入力欄でのイベント遮断**:
  - `#spJsonModal` が開いている間（`isJsonModalOpen()`）は全キーイベントで `e.stopPropagation()` を呼び、`Escape` でモーダルを閉じます。
  - フォーカスが `TEXTAREA` または `INPUT` にある場合も `e.stopPropagation()` でホストページのショートカット誤発火を遮断します。`#spPopupText`（新規コメント欄）および `.sp-edit-textarea`（インライン編集欄）では、非 IME 変換時の `Enter`（`Shift` なし）で保存、`Escape` でキャンセルを行います。
- **単一キーショートカット**（`TEXTAREA`/`INPUT` 外、モーダル閉、かつ `ctrlKey`/`metaKey`/`altKey` なしの時）:
  - `a` / `A`: `pendingSelection` があれば `text-range` ターゲットとして追加し、コメント入力ポップアップを開く。
  - `e` / `E`: 要素選択モード（`startPickMode`）を開始。すでにポップアップが開いている場合（`popupOpen === true`）は選択中のみ `popup.style.visibility = 'hidden'` にして背後の要素を選びやすくし、選択完了または `Escape` キャンセル時に表示を復元して同一コメントにターゲットを追加する。
  - `c` / `C`: 右側のコメント・質問一覧パネル（`#spPanel.open`）を開閉する。
  - `j` / `J`: エクスポート JSON を直接クリップボードへコピー（`copyJsonDirect`）し、`#spBadge` と `#spJsonCopyDirect` の両方に `"✓ Copied"`（対象が 0 件なら `"No comments yet"`）を `1500ms` 間フラッシュ表示する。
- **ホストクリック遮断**: `document` の `click` キャプチャリスナにより、samepage UI 外で非空のテキスト選択が存在する間のクリックイベントは `e.stopPropagation()` され、テキスト選択直後にスライド送り等のホスト側クリックハンドラが誤発火するのを防ぎます。

### 5.3 5 種のターゲット (`targets[].kind`) とフォールバック連鎖

1 つのコメントは `targets[]` 配列に複数箇所を持つことができ、ラベル `"1"`, `"2"`, …（2 件以上のときはパネルやチップ上で丸数字 `①`〜`⑨` として表示）が付与されます。

#### 1. `text-range`（テキスト範囲）
- **生成時**: samepage UI 外での `mouseup` 時に、`window.getSelection().toString().trim()` が非空であり、`range.startContainer` が `[data-sp-unit]` 要素内にある場合に生成されます。
  - `buildFlatMap(unitEl)` は `document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false)` で配下の全テキストノードを走査し、生の `nodeValue`（空白正規化なし）を連結した `{text, nodes, offsets}` を構築します。
  - `contextBefore` は `map.text.slice(Math.max(0, startFlat - 40), startFlat)`（直前最大 40 文字）。
  - `contextAfter` は `map.text.slice(endFlat, endFlat + 40)`（直後最大 40 文字）。
  - すでに `popupOpen === true` であれば `#spSelectBtn` を経由せず即座に `pendingTargets` に追加され、そうでなければ選択範囲付近に `#spSelectBtn`（`💬 Comment`）を表示します。
- **解決ロジック (`locateText(root, target, contextBefore, contextAfter)`)**:
  - `root`（コメントは `unitElement(t.unit || c.unit)`、レスポンスおよび質問ピンは `(unit && unitElement(unit)) || document.body`）に対して `buildFlatMap(root)` を作成。
  - `map.text` 内で `target` が現れるすべての開始位置 `occ` を収集（`from = p + 1` で 1 文字ずつ前進）。
  - `occ.length === 0` なら `null`（`anchored = false`）を返します。
  - `occ.length === 1` なら `occ[0]` を採用。
  - `occ.length > 1`（複数箇所に一致）の場合は各候補位置 `o` をスコアリング:
    - `before = text.slice(Math.max(0, o - 40), o)`
    - `after = text.slice(o + target.length, o + target.length + 40)`
    - `contextBefore` が非空かつ `before.indexOf(contextBefore.slice(-20)) >= 0`（末尾 20 文字が含まれる）なら `score++`。
    - `contextAfter` が非空かつ `after.indexOf(contextAfter.slice(0, 20)) >= 0`（先頭 20 文字が含まれる）なら `score++`。
    - `score` の降順（同点なら出現順）でソートし、最高得点の `scored[0].o` を採用。
  - `chosen` が含まれるテキストノード `node` を特定し、`localStart = chosen - start`、`markLen = Math.min(target.length, node.nodeValue.length - localStart)`（単一テキストノード内にクランプ）を返します。
- **DOM ハイライト**:
  - `insideSvg(loc.node)` が真（`namespaceURI === 'http://www.w3.org/2000/svg'`）の場合、SVG テキスト内に HTML の `<mark>` や `<span>` を挿入すると描画が壊れるため、`anchorTextTarget` と `anchorResponse` はハイライト要素を挿入せずに `true`（アンカー成功）を返し、`anchorQuestion` は `false`（パネル表示のみ）を返します。
  - 通常の HTML テキストであれば `wrapMark` が `<mark class="sp-mark">`（レスポンスは `sp-mark-fixed`）で `range.surroundContents(mark)` を実行します（要素境界をまたぐ等で `surroundContents` が例外を投げた場合も位置自体は特定できているため `true` を返します）。

#### 2. `element`（要素自体）
- **生成時**: `e` モードで要素の上端・下端から `EDGE = 8` px を超える内側をクリックした際に生成されます。
  - `path`: `cssPath(el)` により、`el` から `document.body`（を含まない手前）まで親を辿り、同タグ名の先行兄弟数を数えた `tag:nth-of-type(idx)` を `'body > ...'` 形式で連結（`id` や `class` に一切依存しないパス）。
  - `tag`: `el.tagName.toLowerCase()`。
  - `nearText`: `nearTextOf(el)` — `(el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60)`（連続空白を単一スペースに正規化し先頭 60 文字を切り出し）。
- **解決とフォールバック連鎖 (`resolveByPath(path, tag, nearText)`)**:
  1. 第 1 候補: `document.querySelector(path)`（`try/catch` 保護）を実行し、要素が見つかればそれを返します。
  2. フォールバック: `path` で見つからず、`tag` と `nearText` の両方が指定されている場合、`document.getElementsByTagName(tag)` を先頭から走査し、`#spPanel, #spPopup, #spJsonModal` 内の要素を除外した上で、`nearTextOf(cand) === nearText`（正規化後先頭 60 文字の完全一致）を満たす最初の要素を返します。
- **DOM ハイライト**: 要素に `.sp-mark-el` クラス、`data-sp-cmt-id`、および複数ターゲット時は `data-sp-badge` を付与します。

#### 3. `insertion-point`（要素間の挿入位置）
- **生成時**: `e` モード（かつ親拡大前 `pickLevel === 0`）で要素の上端 `EDGE = 8` px 以内（`where = 'before'`）または下端 `8` px 以内（`where = 'after'`）をクリックした際に生成されます。
  - `prev = (where === 'before') ? el.previousElementSibling : el`
  - `next = (where === 'before') ? el : el.nextElementSibling`
  - フィールド:
    - `afterPath: prev ? cssPath(prev) : null`
    - `beforePath: next ? cssPath(next) : null`
    - `afterTag: prev ? prev.tagName.toLowerCase() : null`
    - `beforeTag: next ? next.tagName.toLowerCase() : null`
    - `nearText: nearTextOf(prev || next)`
- **解決とフォールバック順序**:
  - **コメントのアンカー (`anchorInsertionTarget(c, t)`)**:
    1. `t.afterPath` があれば `after = resolveByPath(t.afterPath, t.afterTag, t.nearText)` を試みます（`afterPath` → 外れたら `afterTag + nearText` でフォールバック）。
    2. `after` が見つからず（`!after`）、かつ `t.beforePath` があれば `before = resolveByPath(t.beforePath, t.beforeTag, t.nearText)` を試みます（`beforePath` → 外れたら `beforeTag + nearText` でフォールバック）。
    3. いずれも解決できなければ `false` を返します。
    4. `<span class="sp-insert-mark">` を作成し、`after` が解決できた場合は `after.parentNode.insertBefore(markEl, after.nextSibling)`（`after` の直後）、そうでなければ `before.parentNode.insertBefore(markEl, before)`（`before` の直前）に挿入します。
  - **質問ピンのアンカー (`anchorQuestion(q)`)**:
    1. `after = t.afterPath ? resolveByPath(t.afterPath, null, null) : null` および `before = t.beforePath ? resolveByPath(t.beforePath, null, null) : null`（`nearText` フォールバックなしの厳密パス解決）を実行します。
    2. `after && after.parentNode` なら `after.nextSibling` の直前にピンを挿入し、そうでなければ `before && before.parentNode` のとき `before` の直前に挿入します。

#### 4. `diagram-node`（SVG 図中の意味単位ノード）
- **生成時と SVG 祖先スナップ**:
  - `pickTargetAt(e)` において、ホバーされた要素 `el` が SVG 名前空間（`el.namespaceURI === 'http://www.w3.org/2000/svg'`）に属する場合、`diagramNodeOf(el)` が `el.closest('[data-sp-node]')` で最も近い祖先 `[data-sp-node]` を探します。
  - `[data-sp-node]` が存在すればその要素へスナップし、存在しなければ `el` 自体を選択します（SVG 内には挿入位置の概念がないため常に `where: null`）。
  - `data-sp-node` を持つ要素をクリックすると以下を生成します:
    - `kind: 'diagram-node'`
    - `nodeId: el.getAttribute('data-sp-node')`
    - `nodeLabel: el.getAttribute('data-sp-label') || null`
    - `nearText: diagramNearText(el)` — `el.cloneNode(true)` からランタイム装飾 `.sp-qpin-svg, .sp-node-halo` を除去した上で `(clone.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60)` を算出。
- **解決とフォールバック連鎖 (`resolveDiagramNode(nodeId, nodeLabel)`)**:
  1. 第 1 候補: `nodeId` があれば `document.querySelector('[data-sp-node="' + cssEsc(nodeId) + '"]')` を検索。
  2. フォールバック: `nodeId` で見つからず `nodeLabel` が指定されている場合、`document.querySelectorAll('[data-sp-node]')` を走査し、`getAttribute('data-sp-label') === nodeLabel` に一致する最初の要素を返します。
  3. いずれも見つからなければ `null` を返します（`nearText` はエクスポート JSON に含まれ、DOM アンカー失敗時に AI エージェントが生成元ソースを推論するために使用されます）。
- **SVG オーバーレイの座標計算 (`svgHalo` & `svgQuestionPin`)**:
  - `box = el.getBBox()` でバウンディングボックスを取得。
  - `appendSvgOverlay(el, node)` は、`el` が `<g>` または `<svg>` の場合は `el` の子要素として直接追加し、それ以外のリーフ要素の場合は `el.parentNode` に追加した上で `el.getAttribute('transform')` をオーバーレイ要素へ複製します。
  - **コメントハロー (`svgHalo`)**: `<rect class="sp-node-halo">` を `x = box.x - 4`, `y = box.y - 4`, `width = box.width + 8`, `height = box.height + 8`, `rx = 6`, `data-sp-cmt-id = c.id` で描画。
  - **質問ピン (`svgQuestionPin`)**: `<text class="sp-qpin-svg" font-size="16">❓</text>` をノード右上の `x = box.x + box.width - 6`, `y = box.y + 4`, `data-sp-q-id = q.id` に配置し、子要素に `<title>{q.question}</title>` を付与。

#### 5. `document`（文書全体）
- **生成時**: パネル内の `#spDocCommentBtn`（「📄 Whole-document comment」、同一コメント内での重複追加は抑止）をクリックするか、`e` モードで `ArrowUp` を押して `document.body` まで拡大してクリックした際に生成されます。
- **フィールド**: `{kind: "document"}`（コメントの `unit: null`, `unitLabel: "Whole document"`）。本文 DOM にはハイライトを追加せず常に `anchored: true` となります。

### 5.4 動詞パレット (`action`)

`#spPopupPalette` から選択できる任意の意図指定:
- `"move"`: 保存時に `pendingTargets.length >= 2` が必須。自動的に 1 つ目のターゲットに `role: "source"`、2 つ目のターゲットに `role: "destination"` を付与します。コメント欄が空欄のまま保存された場合は `"[Move] ① to ②"` が補完されます。
- `"insert"`: 挿入指示（空欄時の既定文言: `"[Insert]"`）。
- `"delete"`: 削除指示（空欄時の既定文言: `"[Delete]"`）。
- `"shorten"`: 短縮・要約指示（空欄時の既定文言: `"[Shorten]"`）。
- `"keep"`: 明示的な肯定承認（`Keep 👍`、空欄時の既定文言: `"[Keep 👍]"`）。AI エージェントは承認された箇所を絶対に変更・撤回してはなりません。

### 5.5 パネルのソート順と Response-only（元コメント不在）アイテムの扱い

- **コメントの表示順**: `renderPanel()` は各コメントの `unitElement(c.unit)` の DOM 出現順（`elA.compareDocumentPosition(elB) & Node.DOCUMENT_POSITION_FOLLOWING`）でソートします（同一 unit 内や `unit: null` 同士は元の順序を維持）。
- **アンカー失敗警告**: `c.targets` のいずれかに `t.anchored === false` がある場合、`<div class="sp-item-noanchor">⚠ Original text not found</div>` を表示します。
- **元コメントが `localStorage` に存在しない場合の Response-only アイテム (`sp-item-response-only`)**:
  - `window.SAMEPAGE_RESPONSES` は HTML ファイルに直接埋め込まれる一方、`comments` はブラウザ固有の `localStorage` に保存されます。そのため、別ブラウザで開いた場合や `localStorage` クリア後には、対応する元コメントがローカルに存在しないレスポンスが生じます。
  - `renderPanel()` の末尾で、`comments` 内に同じ `id` が存在しないすべての `r`（`!known[r.id]`）を独立したカードとして追加描画します:
    - `<div class="sp-item sp-item-response-only" data-sp-cmt-id="{r.id}">`
    - 見出し `<div class="sp-item-unit">(no source comment)</div>`
    - `buildResponseBlock(r)`（`🤖 ` + アクションバッジ `Fixed` / `Partially fixed` / `Declined` / `Acknowledged` + 返信文）。
    - クリック時は `jumpToFixed(r)` を呼び出し、本文中に `mark.sp-mark-fixed[data-sp-resp-id="{r.id}"]` があればそこへ中央スクロール（`block: 'center'`）し、なければ `jumpToUnit(r.unit)` にフォールバックします。

---

## 6. 双方向 JSON 契約 (Bidirectional JSON Contracts)

### 6.1 エクスポート JSON (人間 → AI)

`buildJson()`（`JSON.stringify(..., null, 2)`）で生成されます。`answers` には `a.answer || a.note` が存在する回答のみが含まれます。コメント直下の `selectedText`, `contextBefore`, `contextAfter`, `anchored` は後方互換用のミラーであり、最初の `text-range` ターゲット（`firstTextRange(c)`）の値を複製します（`text-range` ターゲットを持たないコメントでは `selectedText` 等は `null`、`anchored` は `c.targets[0].anchored !== false`）。

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
      "answer": "選択した選択肢",
      "note": "任意の補足メモ",
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
          "selectedText": "対象テキスト",
          "contextBefore": "直前40文字",
          "contextAfter": "直後40文字"
        }
      ],
      "action": null,
      "comment": "この主張の根拠を補足してください。",
      "status": "open",
      "anchored": true,
      "selectedText": "対象テキスト",
      "contextBefore": "直前40文字",
      "contextAfter": "直後40文字",
      "createdAt": "2026-10-17T00:00:00.000Z"
    }
  ]
}
```

### 6.2 返信 JSON (AI → 人間, `--responses`)

```json
{
  "doc": "document-id",
  "respondedAt": "2026-10-17T00:05:00.000Z",
  "responses": [
    {
      "id": "c-8charid",
      "reply": "第2節に根拠と出典を追記しました。",
      "action": "fixed",
      "fixedText": "再生成後のHTML内に実在する修正後テキスト",
      "contextBefore": "同文言が複数ある場合の直前文脈（任意）",
      "contextAfter": "同文言が複数ある場合の直後文脈（任意）",
      "unit": "u1"
    }
  ]
}
```
- 有効な `action`: `"fixed"`（省略時の既定値）, `"declined"`, `"partial"`, `"noted"`。

### 6.3 質問ピン JSON (AI → 人間, `--questions`)

```json
{
  "questions": [
    {
      "id": "q-01",
      "question": "ログの保持期間はどちらに統一しますか？",
      "unit": "u1",
      "target": {
        "kind": "text-range",
        "selectedText": "保持ポリシー",
        "contextBefore": "",
        "contextAfter": ""
      },
      "choices": ["【推奨】 90日", "30日", "1年"]
    }
  ]
}
```
- `choices` がある場合、選択肢ボタンのクリックで `answer` が記録され、`<textarea>` は補足メモ `note` として記録されます。`choices` がない（自由記述）場合は `<textarea>` の変更が直接 `answer` になります。
- 一度回答された質問（エクスポート JSON の `answers[]` に含まれるもの）は、次ラウンド以降で再注入してはなりません。

---

## 7. Finalize（公開用 HTML 切り出し）パイプライン (`--finalize`)

### 7.1 削除用正規表現と定数 (`samepage/cli.py`)

```python
DATA_SP_ATTR = re.compile(r'\s+data-sp-[\w-]+(?:\s*=\s*"[^"]*"|\s*=\s*\'[^\']*\')?(?=[\s/>])')
CLASS_ATTR_RE = re.compile(r'(\sclass\s*=\s*)(["\'])(.*?)\2', re.DOTALL)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img",
             "input", "link", "meta", "source", "track", "wbr"}
```

補助関数 `_merge_spans(spans)` は `(start, end)` の区間リストをソートし、重なり合う区間や入れ子になった区間（`s <= merged[-1][1]`）を外側の境界へ統合することで、逆順スライス削除時に二重削除が起きないようにします。

### 7.2 5 段階の厳密な削除パス (`finalize_html(html)`)

`finalize_html(html)` は以下の 5 段階のパスを厳密な順序で実行します。

1. **`strip_discussion_elements(html)`**:
   - `_DiscussionSpanCollector` がタグスタック `(tag, start_offset, is_discussion)`（`is_discussion` は `any(k == "data-sp-discussion" for k, _ in attrs)`）を追跡します。
   - `VOID_TAGS` に含まれるタグや自己終了タグ（`handle_startendtag`）が `data-sp-discussion` を持つ場合は、スタックに積まずその開始タグ範囲 `(start, start + len(get_starttag_text()))` を即座に記録します。
   - 通常要素は対応する終了タグがポップされた時点で `(start, end_tag_end)` を記録します。
   - `_merge_spans` で統合後、末尾から逆順にスライス削除します。
2. **`strip_runtime_decorations(html)`**:
   - ブラウザでライブ DOM が「名前を付けてページを保存」された場合でも綺麗に戻せるよう、`_RuntimeMarkSpanCollector` が以下を収集します:
     - `REMOVE_CLASSES = ("sp-qpin", "sp-qpin-svg", "sp-insert-mark", "sp-node-halo")`: これらのいずれかのクラストークンを持つ要素は、開始タグから終了タグ（中身を含む）までを `remove_spans` に記録して丸ごと削除。
     - `UNWRAP_CLASSES = ("sp-mark", "sp-mark-fixed")`: これらのクラストークンを持つ `<mark>` 要素は、開始タグ区間 `(start, tag_end)` と終了タグ区間 `(end_start, end_end)` のみを `unwrap_spans` に記録し、タグだけを剥がして内部テキストを保持。
   - `remove_spans + unwrap_spans` を `_merge_spans` で統合し、逆順にスライス削除します。
3. **`strip_marker_block(html)`**:
   - `has_begin == has_end` を検証（片方のみなら `ValueError`）。
   - `MARKER_BEGIN` の先頭から `MARKER_END` の末尾（さらに直後に `"\n"` があればその 1 文字を含む）までを削除します。
4. **`strip_sp_data_attrs(html)`**:
   - `_StartTagSpanCollector` で全開始タグ（自己終了タグ含む）の `(start, end)` 区間のみを収集します。
   - `"data-sp-"` を含む開始タグ文字列に対してのみ `DATA_SP_ATTR.sub("", tag_text)` を適用します。これにより、本文テキストや `<code>` 内に書かれたリテラルの `data-sp-unit="x"` といった文字列は一切誤削除されません。
5. **`strip_runtime_mark_class_token(html)`**:
   - `"sp-mark-el"` を含む開始タグ文字列に対して `_remove_class_token(tag_text, "sp-mark-el")`（`CLASS_ATTR_RE.sub(..., count=1)`）を適用します。
   - `value.split()` から `"sp-mark-el"` を除き、残りのクラストークンが空になれば ` class="..."` 属性自体を削除（`return ""`）し、他のクラスが残れば単一スペースで再結合します。

---

## 8. `grill-on-samepage` と Alignment ビルダー仕様 (`docs/build_alignment_html.py`)

### 8.1 セッションと成果物のディレクトリ構成

```text
docs/alignment/
  INDEX.md                  # 全セッション横断の決定事項・用語集の自動生成索引 (--index)
  NNNN-slug.md              # セッション NNNN の Single Source of Truth (SSOT) Markdown
  NNNN-slug.html            # build_alignment_html.py が生成する HTML（対話セッション中は samepage レビュー層を注入）
  NNNN-slug.final.html      # 合意後に --finalize で切り出した公開用 HTML
```

### 8.2 Design Tree 記法とパーサ仕様 (`parse_design_tree`)

`split_tree_section(body)` は `TREE_HEADING_RE` に一致する見出しを探し、次の `^## ` 見出し（または文書末尾）までの非空行を抽出します。

```python
STATES = ("確定", "frontier", "再検討", "保留")
NODE_RE = re.compile(r"^(?P<indent> *)- \[(?P<id>[A-Za-z]+-\d+)\]\s*(?P<rest>.+?)\s*$")
DEP_RE = re.compile(r"^(?P<indent> *)- \(依存\)\s*\[(?P<id>[A-Za-z]+-\d+)\]\s*$")
TREE_HEADING_RE = re.compile(r"^##\s+.*design tree.*$", re.M)
```

構文とバリデーション規則（違反時は 1 始まりの行番号付きで `TreeError(ValueError)` を送出）:
1. **インデント**: 先頭スペース数は必ず 2 の倍数（`len(indent) % 2 == 0`）とし、`depth = len(indent) // 2` とします。`depth > 0` の行は直近の `depth - 1` に親ノードが存在しなければなりません。
2. **ノード ID**: `[A-Za-z]+-\d+` 形式（例: `[D-1]`）。文書内で一意であり、重複や一度取り消した ID の再利用は `TreeError` となります。
3. **フィールド分割**: `rest` を `"::"` で分割・トリムし、最低 2 フィールド（`title :: state`）が必須です。`state` は `STATES` のいずれかでなければなりません。
4. **決定フィールド (`decision`)**: `decision = fields[2] if len(fields) > 2 else ""`。
   - `state == "確定"` の行は非空の `decision` フィールドを**必ず持たなければなりません**。
   - `確定` 以外の行（`frontier`, `再検討`, `保留`）は `decision` フィールドを**持ってはなりません**。
5. **複数親への依存エッジ (`DEP_RE`)**: `- (依存) [ID]` 行は `depth > 0` で直近の `depth - 1` の所有ノードにぶら下がる必要があり、参照先 `ID` はツリー内の既知ノード（`seen`）に存在しなければなりません。ノードは増やさず `(owner_id, target_id)` を `extra_edges` に追加します。

### 8.3 Design Tree SVG レイアウト定数と描画ロジック (`layout`, `render_svg`)

#### レイアウト定数
```python
BOX_W, BOX_H, COL_GAP, ROW_GAP, TOP = 182, 56, 14, 74, 16
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
```

#### グリッド配置と中央揃え計算式 (`layout(nodes)`)
1. ノードを `depth` ごとの行（`rows[depth]`）に文書順でグループ化します。
2. 各 `depth` の行について:
   - 行全体の幅: `row_span = len(row) * BOX_W + (len(row) - 1) * COL_GAP`
   - 初期 X 座標: `x = i * (BOX_W + COL_GAP)`（`i = 0 .. len(row)-1`）
   - Y 座標: `y = TOP + depth * (BOX_H + ROW_GAP)`
3. SVG 全体の幅: `width = max(n["row_span"] for n in nodes)`。
4. 各行を水平方向中央に揃えます:
   - `n["x"] += (width - n["row_span"]) // 2`
   - ノード中心座標: `n["cx"] = n["x"] + BOX_W // 2`（`+ 91`）、`n["cy"] = n["y"] + BOX_H // 2`（`+ 28`）。
5. SVG 全体の高さ: `height = max(n["y"] + BOX_H for n in nodes) + 40`（下部に凡例領域 40px を確保）。

#### 状態別の配色・記号パレット (`STATE_STYLE`)

| 状態 (`state`) | `fill` | `stroke` | `title` | `sub` | `mark` |
|---|---|---|---|---|---|
| `確定` | `#e6f5f3` | `#0f766e` | `#0f2a28` | `#0b5750` | `✓` |
| `frontier` | `#fdf3e0` | `#b5790c` | `#5a3d05` | `#b5790c` | `❓` |
| `再検討` | `#fdecea` | `#b3261e` | `#5c1512` | `#b3261e` | `↺` |
| `保留` | `#f1f5f4` | `#8fa5a1` | `#3d4a48` | `#5b6c69` | `⏸` |

#### テキスト幅推定と省略 (`_fit(text, budget=170, size=12)`)
各文字 `ch` について、`ord(ch) > 0x2E80`（CJK 文字等）なら `1.0 * size`、それ以外なら `0.55 * size` を累積幅 `w` に加算し、`w > budget`（既定 170px）を超えた時点で `"…"` を付与して切り詰めます。
- 1 行目（`font-size="12"`）: `_fit(f'{n["id"]} {n["title"]}', budget=170, size=12)`
- 2 行目（`font-size="11"`, `font-weight="700"`, `dy="17"`）: `_fit(f'{st["mark"]} {n["decision"] or n["state"]}', budget=170, size=11)`

#### エッジ・ノード・アンカー・凡例の描画
- **矢印マーカー (`<defs>`)**: 同一ページ内の複数 SVG で衝突しないよう `doc_id` で名前空間化し、`id="sp-ar-{doc_id}-ok"`（`#0f766e`）と `id="sp-ar-{doc_id}-dep"`（`#8fa5a1`）を定義します。
- **親子エッジ**: 親ノード下端 `(parent.cx, parent.y + BOX_H)` から子ノード上端 4px 手前 `(child.cx, child.y - 4)` へ、子ノードの `STATE_STYLE[state]["stroke"]` 色・`stroke-width="2"`・`marker-end="url(#sp-ar-{doc_id}-ok)"` の実線を描画します。
- **依存エッジ (`(依存)`)**: 依存元上端 `(src.cx, src.y)` から依存先下端 4px 外側 `(dst.cx, dst.y + BOX_H + 4)` へ、`stroke="#8fa5a1"`・`stroke-width="2"`・`stroke-dasharray="5,4"`・`marker-end="url(#sp-ar-{doc_id}-dep)"` の破線を描画します。
- **ノード構造と台帳アンカー連携**:
  - 各ノードは `<a href="#{anchor_for(n['id'])}">` で囲まれます。`anchor_for(node_id)` は `node_id.replace("-", "").lower()`（例: `D-1` → `#d1`）です。
  - 本文中の決定台帳テーブルの行（`<tr><td>D-1...`）および見出し（`<h2>D-1...` / `<h3>D-1...`）にも `add_row_anchors` / `add_heading_anchors` によって同じ `id="d1"` が自動付与されます。
  - 内部の `<g data-sp-node="{id}" data-sp-label="{label}">` には、`decision` がある場合は `"{id} {title}（{state}: {decision}）"`、ない場合は `"{id} {title}（{state}）"` が `data-sp-label` として設定されます。
- **凡例**: ツリー内に存在する状態を `STATES` の順で走査し、`(lx, height - 28)` に `14x14` の矩形、`(lx + 22, height - 17)` に `"{state}（{count}）"` を描画し、`lx += 40 + 13 * len(s) + 34` ずつ右へ進めます。

### 8.4 残件ブロック (`build_remaining`) の算出ロジック

`docs/build_alignment_html.py` に `--export <export.json>` を渡すと、`build_remaining(export_path, nodes)` がエクスポート JSON と Design Tree のノード状態を集計し、`<article class="sp-article">` の直前に `<div class="sp-discussion" data-sp-discussion>` ブロックを生成します。

1. **集計対象の抽出**:
   - `answers = {a.get("questionId") for a in data.get("answers", []) if a.get("questionId")}`（回答済み質問 ID のユニーク集合）
   - `comments = data.get("comments", [])`
   - `open_ids = [c.get("id") for c in comments if c.get("status") == "open"]`
   - `settled = [n for n in nodes if n["state"] == "確定"]`
   - `pending = [n for n in nodes if n["state"] in ("frontier", "再検討")]`
   - `held = [n for n in nodes if n["state"] == "保留"]`
2. **内訳テーブル（5 行）**:
   1. `回答済みの質問ピン`: 件数 = `len(answers)`, 内訳 = `"export JSON の answers より"`
   2. `未解決のコメント (status: "open")`: 件数 = `len(open_ids)`, 内訳 = `open_ids` があれば `", ".join(open_ids)`、なければ `f"{len(comments)} 件すべて resolved"`
   3. `確定した決定`: 件数 = `len(settled)`, 内訳 = `", ".join(n["id"] for n in settled) or "—"`
   4. `未確定の決定 (frontier / 再検討)`: 件数 = `len(pending)`, 内訳 = `", ".join(n["id"] for n in pending) or "なし"`
   5. `運用へ回した保留`: 件数 = `len(held)`, 内訳 = `", ".join(n["id"] for n in held) or "なし"`
3. **合意ゲート判定式 (`blocked`)**:
   ```python
   blocked = len(open_ids) + len(pending)
   ```
   - `保留`（`held`）のノードや回答済みの質問は `blocked` に加算されません。
   - `blocked == 0` の場合: `<p><strong>残件はゼロです。</strong>D-4 の合意ゲートにより、ここから先は明示的な合意が必要です。</p>` を出力。
   - `blocked > 0` の場合: `<p><strong>残件が {blocked} 件あります。</strong>すべて片付くまで <code>--finalize</code> しないでください（D-4）。</p>` を出力。
4. **Finalize 時の自動除去**: 外枠の `<div class="sp-discussion" data-sp-discussion>` に `data-sp-discussion` 属性が付与されているため、`--finalize` 実行時に残件ブロック全体が自動的に除去されます。

---

## 9. マルチエージェント対応プラグイン・スキル構成

**Google Antigravity**、**Claude Code**、およびその他の AI エージェントで単一リポジトリから同一機能を提供するため、以下の構成を採ります。

| コンポーネント | 配置パス | 対象エージェント・役割 |
|---|---|---|
| Antigravity プラグインマニフェスト | `plugin.json` | Google Antigravity（`~/.gemini/config/plugins/samepage` または `.agents/plugins/samepage`） |
| Claude Code プラグインマニフェスト | `.claude-plugin/plugin.json` | Claude Code（`~/.claude/skills/samepage`） |
| リポジトリルール | `AGENTS.md`, `CLAUDE.md` | Antigravity, Claude Code, Codex, Cursor 等が参照する設計・運用規約 |
| スキル定義 | `skills/samepage/SKILL.md`, `skills/grill-on-samepage/SKILL.md` | 各エージェントがオンデマンドに読み込む実行手順書 |

スキル内のスクリプト呼び出しは、`SKILL.md` のあるディレクトリからの相対パス（`../../samepage/cli.py`）または環境変数（`${CLAUDE_PLUGIN_ROOT}`）の双方で解決できるよう定義されており、エージェント固有のランタイムに縛られず動作します。
