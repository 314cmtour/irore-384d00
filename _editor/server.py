#!/usr/bin/env python3
"""iro:re 作品サイトの編集室（手元の Mac だけで動く・2026-10-18）

「編集室.command」から起動する。ブラウザに編集画面を開き、
  保存   → content.json を書き、index.html を作り直す（手元だけ・外には出ない）
  公開   → git commit して push（GitHub Pages に数分で反映）
  写真   → HEIC/JPEG/PNG を受け取り、向きを直し、長辺2000px・位置情報なしの JPEG にして media/ に置く

★守り: 127.0.0.1 だけで待ち受ける／Host を確かめる／書き込みは起動時に作る合言葉つきのときだけ。
"""
import json, os, re, secrets, shutil, subprocess, sys, tempfile, threading, time, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent.parent
EDITOR = ROOT / "_editor"
MEDIA = ROOT / "media"
TOKEN = secrets.token_urlsafe(24)
PORT = int(os.environ.get("IRORE_EDITOR_PORT", "8490"))
MAX_UPLOAD = 80 * 1024 * 1024
LOCK = threading.Lock()

sys.path.insert(0, str(EDITOR))
import build  # noqa: E402


def run(cmd):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def validate(c):
    assert isinstance(c, dict) and isinstance(c.get("blocks"), list), "形が違います"
    for b in c["blocks"]:
        assert b.get("type") in ("text", "photo", "video", "teaser", "data", "gallery"), f"知らない種類: {b.get('type')}"
        if b["type"] == "gallery":
            assert isinstance(b.get("items"), list) and b["items"], "まとまりに写真がありません"
            for it in b["items"]:
                v = it.get("src", "")
                assert re.fullmatch(r"media/[A-Za-z0-9._-]+", v), f"写真の場所が不正です: {v}"
                assert (ROOT / v).is_file(), f"ファイルがありません: {v}"
        if b["type"] == "text":
            assert b.get("style") in build.STYLES, f"文字の大きさが不正です: {b.get('style')}"
        if b["type"] in ("photo", "video"):
            assert b.get("layout") in build.LAYOUTS, f"配置が不正です: {b.get('layout')}"
        for key in ("src", "poster"):
            if key in b:
                v = b[key]
                assert re.fullmatch(r"media/[A-Za-z0-9._-]+", v), f"写真の場所が不正です: {v}"
                assert (ROOT / v).is_file(), f"ファイルがありません: {v}"
    build.build(c)  # 組み立てられるかを先に確かめる（失敗したら保存しない）


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def referenced(c):
    refs = {c["meta"].get("ogImage", "")}
    for b in c["blocks"]:
        refs.update(b.get(k, "") for k in ("src", "poster"))
        refs.update(it.get("src", "") for it in b.get("items", []))
    return {r for r in refs if r}


def save_photo(data, name):
    ext = Path(name).suffix.lower()
    if ext not in (".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"):
        raise ValueError("写真は HEIC・JPEG・PNG・WebP・TIFF に対応しています")
    from PIL import Image, ImageOps
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{ext}"
        src.write_bytes(data)
        if ext in (".heic", ".heif"):
            jpg = Path(td) / "conv.jpg"
            p = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95", str(src), "--out", str(jpg)], capture_output=True)
            if p.returncode or not jpg.exists():
                raise ValueError("HEIC を読めませんでした")
            src = jpg
        im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        im.thumbnail((2000, 2000), Image.LANCZOS)
        out = MEDIA / f"ph-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}.jpg"
        im.save(out, "JPEG", quality=82, optimize=True, progressive=True)  # exif を渡さない＝位置情報・撮影機器は残らない
        return f"media/{out.name}", im.size


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, *a):
        pass

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if not self._host_ok():
            return self.send_error(403)
        path = urlparse(self.path).path
        if path in ("/", "/editor"):
            self.path = "/_editor/editor.html"
        elif path == "/api/content":
            return self._json(200, json.loads((ROOT / "content.json").read_text(encoding="utf-8")))
        elif path == "/api/token":
            # ブックマークから開いたとき用。同じ画面（127.0.0.1:8490）からの読み取りだけに渡す
            # （他のサイトからは、ブラウザの決まりで中身を読めない／Host 確認で DNS の付け替えも止まる）
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                return self._json(403, {"ok": False})
            return self._json(200, {"token": TOKEN})
        elif path == "/api/status":
            _, out = run(["git", "status", "--short", "--", "content.json", "index.html", "media"])
            _, ahead = run(["git", "rev-list", "--count", "@{u}..HEAD"])
            return self._json(200, {"changes": [l for l in out.splitlines() if l.strip()], "unpushed": ahead})
        elif path == "/api/media":
            files = sorted(p.name for p in MEDIA.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
            return self._json(200, {"files": files})
        real = Path(self.translate_path(self.path)).resolve()
        rel = real.relative_to(ROOT).as_posix().lower() if real.is_relative_to(ROOT) else None
        if rel is None or rel == ".git" or rel.startswith(".git/") or (rel.startswith("_editor/") and rel != "_editor/editor.html"):
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Token") != TOKEN:
            return self._json(403, {"ok": False, "error": "編集室を開き直してください（合言葉が違います）"})
        path = urlparse(self.path).path
        try:
            n = max(0, int(self.headers.get("Content-Length", "0")))
        except ValueError:
            n = 0
        if n > MAX_UPLOAD:
            return self._json(413, {"ok": False, "error": "ファイルが大きすぎます（80MBまで）"})
        data = self.rfile.read(n)
        try:
            with LOCK:
                if path == "/api/content":
                    c = json.loads(data.decode("utf-8"))
                    validate(c)
                    out = build.build(c)
                    write_atomic(ROOT / "content.json", json.dumps(c, ensure_ascii=False, indent=2) + "\n")
                    write_atomic(ROOT / "index.html", out)
                    return self._json(200, {"ok": True})
                if path == "/api/photo":
                    name = unquote(self.headers.get("X-Filename", "photo.jpg"))
                    rel, size = save_photo(data, name)
                    return self._json(200, {"ok": True, "src": rel, "w": size[0], "h": size[1]})
                if path == "/api/publish":
                    return self._json(200, publish())
        except AssertionError as e:
            return self._json(400, {"ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        return self._json(404, {"ok": False, "error": "不明な操作"})


def publish():
    code, out = run(["git", "pull", "--ff-only", "-q"])
    if code:
        return {"ok": False, "error": "最新を取り込めませんでした。何も変えていません。秘書に頼んでください。\n" + out}
    c = json.loads((ROOT / "content.json").read_text(encoding="utf-8"))
    validate(c)
    write_atomic(ROOT / "index.html", build.build(c))
    refs = referenced(c)
    # 編集室で入れた写真（ph-*.jpg）のうち、もう使っていないものは外す（公開済みなら git の履歴に残る）
    removed = []
    for p in MEDIA.glob("ph-*.jpg"):
        if f"media/{p.name}" not in refs:
            p.unlink(); removed.append(p.name)
    run(["git", "add", "-A", "--", "content.json", "index.html", "_editor", "編集室.command", ".gitignore"])
    run(["git", "add", "-A", "--", "media/*.jpg", "media/*.jpeg", "media/*.png"])
    code, out = run(["git", "diff", "--cached", "--quiet"])
    if code == 0:
        return {"ok": True, "message": "公開済みの内容と同じなので、出すものはありませんでした"}
    code, out = run(["git", "commit", "-q", "-m", "編集室から更新（文章・写真）"])
    if code:
        return {"ok": False, "error": out}
    code, out = run(["git", "push", "-q", "origin", "HEAD"])
    if code:
        return {"ok": False, "error": "送れませんでした。\n" + out}
    _, h = run(["git", "log", "-1", "--format=%h"])
    return {"ok": True, "message": f"公開しました（{h}）。数分で反映されます。", "removed": removed}


def main():
    if not shutil.which("git"):
        print("git が見つかりません"); sys.exit(1)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}/#{TOKEN}"
    print(f"{time.strftime('%Y-%m-%d %H:%M')} 編集室を起動しました: http://127.0.0.1:{PORT}/", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
