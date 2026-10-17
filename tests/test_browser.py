"""Browser E2E tests for the samepage review layer.

These tests build a `<!-- samepage:begin -->` block directly from the bundled
assets in `samepage/assets/{samepage.css,panel.html,samepage.js}` plus a
`window.SAMEPAGE_CONFIG` (and optionally `SAMEPAGE_RESPONSES` /
`SAMEPAGE_QUESTIONS`) script, inject it into the fixture HTML before `</body>`,
write the result to a temporary file, and open it in headless Chromium with
Playwright via `file://`.
"""
import json
import re
import textwrap
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(not HAVE_PLAYWRIGHT, reason="playwright not installed")

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "samepage" / "assets"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "review_sample.html"

MARKER_BEGIN = "<!-- samepage:begin -->"
MARKER_END = "<!-- samepage:end -->"


def _read(name):
    text = (ASSETS_DIR / name).read_text(encoding="utf-8").strip()
    assert "</script" not in text.lower(), f"{name} contains a literal </script"
    return text


def build_block(doc_id="review_sample", jump="scroll", storage_key=None,
                 responses=None, questions=None, source_path=None):
    config = {
        "doc": doc_id,
        "jump": jump,
        "storageKey": storage_key or f"samepage:{doc_id}",
        "sourcePath": str(source_path) if source_path else None,
    }
    config_payload = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")
    parts = [
        MARKER_BEGIN,
        f"<style>\n{_read('samepage.css')}\n</style>",
        _read("panel.html"),
        f"<script>window.SAMEPAGE_CONFIG={config_payload};</script>",
    ]
    if responses is not None:
        payload = json.dumps(responses, ensure_ascii=False).replace("</", "<\\/")
        parts.append(f"<script>window.SAMEPAGE_RESPONSES={payload};</script>")
    if questions is not None:
        payload = json.dumps(questions, ensure_ascii=False).replace("</", "<\\/")
        parts.append(f"<script>window.SAMEPAGE_QUESTIONS={payload};</script>")
    parts += [
        f"<script>\n{_read('samepage.js')}\n</script>",
        MARKER_END,
    ]
    return "\n".join(parts) + "\n"


def build_page(tmp_path, **kwargs):
    html = FIXTURE.read_text(encoding="utf-8")
    block = build_block(**kwargs)
    assert "</body>" in html
    html = html.replace("</body>", block + "</body>")
    out = tmp_path / "page.html"
    out.write_text(html, encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    yield pg
    ctx.close()


def open_file(page, path):
    page.goto(f"file://{path}")
    page.wait_for_selector("#spBadge")


def test_text_selection_comment_creates_mark(tmp_path, page):
    path = build_page(tmp_path)
    open_file(page, path)

    intro = page.locator("#intro")
    # select the word "quarterly" inside the intro paragraph
    page.evaluate(
        """() => {
            const p = document.getElementById('intro');
            const text = p.firstChild;
            const idx = text.nodeValue.indexOf('quarterly');
            const range = document.createRange();
            range.setStart(text, idx);
            range.setEnd(text, idx + 'quarterly'.length);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }"""
    )
    page.dispatch_event("#intro", "mouseup")
    page.wait_for_timeout(100)
    page.keyboard.press("a")
    page.wait_for_selector("#spPopupText", state="visible")
    page.fill("#spPopupText", "Please double check this word.")
    page.keyboard.press("Enter")

    page.wait_for_selector("mark.sp-mark")
    marks = page.locator("mark.sp-mark")
    assert marks.count() == 1
    assert marks.first.inner_text() == "quarterly"

    count = page.locator("#spPanelCount").inner_text()
    assert count == "1"


def test_export_json_has_skill_and_text_range_target(tmp_path, page):
    path = build_page(tmp_path)
    open_file(page, path)

    page.evaluate(
        """() => {
            const p = document.getElementById('scope-p1');
            const text = p.firstChild;
            const idx = text.nodeValue.indexOf('internal pilot users');
            const range = document.createRange();
            range.setStart(text, idx);
            range.setEnd(text, idx + 'internal pilot users'.length);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }"""
    )
    page.dispatch_event("#scope-p1", "mouseup")
    page.wait_for_timeout(100)
    page.keyboard.press("a")
    page.wait_for_selector("#spPopupText", state="visible")
    page.fill("#spPopupText", "Is this the final scope decision?")
    page.keyboard.press("Enter")
    page.wait_for_selector("mark.sp-mark")

    data = page.evaluate(
        """() => {
            document.getElementById('spJsonBtn').click();
            return document.getElementById('spJsonText').value;
        }"""
    )
    parsed = json.loads(data)
    assert parsed["_skill"] == "samepage"
    assert len(parsed["comments"]) == 1
    target = parsed["comments"][0]["targets"][0]
    assert target["kind"] == "text-range"
    assert target["selectedText"] == "internal pilot users"


def test_element_pick_yields_nth_of_type_path(tmp_path, page):
    path = build_page(tmp_path)
    open_file(page, path)

    page.keyboard.press("e")
    page.hover("#scope-p2")
    page.wait_for_timeout(50)
    # click near the vertical middle of the paragraph, away from top/bottom edges,
    # so it resolves to the element itself rather than an insertion point
    box = page.locator("#scope-p2").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_selector("#spPopupText", state="visible")
    page.fill("#spPopupText", "Consider trimming this sentence.")
    page.keyboard.press("Enter")

    data = page.evaluate(
        """() => {
            document.getElementById('spJsonBtn').click();
            return document.getElementById('spJsonText').value;
        }"""
    )
    parsed = json.loads(data)
    assert len(parsed["comments"]) == 1
    target = parsed["comments"][0]["targets"][0]
    assert target["kind"] == "element"
    assert re.search(r"nth-of-type\(\d+\)", target["path"])


def test_svg_diagram_node_pick_yields_diagram_node(tmp_path, page):
    path = build_page(tmp_path)
    open_file(page, path)

    page.keyboard.press("e")
    box = page.evaluate(
        """() => {
            const g = document.querySelector('[data-sp-node="n2"]');
            const box = g.getBoundingClientRect();
            return {x: box.x, y: box.y, width: box.width, height: box.height};
        }"""
    )
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(50)
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_selector("#spPopupText", state="visible")
    page.fill("#spPopupText", "Rename this stage to 'Transform'.")
    page.keyboard.press("Enter")

    data = page.evaluate(
        """() => {
            document.getElementById('spJsonBtn').click();
            return document.getElementById('spJsonText').value;
        }"""
    )
    parsed = json.loads(data)
    assert len(parsed["comments"]) == 1
    target = parsed["comments"][0]["targets"][0]
    assert target["kind"] == "diagram-node"
    assert target["nodeId"] == "n2"

    # a halo should be drawn on the node
    assert page.locator(".sp-node-halo").count() == 1


def test_questions_pin_and_answer_recorded(tmp_path, page):
    questions = {
        "questions": [
            {
                "id": "q-abc12345",
                "question": "Should the pilot duration stay at four weeks?",
                "target": {
                    "kind": "text-range",
                    "selectedText": "four weeks",
                    "contextBefore": "and runs for ",
                    "contextAfter": " before the go/no-go",
                },
                "choices": ["Keep four weeks", "Extend to six weeks"],
            }
        ]
    }
    path = build_page(tmp_path, questions=questions)
    open_file(page, path)

    pin = page.locator(".sp-qpin")
    assert pin.count() == 1
    assert pin.first.inner_text() == "❓"

    page.keyboard.press("c")  # open the panel; question items sit off-screen until it's open
    page.wait_for_selector("#spPanel.open")
    page.click(".sp-qitem-choices button:has-text('Keep four weeks')")
    page.wait_for_timeout(100)

    assert page.locator(".sp-qpin.sp-qpin-answered").count() == 1

    data = page.evaluate(
        """() => {
            document.getElementById('spJsonBtn').click();
            return document.getElementById('spJsonText').value;
        }"""
    )
    parsed = json.loads(data)
    assert len(parsed["answers"]) == 1
    assert parsed["answers"][0]["questionId"] == "q-abc12345"
    assert parsed["answers"][0]["answer"] == "Keep four weeks"


def test_response_fixed_text_gets_green_highlight(tmp_path, page):
    responses = {
        "doc": "review_sample",
        "respondedAt": "2026-01-01T00:00:00.000Z",
        "responses": [
            {
                "id": "c-resp0001",
                "reply": "Clarified that external customers are excluded for now.",
                "action": "fixed",
                "fixedText": "External customers are out of scope for this phase",
                "unit": "u1",
            }
        ],
    }
    path = build_page(tmp_path, responses=responses)
    open_file(page, path)

    mark = page.locator("mark.sp-mark-fixed")
    assert mark.count() == 1
    assert "External customers are out of scope" in mark.first.inner_text()


def test_reload_restores_comments_from_local_storage(tmp_path, page):
    path = build_page(tmp_path)
    open_file(page, path)

    page.evaluate(
        """() => {
            const p = document.getElementById('risks-p1');
            const text = p.firstChild;
            const idx = text.nodeValue.indexOf('data migration timing');
            const range = document.createRange();
            range.setStart(text, idx);
            range.setEnd(text, idx + 'data migration timing'.length);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }"""
    )
    page.dispatch_event("#risks-p1", "mouseup")
    page.wait_for_timeout(100)
    page.keyboard.press("a")
    page.wait_for_selector("#spPopupText", state="visible")
    page.fill("#spPopupText", "Who owns this risk?")
    page.keyboard.press("Enter")
    page.wait_for_selector("mark.sp-mark")

    open_file(page, path)  # reload the same file:// URL

    page.wait_for_selector("mark.sp-mark")
    assert page.locator("mark.sp-mark").count() == 1
    assert page.locator("#spPanelCount").inner_text() == "1"


# navigator.clipboard isn't reliably usable on file:// under headless Chromium, so the
# direct-copy tests stub writeText and assert on what the page hands it.
CLIPBOARD_STUB = """() => {
    window.__spCopied = null;
    const stub = {writeText: (t) => { window.__spCopied = t; return Promise.resolve(); }};
    try {
        Object.defineProperty(navigator, 'clipboard', {value: stub, configurable: true});
    } catch (e) {
        navigator.clipboard = stub;
    }
}"""


def test_panel_copy_button_copies_json_without_opening_modal(tmp_path, page):
    path = build_page(tmp_path)
    open_file(page, path)
    page.evaluate(CLIPBOARD_STUB)

    page.evaluate(
        """() => {
            const p = document.getElementById('scope-p1');
            const text = p.firstChild;
            const idx = text.nodeValue.indexOf('internal pilot users');
            const range = document.createRange();
            range.setStart(text, idx);
            range.setEnd(text, idx + 'internal pilot users'.length);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }"""
    )
    page.dispatch_event("#scope-p1", "mouseup")
    page.wait_for_timeout(100)
    page.keyboard.press("a")
    page.wait_for_selector("#spPopupText", state="visible")
    page.fill("#spPopupText", "Is this the final scope decision?")
    page.keyboard.press("Enter")
    page.wait_for_selector("mark.sp-mark")

    page.click("#spBadge")   # open the panel (focus is still in the comment box, so 'c' would type)
    page.click("#spJsonCopyDirect")
    page.wait_for_function(
        "() => document.getElementById('spJsonCopyDirect').textContent.includes('Copied')"
    )

    parsed = json.loads(page.evaluate("() => window.__spCopied"))
    assert parsed["_skill"] == "samepage"
    assert len(parsed["comments"]) == 1
    # the point of the button: same payload as "Show JSON" → "Copy", without the modal
    assert page.evaluate(
        "() => document.getElementById('spJsonModal').classList.contains('open')"
    ) is False


def test_panel_copy_button_reports_when_there_is_nothing_to_copy(tmp_path, page):
    path = build_page(tmp_path)
    open_file(page, path)
    page.evaluate(CLIPBOARD_STUB)

    page.keyboard.press("c")
    page.click("#spJsonCopyDirect")
    page.wait_for_function(
        "() => document.getElementById('spJsonCopyDirect').textContent === 'No comments yet'"
    )
    assert page.evaluate("() => window.__spCopied") is None


def test_j_shortcut_flashes_the_panel_button_too(tmp_path, page):
    """The open panel covers the badge, so 'j' has to report through the button as well."""
    path = build_page(tmp_path)
    open_file(page, path)
    page.evaluate(CLIPBOARD_STUB)

    page.evaluate(
        """() => {
            const p = document.getElementById('scope-p1');
            const text = p.firstChild;
            const idx = text.nodeValue.indexOf('internal pilot users');
            const range = document.createRange();
            range.setStart(text, idx);
            range.setEnd(text, idx + 'internal pilot users'.length);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }"""
    )
    page.dispatch_event("#scope-p1", "mouseup")
    page.wait_for_timeout(100)
    page.keyboard.press("a")
    page.wait_for_selector("#spPopupText", state="visible")
    page.fill("#spPopupText", "Is this the final scope decision?")
    page.keyboard.press("Enter")
    page.wait_for_selector("mark.sp-mark")

    page.click("#spBadge")   # open the panel (focus is still in the comment box, so 'c' would type)
    page.keyboard.press("j")
    page.wait_for_function(
        "() => document.getElementById('spJsonCopyDirect').textContent.includes('Copied')"
    )
    assert json.loads(page.evaluate("() => window.__spCopied"))["_skill"] == "samepage"
    # and the label goes back on its own
    page.wait_for_function(
        "() => document.getElementById('spJsonCopyDirect').textContent.includes('Copy JSON')"
    )
