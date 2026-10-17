# ADR-0004: `grill-on-samepage` によるラウンド制設計合意と Design Tree SSOT

- **Status**: Accepted
- **Date**: 2026-10-17
- **Author**: monasu0v0 (<monasu0v0@gmail.com>)

## Context

コーディングに入る前に設計の曖昧な点を AI が人間にインタビューして詰める手法（[mattpocock/skills](https://github.com/mattpocock/skills) の `grilling` 等）は有効だが、ターミナルのチャット上だけで行うと以下の問題が生じる：
1. **合意の実体がチャット履歴にしか残らない**: 会話が流れた後や別セッションに移った後、「どの選択肢をどういう理由で却下し、何に合意したのか」を参照できる単一の正（SSOT: Single Source of Truth）が残らない。
2. **合意文書に対する部分指摘がしづらい**: チャット上の番号付きリストでは、「過去の決定 D-3 のこの前提が気になる」といった位置指定のフィードバックや、決定木（Design Tree）の全体像を眺めながらの回答が難しい。

## Decision

1. **セッション単位の単一合意文書（`docs/alignment/NNNN-slug.md`）を SSOT とする**
   - 1 回の設計セッションにつき 1 つの Markdown 文書を作成し、そこから `docs/build_alignment_html.py` で HTML を生成して `samepage` のレビュー層と質問ピン（`--questions`）を注入する。
   - 判断材料（選択肢の比較表・利点と欠点・AI の推奨と理由）は質問ピンの中ではなく**文書本文のセクション**に書き、質問ピンはそのセクション見出しを指す。これにより合意後も「なぜそう決めたか」が文書内に完全な形で残る。
2. **Markdown ネイティブな Design Tree 記法と SVG 自動生成**
   - `## design tree` セクションに 2 スペースインデントと `::` 区切り（`- [D-1] タイトル :: 状態 :: 決定内容`）の箇条書き記法を定義する。
   - 状態は `確定` / `frontier` / `再検討` / `保留` の 4 種のみとし、一度採番した `[ID]` は取り消し時も再利用しない。
   - `docs/build_alignment_html.py` がこの記法を厳密に検証し、各ノードに `data-sp-node` と該当セクションへのアンカーリンクが付いたインライン SVG 図を自動生成する。
3. **セッション横断の索引（`docs/alignment/INDEX.md`）の自動生成**
   - 複数の ALIGNMENT 文書にわたる決定一覧と用語集を 1 箇所から参照できるよう、`build_alignment_html.py --index docs/alignment` で `INDEX.md` を自動生成する（手動編集による陳腐化を防ぐ）。
4. **機械判定＋人間合意の二段階コンセンサスゲート**
   - エクスポート JSON から算出した未回答ピン数・未解決コメント数・未確定ノード数を文書冒頭の「残件」ブロック（`data-sp-discussion` 付き）として自動出力する。
   - 残件がゼロになった上で、AI が実装順序を提示し、人間が明示的に合意した後にのみ `--finalize` で `.final.html` を切り出す。

## Alternatives Considered

- **CONTEXT.md + 個別 ADR ファイルへの分割出力**: ADR の厳格な条件を満たさない細かな設計判断がこぼれ落ち、SSOT が 2 箇所に分裂するため、`grill-on-samepage` のセッション記録としては単一 ALIGNMENT.md + 自動生成 `INDEX.md` を採用した（プロジェクト全体のアーキテクチャ決定記録としての `docs/adr/` とは役割を分けて共存させる）。
- **Mermaid 記法による Design Tree**: GitHub 上での表示は可能だが、Python 標準ライブラリだけで `data-sp-node` 付きの安定した SVG に変換するパーサを持たないため、2 スペースインデントの専用箇条書き記法を採用した。

## Consequences

- **Positive**:
  - 設計の依存関係（どれが決まれば次が問えるか＝`frontier`）が視覚的な SVG 図として常にページ上部に表示され、図のノード自体にも直接コメントできる。
  - 決定の撤回（「取り消して再検討」）や実装中のドリフト検知が、同じ ALIGNMENT 文書を再オープンするだけで一貫して行える。
- **Negative / Trade-offs**:
  - ALIGNMENT 文書および README の HTML ビルダー（`docs/build_alignment_html.py`, `docs/build_readme_html.py`）は `markdown` パッケージを必要とするため、CI の `docs` ジョブで生成物の鮮度（再生成忘れがないか）を自動検証する仕組みを併用する。
