"""Local design-only host: original static UI plus labeled response replays; no backend."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import argparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/app"):
            text = (STATIC / "advanced.html").read_text(encoding="utf-8")
            text = text.replace(
                "<title>J-Grad 申请检查向导</title>", "<title>完整前端样板 · J-Grad</title>"
            )
            text = text.replace(
                '<script src="/assets/overview.js"',
                '<link rel="stylesheet" href="/preview/preview.css"><script src="/preview/data.js"></script><script src="/preview/mock.js"></script><script src="/assets/overview.js"',
            )
            text = text.replace(
                '<script src="/assets/app.js" defer></script>',
                '<script src="/assets/app.js" defer></script><script src="/preview/presentation.js" defer></script>',
            )
            text = text.replace(
                "<body>",
                '<body><aside class="preview-banner"><p><strong>完整前端交互样板</strong> · 沿用现有两校四步页面。官方内容为既有历史响应回放；个人准备状态为示例交互，不运行招生规则或问答模型。</p><button type="button" onclick="previewChoose(\'legacy_applicant\')">演示东科大四步流程</button><button type="button" onclick="previewChoose(\'reviewed_material_slice\')">演示东大与依据关系窗口</button></aside>',
            )
            body = text.encode("utf-8")
            kind = "text/html; charset=utf-8"
        elif path.startswith("/assets/") or path.startswith("/preview/"):
            base = STATIC if path.startswith("/assets/") else HERE
            name = path.rsplit("/", 1)[-1]
            if (
                not name
                or ".." in name
                or "/" in name
                or "\\" in name
                or Path(name).suffix not in (".js", ".mjs", ".css")
            ):
                self.send_error(404)
                return
            file = base / name
            if not file.is_file():
                self.send_error(404)
                return
            body = file.read_bytes()
            kind = (
                "text/javascript; charset=utf-8"
                if file.suffix in (".js", ".mjs")
                else "text/css; charset=utf-8"
            )
        else:
            self.send_error(404, "Design preview only; no real backend or PDF serving")
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8029)
    args = parser.parse_args()
    print(
        f"Design preview http://127.0.0.1:{args.port}/app; no product backend or model", flush=True
    )
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
