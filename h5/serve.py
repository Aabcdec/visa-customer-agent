"""本地静态页 + /api/run 反向代理，避免浏览器直连 coze.site 的 CORS 问题。

用法:
  python serve.py
  打开 http://127.0.0.1:8787

密钥从同目录 .env 读取（VISA_API_TOKEN 或 DEEPSEEK_API_KEY），勿提交仓库。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 不覆盖已有环境变量
        os.environ.setdefault(key, value)


load_dotenv(ROOT / ".env")

UPSTREAM = os.environ.get("VISA_API_URL", "https://5dq8j354gp.coze.site/run").rstrip("/")
HOST = os.environ.get("H5_HOST", "127.0.0.1")
PORT = int(os.environ.get("H5_PORT", "8787"))


def resolve_token(header_auth: str) -> str:
    if header_auth and "YOUR_TOKEN" not in header_auth:
        return header_auth
    token = (
        os.environ.get("VISA_API_TOKEN", "").strip()
        or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    )
    return f"Bearer {token}" if token else ""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/api/health":
            has_token = bool(
                os.environ.get("VISA_API_TOKEN", "").strip()
                or os.environ.get("DEEPSEEK_API_KEY", "").strip()
            )
            payload = json.dumps(
                {"ok": True, "upstream": UPSTREAM, "token_configured": has_token},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/api/run":
            self.send_error(404, "Not Found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        auth = resolve_token(self.headers.get("Authorization", ""))

        if not auth:
            data = json.dumps(
                {"message": "未配置 Token：请在 h5/.env 写入 VISA_API_TOKEN 或 DEEPSEEK_API_KEY"},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(401)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        req = urllib.request.Request(
            UPSTREAM,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": auth,
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                status = resp.status
                content_type = resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            data = exc.read()
            status = exc.code
            content_type = exc.headers.get("Content-Type", "application/json")
        except Exception as exc:  # noqa: BLE001
            data = json.dumps({"message": str(exc)}, ensure_ascii=False).encode("utf-8")
            status = 502
            content_type = "application/json"

        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[h5] {self.address_string()} - {fmt % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    has_token = bool(
        os.environ.get("VISA_API_TOKEN", "").strip()
        or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    )
    print(f"H5 ready: http://{HOST}:{PORT}")
    print(f"Proxy POST /api/run -> {UPSTREAM}")
    print(f"Token from .env: {'yes' if has_token else 'NO'}")
    server.serve_forever()


if __name__ == "__main__":
    main()
