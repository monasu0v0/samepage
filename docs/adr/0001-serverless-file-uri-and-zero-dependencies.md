# ADR-0001: サーバーレス（`file://` 完結）およびランタイム外部依存ゼロの採用

- **Status**: Accepted
- **Date**: 2026-10-17
- **Author**: monasu0v0 (<monasu0v0@gmail.com>)

## Context

AI エージェントが生成した HTML レポートや設計資料に対して人間がレビューコメントを付け、それを AI にフィードバックする仕組みを作るにあたり、どのような実行環境・配布形態をとるかが最初の設計分岐となった。

一般的な Web アノテーションツールやレビューシステムは、以下のいずれかを前提としていることが多い。
1. ローカルまたはリモートの HTTP サーバー（FastAPI / Flask / Node.js 等）を立ち上げ、ブラウザと WebSocket や REST API で通信する方式。
2. ブラウザ拡張機能や外部 SaaS アカウントを必要とする方式。
3. Python 側で `beautifulsoup4` や `lxml` などのサードパーティ製パッケージを必須とする方式。

しかし、AI エージェントのスキルとしてあらゆるプロジェクトやマシン環境で即座に動かす場合、「仮想環境の作成や `pip install` が必要」「バックグラウンドサーバーの起動・ポート競合・終了管理が必要」という制約は大きな摩擦となる。

## Decision

1. **完全サーバーレス（`file://` プロトコル完結）とする**
   - レビュアーは HTML ファイルをブラウザで直接開く（`file://`）だけで動作する設計とする。
   - コメントや質問への回答の永続化にはブラウザの `localStorage`（キー: `samepage:<doc>` および `samepage-answers:<doc>`）を使用する。
   - 人間から AI への受け渡しは Clipboard API（`j` キーまたは「📋 Copy JSON」ボタン）による JSON コピー＆ペーストとし、AI から人間への受け渡しは CLI による HTML への再注入（`--responses`, `--questions`）とする。
2. **ランタイム外部依存をゼロにする**
   - `pyproject.toml` の `dependencies` は空（`[]`）とし、Python 3.9+ の標準ライブラリのみで `samepage/cli.py` を実装する。
   - 注入されるフロントエンド資産（`samepage.js`, `samepage.css`, `panel.html`）も外部 CDN やフレームワークを一切使わず、単一ブロックとして HTML 内にインライン展開する。
   - ドキュメント生成補助（`markdown`）やブラウザ自動テスト・GIF 生成（`playwright`, `Pillow`）は開発・CI 時のオプションとして完全に分離し、コア CLI には持ち込まない。

## Alternatives Considered

- **ローカル HTTP サーバー方式**: ブラウザからファイルへ直接書き戻せる利点はあるが、エージェントがバックグラウンドプロセスを管理する必要があり、リモート環境やサンドボックス環境でポートフォワーディング等の問題が起きるため却下。
- **`beautifulsoup4` / `lxml` への依存**: HTML 操作は容易になるが、`git clone` した直後にシステム Python で即実行できる（「クローンすればそのまま動く」）性質が失われるため却下。

## Consequences

- **Positive**:
  - `git clone` するだけで `pip install` すら不要で即座にスキルとして機能する。
  - オフライン環境や厳格なセキュリティポリシー下の環境でも外部通信なしで動作する。
  - HTML ファイル単体が自己完結しているため、そのまま別環境へ渡して閲覧できる。
- **Negative / Trade-offs**:
  - `localStorage` はブラウザプロファイル単位であるため、永続的な記録としてはエクスポート JSON を正とする運用ルールが必要になる。
  - 標準ライブラリの `html.parser` のみで安全な HTML 書き換えを実装する必要がある（→ [ADR-0002](0002-surgical-html-injection-and-safe-finalization.md) で解決）。
