# Architecture Decision Records (ADR)

このディレクトリには、`samepage` および `grill-on-samepage` の設計・構築において下された主要なアーキテクチャ上の意思決定（ADR）を記録しています。

詳細な全体仕様については [仕様書 (`docs/specification.ja.md`)](../specification.ja.md)（[English](../specification.md)）を、対話型セッションによる合意ドキュメント（SSOT）については [`docs/alignment/INDEX.md`](../alignment/INDEX.md) を参照してください。

## ADR 一覧

| ID | タイトル | ステータス | 概要 |
|---|---|---|---|
| [ADR-0001](0001-serverless-file-uri-and-zero-dependencies.md) | サーバーレス（`file://` 完結）およびランタイム外部依存ゼロの採用 | Accepted | Web サーバーや追加パッケージを一切要求せず、Python 標準ライブラリと Vanilla JS、`localStorage`、Clipboard API のみで完結させる判断。 |
| [ADR-0002](0002-surgical-html-injection-and-safe-finalization.md) | 文字列手術による HTML インジェクションと 5 段階の Finalize パイプライン | Accepted | HTML パーサによる DOM 再シリアライズを避けてバイト完全性を保ち、`--finalize` で 5 段階の安全な除去を行う判断。 |
| [ADR-0003](0003-bidirectional-json-contract-and-five-target-kinds.md) | 自己記述型双方向 JSON 契約と 5 種類のターゲット表現 | Accepted | スキル未導入環境でも機能する Handoff ヘッダ、5 種類のターゲット（`diagram-node` 含む）、および返信・逆質問ピンの双方向スキーマ設計。 |
| [ADR-0004](0004-grill-on-samepage-and-design-tree-ssot.md) | `grill-on-samepage` によるラウンド制設計合意と Design Tree SSOT | Accepted | 設計面接ループを HTML 上の質問ピンで行い、Markdown ネイティブな Design Tree 記法と自動生成 `INDEX.md` で SSOT を維持する判断。 |
| [ADR-0005](0005-multi-agent-skill-and-plugin-architecture.md) | マルチエージェント（Antigravity / Claude Code / 汎用エージェント）対応のスキル・プラグイン構成 | Accepted | 単一リポジトリで Google Antigravity、Claude Code、およびその他の AI エージェントすべてにネイティブ対応するユニバーサル構成の採用。 |
