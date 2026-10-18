#!/usr/bin/env python3
"""iro:re 作品サイト：content.json と template.html から index.html を作る（2026-10-18）

★文章と写真の正は content.json。index.html は毎回ここから作り直すので、手で直さない。
  見た目（CSS）や動き（JS）を変えるときは _editor/template.html を直す。
"""
import html, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://314cmtour.github.io/irore-384d00/"
LAYOUTS = ("full", "r60", "l60", "c40")
STYLES = ("statement", "concept", "note")


def t(s):  # 本文：改行は <br>
    return html.escape(s, quote=False).replace("\n", "<br>\n      ")


def a(s):  # 属性
    return html.escape(s, quote=True)


def dd(s):
    return html.escape(s, quote=False).replace("\n", "<br>")


def section(inner, photo=False):
    return f'  <section class="band{" photo" if photo else ""}"><div class="wrap">\n{inner}  </div></section>\n'


def render_block(b):
    k = b["type"]
    if k == "text":
        assert b["style"] in STYLES, b["style"]
        label = f'    <p class="label">{t(b["label"])}</p>\n' if b.get("label") else ""
        ps = "".join(f"      <p>{t(p)}</p>\n" for p in b["paragraphs"] if p.strip())
        return section(f'{label}    <div class="{b["style"]} fade">\n{ps}    </div>\n')
    if k == "photo":
        lay = b.get("layout", "full")
        assert lay in LAYOUTS, lay
        cap = f'<figcaption>{t(b["caption"])}</figcaption>' if b.get("caption", "").strip() else ""
        return section(f'      <figure class="{lay} fade"><img src="{a(b["src"])}" alt="{a(b.get("alt", ""))}" loading="lazy">{cap}</figure>\n', photo=True)
    if k == "video":
        lay = b.get("layout", "full")
        assert lay in LAYOUTS, lay
        return section(f'      <figure class="{lay} fade">\n        <video src="{a(b["src"])}" poster="{a(b["poster"])}" muted loop playsinline preload="none" class="loop" aria-label="{a(b.get("alt", ""))}"></video>\n'
                       + (f'        <figcaption>{t(b["caption"])}</figcaption>\n' if b.get("caption", "").strip() else "")
                       + '      </figure>\n', photo=True)
    if k == "gallery":
        imgs = "".join(f'          <img src="{a(it["src"])}" alt="{a(it.get("alt", ""))}" loading="lazy">\n' for it in b["items"])
        cap = f'        <figcaption>{t(b["caption"])}</figcaption>\n' if b.get("caption", "").strip() else ""
        return section(f'      <figure class="gallery fade">\n        <div class="gal">\n{imgs}        </div>\n{cap}      </figure>\n', photo=True)
    if k == "teaser":
        return section(
            '    <figure class="teaser fade">\n'
            f'      <div class="vbox" data-yt="{a(b["youtube"])}">\n'
            f'        <img src="{a(b["poster"])}" alt="{a(b.get("alt", ""))}" loading="lazy">\n'
            '        <button class="vplay" type="button" aria-label="ティーザーを再生"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="31"/><path d="M27 22 L44 32 L27 42 Z"/></svg></button>\n'
            f'        <span class="vmeta">{t(b.get("meta", ""))}</span>\n'
            '        <button class="vfull" type="button" aria-label="全画面で再生"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 9V3h6M15 3h6v6M21 15v6h-6M9 21H3v-6"/></svg></button>\n'
            '      </div>\n'
            + (f'      <figcaption>{t(b["caption"])}</figcaption>\n' if b.get("caption", "").strip() else "")
            + '    </figure>\n')
    if k == "words":
        # 作品が水面に浮かべる言葉の一覧（まとまりごと）。言葉は1語ずつ span で並べる
        label = f'    <p class="label">{t(b["label"])}</p>\n' if b.get("label") else ""
        gs = ""
        for g in b["groups"]:
            ws = "".join(f"<span>{t(w)}</span>" for w in g.get("words", []) if w.strip())
            if ws or g.get("name", "").strip():
                gs += f'      <div class="wg">\n        <p class="wh">{t(g.get("name", ""))}</p>\n        <p class="wl">{ws}</p>\n      </div>\n'
        cap = f'    <p class="wcap">{t(b["caption"])}</p>\n' if b.get("caption", "").strip() else ""
        return section(f'{label}    <div class="words fade">\n{gs}    </div>\n{cap}')
    if k == "data":
        label = f'    <p class="label">{t(b["label"])}</p>\n' if b.get("label") else ""
        rows = "".join(f'      <dt>{t(r["k"])}</dt><dd>{dd(r["v"])}</dd>\n' for r in b["rows"] if r["k"].strip())
        return section(f'{label}    <dl class="data fade">\n{rows}    </dl>\n')
    raise ValueError(f"知らない種類: {k}")


def build(content):
    tpl = (ROOT / "_editor" / "template.html").read_text(encoding="utf-8")
    m = content["meta"]
    main = "\n\n" + "\n".join(render_block(b) for b in content["blocks"]) + "\n"
    rep = {
        "<!--@TITLE-->": t(m["title"]),
        "<!--@DESCRIPTION-->": a(m["description"]),
        "<!--@OG_TITLE-->": a(m["title"]),
        "<!--@OG_DESCRIPTION-->": a(m["ogDescription"]),
        "<!--@OG_IMAGE-->": a(BASE_URL + m["ogImage"]),
        "<!--@HERO_NAME-->": t(content["hero"]["name"]),
        "<!--@HERO_SUB-->": t(content["hero"]["sub"]),
        "<!--@MAIN-->": main,
        "<!--@FOOTER-->": t(content["footer"]),
    }
    for k, v in rep.items():
        assert tpl.count(k) == 1, k
        tpl = tpl.replace(k, v)
    return tpl


def main():
    content = json.loads((ROOT / "content.json").read_text(encoding="utf-8"))
    out = build(content)
    (ROOT / "index.html").write_text(out, encoding="utf-8")
    print("index.html を作り直しました")


if __name__ == "__main__":
    main()
