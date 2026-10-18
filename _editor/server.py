#!/usr/bin/env python3
"""iro:re 作品サイトの編集室（手元の Mac だけで動く・2026-10-18）

「編集室.command」から起動する。ブラウザに編集画面を開き、
  保存   → content.json を書き、index.html を作り直す（手元だけ・外には出ない）
  公開   → git commit して push（GitHub Pages に数分で反映）
  写真   → HEIC/JPEG/PNG を受け取り、向きを直し、長辺2000px・位置情報なしの JPEG にして media/ に置く

★守り: 127.0.0.1 だけで待ち受ける／Host を確かめる／書き込みは起動時に作る合言葉つきのときだけ。
"""
import hashlib, importlib, json, os, re, secrets, shutil, subprocess, sys, tempfile, threading, time, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

ROOT = Path(__file__).resolve().parent.parent
EDITOR = ROOT / "_editor"
MEDIA = ROOT / "media"
DRAFTS = ROOT / "_drafts"   # 下書きの版（公開しない・git に入れない）。ファイル1つ＝1版
TOKEN = secrets.token_urlsafe(24)
PORT = int(os.environ.get("IRORE_EDITOR_PORT", "8490"))
# ★既定は 127.0.0.1 だけ。母艦では IRORE_EDITOR_BIND に Tailscale の住所（100.x）を足して、
#   自分の端末（tailnet＝健さんの機械だけ）からも開けるようにする。インターネットには出さない（Funnel は使わない）
BIND = ["127.0.0.1"] + [h.strip() for h in os.environ.get("IRORE_EDITOR_BIND", "").split(",") if h.strip()]
for _h in BIND:
    assert _h == "127.0.0.1" or _h.startswith("100."), f"Tailscale の住所（100.x）以外では待ち受けません: {_h}"
HOSTS = {f"{h}:{PORT}" for h in ["127.0.0.1", "localhost"] + BIND
         + [h.strip() for h in os.environ.get("IRORE_EDITOR_HOSTS", "").split(",") if h.strip()]}
MAX_UPLOAD = 80 * 1024 * 1024
LOCK = threading.Lock()

sys.path.insert(0, str(EDITOR))
import build  # noqa: E402


def run(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "時間切れ（通信が止まっています）"
    return p.returncode, (p.stdout + p.stderr).strip()


def _media_ok(v):
    """写真の場所が正しく、実在し、名前の大文字小文字まで一致するか（macOS は区別しないので git が取りこぼす）"""
    return bool(re.fullmatch(r"media/[A-Za-z0-9._-]+", v)) and (ROOT / v).is_file() and Path(v).name in os.listdir(MEDIA)


SERVER_SIG = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()   # 動いている仕組みの印（ディスクの版と比べる）


def validate(c):
    assert isinstance(c, dict) and isinstance(c.get("blocks"), list), "形が違います"
    for b in c["blocks"]:
        assert b.get("type") in ("text", "photo", "video", "teaser", "data", "gallery"), f"知らない種類: {b.get('type')}"
        if b["type"] == "gallery":
            assert isinstance(b.get("items"), list) and b["items"], "まとまりに写真がありません"
            for it in b["items"]:
                v = it.get("src", "")
                assert _media_ok(v), f"写真が見つかりません: {v}"
        if b["type"] == "text":
            assert b.get("style") in build.STYLES, f"文字の大きさが不正です: {b.get('style')}"
        if b["type"] in ("photo", "video"):
            assert b.get("layout") in build.LAYOUTS, f"配置が不正です: {b.get('layout')}"
        for key in ("src", "poster"):
            if key in b:
                v = b[key]
                assert _media_ok(v), f"写真が見つかりません: {v}"
    build.build(c)  # 組み立てられるかを先に確かめる（失敗したら保存しない）


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ── 版（公開中の版＝content.json ／ 下書きの版＝_drafts/<id>.json） ──
def _vid(v):
    assert v == "live" or re.fullmatch(r"[a-z0-9-]{1,40}", v or ""), f"版の名前が不正です: {v}"
    return v


def draft_path(v):
    return DRAFTS / f"{_vid(v)}.json"


def load_version(v):
    if v == "live":
        return json.loads((ROOT / "content.json").read_text(encoding="utf-8"))
    return json.loads(draft_path(v).read_text(encoding="utf-8"))["content"]


def save_draft(v, c, name=None):
    DRAFTS.mkdir(exist_ok=True)
    p = draft_path(v)
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    rec = {"name": name or old.get("name") or v, "updated": time.strftime("%Y-%m-%d %H:%M"), "content": c}
    write_atomic(p, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")


def list_versions():
    out = [{"id": "live", "name": "公開中の版", "updated": ""}]
    if DRAFTS.exists():
        recs = []
        for p in DRAFTS.glob("*.json"):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
                recs.append({"id": p.stem, "name": r.get("name", p.stem), "updated": r.get("updated", "")})
            except Exception:  # noqa: BLE001
                pass
        out += sorted(recs, key=lambda r: r["updated"], reverse=True)
    return out


def new_version(src, name):
    c = load_version(src)
    v = time.strftime("v%Y%m%d-%H%M%S")
    save_draft(v, c, name)
    return v


def rev(v):
    """その版の今の中身の印。読んだときの印と保存のときの印を比べ、別の画面の直しを黙って消さない"""
    try:
        c = load_version(v)
    except FileNotFoundError:
        return ""
    return hashlib.sha256((v + "\n" + json.dumps(c, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]


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
        return self.headers.get("Host", "") in HOSTS

    def _json(self, code, obj, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        for k, val in (headers or {}).items():
            self.send_header(k, val)
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
            v = (parse_qs(urlparse(self.path).query).get("v") or ["live"])[0]
            try:
                c = load_version(_vid(v))
                return self._json(200, c, {"X-Rev": rev(v)})
            except (AssertionError, FileNotFoundError):
                return self._json(404, {"ok": False, "error": "その版は見つかりません"})
        elif path == "/api/versions":
            return self._json(200, {"versions": list_versions()})
        elif re.fullmatch(r"/preview-[a-z0-9-]{1,40}\.html", path):
            # 下書きの版をその場で組み立てて見せる（ルートに置くので写真の相対パスがそのまま効く）
            try:
                body = build.build(load_version(path[len("/preview-"):-len(".html")])).encode()
            except (AssertionError, FileNotFoundError):
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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
                q = parse_qs(urlparse(self.path).query)
                v = _vid((q.get("v") or ["live"])[0])
                if path == "/api/content":
                    c = json.loads(data.decode("utf-8"))
                    validate(c)
                    if v != "live":
                        assert draft_path(v).exists(), "その版は見つかりません（公開されたか、消されました）。版を選び直してください"
                    if self.headers.get("X-Base-Rev", "") != rev(v):
                        return self._json(409, {"ok": False, "conflict": True,
                            "error": "別の画面（または公開）で、この版が先に直されています。保存しませんでした。\n読み込み直してから直してください。いまの書きかけは、この画面に残っています。"})
                    if v != "live":
                        save_draft(v, c)
                    else:
                        out = build.build(c)
                        write_atomic(ROOT / "content.json", json.dumps(c, ensure_ascii=False, indent=2) + "\n")
                        write_atomic(ROOT / "index.html", out)
                    return self._json(200, {"ok": True, "rev": rev(v)})
                if path == "/api/versions/new":
                    body = json.loads(data.decode("utf-8") or "{}")
                    nv = new_version(_vid(body.get("from", "live")), (body.get("name") or "").strip()[:60] or "新しい版")
                    return self._json(200, {"ok": True, "id": nv})
                if path == "/api/versions/rename":
                    body = json.loads(data.decode("utf-8"))
                    assert v != "live", "公開中の版の名前は変えられません"
                    save_draft(v, load_version(v), (body.get("name") or "").strip()[:60] or v)
                    return self._json(200, {"ok": True})
                if path == "/api/versions/delete":
                    assert v != "live", "公開中の版は消せません"
                    if self.headers.get("X-Base-Rev", "") != rev(v):
                        return self._json(409, {"ok": False, "conflict": True, "error": "別の画面でこの版が直されています。消しませんでした。読み込み直してから、もう一度確かめてください。"})
                    draft_path(v).unlink()
                    return self._json(200, {"ok": True})
                if path == "/api/photo":
                    name = unquote(self.headers.get("X-Filename", "photo.jpg"))
                    rel, size = save_photo(data, name)
                    return self._json(200, {"ok": True, "src": rel, "w": size[0], "h": size[1]})
                if path == "/api/publish":
                    if v != "live":
                        # 下書きの版を公開：今の公開中の版を「公開していた版」として残してから入れ替える
                        c = load_version(v)
                        validate(c)
                        live = load_version("live")
                        snap = time.strftime("v%Y%m%d-%H%M%S") + "-prev"
                        old_json = (ROOT / "content.json").read_bytes()
                        old_html = (ROOT / "index.html").read_bytes() if (ROOT / "index.html").exists() else None
                        r = {"ok": False, "error": "公開の途中で止まりました"}
                        try:
                            save_draft(snap, live, f"公開していた版（{time.strftime('%Y-%m-%d %H:%M')} まで）")
                            write_atomic(ROOT / "content.json", json.dumps(c, ensure_ascii=False, indent=2) + "\n")
                            r = publish()
                        finally:
                            if r.get("ok"):
                                draft_path(v).unlink(missing_ok=True)
                                r["message"] += "\nそれまで公開していた版は、版の一覧に残してあります。"
                            else:  # 元の公開中の版に戻す（下書きの版はそのまま残る）
                                (ROOT / "content.json").write_bytes(old_json)
                                if old_html is not None:
                                    (ROOT / "index.html").write_bytes(old_html)
                                draft_path(snap).unlink(missing_ok=True)
                        return self._json(200, r)
                    return self._json(200, publish())
        except AssertionError as e:
            return self._json(400, {"ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        return self._json(404, {"ok": False, "error": "不明な操作"})


def _ahead():
    code, out = run(["git", "rev-list", "--count", "@{u}..HEAD"])
    return int(out) if code == 0 and out.isdigit() else 0


def _rebuild_index():
    try:
        write_atomic(ROOT / "index.html", build.build(json.loads((ROOT / "content.json").read_text(encoding="utf-8"))))
    except Exception:  # noqa: BLE001
        pass


def _new_server_ready():
    """ディスク上の server.py が、動いている仕組みと違い、しかも動く形か"""
    disk = (EDITOR / "server.py").read_bytes()
    if hashlib.sha256(disk).hexdigest() == SERVER_SIG:
        return None
    code, out = run([sys.executable, "-m", "py_compile", str(EDITOR / "server.py")])
    return code == 0


def publish():
    global build
    # 送る準備の欄（index）を、いつも最後の commit にそろえてから始める（前回の失敗の残りを持ち込まない・手元のファイルは消えない）
    run(["git", "reset", "-q"])
    # index.html は content.json から作る生成物。取り込みの邪魔にならないよう commit の形に戻す（このあと作り直す）
    run(["git", "checkout", "-q", "HEAD", "--", "index.html"])
    code, out = run(["git", "pull", "--ff-only", "-q"])
    if code:
        _rebuild_index()
        why = "通信が止まっています" if code == 124 else "別の場所の直しとぶつかっています"
        return {"ok": False, "error": f"最新を取り込めませんでした（{why}）。公開していません。秘書に頼んでください。\n" + out}
    # 編集室そのものが新しくなっていたら、新しい仕組みで立て直してから公開してもらう
    ready = _new_server_ready()
    if ready is not None:
        _rebuild_index()
        if not ready:
            return {"ok": False, "error": "編集室の新しい仕組みに誤りがあるため、公開を止めました（今の編集室はそのまま使えます）。秘書に頼んでください。"}
        threading.Timer(1.0, lambda: os._exit(0)).start()  # 常駐（KeepAlive）が新しい仕組みで立て直す
        return {"ok": False, "error": "編集室の仕組みが新しくなったので、立て直しています。30秒ほど待って読み込み直し、もう一度「公開」を押してください。"}
    try:
        build = importlib.reload(build)
    except Exception as e:  # noqa: BLE001
        _rebuild_index()
        return {"ok": False, "error": f"ページを組み立てる仕組みに誤りがあるため、公開を止めました。秘書に頼んでください。\n{e}"}
    c = json.loads((ROOT / "content.json").read_text(encoding="utf-8"))
    validate(c)
    write_atomic(ROOT / "index.html", build.build(c))
    live_refs = referenced(c)
    keep = set(live_refs)
    for ver in list_versions()[1:]:
        try:
            keep |= referenced(load_version(ver["id"]))
        except Exception:  # noqa: BLE001
            pass
    # 片付け：公開済み（最後の commit に入っている）ph-*.jpg のうち、どの版も使っていないものだけを外す。
    #   まだ公開していない写真は、保存前・下書き用かもしれないので消さない
    published = set(run(["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "media"])[1].split())
    removed = []
    for p in MEDIA.glob("ph-*.jpg"):
        rel = f"media/{p.name}"
        if rel in published and rel not in keep:
            p.unlink(); removed.append(p.name)
    # 載せるもの：仕組みと文章／公開済みの写真の変更と削除／公開する版が使う写真だけ（下書き専用の写真は出さない）
    names = [n for n in ("content.json", "index.html", "_editor", "編集室.command", ".gitignore")
             if (ROOT / n).exists() or run(["git", "ls-files", "--error-unmatch", "--", n])[0] == 0]
    new_media = sorted(r for r in live_refs if r.startswith("media/") and (ROOT / r).is_file())
    for cmd in (["git", "add", "-A", "--", *names], ["git", "add", "-u", "--", "media"]) + ((["git", "add", "--", *new_media],) if new_media else ()):
        code, out = run(cmd)
        if code:
            run(["git", "reset", "-q"])
            return {"ok": False, "error": "公開の準備に失敗しました。何も送っていません。\n" + out}
    committed = False
    code, _ = run(["git", "diff", "--cached", "--quiet"])
    if code:
        code, out = run(["git", "commit", "-q", "-m", "編集室から更新（文章・写真）"])
        if code:
            run(["git", "reset", "-q"])
            return {"ok": False, "error": out}
        committed = True
    if not _ahead():
        return {"ok": True, "message": "公開済みの内容と同じなので、出すものはありませんでした", "removed": removed}
    code, out = run(["git", "push", "-q", "origin", "HEAD"])
    if code:
        # 送り先には届いていた（返事だけ途切れた）ことがあるので、確かめてから決める
        run(["git", "fetch", "-q", "origin"], timeout=60)
        if run(["git", "rev-parse", "HEAD"])[1] != run(["git", "rev-parse", "@{u}"])[1]:
            if committed:  # 送れなかった commit は残さない（準備の欄も外す。手元のファイルはそのまま）
                run(["git", "reset", "-q", "HEAD~1"])
            return {"ok": False, "error": "送れませんでした。もう一度「公開」を押してください。\n" + out}
    _, h = run(["git", "log", "-1", "--format=%h"])
    return {"ok": True, "message": f"公開しました（{h}）。数分で反映されます。", "removed": removed}


def main():
    if not shutil.which("git"):
        print("git が見つかりません"); sys.exit(1)
    servers = [ThreadingHTTPServer((h, PORT), H) for h in BIND]
    url = f"http://127.0.0.1:{PORT}/"
    print(f"{time.strftime('%Y-%m-%d %H:%M')} 編集室を起動しました: " + "  ".join(f"http://{h}:{PORT}/" for h in BIND), flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    for srv in servers[1:]:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
