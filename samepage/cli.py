"""Inject the samepage review layer into an existing HTML file.

Re-serializing HTML through html.parser would mangle raw <script> text and
entity references, so the parser here is only used to locate start tags.
Attribute insertion/removal is done as local string surgery on the original
text, so anything outside a touched span is byte-for-byte identical to the
input.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

# Runnable both as an installed package entry point (`samepage.cli:main`,
# where this module is imported as `samepage.cli` and `assets` is a sibling
# module inside the `samepage` package) and as a bare script
# (`python3 samepage/cli.py`, where sys.path[0] is the samepage/ directory
# itself and `assets` is a top-level module on that path).
try:
    from samepage import assets
except ImportError:
    import assets

SIMPLE_SELECTOR = re.compile(r"^(?:([a-zA-Z][\w-]*))?(?:\.([\w-]+))?$")
ID_SELECTOR = re.compile(r"^#([\w-]+)$")

VALID_ACTIONS = ("fixed", "declined", "partial", "noted")
VALID_TARGET_KINDS = ("text-range", "element", "insertion-point", "diagram-node", "document")


def load_responses(path):
    """Load and validate a responses JSON file; return its top-level dict.

    Raises ValueError if: the file is not valid JSON, the top-level value is
    not an object with a "responses" array, or an element in that array is
    missing a non-empty "id"/"reply" string, has an invalid "action", or a
    non-string/non-null "fixedText". "action" defaults to "fixed" when absent.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"could not parse responses JSON: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("responses"), list):
        raise ValueError("responses JSON must have a top-level \"responses\" array")
    for i, r in enumerate(data["responses"]):
        if not isinstance(r, dict):
            raise ValueError(f"responses[{i}] is not an object")
        for key in ("id", "reply"):
            v = r.get(key)
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"responses[{i}].{key} must be a non-empty string")
        action = r.get("action")
        if action is None:
            r["action"] = "fixed"
        elif action not in VALID_ACTIONS:
            raise ValueError(
                f"responses[{i}].action is invalid: {action!r}"
                f" (must be one of {'/'.join(VALID_ACTIONS)})"
            )
        fixed_text = r.get("fixedText")
        if fixed_text is not None and not isinstance(fixed_text, str):
            raise ValueError(f"responses[{i}].fixedText must be a string or null")
    return data


def load_questions(path):
    """Load and validate a questions JSON file; return its top-level dict."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"could not parse questions JSON: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ValueError("questions JSON must have a top-level \"questions\" array")
    for i, q in enumerate(data["questions"]):
        if not isinstance(q, dict):
            raise ValueError(f"questions[{i}] is not an object")
        for key in ("id", "question"):
            v = q.get(key)
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"questions[{i}].{key} must be a non-empty string")
        target = q.get("target")
        if target is not None:
            if not isinstance(target, dict) or target.get("kind") not in VALID_TARGET_KINDS:
                raise ValueError(
                    f"questions[{i}].target.kind must be one of {'/'.join(VALID_TARGET_KINDS)}"
                )
            if target.get("kind") == "diagram-node":
                node_id = target.get("nodeId")
                if not isinstance(node_id, str) or not node_id.strip():
                    raise ValueError(
                        f"questions[{i}].target.nodeId must be a non-empty string"
                        " (required when kind=diagram-node)"
                    )
        choices = q.get("choices")
        if choices is not None:
            if not isinstance(choices, list) or any(not isinstance(c, str) for c in choices):
                raise ValueError(f"questions[{i}].choices must be an array of strings")
    return data


def parse_selector(selector):
    """Accept only tag / .class / #id / tag.class selectors."""
    selector = (selector or "").strip()
    m = ID_SELECTOR.match(selector)
    if m:
        return (None, None, m.group(1))
    m = SIMPLE_SELECTOR.match(selector)
    if m and (m.group(1) or m.group(2)):
        return (m.group(1), m.group(2), None)
    raise ValueError(
        f"unsupported selector: {selector!r} (only tag / .class / #id / tag.class)"
    )


class _TagSpanCollector(HTMLParser):
    """Collect start-tag spans (offset into the original text) and attributes."""

    def __init__(self, html, tag=None, cls=None, elem_id=None):
        super().__init__(convert_charrefs=False)
        self.want_tag = tag
        self.want_cls = cls
        self.want_id = elem_id
        self.line_offsets = [0]
        for line in html.split("\n"):
            self.line_offsets.append(self.line_offsets[-1] + len(line) + 1)
        self.hits = []

    def _offset(self):
        line, col = self.getpos()
        return self.line_offsets[line - 1] + col

    def handle_starttag(self, tag, attrs):
        attrd = {k: (v or "") for k, v in attrs}
        if self.want_tag and tag != self.want_tag:
            return
        if self.want_cls and self.want_cls not in attrd.get("class", "").split():
            return
        if self.want_id and attrd.get("id") != self.want_id:
            return
        start = self._offset()
        text = self.get_starttag_text() or ""
        self.hits.append({"start": start, "end": start + len(text), "attrs": attrd})


def find_unit_tags(html, selector):
    tag, cls, elem_id = parse_selector(selector)
    p = _TagSpanCollector(html, tag, cls, elem_id)
    p.feed(html)
    p.close()
    return p.hits


def _attr_escape(value):
    return (value.replace("&", "&amp;")
                 .replace('"', "&quot;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))


def add_unit_attrs(html, selector, label_format="{n}"):
    """Add data-sp-unit / data-sp-label / data-sp-index to matched elements.

    An element that already has data-sp-unit is skipped, but its ordinal (n)
    is still consumed so the numbering stays aligned with any host-side hash
    jump numbering.
    """
    hits = find_unit_tags(html, selector)
    inserts = []
    added = 0
    for n, hit in enumerate(hits, start=1):
        if "data-sp-unit" in hit["attrs"]:
            continue
        unit = hit["attrs"].get("id") or f"u{n}"
        label = label_format.replace("{n}", str(n))
        attrs = (
            f' data-sp-unit="{_attr_escape(unit)}"'
            f' data-sp-label="{_attr_escape(label)}"'
            f' data-sp-index="{n}"'
        )
        # Insert just before the closing '>' or '/>' of the start tag.
        tag_text = html[hit["start"]:hit["end"]]
        offset = hit["end"] - (2 if tag_text.endswith("/>") else 1)
        inserts.append((offset, attrs))
        added += 1

    # Insert back-to-front so earlier offsets stay valid.
    out = html
    for offset, attrs in sorted(inserts, reverse=True):
        out = out[:offset] + attrs + out[offset:]
    return out, added


def inject_block(html, block):
    """Replace an existing block in place, or insert it right before </body>."""
    has_begin = assets.MARKER_BEGIN in html
    has_end = assets.MARKER_END in html
    if has_begin != has_end:
        raise ValueError(
            "found only one of the samepage markers; the file may have been"
            " hand-edited and is possibly corrupted, aborting"
        )
    if has_begin:
        start = html.index(assets.MARKER_BEGIN)
        end = html.index(assets.MARKER_END) + len(assets.MARKER_END)
        return html[:start] + block.rstrip("\n") + html[end:]

    idx = html.rfind("</body>")
    if idx < 0:
        raise ValueError("no </body> tag found; cannot determine an injection point")
    return html[:idx] + block + html[idx:]


DATA_SP_ATTR = re.compile(r'\s+data-sp-[\w-]+(?:\s*=\s*"[^"]*"|\s*=\s*\'[^\']*\')?(?=[\s/>])')

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img",
             "input", "link", "meta", "source", "track", "wbr"}


class _DiscussionSpanCollector(HTMLParser):
    """Collect the full span (start tag through end tag) of every element
    carrying a data-sp-discussion attribute."""

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.line_offsets = [0]
        for line in html.split("\n"):
            self.line_offsets.append(self.line_offsets[-1] + len(line) + 1)
        self.spans = []
        self._stack = []  # (tag, start_offset, is_discussion)

    def _offset(self):
        line, col = self.getpos()
        return self.line_offsets[line - 1] + col

    @staticmethod
    def _is_discussion(attrs):
        return any(k == "data-sp-discussion" for k, _ in attrs)

    def _end_tag_end(self, start):
        # For a closing tag only. Closing tags never carry attributes, so a
        # naive find('>') is safe here (unlike a start tag, where a '>'
        # inside a quoted attribute value would end the search too early —
        # that case instead relies on the length of get_starttag_text()).
        gt = self.html.find(">", start)
        return (gt + 1) if gt >= 0 else start

    def handle_starttag(self, tag, attrs):
        start = self._offset()
        if tag in VOID_TAGS:
            if self._is_discussion(attrs):
                text = self.get_starttag_text() or ""
                self.spans.append((start, start + len(text)))
            return
        self._stack.append((tag, start, self._is_discussion(attrs)))

    def handle_startendtag(self, tag, attrs):
        start = self._offset()
        if self._is_discussion(attrs):
            text = self.get_starttag_text() or ""
            self.spans.append((start, start + len(text)))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                _, start, disc = self._stack.pop(i)
                if disc:
                    end = self._end_tag_end(self._offset())
                    self.spans.append((start, end))
                break


def _merge_spans(spans):
    """Merge overlapping/nested spans into their outer bounds."""
    merged = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def strip_discussion_elements(html):
    p = _DiscussionSpanCollector(html)
    p.feed(html)
    p.close()
    out = html
    for s, e in reversed(_merge_spans(p.spans)):
        out = out[:s] + out[e:]
    return out


def strip_marker_block(html):
    has_begin = assets.MARKER_BEGIN in html
    has_end = assets.MARKER_END in html
    if has_begin != has_end:
        raise ValueError(
            "found only one of the samepage markers; the file may be"
            " corrupted, aborting"
        )
    if not has_begin:
        return html
    start = html.index(assets.MARKER_BEGIN)
    end = html.index(assets.MARKER_END) + len(assets.MARKER_END)
    if end < len(html) and html[end] == "\n":
        end += 1
    return html[:start] + html[end:]


def _has_class_token(attrs, tokens):
    d = {k: (v or "") for k, v in attrs}
    classes = d.get("class", "").split()
    return any(t in classes for t in tokens)


class _RuntimeMarkSpanCollector(HTMLParser):
    """Collect spans of runtime-decoration elements that a browser's "Save
    As" of the live DOM would have baked into the static HTML.

    - Elements carrying an sp-qpin / sp-qpin-svg / sp-insert-mark /
      sp-node-halo class: removed whole, including contents.
    - <mark> elements carrying sp-mark / sp-mark-fixed: unwrapped (only the
      start/end tag spans are collected; the text content is kept).
    """

    REMOVE_CLASSES = ("sp-qpin", "sp-qpin-svg", "sp-insert-mark", "sp-node-halo")
    UNWRAP_CLASSES = ("sp-mark", "sp-mark-fixed")

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.line_offsets = [0]
        for line in html.split("\n"):
            self.line_offsets.append(self.line_offsets[-1] + len(line) + 1)
        self.remove_spans = []
        self.unwrap_spans = []
        self._stack = []  # (tag, start, tag_end, kind)

    def _offset(self):
        line, col = self.getpos()
        return self.line_offsets[line - 1] + col

    def _end_tag_end(self, start):
        gt = self.html.find(">", start)
        return (gt + 1) if gt >= 0 else start

    def _kind(self, tag, attrs):
        if _has_class_token(attrs, self.REMOVE_CLASSES):
            return "remove"
        if tag == "mark" and _has_class_token(attrs, self.UNWRAP_CLASSES):
            return "unwrap"
        return None

    def handle_starttag(self, tag, attrs):
        start = self._offset()
        kind = self._kind(tag, attrs)
        text = self.get_starttag_text() or ""
        tag_end = start + len(text)
        if tag in VOID_TAGS:
            if kind == "remove":
                self.remove_spans.append((start, tag_end))
            return
        self._stack.append((tag, start, tag_end, kind))

    def handle_startendtag(self, tag, attrs):
        start = self._offset()
        kind = self._kind(tag, attrs)
        if kind == "remove":
            text = self.get_starttag_text() or ""
            self.remove_spans.append((start, start + len(text)))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                _, start, tag_end, kind = self._stack.pop(i)
                if kind == "remove":
                    end_start = self._offset()
                    end_end = self._end_tag_end(end_start)
                    self.remove_spans.append((start, end_end))
                elif kind == "unwrap":
                    end_start = self._offset()
                    end_end = self._end_tag_end(end_start)
                    self.unwrap_spans.append((start, tag_end))
                    self.unwrap_spans.append((end_start, end_end))
                break


def strip_runtime_decorations(html):
    """Remove sp-qpin/sp-insert-mark/sp-node-halo elements with their
    contents, and unwrap mark.sp-mark/mark.sp-mark-fixed (keeping text)."""
    p = _RuntimeMarkSpanCollector(html)
    p.feed(html)
    p.close()
    spans = _merge_spans(p.remove_spans + p.unwrap_spans)
    out = html
    for s, e in reversed(spans):
        out = out[:s] + out[e:]
    return out


CLASS_ATTR_RE = re.compile(r'(\sclass\s*=\s*)(["\'])(.*?)\2', re.DOTALL)


def _remove_class_token(tag_text, token):
    def repl(m):
        prefix, quote, value = m.group(1), m.group(2), m.group(3)
        tokens = [t for t in value.split() if t != token]
        if not tokens:
            return ""
        return prefix + quote + " ".join(tokens) + quote
    return CLASS_ATTR_RE.sub(repl, tag_text, count=1)


class _StartTagSpanCollector(HTMLParser):
    """Collect the span of every start tag (self-closing included).

    Stripping data-sp-* attributes must never spill over into ordinary body
    text (e.g. text that happens to literally contain the string
    data-sp-unit="x"). Limiting substitutions to spans collected here keeps
    the regex work confined to actual tag markup.
    """

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.line_offsets = [0]
        for line in html.split("\n"):
            self.line_offsets.append(self.line_offsets[-1] + len(line) + 1)
        self.spans = []

    def _offset(self):
        line, col = self.getpos()
        return self.line_offsets[line - 1] + col

    def _record(self):
        start = self._offset()
        text = self.get_starttag_text() or ""
        self.spans.append((start, start + len(text)))

    def handle_starttag(self, tag, attrs):
        self._record()

    def handle_startendtag(self, tag, attrs):
        self._record()


def strip_sp_data_attrs(html):
    """Remove every data-sp-* attribute, but only inside start-tag spans.

    This covers both CLI/generator-set attributes (data-sp-unit,
    data-sp-label, data-sp-index, data-sp-node) and JS-runtime attributes
    (data-sp-q-id, data-sp-cmt-id, data-sp-resp-id, data-sp-badge,
    data-sp-action) — they all share the data-sp- prefix.
    """
    p = _StartTagSpanCollector(html)
    p.feed(html)
    p.close()
    out = html
    for s, e in reversed(p.spans):
        tag_text = out[s:e]
        if "data-sp-" in tag_text:
            out = out[:s] + DATA_SP_ATTR.sub("", tag_text) + out[e:]
    return out


def strip_runtime_mark_class_token(html):
    """Remove the sp-mark-el class token, tag-scoped, keeping the element,
    its other classes, and its contents untouched."""
    p = _StartTagSpanCollector(html)
    p.feed(html)
    p.close()
    out = html
    for s, e in reversed(p.spans):
        tag_text = out[s:e]
        if "sp-mark-el" in tag_text:
            new_text = _remove_class_token(tag_text, "sp-mark-el")
            out = out[:s] + new_text + out[e:]
    return out


def finalize_html(html):
    """Return the clean, publishable HTML with the review layer removed.

    Order: discussion elements -> runtime-decoration elements
    (mark/qpin/insert-mark/node-halo) -> marker block -> data-sp-* attributes
    -> sp-mark-el class token.
    """
    html = strip_discussion_elements(html)
    html = strip_runtime_decorations(html)
    html = strip_marker_block(html)
    html = strip_sp_data_attrs(html)
    return strip_runtime_mark_class_token(html)


def collect_open_comments(path):
    """Load a comments JSON file and return the ids with status=="open"."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"could not parse comments JSON: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("comments"), list):
        raise ValueError("comments JSON must have a top-level \"comments\" array")
    return [c.get("id", "?") for c in data["comments"]
            if isinstance(c, dict) and c.get("status") == "open"]


def _write_atomic(path, text):
    """Write to a temp file and replace, so a crash mid-write cannot corrupt
    the target file."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".sp-tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        # mkstemp always creates the file as 0600; preserve the original
        # file's permissions when overwriting it (matters for HTML that
        # gets handed to people or served over the web).
        if path.exists():
            shutil.copymode(str(path), tmp)
        else:
            # Brand-new output, such as --finalize writing <stem>.final.html.
            # That file is the copy meant to be distributed, so leaving it at
            # mkstemp's 0600 would make it unreadable to everyone else. Follow
            # the process umask, the way a plain open() would.
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(tmp, 0o666 & ~umask)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Inject the samepage review layer into an existing HTML file"
    )
    ap.add_argument("input", help="input HTML file")
    ap.add_argument("--unit-selector", help="selector for unit elements (tag / .class / #id / tag.class)")
    ap.add_argument("--label-format", default="{n}", help="label format; {n} expands to the ordinal")
    ap.add_argument("--doc-id", help="identifier (default: input file stem)")
    ap.add_argument("--jump", choices=["scroll", "hash"], default="scroll")
    ap.add_argument("--out", help="output path (default: overwrite the input)")
    ap.add_argument("--responses", help="responses JSON to embed (replies to review comments)")
    ap.add_argument("--questions", help="questions JSON to embed (question pins)")
    ap.add_argument("--no-source-path", action="store_true",
                     help="embed sourcePath as null (for distributed output where a"
                          " local absolute path should not be baked in)")
    ap.add_argument("--finalize", action="store_true",
                     help="write a publishable HTML with the review layer and"
                          " discussion blocks removed, to a separate file")
    ap.add_argument("--comments", help="comments JSON used to check for unresolved items before finalizing")
    ap.add_argument("--force", action="store_true", help="finalize even if unresolved comments exist")
    a = ap.parse_args(argv)

    src = Path(a.input)
    if not src.is_file():
        print(f"Error: input file not found: {src}", file=sys.stderr)
        return 2

    if a.finalize:
        if a.unit_selector or a.responses or a.questions:
            print("Error: --finalize cannot be combined with injection options", file=sys.stderr)
            return 2
        if a.comments and not Path(a.comments).is_file():
            print(f"Error: comments JSON file not found: {a.comments}", file=sys.stderr)
            return 2
        try:
            if a.comments:
                open_ids = collect_open_comments(a.comments)
                if open_ids and not a.force:
                    print(
                        f"Error: {len(open_ids)} unresolved comment(s): {', '.join(open_ids)}\n"
                        "Run again once all comments are resolved, or pass --force to proceed anyway",
                        file=sys.stderr,
                    )
                    return 2
            else:
                print("Warning: --comments not given; skipped the unresolved-comment check", file=sys.stderr)
            html = src.read_text(encoding="utf-8")
            out_html = finalize_html(html)
        except (ValueError, UnicodeDecodeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        out_path = Path(a.out) if a.out else src.with_name(src.stem + ".final.html")
        _write_atomic(out_path, out_html)
        print(f"finalize complete: {out_path} (input {src} left unchanged)")
        return 0

    if a.responses and not Path(a.responses).is_file():
        print(f"Error: responses JSON file not found: {a.responses}", file=sys.stderr)
        return 2
    if a.questions and not Path(a.questions).is_file():
        print(f"Error: questions JSON file not found: {a.questions}", file=sys.stderr)
        return 2

    try:
        html = src.read_text(encoding="utf-8")
        doc_id = a.doc_id or src.stem

        if a.unit_selector:
            matched = len(find_unit_tags(html, a.unit_selector))
            if matched == 0:
                print(
                    f"Error: selector {a.unit_selector!r} matched 0 elements;"
                    " aborting since this may not be intentional",
                    file=sys.stderr,
                )
                return 2
            html, added = add_unit_attrs(html, a.unit_selector, a.label_format)
        else:
            added = 0
        responses = load_responses(a.responses) if a.responses else None
        questions = load_questions(a.questions) if a.questions else None
        # Path of the HTML that will hold the injected layer. Embedded in
        # the export JSON's "sourceHtml" so a session that only receives the
        # JSON can still locate the target file.
        out_html = Path(a.out) if a.out else src
        block = assets.render_block(
            doc_id, jump=a.jump, responses=responses, questions=questions,
            source_path=None if a.no_source_path else out_html.resolve(),
        )
        html = inject_block(html, block)
    except (ValueError, UnicodeDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    _write_atomic(a.out or src, html)
    n_resp = len(responses["responses"]) if responses else 0
    n_quest = len(questions["questions"]) if questions else 0
    print(
        f"injected: {a.out or src}  units-labeled={added}  responses={n_resp}  questions={n_quest}"
        f"  doc={doc_id}  jump={a.jump}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
