#!/usr/bin/env python3
"""Build docs/images/demo.gif (and demo.png) — a storyboard walkthrough of the
samepage review layer, driven end-to-end with Playwright against
docs/demo/sample.html.

Regenerate with:
    python3 docs/build_demo_gif.py

Requires: playwright (with chromium installed) and Pillow.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: playwright is not installed on this python3.", file=sys.stderr)
    raise SystemExit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "samepage" / "cli.py"
DEMO_SRC = REPO_ROOT / "docs" / "demo" / "sample.html"
OUT_DIR = REPO_ROOT / "docs" / "images"
SCRATCH = Path(tempfile.gettempdir())

VIEWPORT = {"width": 1200, "height": 750}

FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    str(Path.home() / ".local" / "share" / "fonts" / "DejaVuSans.ttf"),
)

CAPTIONS = [
    "1 - Clean document, review layer injected",
    "2 - Select text, press a, write a comment",
    "3 - Comment submitted, highlight appears",
    "4 - Press e to pick a diagram node, comment on it",
    "5 - Press c for the panel, j to copy the JSON",
    "6 - Agent replies (--responses) and asks back (--questions)",
]

CLIP_INIT_SCRIPT = """
() => {
  try {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: () => Promise.resolve() },
      configurable: true,
    });
  } catch (e) { /* already stubbed */ }
}
"""


def run_cli(*args):
    cmd = [sys.executable, str(CLI)] + list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("samepage cli.py failed:", proc.stderr, file=sys.stderr)
        raise SystemExit(2)
    return proc.stdout.strip()


def select_range_js(elem_id, needle):
    """Return a page.evaluate JS snippet that selects `needle` inside the
    first text node of #elem_id, mirroring tests/test_browser.py."""
    return f"""
    () => {{
      const p = document.getElementById('{elem_id}');
      const text = p.firstChild;
      const idx = text.nodeValue.indexOf('{needle}');
      const range = document.createRange();
      range.setStart(text, idx);
      range.setEnd(text, idx + '{needle}'.length);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }}
    """


def _load_caption_font(size: int = 18):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="samepage-demo-", dir=str(SCRATCH)))
    try:
        doc_path = work / "sample.html"
        # Constrain body width to 860px (1200px viewport - 340px right panel)
        # so the right edge of the document card and SVG diagram remain fully
        # visible when the comment panel opens in frames 5 and 6.
        sample_html = DEMO_SRC.read_text(encoding="utf-8").replace(
            "max-width:1200px;", "max-width:860px;"
        )
        doc_path.write_text(sample_html, encoding="utf-8")

        # Step 2: inject the base review layer (no responses/questions yet).
        print(run_cli(
            str(doc_path), "--unit-selector", "body", "--label-format", "Whole",
            "--no-source-path",
        ))

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
            context.add_init_script(CLIP_INIT_SCRIPT)
            page = context.new_page()
            page.goto(f"file://{doc_path}")
            page.wait_for_selector("#spBadge")

            # ---- F1: clean page ----
            page.wait_for_timeout(1500)
            shot1 = work / "f1.png"
            page.screenshot(path=str(shot1))

            # ---- F2: select text, open comment popup, type (not yet submitted) ----
            page.evaluate(select_range_js("intro", "quarterly"))
            page.dispatch_event("#intro", "mouseup")
            page.wait_for_timeout(150)
            page.keyboard.press("a")
            page.wait_for_selector("#spPopupText", state="visible")
            page.fill("#spPopupText", "This claim needs a source.")
            page.wait_for_timeout(1800)
            shot2 = work / "f2.png"
            page.screenshot(path=str(shot2))

            # ---- F3: submit the comment, highlight visible ----
            page.keyboard.press("Enter")
            page.wait_for_selector("mark.sp-mark")
            # Submitting via Enter leaves focus in the (now hidden) textarea; the
            # 'e'/'c'/'j' shortcuts are ignored while focus is in a TEXTAREA/INPUT
            # (see samepage.js's keydown handler), so blur explicitly.
            page.evaluate("() => document.activeElement && document.activeElement.blur()")
            page.wait_for_timeout(1800)
            shot3 = work / "f3.png"
            page.screenshot(path=str(shot3))

            # ---- F4: element-pick mode on a diagram node, add a second comment ----
            page.keyboard.press("e")
            box = page.evaluate(
                """() => {
                    const g = document.querySelector('[data-sp-node="review-layer"]');
                    const r = g.getBoundingClientRect();
                    return {x: r.x, y: r.y, width: r.width, height: r.height};
                }"""
            )
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(150)
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_selector("#spPopupText", state="visible")
            page.fill("#spPopupText", "Rename to 'Review layer'.")
            page.keyboard.press("Enter")
            page.evaluate("() => document.activeElement && document.activeElement.blur()")
            page.wait_for_timeout(2000)
            shot4 = work / "f4.png"
            page.screenshot(path=str(shot4))

            # ---- F5: open panel, press j, capture the "copied" feedback ----
            page.keyboard.press("c")
            page.wait_for_selector("#spPanel.open")
            page.wait_for_timeout(200)
            page.keyboard.press("j")
            page.wait_for_timeout(150)  # badge shows "Copied" briefly
            page.wait_for_timeout(2050)
            shot5 = work / "f5.png"
            page.screenshot(path=str(shot5))

            # Pull the export JSON + comment ids while the context (and its
            # localStorage) is still alive, so F6 can build responses/questions
            # that reference the real comment ids.
            export_raw = page.evaluate(
                """() => {
                    document.getElementById('spJsonBtn').click();
                    return document.getElementById('spJsonText').value;
                }"""
            )
            export_data = json.loads(export_raw)
            comment_ids = [c["id"] for c in export_data["comments"]]
            if len(comment_ids) < 2:
                print(
                    f"Error: expected 2 comments before F6, found {len(comment_ids)}",
                    file=sys.stderr,
                )
                raise SystemExit(2)

            page.close()

            # ---- Build responses + questions JSON, re-inject, reopen ----
            responses = {
                "doc": "sample",
                "respondedAt": "2026-08-28T00:00:00.000Z",
                "responses": [
                    {
                        "id": comment_ids[0],
                        "reply": "Added a link to the internal planning doc that backs this claim.",
                        "action": "fixed",
                        # Deliberately anchored in a different paragraph than the
                        # original comment's "quarterly" mark: a fixedText range
                        # overlapping an existing <mark> would be mis-split.
                        "fixedText": "the finalized artifact that ships externally",
                    },
                    {
                        "id": comment_ids[1],
                        "reply": "Left as 'Review layer' — matches the name used elsewhere in the doc.",
                        "action": "declined",
                    },
                ],
            }
            questions = {
                "questions": [
                    {
                        "id": "q-demo0001",
                        "question": "Should the diagram also show the finalize step?",
                        "target": {"kind": "diagram-node", "nodeId": "final"},
                        "choices": ["Yes, add it", "No, keep it as-is"],
                    }
                ]
            }
            responses_path = work / "responses.json"
            questions_path = work / "questions.json"
            responses_path.write_text(json.dumps(responses, ensure_ascii=False), encoding="utf-8")
            questions_path.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")

            print(run_cli(
                str(doc_path), "--unit-selector", "body", "--label-format", "Whole",
                "--no-source-path",
                "--responses", str(responses_path),
                "--questions", str(questions_path),
            ))

            page = context.new_page()
            page.goto(f"file://{doc_path}")
            page.wait_for_selector("#spBadge")
            page.wait_for_selector("mark.sp-mark-fixed", state="attached")
            page.keyboard.press("c")
            page.wait_for_selector("#spPanel.open")
            page.wait_for_timeout(2600)
            shot6 = work / "f6.png"
            page.screenshot(path=str(shot6))
            page.close()

            context.close()
            browser.close()

        shots = [shot1, shot2, shot3, shot4, shot5, shot6]
        raw_frames = [Image.open(s).convert("RGB") for s in shots]
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # ---- Post-process: caption bar + downscale ----
    TARGET_WIDTH = 960
    CAPTION_H = 40
    captioned = []
    font = _load_caption_font(18)

    for img, caption in zip(raw_frames, CAPTIONS):
        w, h = img.size
        scale = TARGET_WIDTH / w
        new_h = int(h * scale)
        resized = img.resize((TARGET_WIDTH, new_h), Image.LANCZOS)
        canvas = Image.new("RGB", (TARGET_WIDTH, new_h + CAPTION_H), (20, 22, 28))
        canvas.paste(resized, (0, 0))
        draw = ImageDraw.Draw(canvas)
        bbox = draw.textbbox((0, 0), caption, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        tx = (TARGET_WIDTH - text_w) // 2
        ty = new_h + (CAPTION_H - text_h) // 2 - bbox[1]
        draw.text((tx, ty), caption, fill=(255, 255, 255), font=font)
        captioned.append(canvas)

    # Save the last frame as the static PNG fallback.
    png_path = OUT_DIR / "demo.png"
    captioned[-1].save(png_path, format="PNG")

    # ---- Assemble the GIF ----
    durations = [1500, 1800, 1800, 2000, 2200, 2600]

    def build_gif(frames, width, colors, out_path):
        scale = width / frames[0].width
        sized = frames
        if width != frames[0].width:
            sized = [
                f.resize((width, int(f.height * scale)), Image.LANCZOS) for f in frames
            ]
        quantized = [
            f.quantize(colors=colors, method=Image.Quantize.MEDIANCUT) for f in sized
        ]
        quantized[0].save(
            out_path,
            save_all=True,
            append_images=quantized[1:],
            duration=durations,
            loop=0,
            optimize=True,
        )
        return out_path.stat().st_size

    gif_path = OUT_DIR / "demo.gif"
    size = build_gif(captioned, 960, 256, gif_path)
    if size >= 2_500_000:
        size = build_gif(captioned, 880, 256, gif_path)
    if size >= 2_500_000:
        size = build_gif(captioned, 880, 128, gif_path)
    if size >= 4_000_000:
        print(f"Error: GIF still {size} bytes after downscaling; stopping.", file=sys.stderr)
        raise SystemExit(2)

    png_size = png_path.stat().st_size
    with Image.open(gif_path) as g:
        gif_w, gif_h = g.size
        n_frames = g.n_frames

    print(f"wrote {gif_path} ({gif_w}x{gif_h}, {n_frames} frames, {size/1024:.0f} KB)")
    print(f"wrote {png_path} ({png_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()

