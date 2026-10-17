# CLAUDE.md（samepage）

このリポジトリの共通ルールは [`AGENTS.md`](AGENTS.md) に定義されています。以下の規約を遵守してください。

## 設計上の SSOT と仕様書
- 全体仕様は `docs/specification.md`（日本語版: `docs/specification.ja.md`）、設計判断の背景は `docs/adr/` および `docs/alignment/INDEX.md` を参照する。確定している決定を勝手に覆さない。
- 覆す必要があるときは、根拠となる新しい事実を添えて該当の ALIGNMENT 文書で「取り消して再検討」する（手順は `skills/grill-on-samepage/SKILL.md` §4）。黙って別の判断で進めない。
- `docs/alignment/INDEX.md` は生成物。手で編集せず、`python3 docs/build_alignment_html.py --index docs/alignment` で作り直す。

## ブランチ・Git 運用
- 開発は `develop` ブランチで行い、`main` は安定リリースブランチとする。
- **AI は勝手に `git push` を行わない。** `main` へのマージ・直接コミットも行わない（メンテナが行う）。

## 命名・契約
- `data-sp-*` / `sp-` プレフィックス、JSON フィールド名は `docs/specification.md`、`docs/design.md`、および `skills/samepage/SKILL.md` が正。README 側で勝手に変えない。
- `samepage.js` の `HANDOFF_RULES` と `skills/samepage/SKILL.md` §4 のルール表は常に同期させる。

## マルチエージェント・スキル構成
- リポジトリは Google Antigravity 用の `plugin.json` と Claude Code 用の `.claude-plugin/plugin.json` を併せ持つユニバーサルプラグインとして構成されている。スキルは `skills/<name>/SKILL.md` に置く。
- スキル内から同梱スクリプト（`samepage/cli.py` や `docs/build_alignment_html.py`）を参照するときは、`SKILL.md` 自身の位置からの相対パス（`../../samepage/cli.py`、すなわちリポジトリルート基準）または `${CLAUDE_PLUGIN_ROOT}` を用いる。

## README と生成物
- `README.md` と `README.ja.md` は節単位で同期させる。片方だけ変更しない。
- `README.html` / `README.ja.html` / `docs/alignment/*.html` / `docs/alignment/INDEX.md` は生成物。元の `.md` を直して再生成する。**CI の `docs` ジョブが鮮度を検査するので、再生成を忘れると落ちる。** 手順は README の「開発 / Development」節にある。
- 配布・コミット対象の HTML にレビュー層を注入する際は、必ず `--no-source-path` を付けてローカル絶対パスの混入を防ぐ。
- `docs/images/demo.gif` は `python3 docs/build_demo_gif.py` で再生成する（手で編集しない）。
