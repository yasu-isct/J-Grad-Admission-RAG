"""Extend the existing capture-editorial.py workflow for public portfolio sequences.

Only the published, saved-sample Demo is used. No local product service is started.
The earlier shot / at_top / report_content flow is retained with isolated output,
source-file hash verification, size limits, a raw Playwright video and scroll strips.
Requires existing Playwright, Pillow, Edge/Chromium and Playwright's FFmpeg recorder.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import struct
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image
from playwright.sync_api import expect, sync_playwright

BASE = "https://yasu-isct.github.io/J-Grad-Admission-RAG/"
DESKTOP = {"width": 1440, "height": 1000}
MOBILE = {"width": 390, "height": 900}
JST = timezone(timedelta(hours=9))
PNG_LIMIT = 400_000
VIDEO_LIMIT = 3_000_000
SOURCE_SCRIPT_SHA256 = "06e8cc3a9818cdf8b681eb42b50a589fe266264086f603ac93b5e03e76127740"


def now():
    return datetime.now(JST).isoformat(timespec="milliseconds")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={repo.as_posix()}", *args], cwd=repo
    )


def at_top(page, selector):
    # Reused from capture-editorial.py: keep the real sticky target bar visible.
    page.locator(selector).evaluate("""el => {
      const bar=document.getElementById('current-target-bar');
      const offset=bar&&getComputedStyle(bar).position==='sticky'?bar.offsetHeight:0;
      window.scrollTo(0,el.getBoundingClientRect().top+window.scrollY-offset-20);
    }""")


class Capture:
    def __init__(self, args):
        self.args = args
        self.out = args.output.resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        if list(self.out.glob("*.png")) or list(self.out.glob("*.webm")):
            raise ValueError("Use a new output directory; existing captures are never overwritten")
        self.audit = args.audit_dir.resolve()
        self.audit.mkdir(parents=True, exist_ok=True)
        self.records = []
        self.actions = []
        self.groups = []
        self.requests = []
        self.responses = []
        self.served = {}
        self.expected = {}
        self.errors = []
        self.started_at = now()
        self.repo = args.repo.resolve()
        self.commit = git(self.repo, "rev-parse", args.public_commit).decode().strip()
        self.main = git(self.repo, "rev-parse", "origin/main").decode().strip()

    def context(self, browser, viewport, **kwargs):
        context = browser.new_context(viewport=viewport, locale="ja-JP", **kwargs)

        def route_request(route):
            r = route.request
            self.requests.append({"method": r.method, "url": r.url})
            if r.method != "GET" or not r.url.startswith(BASE) or ".pdf" in r.url.lower():
                self.errors.append(f"Blocked unexpected network request: {r.method} {r.url}")
                route.abort()
            else:
                route.continue_()

        context.route("**/*", route_request)
        context.on("response", lambda response: self.responses.append(response))
        context.on("page", lambda page: page.on("pageerror", lambda e: self.errors.append(str(e))))
        return context

    def verify_responses(self):
        for response in self.responses:
            if response.status != 200:
                raise ValueError(f"Unexpected public response: {response.status} {response.url}")
            relative = unquote(urlparse(response.url).path.removeprefix("/J-Grad-Admission-RAG/"))
            if relative.endswith("/"):
                relative += "index.html"
            if relative not in self.expected:
                self.expected[relative] = sha(git(self.repo, "show", f"{self.commit}:{relative}"))
            digest = sha(response.body())
            if digest != self.expected[relative]:
                raise ValueError(f"Published bytes do not match {self.commit}: {relative}")
            self.served[relative] = digest
        self.responses.clear()
        if self.errors:
            raise ValueError(self.errors)

    def open(self, page, school, scenario):
        page.goto(BASE + f"app/?school={school}&scenario={scenario}", wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("lang", "ja")
        expect(page.locator("#requirements-submit")).to_be_enabled()
        self.click(page, "#requirements-submit")
        expect(page.locator("#requirements-continue")).to_be_visible()
        expect(page.locator("#requirements-output .requirement-card").first).to_be_visible()

    def click(self, page, selector, *, locator=None):
        button = locator if locator is not None else page.locator(selector)
        button.click()
        self.actions.append({"at": now(), "url": page.url, "action": "click", "selector": selector})

    def record(self, page, name, selector, started, kind="viewport", **extra):
        path = self.out / name
        raw = path.read_bytes()
        row = {
            "path": name,
            "entry_url": page.url,
            "viewport": page.viewport_size,
            "device_scale_factor": 1,
            "selector": selector,
            "captured_at": started,
            "capture_finished_at": now(),
            "public_commit_sha": self.commit,
            "kind": kind,
            "bytes": len(raw),
            "sha256": sha(raw),
            **extra,
        }
        if name.endswith(".png"):
            row["image_size"] = dict(zip(("width", "height"), struct.unpack(">II", raw[16:24])))
            if len(raw) > PNG_LIMIT:
                raise ValueError(f"PNG exceeds {PNG_LIMIT}: {name} ({len(raw)})")
        elif len(raw) > VIDEO_LIMIT:
            raise ValueError(f"Video exceeds {VIDEO_LIMIT}: {name} ({len(raw)})")
        self.records.append(row)

    def shot(self, page, name, selector=None):
        started = now()
        path = self.out / name
        if selector:
            page.locator(selector).screenshot(path=str(path), animations="disabled")
        else:
            page.screenshot(path=str(path), animations="disabled")
        self.record(
            page,
            name,
            selector or "html",
            started,
            "element crop" if selector else "viewport",
        )

    def graph(self, page):
        self.open(page, "gsfs", "working")
        card = (
            page.locator("#requirements-output .requirement-card")
            .filter(has_text="英語スコア証明")
            .first
        )
        self.click(
            page,
            '#requirements-output .requirement-card:has-text("英語スコア証明") >> nth=0 >> button >> nth=0',
            locator=card.locator("button").first,
        )
        expect(page.locator(".relation-node")).to_have_count(3)
        expect(page.locator(".relation-edge")).to_have_count(2)

    def original_from_graph(self, page):
        self.click(
            page,
            ".relation-node button >> nth=2",
            locator=page.locator(".relation-node button").nth(2),
        )
        expect(page.locator("#drawer-title")).to_have_text("公式原文")
        expect(page.locator(".relation-back")).to_be_visible()
        expect(page.locator("#drawer-content")).to_contain_text("28")

    def group_a(self, browser):
        context = self.context(browser, DESKTOP)
        try:
            page = context.new_page()
            self.graph(page)
            self.shot(page, "a-evidence-main.png")
            self.shot(page, "a-relations-detail.png", ".relation-graph")
            self.original_from_graph(page)
            self.shot(page, "a-original-detail.png", "#evidence-drawer")
            self.click(page, ".relation-back")
            expect(page.locator(".relation-node")).to_have_count(3)
            self.shot(page, "a-return-detail.png", "#evidence-drawer")
            self.verify_responses()
        finally:
            context.close()

    def group_b(self, browser):
        context = self.context(browser, DESKTOP)
        try:
            page = context.new_page()
            self.open(page, "isct", "materials")
            card = (
                page.locator("#requirements-output .requirement-card")
                .filter(has_text="入学志願票")
                .first
            )
            self.click(
                page,
                '#requirements-output .requirement-card:has-text("入学志願票") >> nth=0 >> details.evidence-choice-list > summary',
                locator=card.locator("details.evidence-choice-list > summary"),
            )
            self.click(
                page,
                '#requirements-output .requirement-card:has-text("入学志願票") >> nth=0 >> button >> nth=0',
                locator=card.locator("button").first,
            )
            expect(page.locator("#evidence-drawer")).to_be_visible()
            self.shot(page, "b-requirements.png")
            self.click(page, "#drawer-close")
            self.click(page, "#requirements-continue")
            expect(page.locator("#demo-scenario")).to_have_value("materials")
            at_top(page, "#applicant-panel")
            self.shot(page, "b-prepare-action.png")
            self.click(page, "#comparison-submit")
            expect(page.locator("#readiness-panel .requirement-card").first).to_be_visible()
            at_top(page, "#readiness-panel")
            self.shot(page, "b-preparation-result.png")
            self.verify_responses()
        finally:
            context.close()

    def scroll_report(self, page):
        """Join actual browser pixels from a continuous range, never expand/rewrite DOM."""
        started = now()
        body = page.locator("#reference-report-body")
        limits = body.evaluate("""el => {
          const paper=el.querySelector('.reader-report-paper');
          const materials=[...el.querySelectorAll('.reader-report-section')]
            .find(x=>x.querySelector('h3').textContent==='書類の準備リスト');
          const last=materials.querySelectorAll('li')[1];
          const b=el.getBoundingClientRect();
          return {start:Math.floor(paper.getBoundingClientRect().top-b.top+el.scrollTop),
            end:Math.ceil(last.getBoundingClientRect().bottom-b.top+el.scrollTop+12),
            x:b.x,y:b.y,width:b.width,height:el.clientHeight,scrollHeight:el.scrollHeight};
        }""")
        top = math.ceil(limits["y"])
        left = math.floor(limits["x"])
        right = min(MOBILE["width"], math.ceil(limits["x"] + limits["width"]))
        height = math.floor(limits["height"] - 2)
        start, end = limits["start"], limits["end"]
        strips = []
        pieces = []
        header = None
        for offset in range(start, end, height):
            actual = body.evaluate("(el, y) => {el.scrollTop=y;return el.scrollTop;}", offset)
            page.wait_for_timeout(100)
            frame = Image.open(io.BytesIO(page.screenshot(animations="disabled"))).convert("RGB")
            if header is None:
                header = frame.crop((left, 0, right, top))
            take = min(height, end - offset)
            pieces.append(frame.crop((left, top, right, top + take)))
            strips.append(
                {
                    "captured_at": now(),
                    "scroll_top": actual,
                    "pixels": take,
                    "frame_sha256": sha(frame.tobytes()),
                }
            )
        joined = Image.new("RGB", (right - left, top + sum(p.height for p in pieces)))
        joined.paste(header, (0, 0))
        y = top
        for piece in pieces:
            joined.paste(piece, (0, y))
            y += piece.height
        joined.save(self.out / "c-report-mobile-long.png", optimize=True, compress_level=9)
        self.record(
            page,
            "c-report-mobile-long.png",
            "#reference-report-body .reader-report-paper",
            started,
            "continuous scroll strips, native pixels; excerpt, not full report",
            scroll_range={"start": start, "end": end},
            horizontal_crop={"left": left, "right": right},
            strips=strips,
            image_processing="lossless PNG compression and native-pixel strip joining only",
        )

    def group_c(self, browser):
        context = self.context(browser, MOBILE)
        try:
            page = context.new_page()
            self.open(page, "isct", "materials")
            self.click(page, "#requirements-continue")
            self.click(page, "#comparison-submit")
            expect(page.locator("#readiness-panel .requirement-card").first).to_be_visible()
            self.click(
                page,
                ".reference-generate:visible >> last",
                locator=page.locator(".reference-generate:visible").last,
            )
            expect(page.locator("#reference-copy")).to_be_enabled()
            self.scroll_report(page)
            self.click(page, "#reference-close")
            card = (
                page.locator("#readiness-panel .requirement-card")
                .filter(has_text="入学志願票")
                .first
            )
            self.click(
                page,
                '#readiness-panel .requirement-card:has-text("入学志願票") >> nth=0 >> .evidence-choice-list summary',
                locator=card.locator(".evidence-choice-list summary"),
            )
            self.click(
                page,
                '#readiness-panel .requirement-card:has-text("入学志願票") >> nth=0 >> .evidence-choice-list button >> nth=0',
                locator=card.locator(".evidence-choice-list button").first,
            )
            expect(page.locator("#evidence-drawer")).to_be_visible()
            expect(page.locator(".pdf-source-link").first).to_be_visible()
            page.locator(".pdf-source-link").first.scroll_into_view_if_needed()
            self.shot(page, "c-source-mobile.png")
            self.verify_responses()
        finally:
            context.close()

    def video(self, browser):
        context = self.context(
            browser,
            DESKTOP,
            record_video_dir=str(self.audit / "raw-video"),
            record_video_size=DESKTOP,
        )
        started = now()
        start = time.monotonic()
        page = context.new_page()
        video = page.video
        try:
            self.graph(page)
            page.wait_for_timeout(1600)
            self.original_from_graph(page)
            page.wait_for_timeout(2000)
            self.click(page, ".relation-back")
            expect(page.locator(".relation-node")).to_have_count(3)
            self.verify_responses()
            page.wait_for_timeout(max(0, int((8.5 - (time.monotonic() - start)) * 1000)))
        finally:
            context.close()
        path = self.out / "a-evidence-walkthrough.webm"
        video.save_as(str(path))
        # Metadata is read with the same recorder binary, never encode/trim the output.
        ffmpeg = self.args.ffmpeg.resolve()
        info = subprocess.run([str(ffmpeg), "-i", str(path)], capture_output=True, text=True)
        import re

        duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info.stderr)
        if not duration:
            raise ValueError("Cannot verify raw WebM duration")
        seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
        if not 8 <= seconds <= 12 or "Audio:" in info.stderr:
            raise ValueError(f"Raw recording outside requested duration/audio bounds: {seconds}")
        self.record(
            page,
            path.name,
            [".relation-node button >> nth=2", ".relation-back"],
            started,
            "unmodified Playwright recording",
            duration_seconds=seconds,
            audio_tracks=0,
            post_processing="none",
            raw_recording_sha256=sha(Path(video.path()).read_bytes()),
        )

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=str(self.args.browser))
            self.browser_version = browser.version
            try:
                for name, run in [
                    ("A", self.group_a),
                    ("B", self.group_b),
                    ("C", self.group_c),
                    ("A-video", self.video),
                ]:
                    try:
                        run(browser)
                        self.groups.append({"group": name, "status": "captured"})
                    except Exception as e:
                        self.responses.clear()
                        self.groups.append({"group": name, "status": "skipped", "reason": str(e)})
                    print(name, self.groups[-1]["status"], flush=True)
            finally:
                browser.close()
        manifest = {
            "captured_on": datetime.now(JST).date().isoformat(),
            "started_at": self.started_at,
            "finished_at": now(),
            "public_base_url": BASE,
            "public_commit_sha": self.commit,
            "main_base_commit_sha": self.main,
            "source": "public saved-sample Demo; no free-input RAG",
            "derived_from": {
                "script": "outputs/public-demo/capture-editorial.py",
                "sha256": SOURCE_SCRIPT_SHA256,
            },
            "browser_version": self.browser_version,
            "capture_script_sha256": sha(Path(__file__).read_bytes()),
            "limits_bytes": {"png": PNG_LIMIT, "webm": VIDEO_LIMIT},
            "groups": self.groups,
            "captures": self.records,
            "actions": self.actions,
            "verified_served_files": self.served,
            "network_requests": self.requests,
            "browser_or_network_errors": self.errors,
            "mobile_source_path": "close report, return to preparation card, open original",
        }
        (self.out / "capture-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if any(g["status"] != "captured" for g in self.groups):
            raise SystemExit("Some sequences were skipped; inspect capture-manifest.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--public-commit", required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument(
        "--browser",
        type=Path,
        default=Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    )
    Capture(parser.parse_args()).run()


if __name__ == "__main__":
    main()
