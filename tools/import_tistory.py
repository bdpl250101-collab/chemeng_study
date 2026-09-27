"""티스토리 블로그 글을 content/ 로 가져온다.

공개 글만 가져온다 (비공개/보호 글은 403 이라 건너뛴다).
- 본문 HTML 은 .contents_style 안쪽만 취하고 티스토리 전용 속성·스크립트를 제거한다.
- 이미지는 카카오 CDN 서명 URL 이라 시간이 지나면 만료되므로 docs/images/<id>/ 로 내려받고 (빌드 결과와 같은 자리, 사본 하나만 둔다)
  src 를 상대 경로로 바꾼다.
- 결과: content/posts/<id>.json  { id, title, date, modified, category, tags, summary, html, source_url }

사용:
    python tools/import_tistory.py                 # 1..MAX_ID 전체
    python tools/import_tistory.py --ids 295 300   # 특정 글만
    python tools/import_tistory.py --start 280     # 280 부터 (새 글만 추가할 때)
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment

BLOG = "https://audio268.tistory.com"
ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "content" / "posts"
IMAGES = ROOT / "docs" / "images"
MAX_ID = 330
DELAY = 0.4

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) chemeng-site importer"}
session = requests.Session()
session.headers.update(UA)

DROP_ATTR_PREFIXES = ("data-ke-", "data-origin-", "data-phocus", "data-url", "data-filename",
                      "data-alt", "onerror", "srcset", "loading", "sizes")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch(url: str, **kw) -> requests.Response | None:
    for attempt in range(3):
        try:
            r = session.get(url, timeout=30, **kw)
            if r.status_code in (403, 404):
                return r
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            log(f"  retry {attempt + 1}: {url[:80]} ({e})")
            time.sleep(1.5 * (attempt + 1))
    return None


def real_image_url(src: str) -> str:
    """daumcdn 썸네일 프록시(?fname=원본) 면 원본 URL 을 꺼낸다."""
    if not src:
        return src
    if src.startswith("//"):
        src = "https:" + src
    p = urlparse(src)
    if "daumcdn.net" in p.netloc and "fname=" in p.query:
        fname = parse_qs(p.query).get("fname", [""])[0]
        if fname:
            return unquote(fname)
    return src


def ext_for(resp: requests.Response, url: str) -> str:
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
    ext = mimetypes.guess_extension(ctype) if ctype else None
    if ext in (None, ".jpe"):
        path_ext = Path(urlparse(url).path).suffix.lower()
        ext = path_ext if path_ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp") else ".png"
    if ext == ".jpeg":
        ext = ".jpg"
    return ext


def download_images(article, post_id: int) -> tuple[int, int]:
    """본문 img 를 내려받고 src 를 상대 경로로 바꾼다. (성공, 실패) 수를 돌려준다."""
    ok = fail = 0
    seen: dict[str, str] = {}
    folder = IMAGES / str(post_id)
    n = 0
    for img in article.find_all("img"):
        src = real_image_url(img.get("src") or "")
        if not src:
            img.decompose()
            continue
        if src in seen:
            img["src"] = seen[src]
        else:
            n += 1
            resp = fetch(src, headers={"Referer": BLOG + "/"})
            if resp is None or resp.status_code != 200 or not resp.content:
                fail += 1
                log(f"  image FAIL {src[:90]}")
                img["src"] = src  # 원본이라도 남겨둔다
                img["data-import-failed"] = "1"
            else:
                folder.mkdir(parents=True, exist_ok=True)
                name = f"{n:02d}{ext_for(resp, src)}"
                (folder / name).write_bytes(resp.content)
                rel = f"../images/{post_id}/{name}"
                seen[src] = rel
                img["src"] = rel
                ok += 1
                time.sleep(0.15)
        for a in list(img.attrs):
            if a.startswith(DROP_ATTR_PREFIXES) or a in ("style", "class"):
                del img[a]
        if not img.get("alt"):
            img["alt"] = ""
    return ok, fail


def clean_article(article) -> None:
    for tag in article.find_all(["script", "style", "noscript", "ins", "iframe"]):
        if tag.name == "iframe" and any(h in (tag.get("src") or "") for h in ("youtube", "youtu.be", "vimeo")):
            continue
        tag.decompose()
    for c in article.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    # 이미지 래퍼 <span data-url> / <a> 로 감싼 이미지 -> 이미지만 남긴다
    for span in article.select("span[data-url], span[data-phocus]"):
        span.unwrap()
    for a in article.find_all("a"):
        if a.find("img") and (a.get("href") or "").startswith(("https://blog.kakaocdn", "https://img1.daumcdn")):
            a.unwrap()
    # 코드블록 언어 표시를 class 로 옮긴다
    for pre in article.find_all("pre"):
        lang = pre.get("data-ke-language")
        if lang:
            pre["class"] = [f"language-{lang}"]
    # 파일 첨부 블록은 링크 목록으로 축약
    for fb in article.select("figure.fileblock"):
        links = []
        for a in fb.find_all("a", href=True):
            links.append(f'<a href="{urljoin(BLOG, a["href"])}">{a.get_text(strip=True) or "첨부파일"}</a>')
        repl = BeautifulSoup('<p class="attachment">첨부: ' + " · ".join(links) + "</p>", "lxml").p
        fb.replace_with(repl)
    # 속성 정리
    for tag in article.find_all(True):
        for a in list(tag.attrs):
            if a.startswith(DROP_ATTR_PREFIXES) or a in ("style", "id", "contenteditable"):
                del tag[a]
        if tag.name == "figure":
            tag["class"] = ["figure"]
        elif tag.name in ("p", "span", "div", "table", "td", "th", "tr", "blockquote",
                          "h1", "h2", "h3", "h4", "ul", "ol", "li"):
            if tag.name == "p" and tag.get("class") == ["attachment"]:
                continue
            tag.attrs.pop("class", None)
    # 빈 문단 연속 제거 (티스토리는 &nbsp; 문단으로 줄을 띄운다)
    prev_blank = False
    for p in list(article.find_all("p")):
        blank = not p.get_text(strip=True).replace("\xa0", "") and not p.find(["img", "iframe", "br"])
        if blank and prev_blank:
            p.decompose()
            continue
        prev_blank = blank


def parse_post(post_id: int, html: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    article = soup.select_one(".contents_style")
    if article is None:
        return None

    def meta(prop):
        m = soup.find("meta", property=prop)
        return m["content"].strip() if m and m.get("content") else ""

    title = meta("og:title") or (soup.title.get_text(strip=True) if soup.title else f"글 {post_id}")
    cat_el = soup.select_one("p.category, .category")
    category = cat_el.get_text(strip=True) if cat_el else ""
    tags = [a.get_text(strip=True) for a in soup.select('a[href^="/tag/"]')]
    tags = list(dict.fromkeys(t for t in tags if t))

    clean_article(article)
    ok, fail = download_images(article, post_id)

    inner = article.decode_contents().strip()
    text = article.get_text(" ", strip=True)
    return {
        "id": post_id,
        "title": title,
        "date": meta("article:published_time")[:10],
        "modified": meta("article:modified_time")[:10],
        "category": category,
        "tags": tags,
        "summary": meta("og:description")[:300],
        "source_url": f"{BLOG}/{post_id}",
        "images_ok": ok,
        "images_failed": fail,
        "chars": len(text),
        "html": inner,
    }


def import_one(post_id: int) -> str:
    r = fetch(f"{BLOG}/{post_id}")
    if r is None:
        return "error"
    if r.status_code != 200:
        return str(r.status_code)
    post = parse_post(post_id, r.text)
    if post is None:
        return "no-article"
    out = POSTS / f"{post_id}.json"
    out.write_text(json.dumps(post, ensure_ascii=False, indent=1), encoding="utf-8")
    total = post["images_ok"] + post["images_failed"]
    return f"ok  {post['date']}  [{post['category']}]  {post['title'][:50]}  img {post['images_ok']}/{total}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", type=int, nargs="*")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=MAX_ID)
    args = ap.parse_args()
    ids = args.ids or range(args.start, args.end + 1)
    POSTS.mkdir(parents=True, exist_ok=True)
    stats: dict[str, int] = {}
    for pid in ids:
        res = import_one(pid)
        key = res.split()[0]
        stats[key] = stats.get(key, 0) + 1
        log(f"{pid:>4}  {res}")
        time.sleep(DELAY)
    log("done:", stats)


if __name__ == "__main__":
    main()
