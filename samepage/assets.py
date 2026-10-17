"""Builds the injectable review-layer block for the samepage CLI.

Any future HTML generator that wants a review layer should call
render_block() only. Never copy the review-layer implementation into a
generator script.
"""
import json
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent / "assets"

MARKER_BEGIN = "<!-- samepage:begin -->"
MARKER_END = "<!-- samepage:end -->"

VALID_JUMP = ("scroll", "hash")


def _read_asset(name):
    text = (ASSET_DIR / name).read_text(encoding="utf-8").strip()
    if "</script" in text.lower():
        raise ValueError(f"{name} contains '</script' and cannot be inlined")
    return text


def _embed_json(value):
    """Serialize value as JSON safe to embed inside an inline <script> tag.

    Escaping '</' as '<\\/' prevents a '</script>' substring that might
    appear inside a JSON string (e.g. free-form reply text) from closing
    the surrounding <script> tag early. Inside a JSON string literal,
    '<\\/' is equivalent to '</', so this is semantically a no-op for the
    consumer of the JSON.
    """
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def render_block(doc_id, jump="scroll", storage_key=None, responses=None,
                  questions=None, source_path=None):
    """Return the review-layer block to inject as a single string.

    doc_id: identifier used as the JSON "doc" field and in the localStorage key.
    jump: "scroll" (scrollIntoView) or "hash" (put data-sp-index in location.hash).
    storage_key: explicit override. Defaults to "samepage:{doc_id}".
    source_path: path of the HTML file the layer was injected into (absolute
        path recommended). Embedded as "sourcePath" in the config so that a
        session that only received the export JSON can locate the file.
        None means "sourcePath" is embedded as null.
    responses: validated top-level responses dict. None means no response
        layer is embedded; otherwise embedded as window.SAMEPAGE_RESPONSES
        right after SAMEPAGE_CONFIG, JSON-escaped like the config (reply
        text is free-form human text and may contain "</script>").
    questions: validated top-level questions dict. None means no question
        layer is embedded; otherwise embedded as window.SAMEPAGE_QUESTIONS
        with the same escaping as responses.
    """
    if not doc_id:
        raise ValueError("doc_id is required")
    if jump not in VALID_JUMP:
        raise ValueError(f"jump must be one of {VALID_JUMP}: {jump!r}")

    config = {
        "doc": doc_id,
        "jump": jump,
        "storageKey": storage_key or f"samepage:{doc_id}",
        "sourcePath": str(source_path) if source_path else None,
    }

    parts = [
        MARKER_BEGIN,
        f"<style>\n{_read_asset('samepage.css')}\n</style>",
        _read_asset("panel.html"),
        f"<script>window.SAMEPAGE_CONFIG={_embed_json(config)};</script>",
    ]
    if responses is not None:
        parts.append(f"<script>window.SAMEPAGE_RESPONSES={_embed_json(responses)};</script>")
    if questions is not None:
        parts.append(f"<script>window.SAMEPAGE_QUESTIONS={_embed_json(questions)};</script>")
    parts += [
        f"<script>\n{_read_asset('samepage.js')}\n</script>",
        MARKER_END,
    ]
    return "\n".join(parts) + "\n"
