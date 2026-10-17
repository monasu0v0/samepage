# ADR-0005: マルチエージェント（Antigravity / Claude Code / 汎用エージェント）対応のスキル・プラグイン構成

- **Status**: Accepted
- **Date**: 2026-10-17
- **Author**: monasu0v0 (<monasu0v0@gmail.com>)

## Context

当初、`samepage` と `grill-on-samepage` の 2 つのスキルは Claude Code のプラグイン機構（`.claude-plugin/plugin.json` と環境変数 `${CLAUDE_PLUGIN_ROOT}`、および `CLAUDE.md`）を前提にパッケージングされていた。

しかし、**Google Antigravity** をはじめとするモダンな AI コーディングエージェント（Antigravity、Claude Code、Codex、Cursor 等）のすべてで同じスキル・同じリポジトリをそのまま使えるように再構築し、OSS として公開したいという要件が生じた。

各エージェントのカスタマイズ／スキル発見仕様を比較すると以下の特徴がある：
1. **Google Antigravity**:
   - スキルは `skills/<name>/SKILL.md`（YAML フロントマターに `name` と `description` 必須）として構成される。
   - プラグインはルートに `plugin.json` を置き、配下に `skills/<name>/SKILL.md` や `rules/AGENTS.md` を持つディレクトリ構造（`~/.gemini/config/plugins/<name>` や `.agents/plugins/<name>`）で自動認識される。また、ワークスペースの `.agents/skills/` や `~/.gemini/config/skills/` にスキルを直接配置することもできる。
   - ルールファイルは `AGENTS.md` または `GEMINI.md` を階層的に自動検出する。
   - スキル内からのスクリプト参照は、`SKILL.md` のファイルパスを基準とした相対パス（`../../samepage/cli.py`）で確実に解決できる。
2. **Claude Code**:
   - `~/.claude/skills/<name>` にクローンされた際、`.claude-plugin/plugin.json` があればプラグインとして `skills/<name>/SKILL.md` を自動認識する。
   - スキル内では `${CLAUDE_PLUGIN_ROOT}` がリポジトリルートに展開される。
3. **その他のエージェント（Codex / Cursor 等）**:
   - `AGENTS.md` および `skills/<name>/SKILL.md` の標準的な Markdown 手順書を参照し、相対パスまたはリポジトリルートからのパスで CLI を実行する。

## Decision

単一のリポジトリで **Google Antigravity を第一級サポートしつつ、Claude Code や他のすべてのエージェントでも追加設定なしで動作するユニバーサル構成**を採用する。

1. **デュアルマニフェスト構成**
   - リポジトリルートに Antigravity ネイティブの `plugin.json` を配置する。
   - `.claude-plugin/plugin.json` も併置し、Claude Code の `@skills-dir` プラグイン自動認識も維持する。
2. **エージェント横断ルールファイル（`AGENTS.md` / `rules/AGENTS.md` / `CLAUDE.md`）の整備**
   - 設計上の SSOT（`docs/alignment/INDEX.md` および `docs/adr/`）、命名契約（`docs/specification.md` / `docs/design.md`）、生成物の再ビルド手順を定義した `AGENTS.md` をルートおよびプラグイン用の `rules/AGENTS.md` に配置する。
   - Claude Code 互換のため `CLAUDE.md` も維持し、同一の規約を参照できるようにする。
3. **環境変数に依存しないユニバーサルな `SKILL.md` パス解決**
   - `skills/samepage/SKILL.md` と `skills/grill-on-samepage/SKILL.md` の手順において、スクリプト（`samepage/cli.py` および `docs/build_alignment_html.py`）の呼び出しを特定のエージェント固有変数（`${CLAUDE_PLUGIN_ROOT}`）のみに依存させない。
   - 具体的には、`SKILL.md` 自身の位置からの相対パス（`<repo-root>/samepage/cli.py` すなわち `SKILL.md` の 2 階層上 `../../samepage/cli.py`）を基本とし、Claude Code 等で `${CLAUDE_PLUGIN_ROOT}` が展開される場合はそれも利用できる形に統一する。
4. **UI ヒント文言の汎用化**
   - `samepage/assets/panel.html` 内の JSON モーダル案内文を特定のエージェント名に限定せず、`Copy this JSON and paste it to your AI agent (e.g. Antigravity, Claude Code).` とする。

## Alternatives Considered

- **Antigravity 専用リポジトリと Claude Code 専用リポジトリにフォークして分割する案**: コアの `samepage/cli.py` やアセット、JSON 契約は 100% 共通であるため、リポジトリを分けると二重メンテナンスになり破綻する。マニフェストとパス解決記述をユニバーサル化するだけで単一リポジトリでの完全両立が可能であるため、単一リポジトリ構成を採用した。

## Consequences

- **Positive**:
  - Antigravity ユーザーは `~/.gemini/config/plugins/samepage`（または `.agents/plugins/samepage` / `.agents/skills/`）にクローンするだけで `samepage` と `grill-on-samepage` の両スキルを即座に利用できる。
  - Claude Code ユーザーも従来通り `~/.claude/skills/samepage` にクローンするだけで動作する。
  - どのエージェントでリポジトリを開いても `AGENTS.md` / `CLAUDE.md` により一貫した開発規約と SSOT が適用される。
- **Negative / Trade-offs**:
  - ルートの `AGENTS.md`、`rules/AGENTS.md`、`CLAUDE.md` の内容を整合させておく必要がある（シンプルな構成に保つことでメンテナンス負荷を最小化する）。
