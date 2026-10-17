# AGENTS.md (samepage plugin rules)

- When invoking `samepage` or `grill-on-samepage` skills, resolve `samepage/cli.py` and `docs/build_alignment_html.py` relative to the plugin/repository root (two directories above `skills/<name>/SKILL.md`).
- Never inline or reimplement `samepage/cli.py` or its bundled JS/CSS assets; always execute `samepage/cli.py`.
- When injecting the review layer into HTML files intended for distribution or Git commits, always pass `--no-source-path` so local filesystem paths are not embedded.
